"""C6 — asynchronous constructors.

A type whose handler is a coroutine function (`async def __ainit__` on the
class forms, an `async def` handler in the function form, or `async
def __init__`) makes construction awaitable: `admin = await
user.Admin(...)`. Hooks and blockErrors behave exactly as on the sync
path (postCreation fires after the await; a handler failure becomes an
errored instance). Reading a subtype from the pending awaitable queues
the next construction — a whole chain unwraps with a single await
(C6.3). Tests drive coroutines with asyncio.run (no pytest-asyncio).
"""

import asyncio
from typing import Any, cast

import pytest
from helpers import construct, null_handler

from mnemonica import (
    AsyncChain,
    ErroredInstance,
    Mnemonic,
    WrongModificationPattern,
    WrongTypeDefinition,
    createTypesCollection,
    getProps,
)


def _run(coro: Any) -> Any:
    result = asyncio.run(coro)
    return result


def _sync_user_async_admin(collection: Any) -> tuple[Any, Any]:
    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        async def __ainit__(self, role: str) -> None:
            await asyncio.sleep(0)
            self.role = role

    return User, Admin


# --- C6.1: async handler makes construction awaitable -----------------------


def test_async_subtype_construction_is_awaitable() -> None:
    collection = createTypesCollection()
    User, _ = _sync_user_async_admin(collection)

    async def scenario() -> Any:
        user = User("ada")
        pending = construct(user, "Admin", "root")
        assert isinstance(pending, AsyncChain)
        admin = await pending
        assert admin.role == "root"
        assert admin.name == "ada"  # read-through to the sync parent
        record = getProps(admin)
        assert record is not None
        assert record["parent"] is user
        assert record["args"] == ("root",)
        assert record["self"] is admin  # installed after the await
        return admin

    _run(scenario())


def test_async_root_class_form_and_of_path() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            # the checker-visible constructor signature; at runtime the
            # metaclass never runs __init__ — the async __ainit__ is the
            # handler and construction returns an awaitable
            ...

        async def __ainit__(self, name: str) -> None:
            await asyncio.sleep(0)
            self.name = name

    async def scenario() -> Any:
        pending: Any = User("ada")
        assert isinstance(pending, AsyncChain)
        user = await pending
        assert user.name == "ada"
        # the typed path stays typed through await
        other = await cast(Any, User.of)(None, "grace")
        assert other.name == "grace"
        return user

    _run(scenario())


def test_async_function_form() -> None:
    collection = createTypesCollection()

    async def handler(self: Any, name: str) -> None:
        await asyncio.sleep(0)
        self.name = name

    User = collection.define("User", handler)

    async def scenario() -> Any:
        user = await User("ada")
        assert user.name == "ada"
        return user

    _run(scenario())


def test_ainit_that_is_not_async_is_a_definition_error() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    with pytest.raises(WrongTypeDefinition, match="__ainit__"):

        @User.define
        class Bad(User):
            def __ainit__(self) -> None:  # not async
                pass


# --- C6.2: unchain -----------------------------------------------------------


def test_ainit_returning_none_or_self_resolves_to_the_instance() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Explicit(User):
        async def __ainit__(self) -> None:
            await asyncio.sleep(0)
            self.marker = True
            # Python convention: returning nothing means "this instance"

    @User.define
    class SelfReturn(User):
        async def __ainit__(self) -> Any:  # Any: `return self` is the point
            await asyncio.sleep(0)
            return self

    async def scenario() -> None:
        user = User("ada")
        explicit = await construct(user, "Explicit")
        assert explicit.marker is True
        self_return = await construct(user, "SelfReturn")
        record = getProps(self_return)
        assert record is not None
        assert record["self"] is self_return

    _run(scenario())


def test_unchain_off_rejects_a_different_result() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Wrong(User):
        async def __ainit__(self) -> Any:  # Any: the wrong result is the point
            await asyncio.sleep(0)
            return Wrong  # a different object entirely

    async def scenario() -> None:
        user = User("ada")
        with pytest.raises(WrongModificationPattern, match="return this"):
            await construct(user, "Wrong")

    _run(scenario())


def test_unchain_on_drops_the_chain_and_returns_the_value() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    class Length(User):
        async def __ainit__(self) -> Any:  # Any: the dropped value is the point
            await asyncio.sleep(0)
            self.data = "abcdef"
            return 42  # a plain value: the chain is dropped, the value IS the result

    # config is keyword-only on the class form: call the descriptor directly
    LengthT = User.define(Length, config={"unchain": True})
    assert LengthT is Length  # form B: the decorated class is the type

    async def scenario() -> Any:
        user = User("ada")
        result = await construct(user, "Length")
        assert result == 42
        return result

    _run(scenario())


def test_async_failure_blocked_into_errored_instance() -> None:
    collection = createTypesCollection()
    seen: list[str] = []

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Bad(User):
        async def __ainit__(self) -> None:
            await asyncio.sleep(0)
            raise ValueError("async boom")

    def on_creation_error(data: dict[str, Any]) -> None:
        seen.append("creation-error")

    Bad.registerHook("creationError", on_creation_error)

    async def scenario() -> None:
        user = User("ada")
        with pytest.raises(ErroredInstance, match="async boom"):
            await construct(user, "Bad")
        assert seen == ["creation-error"]

    _run(scenario())


def test_async_failure_propagates_when_block_errors_off() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    class Bad(User):
        async def __ainit__(self) -> None:
            await asyncio.sleep(0)
            raise ValueError("async boom")

    BadT = User.define(Bad, config={"blockErrors": False})
    assert BadT is Bad  # form B: the decorated class is the type

    async def scenario() -> None:
        user = User("ada")
        with pytest.raises(ValueError, match="async boom"):
            await construct(user, "Bad")

    _run(scenario())


# --- hooks on the async path --------------------------------------------------


def test_hooks_fire_around_the_await() -> None:
    collection = createTypesCollection()
    log: list[str] = []

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        async def __ainit__(self, role: str) -> None:
            await asyncio.sleep(0)
            log.append("handler")
            self.role = role

    def on_pre(data: dict[str, Any]) -> None:
        log.append("pre")

    def on_post(data: dict[str, Any]) -> None:
        log.append("post")

    Admin.registerHook("preCreation", on_pre)
    Admin.registerHook("postCreation", on_post)

    async def scenario() -> None:
        user = User("ada")
        pending = construct(user, "Admin", "root")
        # preCreation ran at call time; postCreation waits for the await
        assert log == ["pre"]
        await pending
        assert log == ["pre", "handler", "post"]

    _run(scenario())


# --- C6.3: single-await chain --------------------------------------------------


def test_single_await_unwraps_the_whole_chain() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        async def __ainit__(self, role: Any) -> None:
            await asyncio.sleep(0)
            self.role = role

    @Admin.define
    class SuperAdmin(Admin):
        async def __ainit__(self, level: int) -> None:
            await asyncio.sleep(0)
            self.level = level

    async def scenario() -> Any:
        result = await User("ada").Admin("root").SuperAdmin(3)
        assert result.name == "ada"
        assert result.role == "root"
        assert result.level == 3
        record = getProps(result)
        assert record is not None
        assert type(record["parent"]).__name__ == "Admin"
        parent_record = getProps(record["parent"])
        assert parent_record is not None
        assert parent_record["parent"] is not None
        return result

    _run(scenario())


def test_chain_mixed_async_and_sync_steps() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Admin(User):
        async def __ainit__(self, role: str) -> None:
            await asyncio.sleep(0)
            self.role = role

    @Admin.define
    class Tagged(Admin):
        def __init__(self, tag: str) -> None:
            self.tag = tag

    async def scenario() -> Any:
        result = await User("ada").Admin("root").Tagged("t1")
        assert (result.name, result.role, result.tag) == ("ada", "root", "t1")
        return result

    _run(scenario())


def test_chain_strict_chain_point_1() -> None:
    collection = createTypesCollection()
    User, _ = _sync_user_async_admin(collection)
    User.define("Guest", null_handler)  # sibling of Admin, up the chain

    async def loose_handler(self: Any) -> None:
        await asyncio.sleep(0)

    User.define("Loose", loose_handler, {"strictChain": False})

    async def scenario() -> None:
        user = User("ada")
        guest_name = "Guest"
        missing_name = "Missing"
        chain = construct(user, "Admin", "root")
        # Admin's own type is strict: Guest (found on User, up the chain)
        # must not resolve from a pending Admin
        with pytest.raises(AttributeError):
            getattr(chain, guest_name)
        await chain  # consume the pending construction

        # a loose pending type allows the walk up
        loose_chain = construct(user, "Loose")
        guest = await getattr(loose_chain, guest_name)()
        assert type(guest).__name__ == "Guest"

        # the walk continues past ancestors without the name: Deep hangs
        # under Admin, and Guest lives one level higher, on User
        deep_name = "Deep"
        AdminType = User.subtypes["Admin"]
        AdminType.define(deep_name, loose_handler, {"strictChain": False})

        admin = await construct(user, "Admin", "root")
        deep_chain = construct(admin, deep_name)
        found = await getattr(deep_chain, guest_name)()
        assert type(found).__name__ == "Guest"

        # ... and exhausts with AttributeError when nothing matches
        admin2 = await construct(user, "Admin", "root")
        deep_chain2 = construct(admin2, deep_name)
        with pytest.raises(AttributeError):
            getattr(deep_chain2, missing_name)
        await deep_chain2  # consume the pending construction

    _run(scenario())


def test_chain_unknown_subtype_and_dunder_refused() -> None:
    collection = createTypesCollection()
    User, _ = _sync_user_async_admin(collection)

    async def scenario() -> None:
        user = User("ada")
        missing_name = "Missing"
        chain = construct(user, "Admin", "root")
        with pytest.raises(AttributeError):
            getattr(chain, missing_name)
        dunder = "__not_a_real_dunder__"
        with pytest.raises(AttributeError):
            getattr(chain, dunder)
        await chain  # consume the pending construction

    _run(scenario())


def test_chain_cannot_continue_on_a_dropped_result() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    class Number(User):
        async def __ainit__(self) -> Any:  # Any: the dropped value is the point
            await asyncio.sleep(0)
            return 7

    # strictChain off so the sibling Admin resolves from a pending
    # Number; unchain on so Number's construction drops the chain
    NumberT = User.define(Number, config={"unchain": True, "strictChain": False})
    assert NumberT is Number  # form B: the decorated class is the type

    @User.define
    class Admin(User):
        async def __ainit__(self, role: str) -> None:
            await asyncio.sleep(0)
            self.role = role

    async def scenario() -> None:
        user = User("ada")
        with pytest.raises(WrongModificationPattern, match="dropped"):
            await construct(user, "Number").Admin("root")

    _run(scenario())


def test_chain_block_errors_refuse_errored_parent() -> None:
    collection = createTypesCollection()

    @collection.define
    class User(Mnemonic):
        def __init__(self, name: str) -> None:
            self.name = name

    @User.define
    class Bad(User):
        async def __ainit__(self) -> None:
            await asyncio.sleep(0)
            raise ValueError("boom")

    async def scenario() -> None:
        user = User("ada")
        with pytest.raises(ErroredInstance, match="boom"):
            await construct(user, "Bad")
        errored = None
        try:
            await construct(user, "Bad")
        except ErroredInstance as caught:
            errored = caught
        assert errored is not None
        # constructing the next chained step from the errored parent is
        # refused exactly like the sync path
        Admin = User.define("Admin", null_handler, {"strictChain": False})
        with pytest.raises(ErroredInstance):
            await cast(Any, Admin.of)(errored)

    _run(scenario())


# --- handler swap across the sync/async boundary (C1.5) -----------------------


def test_handler_swapped_from_async_to_sync_stays_awaitable() -> None:
    collection = createTypesCollection()

    async def async_handler(self: Any) -> None:
        await asyncio.sleep(0)
        self.origin = "async"

    SyncUser = collection.define("SyncUser", async_handler)

    def sync_handler(self: Any) -> None:
        self.origin = "swapped"

    async def scenario() -> Any:
        user = await SyncUser()
        assert user.origin == "async"
        SyncUser.handler = sync_handler
        swapped: Any = SyncUser()
        assert isinstance(swapped, AsyncChain)
        resolved = await swapped
        assert resolved.origin == "swapped"
        return resolved

    _run(scenario())


def test_handler_swapped_from_sync_to_async_returns_awaitable() -> None:
    collection = createTypesCollection()

    def sync_handler(self: Any) -> None:
        self.origin = "sync"

    User = collection.define("User", sync_handler)

    async def async_handler(self: Any) -> None:
        await asyncio.sleep(0)
        self.origin = "swapped"

    async def scenario() -> Any:
        user = User()
        assert user.origin == "sync"
        User.handler = async_handler
        pending = User()
        assert isinstance(pending, AsyncChain)
        resolved = await pending
        assert resolved.origin == "swapped"
        return resolved

    _run(scenario())
