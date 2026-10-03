"""Cross-module subtype: the parent lives in app.py.

stubgen cannot link the parent attribute across modules (the Protocol
would reference a name this module does not import): it emits the class
and warns instead.
"""

from app import User


def sub_handler(self, tag: str) -> None:
    self.tag = tag


Sub = User.define("Sub", sub_handler)
