"""C3 — the construction context record, getProps/setProps."""

from typing import Any

import pytest
from helpers import construct, null_handler

from mnemonica import (
    Mnemonic,
    MnemonicaError,
    createTypesCollection,
    getProps,
    setProps,
)


def test_record_fields() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str, *, active: bool = True) -> None:
            self.role = role
            self.active = active

    user: User = User("ada")
    admin: Admin = construct(user, "Admin", "root", active=False)

    props = getProps(admin)
    assert props is not None
    assert props["type"] is Admin
    assert props["parent"] is user
    assert props["args"] == ("root",)
    assert props["kwargs"] == {"active": False}
    assert props["collection"] is collection
    assert props["subtypes"] is Admin.subtypes
    assert props["self"] is admin
    # the creator context of this construction is this construction's record
    assert props["creator"] is props
    # JS records milliseconds since epoch
    timestamp = props["timestamp"]
    assert isinstance(timestamp, int)
    assert timestamp > 1_700_000_000_000


def test_root_record_has_no_parent() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    user: User = User("ada")
    props = getProps(user)
    assert props is not None
    assert props["parent"] is None
    assert props["type"] is User
    assert props["args"] == ("ada",)
    assert props["kwargs"] == {}


def test_self_is_installed_after_the_handler_runs() -> None:
    collection = createTypesCollection()
    seen: dict[str, Any] = {}

    def spying_handler(self: object, name: str) -> None:
        props = getProps(self)
        assert props is not None
        # identity first, data second: the record exists mid-construction,
        # but `self` cannot exist before the instance is made (JS __self__)
        seen["self_present_during"] = "self" in props
        seen["parent_during"] = props["parent"]
        name_key = "name"
        setattr(self, name_key, name)

    User = collection.define("User", spying_handler)
    user: Any = User("ada")
    assert seen["self_present_during"] is False
    assert seen["parent_during"] is None
    props = getProps(user)
    assert props is not None
    assert props["self"] is user


def test_subtypes_entry_is_live() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    user: User = User("ada")
    props = getProps(user)
    assert props is not None
    assert props["subtypes"] == {}
    # subtypes declared after the instance exist are visible (live view)
    User.define("Admin", null_handler)
    assert list(props["subtypes"]) == ["Admin"]


def test_get_props_of_plain_object_is_none() -> None:
    assert getProps(object()) is None


def test_get_props_of_non_mnemonica_instance_is_none() -> None:
    class Plain:
        pass

    assert getProps(Plain()) is None


def test_set_props_merges() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    user: User = User("ada")
    props = getProps(user)
    assert props is not None
    setProps(user, {"note": "hi"})
    assert props["note"] == "hi"
    # merged, not replaced
    assert props["type"] is User


def test_set_props_on_unknown_instance_raises() -> None:
    with pytest.raises(MnemonicaError, match="no construction context"):
        setProps(object(), {"note": "hi"})
