"""Very simple bibtex parser for use in MSMBuilder doc generation

Matthew Harrigan
(c) 2016, MIT License
"""

from pyparsing import CaselessKeyword as kwd
from pyparsing import QuotedString, Word, alphanums, Suppress, OneOrMore, nums, \
    Group, Optional, ZeroOrMore, alphas, alphas8bit, delimitedList, nestedExpr, printables, ParseResults, Dict
import string
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
import sys
import yaml

entry_type = kwd("article") | kwd("unpublished") | kwd("incollection")
cite_key = Word(alphanums + ":/._-")

LCURLY = Suppress('{')
RCURLY = Suppress('}')
COMMA = Suppress(',')
AT = Suppress('@')
EQUALS = Suppress('=')


def un_nest(t):
    if isinstance(t, str):
        return t
    else:
        return ''.join(un_nest(t2) for t2 in t)


field_content = Word(string.printable, excludeChars='{}')
field_val = Word(nums) | nestedExpr('{', '}', content=field_content, ignoreExpr=None)
field_val.setParseAction(un_nest)
title_field = Group(kwd('title') + EQUALS + field_val)
journal_field = Group(kwd('journal') + EQUALS + field_val)
year_field = Group(kwd('year') + EQUALS + field_val)
volume_field = Group(kwd('volume') + EQUALS + field_val)
pages_field = Group(kwd('pages') + EQUALS + field_val)
abstract_field = Group(kwd('abstract') + EQUALS + field_val)
doi_field = Group(kwd('doi') + EQUALS + field_val)
other_field = Group(Word(alphanums) + EQUALS + field_val)

author = OneOrMore(~kwd('and') + Word(alphas + alphas8bit + '.,-'))
author.setParseAction(lambda xx: ' '.join(str(x) for x in xx))
author_list = LCURLY + delimitedList(author, 'and') + RCURLY
author_field = Group(kwd('author') + EQUALS + Group(author_list))

entry_item = (title_field | author_field | journal_field | year_field
              | volume_field | pages_field | abstract_field | doi_field
              | Suppress(other_field))

entry_item_list = Group(ZeroOrMore(entry_item + Suppress(',')) + Optional(entry_item))
entry = Group(Suppress('@') + entry_type + Suppress('{') + cite_key + Suppress(',') + entry_item_list + Suppress('}'))
Entries = OneOrMore(entry)

def _to_python(x):
    if isinstance(x, ParseResults):
        return x.asList()
    try:
        return int(x)
    except ValueError:
        return x

def entries_to_python(entries):
    for type, key, fields in entries:
        fields = {k: _to_python(v) for k, v in fields}
        yield type, key, fields


Entries.setParseAction(entries_to_python)

def _doi_only(fields):
    if 'doi' in fields:
        return {'doi': fields['doi']}
    else:
        return fields

def main():
    parser = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument(dest='bib_fn', help='.bib File')
    parser.add_argument('--doi-only', action='store_true', default=False, help='Only keep DOI')
    args = parser.parse_args()

    entries = Entries.parseFile(args.bib_fn, parseAll=True)
    entries = {key: fields for _, key, fields in entries}

    if args.doi_only:
        entries = {key: _doi_only(fields) for key, fields in entries.items()}

    yaml.dump(entries, sys.stdout, default_flow_style=False)


if __name__ == '__main__':
    main()
