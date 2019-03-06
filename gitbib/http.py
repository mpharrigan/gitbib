from dataclasses import asdict

import tornado.web


class BaseHandler(tornado.web.RequestHandler):

    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "x-requested-with")
        self.set_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')


class MainHandler(BaseHandler):
    def get(self):
        entries = self.application.entries
        print("GET")
        self.write({'entries': [asdict(entry) for entry in entries]})


class GitbibApplication(tornado.web.Application):
    def __init__(self, entries):
        super().__init__([
            (r'/entries', MainHandler),
        ])
        self.entries = entries
