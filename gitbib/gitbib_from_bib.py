from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
import sys
import yaml

from .bibparse import entries as Entries

def main():
    parser = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument(dest='bib_fn', help='.bib File')
    args = parser.parse_args()

    entries = Entries.parseFile(args.bib_fn)
    entries = {entry.cite_key: entry.fields for entry in entries}
    for entry in entries:
        #print(entry)
        #print(entries[entry])
        pass

    yaml.dump(entries, sys.stdout)

