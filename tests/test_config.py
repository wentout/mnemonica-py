"""C4 — per-type config with collection-inherited defaults.

Covers strictChain (both guard points, per FOR_HUMANS "What strictChain
actually guards"), blockErrors (errored instance; refusal; propagation
when off), submitStack, config filtering (unknown keys dropped, non-boolean
values fall back), and the reserved unchain name.
"""

from typing import Any, cast

import pytest
from helpers import construct, null_handler

from mnemonica import (
    ErroredInstance,
    Mnemonic,
    OptionsError,
    WrongModificationPattern,
    createTypesCollection,
    getProps,
)


def test_block_errors_default_produces_errored_instance() -> None:
    collection = createTypesCollection()

    def bad_handler(self: object) -> None:
        raise ValueError("boom")

    Bad = collection.define("Bad", bad_handler)
    with pytest.raises(ErroredInstance) as caught:
        Bad()
    errored = caught.value
    record = getProps(errored)
    assert record is not None
    assert isinstance(record["originalError"], ValueError)
    assert record["exceptionReason"] is record["originalError"]
    assert record["reasons"] == [record["originalError"]]
    assert record["surplus"] == []
    assert record["args"] == ()
    assert record["instance"] is errored
    assert record["type"] is Bad


def test_block_errors_off_propagates_as_is() -> None:
    collection = createTypesCollection()

    def bad_handler(self: object) -> None:
        raise ValueError("boom")

    Bad = collection.define("Bad", bad_handler, {"blockErrors": False})
    with pytest.raises(ValueError, match="boom"):
        Bad()


def test_constructing_from_errored_instance_is_refused() -> None:
    collection = createTypesCollection()

    def bad_handler(self: object) -> None:
        raise ValueError("boom")

    Bad = collection.define("Bad", bad_handler)
    with pytest.raises(ErroredInstance) as caught:
        Bad()
    parent = caught.value

    # a subtype that accepts a parent of any kind still refuses an
    # errored one while its own blockErrors is on (C4.2)
    Child = Bad.define(
        "Child", null_handler, {"strictChain": False, "blockErrors": True}
    )
    with pytest.raises(ErroredInstance) as caught:
        Child.of(parent)
    refusal_record = getProps(caught.value)
    assert refusal_record is not None
    assert isinstance(refusal_record["originalError"], ErroredInstance)

    # with blockErrors off the errored parent is accepted as a parent
    Loophole = Bad.define(
        "Loophole",
        null_handler,
        {"strictChain": False, "blockErrors": False},
    )
    assert Loophole.of(parent) is not None


def test_strict_chain_point_1_subtype_resolution() -> None:
    collection = createTypesCollection()
    User = collection.define("User", null_handler)
    Admin = User.define("Admin", null_handler)
    Admin.define("Super", null_handler)

    user = User()
    admin = construct(user, "Admin")
    super_admin = construct(admin, "Super")

    # Super instances see Admin up the MRO, but their own type's
    # strictChain (default true) forbids constructing it (C4.1 point 1)
    admin_name = "Admin"
    with pytest.raises(AttributeError):
        getattr(super_admin, admin_name)
    # the entity's type may allow it
    Admin.define("Loose", null_handler, {"strictChain": False})
    loose = construct(admin, "Loose")
    loose_child = construct(loose, "Admin")
    assert isinstance(loose_child, Admin)


def test_strict_chain_point_2_parent_kind_check() -> None:
    collection = createTypesCollection()
    User = collection.define("User", null_handler)
    Widget = collection.define("Widget", null_handler)
    Admin = User.define("Admin", null_handler)
    Guest = User.define("Guest", null_handler, {"strictChain": False})

    widget = Widget()
    with pytest.raises(WrongModificationPattern, match="User"):
        Admin.of(widget)
    # the target type's strictChain off: a parent of another kind is fine
    guest: Any = Guest.of(widget)
    assert isinstance(guest, Guest)


def test_collection_config_is_inherited_and_overridable() -> None:
    collection = createTypesCollection({"blockErrors": False, "submitStack": True})
    User = collection.define("User", null_handler)
    Admin = User.define("Admin", null_handler, {"submitStack": False})

    assert User.config["blockErrors"] is False
    assert User.config["submitStack"] is True
    assert Admin.config["blockErrors"] is False
    assert Admin.config["submitStack"] is False
    # defaults for what neither level sets
    assert User.config["strictChain"] is True

    user = User()
    assert "stack" in cast(dict[str, Any], getProps(user))
    admin: Any = Admin.of(user)
    assert "stack" not in cast(dict[str, Any], getProps(admin))


def test_config_filtering_unknown_keys_and_wrong_types() -> None:
    collection = createTypesCollection(
        cast(
            Any,
            {"strictChain": False, "unknown": True, "blockErrors": "yes"},
        )
    )
    config = collection.config
    assert config["strictChain"] is False
    assert config["blockErrors"] is True  # non-boolean falls back
    assert "unknown" not in config

    with pytest.raises(OptionsError):
        createTypesCollection(cast(Any, "not a mapping"))
    with pytest.raises(OptionsError):
        collection.define("X", null_handler, cast(Any, ["not a mapping"]))


def test_unchain_name_is_reserved() -> None:
    # unchain is accepted and stored but has no effect until P4 (C6)
    collection = createTypesCollection({"unchain": True})
    User = collection.define("User", null_handler)
    assert collection.config["unchain"] is True
    assert User.config["unchain"] is True
    assert User().__class__ is User


def test_subtype_attribute_binds_even_without_a_record() -> None:
    # a fresh instance (copy/pickle reconstruction) has no context record
    # yet; reading a subtype from it still binds the constructor
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    fresh = Admin.__new__(Admin)
    admin_name = "Admin"
    bound: Any = getattr(fresh, admin_name)
    child = bound("root")
    assert isinstance(child, Admin)
    record = getProps(child)
    assert record is not None
    assert record["parent"] is fresh


def test_class_form_define_accepts_config() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    # config is keyword-only on the class form: a decorator with arguments
    # has no bare-@ syntax, so the descriptor is called directly
    Registered = User.define(Admin, config={"submitStack": True})
    assert Registered.config["submitStack"] is True
    admin = construct(User("ada"), "Admin", "root")
    assert admin.role == "root"
    assert "stack" in cast(dict[str, Any], getProps(admin))
