# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Manage references with git.

This program loads a collection of yaml files containing bibliographic entries,
collects additional metadata based on DOI or equivalent, and renders the entries
in a variety of formats.
"""

__version__ = "8"

from .gitbib import Gitbib
