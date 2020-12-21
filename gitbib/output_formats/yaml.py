from collections import defaultdict
from collections import defaultdict
from dataclasses import astuple
from textwrap import TextWrapper
from typing import List, Iterable

from gitbib.gitbib import yaml_indent
from gitbib.gitbib2 import Author, Citation, DateTuple, ContainerTitle, Entry, Indices


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


def to_yaml_files(indices: Indices):
    byfn = defaultdict(lambda: "")
    for fn, entries in indices.by_fn.items():
        s = ''
        for entry in entries:
            s += to_yaml(entry) + '\n\n'
        byfn[fn] = s

    return byfn
