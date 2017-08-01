# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import datetime
import itertools
import logging
import re
import textwrap
import time
import os
import glob
from xml.etree import ElementTree

import requests
import yaml
import json
from jinja2 import Environment, PackageLoader
from pkg_resources import resource_filename
import difflib
import functools

from .cache import Crossref, Arxiv

from sqlalchemy.orm.exc import NoResultFound

log = logging.getLogger(__name__)

# [ident] or [ident=111] NOT [ident](...
# [ident] = [alphanumeric and hypen] OR [doi:[alphanum .] / [alphanum .] ] OR [arxiv:
IN_TEXT_CITATION_RE = r'\[((doi\:[\w\.]+\/[\w\.]+)|(arxiv\:\d+\.\d+)|([\w\-]+))(\=(\d+))?\](?!\()'

# [=111] NOT [=111](...
SHORT_IN_TEXT_CITATION_RE = r'\[\=(\d+)\](?!\()'

with open(resource_filename('gitbib', 'abbreviations.json')) as f:
    ABBREVS = {long.lower(): short for short, long in json.load(f)}


# The cached data should be as faithful to the original data as possible.
# For json api's this is easy. Just dump the json-loaded dictionary.
# Note that our internal representation is probably different. But since our
# internal representation may change, we'll just keep the cached data as
# faithful as possible.

class NoCrossref(RuntimeError):
    pass


def _fetch_crossref(ident, doi):
    log.debug("{} doi: {}".format(ident, doi))
    headers = {'Accept': 'application/json; charset=utf-8'}
    url = "http://api.crossref.org/works/{doi}".format(doi=doi)
    r = requests.get(url, headers=headers)
    time.sleep(1)
    log.debug("Request for {} returned {}".format(url, r.status_code))
    if r.status_code != 200:
        raise NoCrossref()
    data = r.json()['message']
    c = Crossref(doi=doi, data=data)
    return c


class NoArxiv(RuntimeError):
    pass


def _fetch_arxiv(ident, arxivid):
    url = 'http://export.arxiv.org/api/query?id_list={}'.format(arxivid)
    r = requests.get(url)
    time.sleep(1)
    log.debug("Request for {} returned {}".format(url, r.status_code))
    if r.status_code != 200:
        raise NoArxiv()

    # TODO: catch xml errors?
    ns = {'atom': "http://www.w3.org/2005/Atom"}
    tree = ElementTree.fromstring(r.text).find('atom:entry', ns)
    data = {
        'title': tree.find('atom:title', ns).text,
        'published': tree.find('atom:published', ns).text,
        'updated': tree.find('atom:updated', ns).text,
        'summary': tree.find('atom:summary', ns).text,
        'authors': [],
    }
    for auth in tree.iterfind('atom:author', ns):
        data['authors'] += [auth.find('atom:name', ns).text]
    a = Arxiv(arxivid=arxivid, data=data)
    return a


def cache(ident, my_meta, *, session, ulog):
    crossref = None
    if 'doi' in my_meta:
        try:
            crossref = session.query(Crossref).filter(Crossref.doi == my_meta['doi']).one()
            ulog.debug("{}'s entry was cached via doi/crossref".format(ident))
        except NoResultFound:
            try:
                ulog.info("Fetching data for {} via doi/crossref".format(ident))
                crossref = _fetch_crossref(ident, my_meta['doi'])
                session.add(crossref)
            except NoCrossref:
                ulog.error("A doi was given for {}, but the crossref request failed!".format(ident))

    arxiv = None
    if 'arxiv' in my_meta:
        try:
            arxiv = session.query(Arxiv).filter(Arxiv.arxivid == my_meta['arxiv']).one()
            ulog.debug("{}'s entry was cached via arxiv".format(ident))
        except NoResultFound:
            try:
                ulog.info("Fetching data for {} via arxiv".format(ident))
                arxiv = _fetch_arxiv(ident, my_meta['arxiv'])
                session.add(arxiv)
            except NoArxiv:
                ulog.error("An arxiv id was given for {}, but we couldn't get the data!".format(ident))

    biorxiv = None
    if 'biorxiv' in my_meta:
        try:
            biorxiv = session.query(Crossref).filter(Crossref.doi == my_meta['biorxiv']).one()
            ulog.debug("{}'s biorxiv entry was cached via doi/crossref".format(ident))
        except NoResultFound:
            try:
                ulog.info("Fetching data for {} biorxiv via doi/crossref".format(ident))
                biorxiv = _fetch_crossref(ident, my_meta['biorxiv'])
                session.add(biorxiv)
            except NoCrossref:
                ulog.error("A biorxiv doi was given for {}, but the crossref request failed!".format(ident))


    ret = {'none': my_meta}
    if crossref is not None:
        ret['doi'] = crossref.data
    if arxiv is not None:
        ret['arxiv'] = arxiv.data
    if biorxiv is not None:
        ret['biorxiv'] = biorxiv.data

    return ret


# Out input entries may be spread across multiple yaml files.
# The top level of each should be a mapping (dictonary), so the end
# result should be a big dictionary whose keys are the union of each
# files' keys.

def read_yaml(fn):
    log.debug("Parsing {}".format(fn))
    with open(fn) as f:
        res = yaml.load(f)
    if not isinstance(res, dict):
        raise ValueError("Source yaml files must be a mapping (dictionary)")
    return res


class DuplicateKeyError(KeyError):
    def __init__(self, duplicate_key):
        self.duplicate_key = duplicate_key


class GitbibFileNotFoundError(FileNotFoundError):
    pass


def read_yamls(repo_dir, gitbib_yaml_fn, *, ulog):
    abs_gitbib_fn = "{}/{}".format(repo_dir, gitbib_yaml_fn)
    abs_gitbib_fn = os.path.abspath(abs_gitbib_fn)
    if not os.path.exists(abs_gitbib_fn):
        raise GitbibFileNotFoundError()
    with open(abs_gitbib_fn) as f:
        config = yaml.load(f)
    source_files = config.get('source_files', '*.yaml')
    if not isinstance(source_files, list):
        source_files = [source_files]
    source_files = list(itertools.chain.from_iterable(glob.iglob("{}/{}".format(repo_dir, fn)) for fn in source_files))
    ulog.info("Loading these yaml files: {}".format(", ".join(source_files)))
    my_meta = dict()
    for fn in source_files:
        if os.path.abspath(fn) == abs_gitbib_fn:
            ulog.debug("Skipping {}".format(fn))
            continue
        rel_fn = os.path.relpath(fn, repo_dir)
        for k, v in read_yaml(fn).items():
            if k in my_meta:
                raise DuplicateKeyError(k)
            v['input_fn'] = rel_fn
            my_meta[k] = v
    return config, my_meta


# We have to do some massaging of the data returned by the api's.
# For convenience, we model ourselves off of the dx.doi.org fields
# (with minor adjustments (we convert dates into something sensible)).
# The dx.doi.org fields should be general enough to adapt any API
# into it.

def _doi_to_pydate(date_spec):
    parts = date_spec['date-parts'][0]
    try:
        year, month, day = parts
    except ValueError:
        try:
            year, month = parts
            day = 1
        except ValueError:
            year, = parts
            month = 1
            day = 1

    return datetime.date(year, month, day)


def _container_title_logic(ctitles, *, ulog):
    ctitles = sorted(ctitles, key=lambda x: len(x), reverse=True)
    for title in ctitles:
        ltitle = title.lower()

        attempts = [
            ltitle,
            ltitle.replace('the', '').strip(),
        ]

        for attempt in attempts:
            if attempt in ABBREVS:
                return {
                    'full': title,
                    'short': ABBREVS[attempt],
                }
    ulog.warn("Couldn't find a journal abbreviation for {}".format(ctitles))
    return {
        'full': ctitles[0],
        'short': ctitles[-1],
    }

def _crossref_internal_rep_helper1(ulog):
    want = {k: lambda x: x
            for k in [
                'author',
                'publisher',
                'volume',
                'issue',
                'page',
                'short-title',
                'ISSN',
                'subject',
                'URL',
                'published-print',
                'published-online',
                'container-title',
                'type']
            }
    want['published-print'] = _doi_to_pydate
    want['published-online'] = _doi_to_pydate
    want['title'] = lambda ts: ts[0]
    want['container-title'] = lambda x: _container_title_logic(x, ulog=ulog)
    return want


def _crossref_internal_rep_helper2(my_meta, their_meta, want, want_keys, other_keys):
    return {**my_meta,
            **{k: want[k](v) for k, v in their_meta.items() if k in want_keys},
            'other_keys': list(other_keys),
            }


def _internal_rep_doi(my_meta, their_meta, *, ulog):
    want = _crossref_internal_rep_helper1(ulog)
    their_meta_keys = set(their_meta)
    want_keys = their_meta_keys & set(want.keys())
    other_keys = their_meta_keys - want_keys
    return _crossref_internal_rep_helper2(my_meta, their_meta, want, want_keys, other_keys)

def _internal_rep_biorxiv(my_meta, their_meta, *, ulog):
    want = _crossref_internal_rep_helper1(ulog)
    want['container-title'] = lambda x: {'full':'bioRxiv', 'short': 'bioRxiv'}
    their_meta_keys = set(their_meta)
    want_keys = their_meta_keys & set(want.keys())
    other_keys = their_meta_keys - want_keys
    return _crossref_internal_rep_helper2(my_meta, their_meta, want, want_keys, other_keys)


def _internal_rep_arxiv(my_meta, their_meta, *, ulog):
    new_their_meta = {k: v for k, v in their_meta.items() if k in ['title']}
    new_their_meta['published-online'] = (datetime.datetime.strptime(their_meta['published'], '%Y-%m-%dT%H:%M:%SZ')
                                          .date())
    new_their_meta['abstract'] = their_meta['summary']
    authors = []
    for a in their_meta['authors']:
        splits = a.split()
        if len(splits) > 1:
            authors += [
                {'given': ' '.join(splits[:-1]), 'family': splits[-1]}
            ]
        else:
            authors += [{'family': splits[0]}]

    new_their_meta['author'] = authors
    new_their_meta['type'] = 'unpublished'
    return {**my_meta,
            **{k: v for k, v in new_their_meta.items()}
            }


def _internal_rep_none(my_meta, their_meta, *, ulog):
    if 'author' in my_meta:
        if isinstance(my_meta['author'], str):
            ulog.warn("{}'s `author` field should be a list")
        else:
            new_auths = []
            for a in my_meta['author']:
                if isinstance(a, dict):
                    new_auths += [a]
                elif isinstance(a, str):
                    if ',' in a:
                        splits = [s.strip() for s in a.split(',')]
                        new_auths += [{'family': splits[0], 'given': splits[1]}]
                    else:
                        splits = a.split()
                        new_auths += [{'family': splits[-1], 'given': ' '.join(splits[:-1])}]
            my_meta['author'] = new_auths

    if 'number' in my_meta and 'issue' not in my_meta:
        my_meta['issue'] = my_meta['number']

    if 'pages' in my_meta and 'page' not in my_meta:
        my_meta['page'] = my_meta['pages'].replace('--', '-')

    if 'journal' in my_meta and 'container-title' not in my_meta:
        my_meta['container-title'] = _container_title_logic([my_meta['journal']], ulog=ulog)

    return my_meta


def _internal_representation(ident, my_meta, *, session, ulog):
    funcs = {
        'doi': _internal_rep_doi,
        'arxiv': _internal_rep_arxiv,
        'biorxiv': _internal_rep_biorxiv,
        'none': _internal_rep_none,
    }
    their_meta = cache(ident, my_meta, session=session, ulog=ulog)
    # TODO: better merging.
    # Right now we prefer doi -> arxiv -> biorxiv -> none
    # Really, we should merge data
    if 'doi' in their_meta:
        k = 'doi'
    elif 'arxiv' in their_meta:
        k = 'arxiv'
    elif 'biorxiv' in their_meta:
        k = 'biorxiv'
    else:
        k = 'none'
    return funcs[k](my_meta, their_meta[k], ulog=ulog)


def internal_representation(all_my_meta, *, session, ulog):
    return {ident: _internal_representation(ident, all_my_meta[ident], session=session, ulog=ulog)
            for ident in all_my_meta}


# With a good enough internal representation, most of the logic
# can be expressed eloquently in the jinja2 templates. We set up some
# jinja2 "filters" here to use to clean up the templates.

def fnln_name_from_dict(author):
    if isinstance(author, dict):
        return "{given} {family}".format(**author)
    else:
        return author


def lnfn_name_from_dict(author):
    if isinstance(author, dict):
        return "{family}, {given}".format(**author)
    else:
        return author


def pretty_author_list(authors):
    return "; ".join(fnln_name_from_dict(author) for author in authors)


def bibtex_author_list(authors):
    return " and ".join(latex_escape(lnfn_name_from_dict(author)) for author in authors)


def bibtex_capitalize(title):
    out_words = []

    # For this logic, we need Hyphenated-Words to be considered
    # separately, but obviously re-combined correctly

    words_and_seps = re.split(r'([\s\-])', title)
    for word in words_and_seps:
        if any(x.isupper() for x in word[1:]):
            out_words += ["{%s}" % word]
        else:
            out_words += [word]
    return "".join(out_words)


def to_isodate(date):
    return date.isoformat()


def to_prettydate(date):
    return date.strftime("%B %d, %Y")


def respace(text):
    splits = re.split(r'\n\n+', text)
    return "\n\n".join(
        textwrap.fill(s, width=75, break_long_words=False, break_on_hyphens=False) for s in splits)


def safe_css(id):
    replace = re.sub(r'[^a-zA-Z0-9\-]', '', id)
    if replace != id:
        return "safe-css-{}".format(replace)
    else:
        # Can't start with a number
        if re.match(r'^[0-9]', id):
            return "n{}".format(replace)
        else:
            return id


def list_of_pdbs(pdbs):
    rcsb_fmt = "http://www.rcsb.org/pdb/explore/explore.do?structureId={code}"
    lines = []
    for pdb in pdbs:
        if isinstance(pdb, dict):
            if 'code' in pdb:
                pdb_d = pdb
                if 'href' not in pdb_d:
                    pdb_d['href'] = rcsb_fmt.format(code=pdb_d['code'])
                if 'description' in pdb_d:
                    pdb_d['desc'] = pdb_d['description']
            else:
                pdb_d = {'code': '{}'.format(pdb)}
        else:
            pdb_d = {'code': '{}'.format(pdb), 'href': rcsb_fmt.format(code=pdb)}

        if 'href' in pdb_d:
            line = '<a href="{href}">{code}</a>'.format(**pdb_d)
        else:
            line = '{code}'.format(**pdb_d)

        if 'desc' in pdb_d:
            line = "{line} ({desc})".format(line=line, desc=pdb_d['desc'])

        lines += [line]
    return ', '.join(lines)


def markdownify(text, entries):
    def _replace1(ma):
        ident, _doi_ident, _arxiv_ident, _normal_ident, _equals_sign, n = ma.groups()
        if ident not in entries:
            if n is not None:
                return '[{i} (ref. {n})]'.format(i=ident, n=n)
            else:
                return '[{i}]'.format(i=ident)
        if n is not None:
            return '<a href="#{i_css}">{i} (ref. {n})</a>'.format(i_css=safe_css(ident), i=ident, n=n)
        else:
            return '<a href="#{i_css}">{i}</a>'.format(i_css=safe_css(ident), i=ident)

    # [ident] or [ident=111] NOT [ident](...
    text = re.sub(IN_TEXT_CITATION_RE, _replace1, text)

    def _replace2(ma):
        s, href = ma.groups()
        if href.startswith('http'):
            return '<a href="{}">{}</a>'.format(href, s)
        else:
            return '<a href="http://{}">{}</a>'.format(href, s)

    # [text](link) followed by space or punctuation
    text = re.sub(r'\[(.+)\]\(([\w\.\:\/]+)\)(?=[\s\?\.\!])', _replace2, text)

    splits = re.split(r'\n\n+', text)
    return "\n".join('<p class="card-text">{}</p>'.format(s) for s in splits)


def bibtype(key, entries, ulog):
    type_mapping = {
        'journal-article': 'article',
        'unpublished': 'unpublished',
        # TODO: More type mappings. Is there any dx.doi.org documentation for these?
    }
    s = entries[key].get('type', '')
    if s in type_mapping:
        return type_mapping[s]
    if str(s).strip() == "":
        ulog.warn("No type specified for {}. Using `article`".format(key))
        return 'article'
    ulog.warn("Unknown type `{}` specified for {}".format(s, key))
    return str(s)


def latex_escape(s):
    # http://stackoverflow.com/questions/16259923/
    # http://stackoverflow.com/a/4580132
    conv = {'&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_', '{': r'\{', '}': r'\}',
            '~': r'\textasciitilde{}', '^': r'\^{}', '\\': r'\textbackslash{}', '<': r'\textless',
            '>': r'\textgreater',
            # no breaking space
            '\u00A0': '~',
            }
    accents = dict([
        # Grave accents
        (u"à", "\\`a"), (u"è", "\\`e"), (u"ì", "\\`\\i"), (u"ò", "\\`o"), (u"ù", "\\`u"), (u"ỳ", "\\`y"),
        (u"À", "\\`A"), (u"È", "\\`E"), (u"Ì", "\\`\\I"), (u"Ò", "\\`O"), (u"Ù", "\\`U"), (u"Ỳ", "\\`Y"),
        (u"á", "\\'a"),
        # Acute accent
        (u"é", "\\'e"), (u"í", "\\'\\i"), (u"ó", "\\'o"), (u"ú", "\\'u"), (u"ý", "\\'y"), (u"Á", "\\'A"),
        (u"É", "\\'E"), (u"Í", "\\'\\I"), (u"Ó", "\\'O"), (u"Ú", "\\'U"), (u"Ý", "\\'Y"), (u"â", "\\^a"),
        # Circumflex
        (u"ê", "\\^e"), (u"î", "\\^\\i"), (u"ô", "\\^o"), (u"û", "\\^u"), (u"ŷ", "\\^y"), (u"Â", "\\^A"),
        (u"Ê", "\\^E"), (u"Î", "\\^\\I"), (u"Ô", "\\^O"), (u"Û", "\\^U"), (u"Ŷ", "\\^Y"), (u"ä", "\\\"a"),
        # Umlaut or dieresis
        (u"ë", "\\\"e"), (u"ï", "\\\"\\i"), (u"ö", "\\\"o"), (u"ü", "\\\"u"), (u"ÿ", "\\\"y"), (u"Ä", "\\\"A"),
        (u"Ë", "\\\"E"), (u"Ï", "\\\"\\I"), (u"Ö", "\\\"O"), (u"Ü", "\\\"U"), (u"Ÿ", "\\\"Y"), (u"ç", "\\c{c}"),
        # Cedilla
        (u"Ç", "\\c{C}"), (u"œ", "{\\oe}"),
        # Ligatures
        (u"Œ", "{\\OE}"), (u"æ", "{\\ae}"), (u"Æ", "{\\AE}"), (u"å", "{\\aa}"), (u"Å", "{\\AA}"), (u"–", "--"),
        # Dashes
        (u"—", "---"), (u"ø", "{\\o}"),
        # Misc latin-1 letters
        (u"Ø", "{\\O}"), (u"ß", "{\\ss}"), (u"¡", "{!`}"), (u"¿", "{?`}"), (u"\\", "\\\\"),
        # Characters that should be quoted
        (u"~", "\\~"), (u"&", "\\&"), (u"$", "\\$"), (u"{", "\\{"), (u"}", "\\}"), (u"%", "\\%"), (u"#", "\\#"),
        (u"_", "\\_"), (u"≥", "$\\ge$"),
        # Math operators
        (u"≤", "$\\le$"), (u"≠", "$\\neq$"), (u"©", "\copyright"),
        # Misc
        (u"ı", "{\\i}"), (u"µ", "$\\mu$"), (u"°", "$\\deg$"), (u"‘", "`"),
        # Quotes
        (u"’", "'"), (u"“", "``"), (u"”", "''"), (u"‚", ","), (u"„", ",,"),
    ])
    for k in accents:
        # This extra bracketing is necessary for bibtex
        accents[k] = "{%s}" % accents[k]
    conv.update(accents)

    regex = re.compile('|'.join(re.escape(key) for key in sorted(conv.keys(), key=lambda item: - len(item))))
    return regex.sub(lambda match: conv[match.group()], s)


# Rendering is straightforward application of jinja2. Note that we have
# to pass a sorted list of ident's (keys to the entries dictionary)

def sort_entry_date(entries, k):
    entry = entries[k]
    if 'published-online' in entry:
        return entry['published-online']
    if 'published-print' in entry:
        return entry['published-print']
    log.warn("Missing date for {}".format(k))
    return datetime.date(1970, 1, 1)


def sort_entry_title(entries, k):
    entry = entries[k]
    if 'title' in entry:
        return entry['title']
    log.warn("Missing title for {} (for sorting)".format(k))
    return "zzzz"


def sort_entry_key(entries, k):
    return sort_entry_date(entries, k), sort_entry_title(entries, k)


def is_stubbable(ident):
    return ident.startswith("doi:") or ident.startswith("arxiv:")


def stub(ident, *, session, ulog):
    my_meta = {}
    if ident.startswith('doi:'):
        my_meta['doi'] = ident[len('doi:'):]
    elif ident.startswith('arxiv:'):
        my_meta['arxiv'] = ident[len('arxiv:'):]
    else:
        raise ValueError("Not stubbable")

    ulog.info("Creating a stub for {}".format(ident))
    return ident, _internal_representation(ident, my_meta, session=session, ulog=ulog)


def extract_citations_from_description(text, *, ulog):
    cites = []
    references = []
    # [ident] or [ident=111] NOT [ident](...
    for ma in re.finditer(IN_TEXT_CITATION_RE, text):
        i, _doi_ident, _arxiv_ident, _normal_ident, _equals_sign, n = ma.groups()
        if n is not None:
            # If no number is specified, we don't want it to show up in the references table
            cites += [{'id': i, 'num': n}]
            ulog.debug('Extracted citation for {} numbered {}'.format(i, n))
        else:
            references += [{'id': i}]
            ulog.debug("Extracted a reference to {}".format(i))
    return cites, references


def resolve_short_description_crossrefs(text, ident, entry, *, ulog):
    def _replace1(ma):
        num = int(ma.groups()[0])
        if not 'cites' in entry:
            ulog.warn("{} uses short description references for ref {} "
                      "but doesn't have citations listed".format(ident, num))
            return "(ref. {n})".format(n=num)

        for cite in entry['cites']:
            if 'num' in cite and 'id' in cite and cite['num'] == int(num):
                return "[{i}={n}]".format(i=cite['id'], n=num)

        ulog.warn("{} uses short description references for ref {} "
                  "but this citation wasn't found in the citation list".format(ident, num))
        return "(ref. {n})".format(n=num)

    # [ident] or [ident=111] NOT [ident](...
    text = re.sub(SHORT_IN_TEXT_CITATION_RE, _replace1, text)
    return text


def resolve_crossrefs(entries, *, session, ulog):
    # TODO: Maybe do (a subset of the markdownification) here and
    # TODO: also add those things to cites / do error checking / whatever
    stubs = []
    for ident, entry in entries.items():
        if 'description' in entry:
            ulog.debug("Trying to extract references from {}'s description".format(ident))
            cites, references = extract_citations_from_description(entry['description'], ulog=ulog)
            if len(cites) > 0:
                if 'cites' in entry:
                    entry['cites'] += cites
                else:
                    entry['cites'] = cites

            if len(references) > 0:
                if 'references' in entry:
                    entry['references'] += references
                else:
                    entry['references'] = references

        if 'cites' in entry:
            ulog.debug("Processing citations for {}".format(ident))
            for cite in entry['cites']:
                if 'id' in cite:
                    if cite['id'] in entries:
                        cite['resolved'] = True
                    else:
                        if is_stubbable(cite['id']):
                            stubs += [stub(cite['id'], session=session, ulog=ulog)]
                            cite['resolved'] = True
                        else:
                            cite['resolved'] = False
                else:
                    ulog.warn("{}'s citation doesn't contain `id`: {}".format(ident, cite))

        if 'references' in entry:
            ulog.debug("Processing crossreferences for {}".format(ident))
            for ref in entry['references']:
                if ref['id'] in entries:
                    ref['resolved'] = True
                else:
                    ulog.warn("{}'s reference to {} is unresolved".format(ident, ref['id']))
                    ref['resolved'] = False

        if 'description' in entry:
            entry['description'] = resolve_short_description_crossrefs(entry['description'], ident, entry, ulog=ulog)

    entries.update(dict(stubs))
    return entries


def render_all(entries, should_be_true, *, ulog):
    if not should_be_true:
        ulog.error("When using `all` output, set it to `True`")
        return {}
    return sorted(entries.keys())


def render_categories(entries, want_tags, *, ulog):
    matching_idents = []
    for ident, entry in entries.items():
        its_tags = entry.get('tags', [])
        for it in its_tags:
            if it in want_tags:
                matching_idents += [ident]
    return matching_idents


def _render_tree(node_ident, entries, matching_entries, ulog):
    # Deprecated
    node = entries[node_ident]
    matching_entries[node_ident] = node
    if 'cites' in node:
        for cite in node['cites']:
            if 'resolved' in cite and cite['resolved']:
                _render_tree(cite['id'], entries, matching_entries, ulog)
            else:
                if 'id' in cite:
                    ulog.warn("{}'s unresolved citation {} won't be included in the `tree` output."
                              .format(node_ident, cite['id']))
    return matching_entries


def render_tree(entries, root, *, ulog):
    # Deprecated
    matching_entries = dict()
    matching_entries = _render_tree(root, entries, matching_entries, ulog)
    return matching_entries


def _descendants(ident, entries, out_idents, *, ulog):
    node = entries[ident]
    if 'cites' in node:
        for cite in node['cites']:
            if 'resolved' in cite and cite['resolved']:
                out_idents.add(cite['id'])
                _descendants(cite['id'], entries, out_idents, ulog=ulog)
            else:
                if 'id' in cite:
                    ulog.warn("{}'s unresolved citation {} won't be included as a descendant."
                              .format(ident, cite['id']))

    return out_idents


def descendants(idents, entries, *, ulog):
    out_idents = set()
    for ident in idents:
        out_idents.update(_descendants(ident, entries, out_idents, ulog=ulog))
    return sorted(out_idents)


def render_by_input_filename(entries, input_fn, *, ulog):
    idents = []
    for k, v in entries.items():
        if v.get('input_fn', None) == input_fn:
            idents += [k]
    return idents


class Renderfunc:
    def __init__(self, fn, fext, list_of_idents, entries, ulog):
        env = Environment(loader=PackageLoader('gitbib'))
        env.filters['latex_escape'] = latex_escape
        env.filters['bibtype'] = lambda k: bibtype(k, entries, ulog)
        env.filters['pretty_author_list'] = pretty_author_list
        env.filters['bibtex_author_list'] = bibtex_author_list
        env.filters['bibtex_capitalize'] = bibtex_capitalize
        env.filters['to_isodate'] = to_isodate
        env.filters['to_prettydate'] = to_prettydate
        env.filters['respace'] = respace
        env.filters['safe_css'] = safe_css
        env.filters['list_of_pdbs'] = list_of_pdbs
        env.filters['markdownify'] = lambda s: markdownify(s, entries)

        sorted_tags = sorted(set(
            itertools.chain.from_iterable(entries[k].get('tags', [])
                                          for k in itertools.chain.from_iterable(list_of_idents))))

        idents_by_tag = {tag: [k for k in itertools.chain.from_iterable(list_of_idents)
                               if tag in entries[k].get('tags', [])]
                         for tag in sorted_tags}

        list_of_sorted_ids = []
        for idents in list_of_idents:
            sorted_idents = sorted(idents, reverse=True, key=lambda k: sort_entry_key(entries, k))
            list_of_sorted_ids += [sorted_idents]

        self.fn = fn
        self.fext = fext
        self.env = env
        self.entries = entries
        self.list_of_sorted_ids = list_of_sorted_ids
        self.all_tags = sorted_tags
        self.idents_by_tag = idents_by_tag

    def __call__(self, out_f, user_info):
        template = self.env.get_template('template.{}'.format(self.fext))
        out_f.write(template.render(
            fn=self.fn,
            entries=self.entries,
            list_of_idents=self.list_of_sorted_ids,
            idents_by_tag=self.idents_by_tag,
            all_tags=self.all_tags,
            user_info=user_info,
        ).encode())


class IndexRenderfunc:
    def __init__(self, out_config, out_fmts):
        env = Environment(loader=PackageLoader('gitbib'))
        self.env = env
        self.out_config = out_config
        self.out_fmts = out_fmts

    def __call__(self, out_f, user_info):
        template = self.env.get_template('index.html')
        out_f.write(template.render(
            out_fmts=self.out_fmts,
            out_config=self.out_config,
        ).encode())


class Gitbib:
    def __init__(self, *, session, user_logger, repo_dir=".", gitbib_yaml_fn='gitbib.yaml'):
        ulog = user_logger
        ulog.debug("Connected to logging.")
        unknown_err_str = "An unknown error occured ({}): {} ({}). Please alert the developers"
        try:
            config, my_meta = read_yamls(repo_dir, gitbib_yaml_fn, ulog=ulog)
        except GitbibFileNotFoundError as e:
            ulog.error("Gitbib file not found. Are you sure this is a gitbib repository?")
            raise e
        except DuplicateKeyError as e:
            ulog.error("Found a duplicate key: `{}`. Keys must be unique.".format(e.duplicate_key))
            raise e
        except Exception as e:
            ulog.error(unknown_err_str.format(1, e, type(e)))
            raise e

        try:
            entries = internal_representation(my_meta, session=session, ulog=ulog)
        except Exception as e:
            ulog.error(unknown_err_str.format(2, e, type(e)))
            raise e

        try:
            entries = resolve_crossrefs(entries, session=session, ulog=ulog)
        except Exception as e:
            ulog.error(unknown_err_str.format(3, e, type(e)))
            raise e

        self.entries = entries
        self.config = config

    out_render_types = {
        'all': render_all,
        'categories': render_categories,
        'input-fn': render_by_input_filename,
    }

    out_render_formats = {
        'html': 'text/html',
        'bib': 'application/x-bibtex',
        'tex': 'application/x-latex',
        'md': 'text/markdown',
    }

    def renderers(self, out_formats, user_logger):
        ulog = user_logger
        fns = set()
        out_formats = set(out_formats)
        for out_spec in self.config['outputs']:
            if 'fn' not in out_spec:
                ulog.error("No output filename given: {}".format(out_spec))
                continue
            fn = out_spec['fn']
            if not re.match(r'[\w\-\.]+$', fn):
                ulog.error("Please use a filename that is only alphanumeric characters. Not {}".format(fn))
                continue
            if fn in fns:
                ulog.error("Duplicate output filename! {}".format(fn))
                continue
            fns.add(fn)

            n_out_types = 0
            out_type = None
            for ot in self.out_render_types:
                if ot in out_spec:
                    n_out_types += 1
                    out_type = ot
            if n_out_types > 1:
                ulog.error("Too many output specifications given for {}".format(fn))
                continue
            if n_out_types < 1:
                ulog.error("No output specification given for {}".format(fn))
                continue

            idents = self.out_render_types[out_type](self.entries, out_spec[out_type], ulog=ulog)
            list_of_idents = [idents]
            if out_type in ['all']:
                if 'include_descendants' in out_spec:
                    ulog.warn("`include_descendants` option is ignored for output type `{}`".format(out_type))
            else:
                include_descendants = out_spec.get('include_descendants', False)
                if include_descendants:
                    list_of_idents += [descendants(idents, self.entries, ulog=ulog)]

            if len(idents) > 0:
                for ofmt in out_formats:
                    yield "{}.{}".format(fn, ofmt), self.out_render_formats[ofmt], Renderfunc(fn, ofmt, list_of_idents,
                                                                                              self.entries, ulog=ulog)
            else:
                ulog.warn("No entries matched the specification for {}".format(fn))

        yield "index.html", "text/html", IndexRenderfunc(self.config, out_formats)
