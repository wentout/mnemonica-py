"""Edge fixture: a subtype of a parent that lives outside the package.

The stub keeps the written parent name as the base and does not try to
link a parent attribute. Golden-file comparison only (the external
parent intentionally does not resolve for the checkers).
"""

from somewhere import External


def ext_handler(self, tag: str) -> None:
    self.tag = tag


Ext = External.define("Ext", ext_handler)
