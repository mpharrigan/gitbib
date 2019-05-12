import re
import textwrap
from dataclasses import dataclass
from typing import List, Optional

from gitbib.gitbib import IN_TEXT_CITATION_RE, SHORT_IN_TEXT_CITATION_RE


class DescriptionPart:
    def _markdown(self):
        raise NotImplementedError()


@dataclass
class Text(DescriptionPart):
    content: str

    def __repr__(self):
        return repr(self.content)

    def _markdown(self):
        return self.content

    def yaml(self):
        return self._markdown()

    def __str__(self):
        return self.content


@dataclass
class Citation(DescriptionPart):
    ident: str
    num: Optional[int]

    def __repr__(self):
        num_str = f', {self.num}' if self.num is not None else ''
        return f'Citation[{self.ident}{num_str}]'

    def _markdown(self):
        num_str = f'={self.num}' if self.num is not None else ''
        return f'[{self.ident}{num_str}]'

    def yaml(self):
        return self._markdown()

    def __str__(self):
        return self._markdown()


@dataclass
class Paragraph(DescriptionPart):
    parts: List[DescriptionPart]

    def __repr__(self):
        x = 'Paragraph[{}]'.format(', '.join(repr(p) for p in self.parts))
        return textwrap.fill(x, width=100)

    def _markdown(self):
        return ''.join(p._markdown() for p in self.parts)

    def yaml(self):
        return textwrap.fill(self._markdown(), width=78)

    def __str__(self):
        return textwrap.fill(self._markdown())


@dataclass
class Description:
    paragraphs: List[Paragraph]

    def __repr__(self):
        return repr(self.paragraphs)

    # TODO?: This should be a function in YAML_FMT
    def yaml(self):
        return '\n\n'.join(p.yaml() for p in self.paragraphs)


def parse_paragraph(text: str) -> Paragraph:
    text = re.sub(r'\n', r' ', text)
    parts = []
    # [ident] or [ident=111] NOT [ident](...
    raw_parts = iter(re.split(IN_TEXT_CITATION_RE, text))

    try:
        while True:
            parts += [Text(next(raw_parts))]
            i = next(raw_parts)
            _doi_ident = next(raw_parts)
            _arxiv_ident = next(raw_parts)
            _normal_ident = next(raw_parts)
            _equals_sign = next(raw_parts)
            n = next(raw_parts)
            if n is not None:
                n = int(n)
            parts += [Citation(i, n)]
    except StopIteration:
        pass

    return Paragraph(parts)


def parse_description(desc: str) -> Description:
    raw_paras = re.split(r'\n\n', desc)
    return Description([parse_paragraph(para) for para in raw_paras])
