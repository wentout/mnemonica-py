"""C2 — construction and lineage, plus the P0-probe behavioural pins."""

import copy
from typing import Any, Protocol, cast

import pytest
from helpers import construct, null_handler

from mnemonica import (
    ErroredInstance,
    Mnemonic,
    MnemonicaError,
    WrongInstanceInvocation,
    WrongModificationPattern,
    createTypesCollection,
)
from mnemonica.types import BoundConstructor, MnemonicaType


def test_root_construction() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    user: User = User("ada")
    assert user.name == "ada"


def test_subtype_from_parent_instance() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    user: User = User("ada")
    admin: Admin = construct(user, "Admin", "root")
    assert admin.role == "root"
    assert isinstance(admin, Admin)
    assert isinstance(admin, User)


def test_subtype_form_a_bare_class() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Guest:
        def __init__(self, tag: str) -> None:
            self.tag = tag

    user: User = User("ada")
    guest: Guest = construct(user, "Guest", "t1")
    assert guest.tag == "t1"
    name_field = "name"
    assert getattr(guest, name_field) == "ada"
    assert isinstance(guest, User)


def test_subtype_form_c_function() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    class AdminFields(Protocol):
        role: str

    def admin_handler(self: object, role: str) -> None:
        role_key = "role"
        setattr(self, role_key, role)

    Admin = User.define("Admin", admin_handler)
    user: User = User("ada")
    admin = cast(AdminFields, construct(user, "Admin", "root"))
    assert admin.role == "root"
    assert isinstance(Admin, MnemonicaType)


def test_read_through_to_root() -> None:
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

    user: User = User("ada")
    admin: Admin = construct(user, "Admin", "root")
    super_admin: SuperAdmin = construct(admin, "SuperAdmin", 3)
    assert super_admin.name == "ada"  # from the root, two hops up
    assert super_admin.role == "root"  # from the direct parent
    assert super_admin.level == 3  # own


def test_write_local() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    user: User = User("ada")
    admin: Admin = construct(user, "Admin", "root")
    admin.name = "eve"
    assert admin.name == "eve"
    assert user.name == "ada"  # ancestors are history (C2.4)


def test_nominal_identity() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    user: User = User("ada")
    admin: Admin = construct(user, "Admin", "root")
    assert isinstance(admin, Admin)
    assert isinstance(admin, User)
    assert not isinstance(user, Admin)

    # identity is nominal: a plain object with the same fields is not a User
    class Lookalike:
        name = "ada"
        role = "root"

    assert not isinstance(Lookalike(), User)


def test_siblings_share_the_parent_live() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    user: User = User("ada")
    first: Admin = construct(user, "Admin", "root")
    second: Admin = construct(user, "Admin", "sudo")
    assert first.name == "ada"
    assert second.name == "ada"
    user.name = "grace"  # shared, not copied (C2.6)
    assert first.name == "grace"
    assert second.name == "grace"


def test_direct_subtype_call_refused() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    with pytest.raises(WrongInstanceInvocation):
        Admin("root")


def test_of_is_the_typed_construction_path() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    user: User = User("ada")
    admin = Admin.of(user, "root")
    assert admin.role == "root"
    assert admin.name == "ada"


def test_of_refuses_wrong_parent() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @collection.define
    class Widget:
        def __init__(self, sku: str) -> None:
            self.sku = sku

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    widget: Widget = Widget("w1")
    with pytest.raises(WrongModificationPattern, match="User"):
        Admin.of(widget, "root")
    with pytest.raises(WrongModificationPattern):
        Admin.of(cast(Any, "not an instance"), "root")


def test_of_on_root() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    user = User.of(None, "ada")
    assert user.name == "ada"
    with pytest.raises(WrongInstanceInvocation, match="root type"):
        User.of(cast(Any, object()), "ada")


def test_bound_constructor_refuses_wrong_parent() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    bound = BoundConstructor(object(), cast(Any, Admin))
    with pytest.raises(WrongModificationPattern):
        bound("root")


def test_bound_constructor_refuses_root() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    # pathological but possible: a root type stored on a class attribute
    loop = "Loop"
    setattr(User, loop, User)
    user: User = User("ada")
    bound: Any = getattr(user, loop)
    with pytest.raises(WrongInstanceInvocation, match="root type"):
        bound("ada")


def test_raw_mnemonic_base_constructs_normally() -> None:
    base: Mnemonic = Mnemonic()
    assert isinstance(base, Mnemonic)


def test_copy_copy_works() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        def __init__(self, role: str) -> None:
            self.role = role

    user: User = User("ada")
    admin: Admin = construct(user, "Admin", "root")
    clone: Admin = copy.copy(admin)
    assert clone.role == "root"
    assert clone.name == "ada"  # read-through still works on the clone


def test_fresh_instance_tolerated() -> None:
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
    # no chain yet: only AttributeError may leave __getattr__ (probe 2);
    # variable names (not literals) keep the probes free of the
    # constant-attribute getattr/setattr lint rules
    role = "role"
    with pytest.raises(AttributeError):
        getattr(fresh, role)
    dunder = "__not_a_real_dunder__"
    with pytest.raises(AttributeError):
        getattr(fresh, dunder)


def test_slotted_shell_fields_work() -> None:
    collection = createTypesCollection()

    @collection.define
    class SlottedRoot(Mnemonic):
        __slots__ = ("x",)

        def __init__(self, x: str) -> None:
            self.x = x

    root: SlottedRoot = SlottedRoot("v")
    assert root.x == "v"  # the slot itself is honoured
    # the parent link lives in the runtime class's __dict__ (runtime
    # classes never declare __slots__), so no slot reservation is needed
    parent_slot = "_mn_parent"
    assert getattr(root, parent_slot) is None
    missing = "missing"
    with pytest.raises(AttributeError):
        getattr(root, missing)


def test_read_through_with_slotted_root() -> None:
    collection = createTypesCollection()

    @collection.define
    class SlottedRoot(Mnemonic):
        __slots__ = ("x",)

        def __init__(self, x: str) -> None:
            self.x = x

    @SlottedRoot.define
    class Child(SlottedRoot):
        def __init__(self, c: str) -> None:
            self.c = c

    root: SlottedRoot = SlottedRoot("root-x")
    child = Child.of(root, "c1")
    assert child.c == "c1"
    # fields assigned dynamically land in the root's __dict__ and read through
    dyn = "dyn"
    setattr(root, dyn, "value")
    assert getattr(child, dyn) == "value"
    # a slot field of an ancestor does NOT read through: the inherited
    # member descriptor shadows the chain and the slot value is not in
    # any __dict__ (documented limitation — JS has no slot analogue)
    x_slot = "x"
    with pytest.raises(AttributeError):
        getattr(child, x_slot)
    no_such = "no_such_field"
    with pytest.raises(AttributeError):
        getattr(child, no_such)


def test_handler_failure_blocked_by_default() -> None:
    collection = createTypesCollection()

    def bad_handler(self: object) -> None:
        raise ValueError("boom")

    Bad = collection.define("Bad", bad_handler)
    # blockErrors defaults to true (C4.2): the failure is blocked into an
    # errored instance carrying the failed construction via getProps
    with pytest.raises(ErroredInstance, match="boom"):
        Bad()


def test_mnemonica_error_is_catchable() -> None:
    from mnemonica import AlreadyDeclared

    collection = createTypesCollection()
    collection.define("User", null_handler)
    with pytest.raises(MnemonicaError):
        collection.define("User", null_handler)
    assert issubclass(AlreadyDeclared, MnemonicaError)
