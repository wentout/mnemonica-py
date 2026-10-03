"""C1 — types and collections, and the define-time error matrix (C8)."""

from typing import Any, cast

import pytest
from helpers import null_handler

from mnemonica import (
    AlreadyDeclared,
    HandlerMustBeAFunction,
    MissingCallbackArgument,
    Mnemonic,
    TypenameMustBeAString,
    WrongTypeDefinition,
    createTypesCollection,
    default_collection,
    define,
    lookup,
)
from mnemonica.types import MnemonicaType


def test_root_function_form() -> None:
    collection = createTypesCollection()

    def user_handler(self: object, name: str) -> None:
        name_key = "name"
        setattr(self, name_key, name)

    User = collection.define("User", user_handler)
    assert isinstance(User, MnemonicaType)
    assert User.path == "User"
    assert collection.lookup("User") is User
    # the function form is the JS-style shape; construction is dynamic
    user: Any = User("ada")
    assert user.name == "ada"


def test_root_class_form() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    assert isinstance(User, type)
    user: User = User("ada")
    assert user.name == "ada"
    assert User.path == "User"


def test_root_class_form_without_handler() -> None:
    collection = createTypesCollection()

    @collection.define
    class Marker:
        pass

    marker: Marker = Marker()
    assert isinstance(marker, Marker)


def test_free_define_uses_default_collection() -> None:
    def probe_handler(self: object) -> None:
        pass

    Probe = define("P1DefaultCollectionProbe", probe_handler)
    assert lookup("P1DefaultCollectionProbe") is Probe
    assert default_collection().lookup("P1DefaultCollectionProbe") is Probe


def test_duplicate_root_raises() -> None:
    collection = createTypesCollection()

    def first(self: object) -> None:
        pass

    collection.define("User", first)
    with pytest.raises(AlreadyDeclared):
        collection.define("User", first)


def test_duplicate_root_class_form_raises() -> None:
    collection = createTypesCollection()

    class Shell:
        pass

    define(Shell, collection=collection)
    with pytest.raises(AlreadyDeclared):
        define(Shell, collection=collection)


def test_duplicate_subtype_raises() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        pass

    User.define("Admin", null_handler)
    with pytest.raises(AlreadyDeclared):
        User.define("Admin", null_handler)


def test_duplicate_subtype_class_form_raises() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        pass

    @User.define
    class Admin(User):
        pass

    # a second class with the same name: the duplicate path fires at
    # registration time, before anything is bound
    duplicate = type("Admin", (User,), {})
    with pytest.raises(AlreadyDeclared):
        User.define(duplicate)


def test_subtype_class_form_with_handler_refused() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        pass

    class Shell(User):
        pass

    with pytest.raises(WrongTypeDefinition):
        User.define(cast(Any, Shell), cast(Any, null_handler))


def test_subtype_paths_and_nested_lookup() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    @Admin.define
    class SuperAdmin(Admin):
        def __init__(self, level: int) -> None:
            self.level = level

    assert Admin.path == "User.Admin"
    assert SuperAdmin.path == "User.Admin.SuperAdmin"
    assert collection.lookup("User.Admin") is Admin
    assert collection.lookup("User.Admin.SuperAdmin") is SuperAdmin
    # unknown paths resolve to None, never raise (C1.4)
    assert collection.lookup("User.Nope") is None
    assert collection.lookup("Nope") is None
    assert collection.lookup("User.Admin.Nope") is None
    assert collection.lookup("") is None


def test_subtypes_map_is_live() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        pass

    assert User.subtypes == {}
    User.define("Admin", null_handler)
    assert list(User.subtypes) == ["Admin"]


def test_handler_is_read_at_every_construction() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    before: User = User("ada")
    assert before.name == "ada"

    def replacement(self: object, name: str) -> None:
        name_key = "name"
        setattr(self, name_key, name.upper())

    User.handler = replacement
    after: User = User("eve")
    assert after.name == "EVE"
    # existing instances are unaffected (C1.5)
    assert before.name == "ada"


def test_typename_must_be_a_string() -> None:
    collection = createTypesCollection()
    with pytest.raises(TypenameMustBeAString):
        define(cast(Any, 123), null_handler, collection=collection)


def test_typename_must_be_a_string_subtype() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        pass

    with pytest.raises(TypenameMustBeAString):
        User.define(cast(Any, 123), null_handler)


def test_handler_must_be_a_function() -> None:
    collection = createTypesCollection()
    with pytest.raises(HandlerMustBeAFunction):
        collection.define("User", cast(Any, "not-callable"))


def test_missing_callback_argument() -> None:
    collection = createTypesCollection()
    with pytest.raises(MissingCallbackArgument):
        collection.define(cast(Any, "User"))


def test_class_form_with_handler_refused() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        pass

    class Shell:
        pass

    with pytest.raises(WrongTypeDefinition):
        define(Shell, cast(Any, null_handler), collection=collection)


def test_wrong_base_form_b_refused() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        pass

    @collection.define
    class Widget(Mnemonic):
        pass

    with pytest.raises(WrongTypeDefinition, match="extends"):

        @User.define
        class Gadget(Widget):
            pass


def test_set_name_is_called_when_binding() -> None:
    collection = createTypesCollection()
    calls: list[tuple[type, str]] = []

    class RecordingDescriptor:
        def __set_name__(self, owner: type, name: str) -> None:
            calls.append((owner, name))

        def __get__(self, instance: object, owner: type | None = None) -> int:
            result = 7
            return result

    @collection.define
    class User(Mnemonic):
        marker = RecordingDescriptor()

    User.define("Admin", null_handler)

    # first call: the class statement names the descriptor on the shell;
    # second call: type.__new__ names it on the runtime class (form A)
    assert len(calls) == 2
    assert calls[0][1] == "marker"
    assert calls[1] == (User, "marker")


def test_define_class_form_via_free_define() -> None:
    collection = createTypesCollection()

    class Shell:
        def __init__(self, name: str) -> None:
            self.name = name

    User = define(Shell, collection=collection)
    user: Shell = User("ada")
    assert user.name == "ada"
    assert collection.lookup("Shell") is User
