"""The lookup-order deviation, pinned (conformance matrix row D-lookup).

JS order:  own → subtype methods → parent instance fields → parent methods.
Here:      own → subtype methods → parent methods → parent instance fields.

It differs only when an instance FIELD and a METHOD share a name: Python's
class MRO is consulted before __getattr__ ever runs, so the Admin method
wins; in JS the parent instance's field would win.
"""

from helpers import construct

from mnemonica import Mnemonic, createTypesCollection


def test_method_wins_over_parent_field() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def tag(self) -> str:
            result = "method-on-admin"
            return result

    user: User = User("ada")
    tag_field = "tag"
    setattr(user, tag_field, "field-on-user")

    assert getattr(user, tag_field) == "field-on-user"
    # JS would read "field-on-user" here (parent instance fields precede
    # parent methods); the Python port reads the method first
    admin: Admin = construct(user, "Admin", "root")
    assert admin.tag() == "method-on-admin"
