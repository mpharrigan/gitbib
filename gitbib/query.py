import requests
import time

headers = {'Accept': 'application/json; charset=utf-8'}
url = "https://api.crossref.org"


def query(entry):
    e_query = []
    if 'title' in entry:
        e_query += [('query.title', entry['title'])]
    if 'author' in entry:
        e_query += [('query.author', '+'.join('+'.join(x.split(', ')) for x in entry['author']))]
    if 'journal' in entry:
        e_query += [('query.container-title', entry['journal'])]
    e_query += [('sort', 'score')]
    e_query = ['{}={}'.format(x1, x2) for x1, x2 in e_query]

    q_string = "{}/works?{}".format(url, '&'.join(e_query))
    r = requests.get(q_string, headers=headers)

    items = r.json()['message']['items']
    return {
        'doi': items[0]['DOI'],
        'score': items[0]['score'],
    }
