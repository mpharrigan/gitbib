from gitbib.gitbib import parse_in_text_citation, parse_in_text_link


def test_parse_in_text_citation():
    desc = "They take qaoa [qaoa=1] [qaoa2=2] and formulate it as a grovers search."
    parts = parse_in_text_citation(desc)
    assert parts == [
        'They take qaoa ',
        {'i': 'qaoa', 'n': 1},
        ' ',
        {'i': 'qaoa2', 'n': 2},
        ' and formulate it as a grovers search.'
    ]


def test_parse_link():
    desc = "Check out this [link](http://whatever.com). Isn't it cool? Like [this](google.com)."
    parts = parse_in_text_link(desc)
    assert parts == [
        'Check out this ',
        {'s': 'link', 'href': 'http://whatever.com'},
        ". Isn't it cool? Like ",
        {'s': 'this', 'href': 'google.com'},
        '.',
    ]
