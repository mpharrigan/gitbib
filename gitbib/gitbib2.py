import datetime
import os
from collections import defaultdict
from dataclasses import dataclass, asdict, astuple, replace
from textwrap import TextWrapper
from typing import Dict, Any, Optional, List, Tuple, Union, Iterable

import networkx as nx
import yaml
from sqlalchemy.orm.exc import NoResultFound
from fuzzywuzzy import fuzz

from gitbib.cache import Crossref, Arxiv, Cache
from gitbib.command_line import ConsoleLogger
from gitbib.description import parse_description, Description, Citation as DescriptionCitation, \
    parse_abstract
from gitbib.gitbib import _fetch_crossref, _fetch_arxiv, NoCrossref, NoArxiv, \
    _container_title_logic, yaml_indent, latex_escape, bibtype, pretty_author_list, \
    bibtex_author_list, bibtex_capitalize, to_isodate, to_prettydate, respace, safe_css, \
    list_of_pdbs, markdownify, CROSSREF_TO_BIB_TYPE


def get_and_cache_crossref(doi, *, session, ulog, ident):
    try:
        crossref = session.query(Crossref).filter(Crossref.doi == doi).one()
        ulog.debug("{}'s entry was cached via doi/crossref".format(ident))
        return crossref.data
    except NoResultFound:
        try:
            ulog.info("Fetching data for {} via doi/crossref".format(ident))
            crossref_data = _fetch_crossref(doi=doi)
            crossref = Crossref(doi=doi, data=crossref_data)
            session.add(crossref)
            return crossref_data
        except NoCrossref:
            ulog.error("A doi was given for {}, but the crossref request failed!".format(ident))
            return None


def get_and_cache_arxiv(arxivid, *, session, ulog, ident):
    try:
        arxiv = session.query(Arxiv).filter(Arxiv.arxivid == arxivid).one()
        ulog.debug("{}'s entry was cached via arxiv".format(ident))

        if False:  # TODO!
            session.delete(arxiv)
            raise NoResultFound("Invalidating!")

        return arxiv.data
    except NoResultFound:
        try:
            ulog.info("Fetching data for {} via arxiv".format(ident))
            arxiv_data = _fetch_arxiv(arxivid)
            session.add(Arxiv(arxivid=arxivid, data=arxiv_data))
            return arxiv_data
        except NoArxiv:
            ulog.error("An arxiv id was given for {}, "
                       "but we couldn't get the data!".format(ident))
            return None


@dataclass
class RawEntry:
    user_data: Dict[str, Any]
    crossref_data: Optional[Dict[str, Any]] = None
    arxiv_data: Optional[Dict[str, Any]] = None

    @property
    def ident(self):
        return self.user_data.get('ident', self.__str__())


@dataclass(frozen=True)
class Author:
    given: str
    family: str


DateTuple = Tuple[int, int, int]


@dataclass(frozen=True)
class ContainerTitle:
    full_name: Optional[str]
    short_name: Optional[str]


@dataclass(frozen=True)
class TargetIdent:
    ident: str
    target_type: str


@dataclass(frozen=True)
class Citation:
    target_ident: TargetIdent
    num: Optional[Union[int, str]]
    why: Optional[str]


@dataclass(frozen=True)
class Entry:
    ident: str
    fn: str
    title: str
    authors: List[Author]
    type: str
    published_online: Optional[DateTuple]
    published_print: Optional[DateTuple]
    container_title: Optional[ContainerTitle]
    volume: Optional[int]
    issue: Optional[int]
    page: Optional[Tuple[int, int]]
    url: Optional[str]
    doi: Optional[str]
    arxiv: Optional[str]
    pdf: Optional[str]
    description: Optional[Description]
    abstract: Optional[Description]
    cites: List[Citation]
    tags: List[str]

    @property
    def first_published(self):
        if self.published_online is None and self.published_print is None:
            return (0, 0, 0)

        if self.published_online is not None and self.published_print is None:
            return self.published_online

        if self.published_print is not None and self.published_online is None:
            return self.published_print

        return min(self.published_online, self.published_print)


def merge_ident(entry: RawEntry) -> str:
    ident = entry.user_data['ident']
    assert ident is not None
    assert isinstance(ident, str)
    assert len(ident) > 0
    return ident


def merge_fn(entry: RawEntry) -> str:
    fn = entry.user_data['fn']
    assert fn is not None
    assert isinstance(fn, str)
    assert len(fn) > 0
    return fn


def merge_title(entry: RawEntry, *, ulog) -> str:
    title = None
    if entry.crossref_data is not None:
        title = entry.crossref_data['title']
        if len(title) > 1:
            print(f"Crossref has returned multiple titles for {entry.ident}: {title}")
        if len(title) == 0:
            print(f"Crossref has returned no title for {entry.ident}")
            title = None
        else:
            title = title[0]
            assert isinstance(title, str)
            assert len(title) > 0

    if entry.arxiv_data is not None:
        arxiv_title = entry.arxiv_data['title']
        if title is not None:
            if fuzz.ratio(arxiv_title, title) < 90:
                ulog.warn(f"Titles for {entry.ident} differ: {title} vs {arxiv_title}")
        else:
            assert isinstance(arxiv_title, str)
            assert len(arxiv_title) > 0
            title = arxiv_title

    if 'title' in entry.user_data:
        if title is not None:
            ulog.warn(f"Using user-specified title for {entry.ident}: "
                      f"{title} vs {entry.user_data['title']}")
        title = entry.user_data['title']

    if title is None:
        ulog.error(f"No title for {entry.ident}")
        title = ''

    return title


def merge_authors(entry, *, ulog) -> List[Author]:
    if entry.crossref_data is not None and 'author' in entry.crossref_data:
        crossref_authors = entry.crossref_data['author']
        return [Author(given=author.get('given', ''),
                       family=author.get('family', ''))
                for author in crossref_authors]

    if entry.arxiv_data is not None:
        authors = []
        for a in entry.arxiv_data['authors']:
            splits = a.split()
            if len(splits) > 1:
                authors += [
                    {'given': ' '.join(splits[:-1]), 'family': splits[-1]}
                ]
            else:
                authors += [{'family': splits[0]}]
        return [Author(given=author['given'],
                       family=author['family'])
                for author in authors]

    if 'author' in entry.user_data:
        author_spec = entry.user_data['author']
        if isinstance(author_spec, str):
            ulog.warn("{}'s `author` field should be a list")
            return []

        new_auths = []
        for a in author_spec:
            if isinstance(a, dict):
                new_auths += [a]
            elif isinstance(a, str):
                if ',' in a:
                    splits = [s.strip() for s in a.split(',')]
                    new_auths += [{'family': splits[0], 'given': splits[1]}]
                else:
                    splits = a.split()
                    new_auths += [{'family': splits[-1], 'given': ' '.join(splits[:-1])}]
        return [Author(given=author['given'],
                       family=author['family'])
                for author in new_auths]

    return []


def merge_type(entry, *, ulog) -> str:
    if 'type' in entry.user_data:
        return entry.user_data['type']

    if entry.crossref_data is not None:
        return entry.crossref_data['type']

    return 'article'


def merge_published_online(entry) -> Optional[DateTuple]:
    crossref_date = None
    arxiv_date = None

    if entry.crossref_data is not None and 'published-online' in entry.crossref_data:
        crossref_date = entry.crossref_data['published-online']['date-parts']
        assert len(crossref_date) == 1, 'crossref randomly puts a list here'
        crossref_date = tuple(crossref_date[0])

    if entry.arxiv_data is not None and 'published' in entry.arxiv_data:
        arxiv_date = entry.arxiv_data['published']
        arxiv_date = datetime.datetime.strptime(arxiv_date, '%Y-%m-%dT%H:%M:%SZ').date()
        arxiv_date = (arxiv_date.year, arxiv_date.month, arxiv_date.day)

    if crossref_date is None and arxiv_date is None:
        return None
    elif crossref_date is not None and arxiv_date is not None:
        if crossref_date == arxiv_date:
            return crossref_date
        # judgement call: published online gets first date
        return min(crossref_date, arxiv_date)
    elif crossref_date is not None:
        return crossref_date
    elif arxiv_date is not None:
        return arxiv_date

    raise ValueError()


def merge_published_print(entry) -> Optional[DateTuple]:
    if entry.crossref_data is not None and 'published-print' in entry.crossref_data:
        crossref_date = entry.crossref_data['published-print']['date-parts']
        assert len(crossref_date) == 1, 'crossref randomly puts a list here'
        crossref_date = crossref_date[0]
        return tuple(crossref_date)


def merge_container_title(entry, *, ulog) -> Optional[ContainerTitle]:
    if entry.crossref_data is not None and 'container-title' in entry.crossref_data:
        crossref_ctitles = entry.crossref_data['container-title']
        crossref_shortctitles = entry.crossref_data['short-container-title']

        if len(crossref_ctitles) == 0 and len(crossref_shortctitles) == 0:
            # No titles whatsoever
            return

        if len(crossref_ctitles) == 1 and len(crossref_shortctitles) == 0:
            # Cross-ref says there's no short title.
            return ContainerTitle(
                full_name=crossref_ctitles[0],
                short_name=None,
            )

        if len(crossref_ctitles) > 1 and len(crossref_shortctitles) == 0:
            ulog.warn(f"Multiple container titles: {entry.user_data['ident']}: {crossref_ctitles}")
            return ContainerTitle(
                full_name=crossref_ctitles[0],
                short_name=None
            )

        if len(crossref_ctitles) == 1 and len(crossref_shortctitles) == 1:
            # Best case: crossref tells us what we want
            return ContainerTitle(
                full_name=crossref_ctitles[0],
                short_name=crossref_shortctitles[0],
            )

        if len(crossref_ctitles) == 1 and len(crossref_shortctitles) > 1:
            # Case-by-case basis.
            ulog.warn(f"Multiple short titles {crossref_shortctitles} for {crossref_ctitles[0]}")

            # It seems we can just take the first...
            return ContainerTitle(
                full_name=crossref_ctitles[0],
                short_name=crossref_shortctitles[0],
            )

        ulog.error(f"Unhandled container-title logic {crossref_ctitles} {crossref_shortctitles}")


def merge_volume(entry) -> Optional[int]:
    if entry.crossref_data is not None and 'volume' in entry.crossref_data:
        try:
            return int(entry.crossref_data['volume'])
        except ValueError as e:
            print(f"Unknown volume {e}")
            return None


def merge_issue(entry) -> Optional[int]:
    if entry.crossref_data is not None and 'issue' in entry.crossref_data:
        if '-' in entry.crossref_data['issue']:
            return int(entry.crossref_data['issue'].split('-')[0])
        try:
            return int(entry.crossref_data['issue'])
        except ValueError as e:
            print(f"Unknown issue {e}")
            return None


def merge_page(entry) -> Optional[Tuple[int, int]]:
    if entry.crossref_data is not None and 'page' in entry.crossref_data:
        pages = entry.crossref_data['page'].split('-')
        if len(pages) == 1:
            try:
                p = int(pages[0])
            except ValueError:
                return None
            return p, p
        elif len(pages) == 2:
            try:
                return int(pages[0]), int(pages[1])
            except ValueError as e:
                print(f"Unknown pages {e}")
                return None
        else:
            raise ValueError(pages)


def merge_url(entry) -> Optional[str]:
    if entry.crossref_data is not None and 'url' in entry.crossref_data:
        return entry.crossref_data['url']


def merge_doi(entry) -> Optional[str]:
    if entry.crossref_data is not None and 'DOI' in entry.crossref_data:
        return entry.crossref_data['DOI']


def merge_arxiv(entry) -> Optional[str]:
    # TODO: arxiv_data should have arxivid
    if 'arxiv' in entry.user_data:
        return entry.user_data['arxiv']


def merge_pdf(entry) -> Optional[str]:
    if 'pdf' in entry.user_data:
        return entry.user_data['pdf']


def merge_description(entry) -> Optional[Description]:
    if 'description' in entry.user_data:
        return parse_description(entry.user_data['description'])


def merge_abstract(entry) -> Optional[Description]:
    if entry.arxiv_data is not None and 'summary' in entry.arxiv_data:
        return parse_abstract(entry.arxiv_data['summary'])


def merge_cites(entry) -> List[Citation]:
    cites = []

    if entry.crossref_data is not None and 'reference' in entry.crossref_data:
        for ref in entry.crossref_data['reference']:
            if 'DOI' not in ref:
                continue
            cites.append(Citation(
                target_ident=TargetIdent(ident=ref['DOI'], target_type='doi'),
                num=None,  # TODO: try to get this from crossref
                why='crossref',
            ))

    if 'cites' in entry.user_data:
        for cite in entry.user_data['cites']:
            cites.append(Citation(
                target_ident=TargetIdent(ident=cite['id'], target_type='ident'),
                num=cite.get('num', None),
                why=cite.get('why', None),
            ))

    return cites


def merge_tags(entry):
    return []


def _load_user_data(fns, *, ulog):
    for fn in fns:
        with open(f'{fn}.yaml') as f:
            for ident, user_data in yaml.load(f).items():
                user_data['ident'] = ident
                user_data['fn'] = fn

                pdf_fn = f'pdfs/{ident}.pdf'
                if os.path.isfile(pdf_fn):
                    user_data['pdf'] = pdf_fn

                yield RawEntry(user_data=user_data)


def _fetch_data_for_user_spec_id(entry, *, session, ulog):
    ident = entry.user_data['ident']
    if 'doi' in entry.user_data:
        entry.crossref_data = get_and_cache_crossref(doi=entry.user_data['doi'],
                                                     ulog=ulog, session=session,
                                                     ident=ident)
    if 'arxiv' in entry.user_data:
        entry.arxiv_data = get_and_cache_arxiv(arxivid=entry.user_data['arxiv'],
                                               ulog=ulog, session=session, ident=ident)

    return entry


def _fetch_data_for_fetched_id(entry, *, session, ulog):
    ident = entry.user_data['ident']

    # 3.1 arxiv -> crossref
    if entry.arxiv_data is not None:
        if 'doi' in entry.arxiv_data:
            doi = entry.arxiv_data['doi']
            if entry.crossref_data is not None and doi.lower() != entry.crossref_data[
                'DOI'].lower():
                raise ValueError(f"Inconsistent DOIs: {doi} and {entry.crossref_data['DOI']}")

            if entry.crossref_data is None:
                entry.crossref_data = get_and_cache_crossref(doi=doi,
                                                             ulog=ulog, session=session,
                                                             ident=ident)

    # 3.2 crossref -> arxiv (TODO)
    pass

    return entry


def _resolve_doi_cites(entry: Entry, by_doi: Dict[str, Entry]) -> Entry:
    if entry.cites is None:
        return entry

    new_cites = []
    for cite in entry.cites:
        if cite.target_ident.target_type == 'doi' and cite.target_ident.ident in by_doi:
            new_cite = replace(cite, target_ident=TargetIdent(
                ident=by_doi[cite.target_ident.ident].ident,
                target_type='ident',
            ))
        else:
            new_cite = cite
        new_cites += [new_cite]
    return replace(entry, cites=new_cites)


def _configure(*, cache_url: str = 'sqlite:///cache.sqlite', logger_type: str = 'console'):
    c = Cache(cache_url)
    if logger_type == 'console':
        ulog = ConsoleLogger(20)
    else:
        raise ValueError(f"Unknown logger_type {logger_type:!r}")
    return c, ulog


def main(fns: List[str],
         *,
         cache_url: str = 'sqlite:///cache.sqlite',
         logger_type: str = 'console',
         ):
    c, ulog = _configure(cache_url=cache_url, logger_type=logger_type)

    # 1. User data
    entries = list(_load_user_data(fns, ulog=ulog))

    # 2. Fetch data given by user-specified ids.
    with c.scoped_session() as session:
        entries = [_fetch_data_for_user_spec_id(entry, session=session, ulog=ulog) for entry in
                   entries]

    # 3. Fetch data given by fetched ids
    with c.scoped_session() as session:
        entries = [_fetch_data_for_fetched_id(entry, session=session, ulog=ulog) for entry in
                   entries]

    # 4. Merge data and convert to internal representation
    entries = [Entry(
        ident=merge_ident(entry),
        fn=merge_fn(entry),
        title=merge_title(entry, ulog=ulog),
        authors=merge_authors(entry, ulog=ulog),
        type=merge_type(entry, ulog=ulog),
        published_online=merge_published_online(entry),
        published_print=merge_published_print(entry),
        container_title=merge_container_title(entry, ulog=ulog),
        volume=merge_volume(entry),
        issue=merge_issue(entry),
        page=merge_page(entry),
        url=merge_url(entry),
        doi=merge_doi(entry),
        arxiv=merge_arxiv(entry),
        pdf=merge_pdf(entry),
        description=merge_description(entry),
        abstract=merge_abstract(entry),
        cites=merge_cites(entry),
        tags=merge_tags(entry),
    ) for entry in entries]
    indices = _create_indices(entries)

    # 6. Resolve doi citations to indent, where possible
    entries = [_resolve_doi_cites(entry, indices.by_doi) for entry in entries]

    # 4. Extract citations from description
    for entry in entries:
        if entry.description is None:
            continue
        for para in entry.description.paragraphs:
            for part in para.parts:
                if isinstance(part, DescriptionCitation):
                    citation = Citation(
                        target_ident=TargetIdent(
                            ident=part.ident,
                            target_type='ident'),
                        num=part.num,
                        why='description'
                    )
                    if citation not in entry.cites:
                        entry.cites.append(citation)
    indices = _create_indices(entries)

    # 5. Link
    cite_network = nx.DiGraph()
    for entry in entries:
        if entry.cites is not None:
            for cite in entry.cites:
                t = cite.target_ident
                if t.target_type not in ['doi', 'arxivid', 'ident']:
                    raise ValueError(f"Unknown citation target type {t}")
                if t.target_type == 'doi' and t.ident in indices.by_doi:
                    cite_network.add_edge(entry.ident, indices.by_doi[t.ident].ident)
                elif t.target_type == 'arxivid' and t.ident in indices.by_arxivid:
                    cite_network.add_edge(entry.ident, indices.by_arxivid[t.ident].ident)
                elif t.target_type == 'ident' and t.ident in indices.by_ident:
                    cite_network.add_edge(entry.ident, indices.by_ident[t.ident].ident)

    indices = _create_indices_2(indices, cite_network)

    # 7. [WIP] output
    with open('quantum.json', 'w') as f:
        import json
        json.dump([asdict(entry) for entry in entries], f, indent=2)

    try:
        from matplotlib import pyplot as plt
        for con in nx.weakly_connected_components(cite_network):
            nx.draw_networkx(cite_network.subgraph(con))
            plt.show()
    except ImportError:
        pass

    return entries, indices, cite_network


def _quote(x):
    return f'"{x}"'


def _id(x):
    return x


def _yaml_list(xs: Iterable[str]):
    return '\n' + '\n'.join('    - {}'.format(x) for x in xs)


def _yaml_title(x: str):
    x = _quote(x)
    if len(x) + len("  title: ") > 82:
        return TextWrapper(width=80,
                           subsequent_indent=" " * len('  title: "'),
                           break_long_words=False).fill(x)
    return x


class AuthorWrapper(TextWrapper):
    def _split_chunks(self, authors: List[Author]):
        chunks = []
        for i, author in enumerate(authors):
            chunk = _quote(' '.join(astuple(author)))
            if i + 1 != len(authors):
                chunk += ', '
            chunks += [chunk]
        return chunks


def _yaml_authors(xs: List[Author]):
    if len(xs) > 7:
        return '[\n' + AuthorWrapper(width=80,
                                     initial_indent=" " * 4,
                                     subsequent_indent=" " * 4,
                                     break_long_words=False) \
            .fill(xs) + ']'

    return _yaml_list(' '.join(astuple(x)) for x in xs)


def _yaml_cites(xs: List[Citation]):
    xs = [x for x in xs if x.target_ident.target_type == 'ident']
    if len(xs) == 0:
        return None

    # This depends on the implementation details of _yaml_list for indent length :(
    def _yaml_cite(x: Citation):
        ret = f'id: {x.target_ident.ident}'
        if x.num is not None:
            ret += f'\n      num: {x.num}'
        if x.why is not None:
            ret += f'\n      why: {x.why}'
        return ret

    return _yaml_list(_yaml_cite(x) for x in xs)


def _yaml_date(xs: DateTuple):
    return '-'.join(str(x) for x in xs)


def _yaml_container_title(x: ContainerTitle):
    if ':' in x.full_name:
        return _quote(x.full_name)
    return x.full_name


YAML_FMT = {
    'title': _yaml_title,
    'arxiv': _quote,
    'doi': _id,
    'authors': _yaml_authors,
    'published_online': _yaml_date,
    'published_print': _yaml_date,
    'container_title': _yaml_container_title,
    'volume': _id,
    'issue': _id,
    'page': _id,
    'url': _id,
    'pdf': _id,
    'cites': _yaml_cites,
    'tags': _id,
}


def to_yaml(entry: Entry):
    ret = f"{entry.ident}:\n"
    for field, ffunc in YAML_FMT.items():
        val = entry.__getattribute__(field)
        if val is not None:
            val = ffunc(val)
            if val is not None:
                ret += f"  {field}: {val}\n"

    if entry.description is not None:
        ret += "  description: |+\n" + yaml_indent(entry.description.yaml(), 4)

    return ret


def to_yaml_files(entries: List[Entry]):
    yamls = defaultdict(lambda: "")
    for entry in entries:
        yamls[entry.fn] += to_yaml(entry) + '\n\n'

    return yamls


def _html_authors(xs: List[Author]):
    return "; ".join(f'{x.given} {x.family}' for x in xs)


def _html_date(xs: DateTuple):
    return '-'.join(str(x) for x in xs)


def _html_container_title(x: ContainerTitle):
    if x.full_name is not None:
        primary = x.full_name
        if x.short_name is not None:
            secondary = f' ({x.short_name})'
        else:
            secondary = ''
    elif x.short_name is not None:
        primary = x.short_name
        secondary = ''
    else:
        return None

    return f'<em>{primary}{secondary}</em>'


HTML_FMT = {
    'title': _id,
    'arxiv': _id,
    'doi': _id,
    'authors': _html_authors,
    'published_online': _html_date,
    'published_print': _html_date,
    'container_title': _html_container_title,
    'volume': _id,
    'issue': _id,
    'page': _id,
    'url': _id,
    'pdf': _id,
    'cites': _yaml_cites,
    'tags': _id,
    'description': lambda x: x.html(),
}


def to_html_file(entries: List[Entry]):
    from jinja2 import Environment, PackageLoader
    env = Environment(loader=PackageLoader('gitbib'), keep_trailing_newline=True)
    env.filters['latex_escape'] = latex_escape
    env.filters['bibtype'] = lambda k: bibtype(k, entries, None)
    env.filters['pretty_author_list'] = pretty_author_list
    env.filters['bibtex_author_list'] = bibtex_author_list
    env.filters['bibtex_capitalize'] = bibtex_capitalize
    env.filters['to_isodate'] = to_isodate
    env.filters['to_prettydate'] = to_prettydate
    env.filters['respace'] = respace
    env.filters['safe_css'] = safe_css
    env.filters['list_of_pdbs'] = list_of_pdbs
    env.filters['markdownify'] = lambda s: markdownify(s, entries)
    for k, func in HTML_FMT.items():
        env.filters[k] = func

    template = env.get_template(f'template2.html')
    default_user_info = {
        'slugname': 'gitbib',
        'index_url': 'index.html',
    }
    return template.render(
        entries=entries,
        all_tags=[],
        user_info=default_user_info,
    )


@dataclass
class Indices:
    by_doi: Dict[str, Entry]
    by_ident: Dict[str, Entry]
    by_arxivid: Dict[str, Entry]
    by_fn: Dict[str, List[Entry]]
    secondary_by_fn: Dict[str, List[Entry]]

    def get_sorted_by_fn(self, fn: str, sort_by: str):
        if sort_by == 'file':
            return self.by_fn[fn]
        if sort_by == 'first_published':
            return sorted(self.by_fn[fn], key=lambda x: x.first_published, reverse=True)
        raise ValueError(f"Unknown `sort_by` {sort_by}")

    def get_sorted_secondary_by_fn(self, fn: str, sort_by: str):
        if sort_by == 'file':
            return self.secondary_by_fn[fn]
        if sort_by == 'first_published':
            return sorted(self.secondary_by_fn[fn], key=lambda x: x.first_published, reverse=True)
        raise ValueError(f"Unknown `sort_by` {sort_by}")


def _create_indices(entries):
    by_doi = {}
    by_ident = {}
    by_arxivid = {}
    by_fn = defaultdict(list)

    def add_with_check(d, k, e, dname):
        if k is None:
            return
        if k in d:
            other_e = d[k]
            print(f"{k} already in {dname}: "
                  f"Trying to add {e.ident} in {e.fn}. "
                  f"Found {other_e.ident} in {other_e.fn}")
            return
        d[k] = e

    for entry in entries:
        add_with_check(by_ident, entry.ident, entry, 'by_ident')
        add_with_check(by_doi, entry.doi, entry, 'by_doi')
        add_with_check(by_arxivid, entry.arxiv, entry, 'by_arxivid')
        by_fn[entry.fn] += [entry]

    return Indices(
        by_doi=by_doi,
        by_ident=by_ident,
        by_arxivid=by_arxivid,
        by_fn=dict(by_fn),
        secondary_by_fn={},
    )


def _create_indices_2(indices: Indices, cite_network: nx.DiGraph):
    secondary_by_fn = {}
    for fn in indices.by_fn:
        secondary = []
        for entry in indices.by_fn[fn]:
            if entry.ident not in cite_network:
                continue

            for child_ident in cite_network.successors(entry.ident):
                child = indices.by_ident[child_ident]
                assert isinstance(child, Entry)
                if child.fn == fn:
                    # Already included in primary
                    continue
                secondary.append(child)
        secondary_by_fn[fn] = secondary
    return Indices(
        by_doi=indices.by_doi,
        by_ident=indices.by_ident,
        by_arxivid=indices.by_arxivid,
        by_fn=indices.by_fn,
        secondary_by_fn=secondary_by_fn
    )


def to_html_files(indices: Indices, sort_by='file'):
    from jinja2 import Environment, PackageLoader
    env = Environment(loader=PackageLoader('gitbib'), keep_trailing_newline=True)
    for k, func in HTML_FMT.items():
        env.filters[k] = func
    env.filters['safe_css'] = safe_css

    template = env.get_template(f'template2.html')
    return {
        fn: template.render(entries1=indices.get_sorted_by_fn(fn, sort_by=sort_by),
                            entries2=indices.get_sorted_secondary_by_fn(fn, sort_by=sort_by))
        for fn in indices.by_fn.keys()
    }


def _bib_title(x: str):
    return latex_escape(bibtex_capitalize(x))


def _bib_authors(xs: List[Author]):
    return " and ".join(latex_escape(f'{x.family}, {x.given}') for x in xs)


def _bib_type(x: str):
    return CROSSREF_TO_BIB_TYPE[x]


def _bib_year(x: DateTuple):
    if x is None:
        return
    return x[0]


def _bib_page(x: Tuple[int, int]):
    if x is None:
        return

    x1, x2 = x
    if x1 == x2:
        return x1

    return f'{x1}--{x2}'


BIB_FMT = {
    'title': _bib_title,
    'arxiv': _quote,
    'doi': _id,
    'authors': _bib_authors,
    'type': _bib_type,
    'published_online': _bib_year,
    'published_print': _bib_year,
    'container_title': _yaml_container_title,
    'volume': _id,
    'issue': _id,
    'page': _bib_page,
    'url': _id,
    'pdf': _id,
    'cites': _yaml_cites,
    'tags': _id,
    'description': lambda x: x.html(),
}


def to_bib_files(indices: Indices):
    from jinja2 import Environment, PackageLoader
    env = Environment(loader=PackageLoader('gitbib'), keep_trailing_newline=True)
    for k, func in BIB_FMT.items():
        env.filters[k] = func

    template = env.get_template(f'template2.bib')
    return {
        fn: template.render(entries1=indices.by_fn[fn],
                            entries2=indices.secondary_by_fn[fn])
        for fn in indices.by_fn.keys()
    }


TEX_FMT = {
    'ident': latex_escape,
    'title': _bib_title,
    'arxiv': _quote,
    'doi': _id,
    'authors': _bib_authors,
    'type': _bib_type,
    'published_online': _yaml_date,
    'published_print': _yaml_date,
    'container_title': _yaml_container_title,
    'volume': _id,
    'issue': _id,
    'page': _id,
    'url': _id,
    'pdf': _id,
    'cites': _yaml_cites,
    'tags': _id,
    'description': lambda x: latex_escape(x.yaml()),
}


def to_tex_files(entries: List[Entry], indices: Indices):
    from jinja2 import Environment, PackageLoader
    env = Environment(loader=PackageLoader('gitbib'), keep_trailing_newline=True)
    for k, func in TEX_FMT.items():
        env.filters[k] = func

    template = env.get_template(f'template2.tex')
    return {
        fn: template.render(entries=indices.by_fn[fn], fn=fn)
        for fn in indices.by_fn.keys()
    }
