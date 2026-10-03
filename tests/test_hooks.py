"""C5 — lifecycle hooks: preCreation, postCreation, creationError.

Registered on a type or on a collection; order and abort rules per C5.2
(and the JS InstanceCreator, which calls collection pre-hooks before type
pre-hooks, but type post-hooks before collection post-hooks).
"""

from typing import Any, cast

import pytest
from helpers import construct, null_handler

from mnemonica import (
    ErroredInstance,
    MissingHookCallback,
    WrongHookType,
    createTypesCollection,
    getProps,
)
from mnemonica.collection import TypesCollection
from mnemonica.types import MnemonicaType

HookData = dict[str, Any]


def _spy(log: list[str], label: str) -> Any:
    def callback(hook_data: HookData) -> None:
        log.append(label)

    return callback


def test_wrong_hook_type_and_missing_callback() -> None:
    collection = createTypesCollection()
    User = collection.define("User", null_handler)

    with pytest.raises(WrongHookType):
        User.registerHook("wrongKind", null_handler)
    with pytest.raises(WrongHookType):
        collection.registerHook(cast(Any, "wrongKind"), null_handler)
    with pytest.raises(MissingHookCallback):
        User.registerHook("preCreation", cast(Any, None))
    with pytest.raises(MissingHookCallback):
        collection.registerHook("postCreation", cast(Any, "not callable"))


def test_hook_order_collection_then_type() -> None:
    collection = createTypesCollection()
    log: list[str] = []
    collection.registerHook("preCreation", _spy(log, "collection-pre"))
    collection.registerHook("postCreation", _spy(log, "collection-post"))
    User = collection.define("User", null_handler)
    User.registerHook("preCreation", _spy(log, "type-pre"))
    User.registerHook("postCreation", _spy(log, "type-post"))

    User()
    # pre: collection then type; post: type then collection (C5.2, the JS
    # invokePostHooks order)
    assert log == [
        "collection-pre",
        "type-pre",
        "type-post",
        "collection-post",
    ]


def test_hook_data_contents() -> None:
    collection = createTypesCollection()
    seen: list[HookData] = []
    User = collection.define("User", null_handler)
    Admin = User.define("Admin", null_handler)
    User.registerHook("preCreation", seen.append)
    Admin.registerHook("postCreation", seen.append)

    user = User()
    admin = construct(user, "Admin")
    pre, post = seen

    assert pre["type"] is User
    assert pre["TypeName"] == "User"
    assert pre["existentInstance"] is None  # root construction
    assert pre["args"] == ()
    assert "inheritedInstance" not in pre

    assert post["type"] is Admin
    assert post["TypeName"] == "Admin"
    assert post["existentInstance"] is user
    assert post["inheritedInstance"] is admin
    assert callable(post["throwModificationError"])


def test_pre_creation_failure_aborts_without_creation_error() -> None:
    collection = createTypesCollection()
    log: list[str] = []
    User = collection.define("User", null_handler)
    User.registerHook("preCreation", _spy(log, "pre"))
    User.registerHook("creationError", _spy(log, "creation-error"))

    def exploding_pre(hook_data: HookData) -> None:
        raise RuntimeError("abort")

    User.registerHook("preCreation", exploding_pre)
    with pytest.raises(RuntimeError, match="abort"):
        User()
    # the aborting pre-hook itself ran; nothing else did (C5.2)
    assert log == ["pre"]


def test_creation_error_fires_for_errored_instance() -> None:
    collection = createTypesCollection()
    seen: list[HookData] = []
    collection.registerHook("creationError", seen.append)

    def bad_handler(self: object) -> None:
        raise ValueError("boom")

    collection.define("Bad", bad_handler)
    with pytest.raises(ErroredInstance):
        Bad = collection.lookup("Bad")
        assert Bad is not None
        Bad()
    (hook_data,) = seen
    errored = hook_data["inheritedInstance"]
    assert isinstance(errored, ErroredInstance)
    record = getProps(errored)
    assert record is not None
    assert isinstance(record["originalError"], ValueError)


def test_creation_error_not_fired_when_block_errors_off() -> None:
    collection = createTypesCollection()
    log: list[str] = []

    def bad_handler(self: object) -> None:
        raise ValueError("boom")

    collection.define("Bad", bad_handler, {"blockErrors": False})
    Bad = collection.lookup("Bad")
    assert Bad is not None
    Bad.registerHook("creationError", _spy(log, "creation-error"))
    with pytest.raises(ValueError, match="boom"):
        Bad()
    assert log == []


def test_throw_modification_error_from_post_hook() -> None:
    collection = createTypesCollection()

    def reject(hook_data: HookData) -> None:
        hook_data["throwModificationError"](ValueError("rejected"))

    User = collection.define("User", null_handler)
    User.registerHook("postCreation", reject)
    with pytest.raises(ErroredInstance, match="rejected"):
        User()


def test_collection_hooks_fire_for_every_type_in_it() -> None:
    collection = createTypesCollection()
    other = createTypesCollection()
    log: list[str] = []
    collection.registerHook("postCreation", _spy(log, "hit"))
    other.registerHook("postCreation", _spy(log, "other"))

    collection.define("User", null_handler)()
    assert log == ["hit"]


def test_multiple_callbacks_accumulate_in_registration_order() -> None:
    collection = createTypesCollection()
    log: list[str] = []
    User = collection.define("User", null_handler)
    User.registerHook("postCreation", _spy(log, "first"))
    User.registerHook("postCreation", _spy(log, "second"))
    User()
    assert log == ["first", "second"]


def test_hooks_see_kwargs_and_root_parent_is_none() -> None:
    collection = createTypesCollection()
    seen: list[HookData] = []
    User = collection.define("User", null_handler)
    User.registerHook("preCreation", seen.append)
    User(name="ada")
    (hook_data,) = seen
    assert hook_data["args"] == ()
    assert hook_data["existentInstance"] is None


def test_hook_data_type_names_are_static_checkable() -> None:
    # the hook registry lives on both the collection and the type
    collection = createTypesCollection()
    assert isinstance(collection, TypesCollection)
    User = collection.define("User", null_handler)
    assert isinstance(User, MnemonicaType)
    assert User.mn_hooks == {}
