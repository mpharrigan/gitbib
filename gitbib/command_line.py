
import os
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from .gitbib import Gitbib
from .cache import Cache

if os.name == 'posix':
    class bcolors:
        OKBLUE = '\033[34m'
        OKGREEN = '\033[32m'
        WARNING = '\033[33m'
        FAIL = '\033[31m'
        ENDC = '\033[0m'
else:
    class bcolors:
        OKBLUE = ''
        OKGREEN = ''
        WARNING = ''
        FAIL = ''
        ENDC = ''


class ConsoleLogger:
    def __init__(self, level=20):
        self.level=level

    def _record(self, level, message):
        message = str(message)
        if level >= self.level:
            print(message)
        return message

    def debug(self, message):
        return self._record(10, "- {}".format(message))

    def info(self, message):
        return self._record(20, "- {}".format(message))

    def warn(self, message):
        return self._record(30, "- {}{}{}".format(bcolors.WARNING, message, bcolors.ENDC))

    def error(self, message):
        return self._record(40, "- {}{}{}".format(bcolors.FAIL, message, bcolors.ENDC))

def main():
    parser = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument(dest='gitbib_dir', help='Directory of gitbib files.')
    parser.add_argument('--gitbib_yaml', '-g', help='Where to find gitbib configuration file', default='gitbib.yaml')
    parser.add_argument('--cache_fn', '-c', help='Database for caching entries', default='gitbib.sqlite')
    parser.add_argument('--out_dir', '-o', help='Directory for output files', default='gitbib')
    args = parser.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    c = Cache("sqlite:///{}".format(args.cache_fn))
    l = ConsoleLogger(20)
    with c.scoped_session() as session:
        g = Gitbib(session=session, user_logger=l, repo_dir=args.gitbib_dir, gitbib_yaml_fn=args.gitbib_yaml)

    user_info = {
        'slugname': 'gitbib',
        'index_url': 'index.html',
    }
    for fn, mime, render in g.renderers({'html', 'bib', 'tex', 'md'}, user_logger=l):
        with open('{}/{}'.format(args.out_dir, fn), 'wb') as f:
            render(f, user_info)
