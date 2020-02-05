from xml.etree import ElementTree
import os

from gitbib.gitbib import _fetch_arxiv

TESTDIR = os.path.dirname(os.path.abspath(__file__))


def test_fetch_arxiv():
    def raw_injector(arxivid):
        if arxivid != '1712.05771':
            raise ValueError()

        return ElementTree.parse(f'{TESTDIR}/1712.05771.xml').getroot()

    record = _fetch_arxiv('1712.05771', fetcher=raw_injector)
    assert record['primary_category'] == 'quant-ph'
