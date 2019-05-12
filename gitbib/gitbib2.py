from collections import defaultdict
from dataclasses import dataclass, asdict, astuple, replace
from typing import Dict, Any, Optional, List, Tuple, Union, Iterable

import networkx as nx
import yaml
from sqlalchemy.orm.exc import NoResultFound

from gitbib.cache import Crossref, Arxiv
from gitbib.description import parse_description, Description
from gitbib.gitbib import _fetch_crossref, _fetch_arxiv, NoCrossref, NoArxiv, extract_citations_from_entry, \
    _container_title_logic, yaml_indent


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
    cites: Optional[List[Citation]]
    tags: Optional[List[str]]


def merge_ident(entry: RawEntry):
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


def merge_title(entry: RawEntry, *, ulog):
    title = None
    if entry.crossref_data is not None:
        title = entry.crossref_data['title']
        assert len(title) == 1, 'crossref returning multiple titles for {entry}'
        title = title[0]
        assert isinstance(title, str)
        assert len(title) > 0

    if 'title' in entry.user_data:
        if title is not None:
            ulog.warn("Overwriting crossref title for {entry}")
            title = entry.user_data['title']

    if entry.arxiv_data is not None:
        arxiv_title = entry.arxiv_data['title']
        if title is not None:
            if arxiv_title != title:
                ulog.warn(f"Titles for {entry} differ: {title} vs {arxiv_title}")
        else:
            assert isinstance(arxiv_title, str)
            assert len(arxiv_title) > 0
            title = arxiv_title

    return title


def merge_authors(entry, *, ulog):
    if entry.crossref_data is not None:
        crossref_authors = entry.crossref_data['author']
        return [Author(given=author['given'],
                       family=author['family'])
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
            return None

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

    return None


def merge_published_online(entry):
    if entry.crossref_data is not None and 'published-online' in entry.crossref_data:
        crossref_date = entry.crossref_data['published-online']['date-parts']
        assert len(crossref_date) == 1, 'crossref randomly puts a list here'
        crossref_date = crossref_date[0]
        return tuple(crossref_date)


def merge_published_print(entry):
    if entry.crossref_data is not None and 'published-print' in entry.crossref_data:
        crossref_date = entry.crossref_data['published-print']['date-parts']
        assert len(crossref_date) == 1, 'crossref randomly puts a list here'
        crossref_date = crossref_date[0]
        return tuple(crossref_date)


def merge_container_title(entry, *, ulog):
    if entry.crossref_data is not None and 'container-title' in entry.crossref_data:
        crossref_ctitles = entry.crossref_data['container-title']
        ctitles_dict = _container_title_logic(crossref_ctitles, ulog=ulog)
        return ContainerTitle(
            full_name=ctitles_dict['full'],
            short_name=ctitles_dict['short'],
        )


def merge_volume(entry) -> int:
    if entry.crossref_data is not None and 'volume' in entry.crossref_data:
        return int(entry.crossref_data['volume'])


def merge_issue(entry) -> int:
    if entry.crossref_data is not None and 'issue' in entry.crossref_data:
        return int(entry.crossref_data['issue'])


def merge_page(entry) -> Optional[Tuple[int, int]]:
    # TODO: Tuple[int, int]?
    if entry.crossref_data is not None and 'page' in entry.crossref_data:
        pages = entry.crossref_data['page'].split('-')
        if len(pages) == 1:
            try:
                p = int(pages[0])
            except ValueError:
                return None
            return p, p
        elif len(pages) == 2:
            return int(pages[0]), int(pages[1])
        else:
            raise ValueError(pages)


def merge_url(entry) -> str:
    if entry.crossref_data is not None and 'url' in entry.crossref_data:
        return entry.crossref_data['url']


def merge_doi(entry) -> str:
    if entry.crossref_data is not None and 'DOI' in entry.crossref_data:
        return entry.crossref_data['DOI']


def merge_arxiv(entry):
    # TODO: arxiv_data should have arxivid
    if 'arxiv' in entry.user_data:
        return entry.user_data['arxiv']


def merge_pdf(entry):
    pass


def merge_description(entry) -> Description:
    if 'description' in entry.user_data:
        return parse_description(entry.user_data['description'])


def merge_cites(entry):
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
    pass


def _load_user_data(fns, *, ulog):
    for fn in fns:
        with open(f'{fn}.yaml') as f:
            for ident, user_data in yaml.load(f).items():
                user_data['ident'] = ident
                user_data['fn'] = fn
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
            if entry.crossref_data is not None and doi.lower() != entry.crossref_data['DOI'].lower():
                raise ValueError(f"Inconsistent DOIs: {doi} and {entry.crossref_data['DOI']}")

            if entry.crossref_data is None:
                entry.crossref_data = get_and_cache_crossref(doi=doi,
                                                             ulog=ulog, session=session,
                                                             ident=ident)

    # 3.2 crossref -> arxiv (TODO)
    pass

    return entry


def _link_entry(entry: Entry, by_doi: Dict[str, Entry]) -> Entry:
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


def main(fns, c, ulog):
    # 1. User data
    entries = list(_load_user_data(fns, ulog=ulog))

    # 2. Fetch data given by user-specified ids.
    with c.scoped_session() as session:
        entries = [_fetch_data_for_user_spec_id(entry, session=session, ulog=ulog) for entry in entries]

    # 3. Fetch data given by fetched ids
    with c.scoped_session() as session:
        entries = [_fetch_data_for_fetched_id(entry, session=session, ulog=ulog) for entry in entries]

    # 4. Merge data and convert to internal representation
    entries = [Entry(
        ident=merge_ident(entry),
        fn=merge_fn(entry),
        title=merge_title(entry, ulog=ulog),
        authors=merge_authors(entry, ulog=ulog),
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
        cites=merge_cites(entry),
        tags=merge_tags(entry),
    ) for entry in entries]

    # 5. Create indices for data
    by_doi = {}
    by_ident = {}
    by_arxivid = {}
    cite_network = nx.DiGraph()
    by_fn = defaultdict(list)
    for entry in entries:
        by_ident[entry.ident] = entry
        by_doi[entry.doi] = entry
        by_arxivid[entry.arxiv] = entry
        by_fn[entry.fn] += [entry]

    # 6. Link
    entries = [_link_entry(entry, by_doi) for entry in entries]

    # 7. [WIP] output
    with open('quantum.json', 'w') as f:
        import json
        json.dump([asdict(entry) for entry in entries], f, indent=2)

    return entries


def _quote(x):
    return f'"{x}"'


def _id(x):
    return x


def _yaml_list(xs: Iterable[str]):
    return '\n' + '\n'.join('    - {}'.format(x) for x in xs)


def _yaml_authors(xs: List[Author]):
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
    return x.full_name


YAML_FMT = {
    'title': _quote,
    'arxiv': _quote,
    'doi': lambda x: x,
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
