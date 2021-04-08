from typing import List, Tuple, Callable, Any, Sequence

from gitbib.gitbib import latex_escape, bibtex_capitalize, CROSSREF_TO_BIB_TYPE
from gitbib.gitbib2 import Author, DateTuple, ContainerTitle, Indices, Entry


def _quote(x) -> str:
    return f'"{x}"'


def _bib_title(x: str) -> str:
    return _quote(bibtex_capitalize(latex_escape(x)))


def _bib_authors(xs: List[Author]) -> str:
    s = " and ".join(latex_escape(f'{x.family}, {x.given}') for x in xs)
    return _quote(s)


def _bib_type(x: str) -> str:
    return CROSSREF_TO_BIB_TYPE[x]


def _bib_year(x: DateTuple) -> str:
    if x is None:
        raise ValueError()

    return _quote(x[0])


def _yaml_container_title(x: ContainerTitle) -> str:
    if ':' in x.full_name:
        return _quote(x.full_name)
    return _quote(x.full_name)


def _bib_page(x: Tuple[int, int]) -> str:
    if x is None:
        raise ValueError()

    x1, x2 = x
    if x1 == x2:
        return _quote(x1)

    return _quote(f'{x1}--{x2}')


def to_bib(entry: Entry):
    s = '@' + _bib_type(entry.type) + '{' + entry.ident + ',\n'

    fields: List[Tuple[str, str, Callable[[Any], str]]] = [
        ('author', 'authors', _bib_authors),
        ('title', 'title', _bib_title),
        # ('booktitle', 'booktitle', _id),  # TODO: booktitle?
        ('year', 'first_published', _bib_year),
        ('journal', 'container_title', _yaml_container_title),  # TODO factor out yaml stuff
        # ('address', 'address', _id),  # TODO: address?
        ('volume', 'volume', _quote),
        ('number', 'issue', _quote),
        # ('chapter', 'chapter', _id),  # TODO: chapter?
        ('pages', 'page', _bib_page),
        (None, 'arxiv', None),
        # ('publisher', 'publisher', _id),  # TODO: publisher?
        ('doi', 'doi', _quote),  # TODO: bioarxiv?
    ]

    for bib_field_name, entry_field_name, fmt_func in fields:
        # 0. Special case
        if entry_field_name == 'arxiv':
            if entry.arxiv is None:
                continue

            s += '  archivePrefix = "arXiv",\n'
            s += '  eprint        = ' + _quote(entry.arxiv) + ',\n'
            s += '  primaryClass  = ' + _quote(entry.arxiv_category) + ',\n'
            continue

        # 1. Normal 1:1 field correspondence.
        value = entry.__getattribute__(entry_field_name)
        if value is None:
            continue
        s += f'  {bib_field_name:9s} = ' + fmt_func(value) + ',\n'

    s += '}'
    return s

def to_bibs(entries: Sequence[Entry]):
    s = ''
    for entry in entries:
        s += to_bib(entry) + '\n\n'
    return s


def to_bib_files(indices: Indices):
    byfn = dict()
    for fn, entries in indices.by_fn.items():
        s = ''
        for entry in entries:
            s += to_bib(entry) + '\n\n'
        byfn[fn] = s

    for fn, entries in indices.secondary_by_fn.items():
        s = '\n' + '%' * 78 + '\n\n'
        for entry in entries:
            s += to_bib(entry) + '\n\n'
        byfn[fn] += s

    return byfn
