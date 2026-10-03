"""Types, subtypes, and construction (C1, C2, C6).

Central decision (PLAN.md): subtypes ARE subclasses. Every mnemonica type
is a real Python class with the MnemonicaType metaclass; a subtype really
subclasses its parent type, so isinstance is native. Every instance links
to its parent INSTANCE via the _mn_parent slot, and the Mnemonic base's
__getattr__ walks that link on read misses (C2.3). Writes land in the
instance's own __dict__ (C2.4) — ancestors are history.

Async (C6): a type whose handler is a coroutine function — `async def
__ainit__` on the class forms, or an `async def` handler in the function
form — makes construction AWAITABLE: `admin = await user.Admin(...)`.
The call runs the blockErrors check and preCreation hooks eagerly (the JS
fires them at `new` time); awaiting completes the handler, validates the
result per unchain (C6.2), installs self and runs postCreation/
creationError exactly as the sync path. Reading a subtype from the
pending awaitable (AsyncChain) queues the next construction, so a whole
chain unwraps with a single await (C6.3 — probed before building; the
probe is recorded in the conformance matrix).

Static typing (P0 probe 3, claude's decision 1): the metaclass kwarg or
the Mnemonic base makes class-level API (define, of, path, handler,
subtypes) visible to checkers; `type[T]` keeps it through decoration and
inheritance. Full static enrichment of `user.Admin(...)` lands with the
P5 stub generator.

Definition forms:
- B (primary, documented): @User.define / class Admin(User) — the user
  writes the base; the decorator verifies it and uses the class as-is.
- A: @User.define / class Admin: — the decorator builds the real subclass.
- C: User.define("Admin", handler) — the JS-style function form.
Admin.of(parent, ...) is the always-typed construction path.

Names reserved on a type (metaclass surface): define, of, path, handler,
subtypes, config, registerHook.
"""

from collections.abc import Callable, Mapping
from inspect import iscoroutine, iscoroutinefunction
from typing import TYPE_CHECKING, Any, NoReturn, cast, overload

from .collection import resolve_options
from .errors import (
    AlreadyDeclared,
    ErroredInstance,
    HandlerMustBeAFunction,
    MissingCallbackArgument,
    TypenameMustBeAString,
    WrongInstanceInvocation,
    WrongModificationPattern,
    WrongTypeDefinition,
)
from .hooks import (
    CREATION_ERROR,
    POST_CREATION,
    PRE_CREATION,
    HookRegistry,
    invoke_hooks,
    make_registry,
    register_hook,
)
from .props import (
    capture_stack,
    get_props,
    init_record,
    install_self,
    make_record,
    store_record,
)

if TYPE_CHECKING:
    from .collection import TypesCollection

# Reserved slot/attribute name every mnemonica instance carries.
PARENT_SLOT = "_mn_parent"


def _noop_handler(self: object, *args: Any, **kwargs: Any) -> None:
    """Default handler for types declared without one."""


class MnemonicaType(type):
    """Metaclass of every mnemonica type."""

    # set on each type at define time; declared here so checkers see them
    mn_name: str
    mn_path: str
    mn_parent_type: "MnemonicaType | None"
    mn_collection: "TypesCollection"
    mn_subtypes: dict[str, "MnemonicaType"]
    mn_handler: Callable[..., Any]
    mn_config: dict[str, bool]
    mn_hooks: HookRegistry
    mn_is_async: bool

    def __get__(cls, instance: object | None, owner: type | None = None) -> Any:
        # a subtype class stored on its parent class behaves like a
        # method: reading it from an instance binds it to that instance
        if instance is None:
            result: Any = cls
            return result
        record = get_props(instance)
        if record is not None and cls.mn_parent_type is not None:
            entity_type = cast(MnemonicaType, record["type"])
            if (
                cls.mn_parent_type is not entity_type
                and entity_type.mn_config["strictChain"]
            ):
                # C4.1 point 1: the entity's own type forbids constructing a
                # subtype found up the chain, so the attribute does not
                # resolve (the JS proxy returns undefined; AttributeError is
                # the Python equivalent of a lookup miss)
                raise AttributeError(cls.mn_name)
        result = BoundConstructor(instance, cls)
        return result

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        # calling a mnemonica TYPE constructs an instance; class creation
        # calls the metaclass itself and never reaches this method
        if "mn_path" not in vars(cls):
            # the raw Mnemonic base (or a shell mid-decoration) is not a
            # registered type: construct it normally
            result = super().__call__(*args, **kwargs)
            return result
        if cls.mn_parent_type is None:
            result = _construct(cls, None, args, kwargs)
            return result
        raise WrongInstanceInvocation(
            f"{cls.mn_parent_type.mn_path} subtypes are constructed from"
            f" a parent instance: parent.{cls.mn_name}(...)"
            f" or {cls.mn_name}.of(parent, ...)"
        )

    @property
    def path(cls) -> str:
        """The dotted path of this type in its collection (C1.2)."""
        result = cls.mn_path
        return result

    @property
    def handler(cls) -> Callable[..., Any]:
        """The constructor body; read at every construction (C1.5)."""
        result = cls.mn_handler
        return result

    @handler.setter
    def handler(cls, value: Callable[..., Any]) -> None:
        cls.mn_handler = value

    @property
    def subtypes(cls) -> dict[str, "MnemonicaType"]:
        """This type's subtypes, live (C1.2)."""
        result = cls.mn_subtypes
        return result

    @property
    def config(cls) -> dict[str, bool]:
        """This type's config, live (C4); inherits collection defaults."""
        result = cls.mn_config
        return result

    def registerHook(cls, hook_type: object, callback: object) -> None:
        """Register a hook on this type (C5.1)."""
        register_hook(cls.mn_hooks, hook_type, callback)

    @overload
    def define[T](
        cls, sub: type[T], /, *, config: Mapping[str, Any] | None = None
    ) -> type[T]: ...

    @overload
    def define(
        cls,
        name: str,
        handler: Callable[..., Any],
        config: object = None,
        /,
    ) -> "MnemonicaType": ...

    def define(
        cls,
        sub_or_name: object,
        handler: object = None,
        config: object = None,
    ) -> "MnemonicaType | type[Any]":
        """Declare a subtype under this type (C1.2); forms in module doc."""
        if isinstance(sub_or_name, str):
            name = sub_or_name
            fn = _check_handler(handler, f"{cls.mn_path}.define({name!r})")
            if name in cls.mn_subtypes:
                raise AlreadyDeclared(f"{cls.mn_path}.{name} is already declared")
            resolved = resolve_options(config, cls.mn_collection.mn_config)
            namespace: dict[str, Any] = {
                "__init__": fn,
                "__module__": getattr(fn, "__module__", "mnemonica"),
            }
            runtime = cast(MnemonicaType, _make_runtime_class(name, (cls,), namespace))
            _bind_subtype(cls, name, runtime)
            _set_type_attrs(
                runtime,
                name=name,
                path=f"{cls.mn_path}.{name}",
                parent_type=cls,
                collection=cls.mn_collection,
                handler=fn,
                config=resolved,
                is_async=iscoroutinefunction(fn),
            )
            cls.mn_subtypes[name] = runtime
            result = runtime
            return result
        if not isinstance(sub_or_name, type):
            raise TypenameMustBeAString(
                f"{cls.mn_path}.define: the type name must be a string"
            )
        shell = sub_or_name
        name = shell.__name__
        if handler is not None:
            raise WrongTypeDefinition(
                f"{cls.mn_path}.define: the class form takes no"
                " handler; use define(name, handler) for that"
            )
        if name in cls.mn_subtypes:
            raise AlreadyDeclared(f"{cls.mn_path}.{name} is already declared")
        resolved = resolve_options(config, cls.mn_collection.mn_config)
        # cast: pyright's Self@MnemonicaType has a false "no overlap" with
        # type here; identity comparison is the check
        cls_any = cast(Any, cls)
        if any(base is cls_any for base in shell.__bases__):
            # form B: the user wrote the base; use the class as-is
            runtime = cast(MnemonicaType, shell)
        else:
            for base in shell.__bases__:
                if isinstance(base, MnemonicaType):
                    raise WrongTypeDefinition(
                        f"{name} extends {base.mn_path}, not {cls.mn_path}"
                    )
            # form A: the decorator builds the real subclass
            runtime = cast(
                MnemonicaType,
                _make_runtime_class(name, (shell, cls), _namespace_from(shell)),
            )
        type_handler, is_async = _handler_from_shell(shell)
        _bind_subtype(cls, name, runtime)
        _set_type_attrs(
            runtime,
            name=name,
            path=f"{cls.mn_path}.{name}",
            parent_type=cls,
            collection=cls.mn_collection,
            handler=type_handler,
            config=resolved,
            is_async=is_async,
        )
        cls.mn_subtypes[name] = runtime
        result = runtime
        return result

    def of[A](cls: "type[A]", parent: object, *args: Any, **kwargs: Any) -> A:
        """Typed construction (C2.2): Admin.of(user, "root")."""
        self_type = cast(MnemonicaType, cls)
        parent_type = self_type.mn_parent_type
        if parent_type is None:
            if parent is not None:
                raise WrongInstanceInvocation(
                    f"{self_type.mn_path} is a root type: parent must be None"
                )
            result = cast(A, _construct(self_type, None, args, kwargs))
            return result
        # C4.1 point 2: the target type's strictChain decides whether the
        # parent must be an instance of the declared parent type
        if self_type.mn_config["strictChain"] and not isinstance(parent, parent_type):
            raise WrongModificationPattern(
                f"{self_type.mn_path} should inherit from"
                f" {parent_type.mn_path} but made on {type(parent).__name__}"
            )
        result = cast(A, _construct(self_type, parent, args, kwargs))
        return result


class Mnemonic(metaclass=MnemonicaType):
    """Base of every mnemonica instance; subclasses may declare it to make
    class-level API visible to static checkers (see module docstring).

    Python calls __getattr__ only when normal lookup MISSES, so by the
    time we run, the instance dict and the whole class MRO (own fields,
    subtype methods, parent methods) have already been consulted.

    The walk reads ancestor instance dicts; fields stored in __slots__ of
    an ancestor are not reachable this way — the subclass inherits the
    slot's member descriptor, which shadows the chain, and the value is
    not in any __dict__ (JS has no slot analogue; documented limitation).
    """

    __slots__ = ()

    def __getattr__(self, name: str) -> Any:
        # Dunders are resolved on the type by the interpreter itself;
        # answering them from the chain corrupts copy/pickle protocols
        # that probe instances for hooks (P0 probe 2, claude decision 2).
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        try:
            node: object | None = object.__getattribute__(self, PARENT_SLOT)
        except AttributeError:
            # fresh instance (copy/pickle reconstruction has no chain
            # yet); only AttributeError may ever leave __getattr__
            raise AttributeError(name) from None
        while node is not None:
            # runtime classes never declare __slots__: every instance in
            # the chain has __dict__ (see _construct), and vars() is how
            # we read it without a constant-attribute getattr
            node_dict = vars(node)
            if name in node_dict:
                result = node_dict[name]
                return result
            node = node_dict.get(PARENT_SLOT)
        raise AttributeError(name)


class BoundConstructor:
    """Reading a subtype from an instance returns this: parent + subtype."""

    __slots__ = ("_parent", "_subtype")

    def __init__(self, parent: object, subtype: "MnemonicaType") -> None:
        self._parent = parent
        self._subtype = subtype

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        subtype = self._subtype
        parent_type = subtype.mn_parent_type
        if parent_type is None:
            raise WrongInstanceInvocation(
                f"{subtype.mn_path} is a root type and cannot be"
                " constructed from a parent instance"
            )
        # C4.1 point 2: the target type's strictChain decides whether the
        # parent must be an instance of the declared parent type
        if subtype.mn_config["strictChain"] and not isinstance(
            self._parent, parent_type
        ):
            raise WrongModificationPattern(
                f"{subtype.mn_path} should inherit from"
                f" {parent_type.mn_path} but made on"
                f" {type(self._parent).__name__}"
            )
        result = _construct(subtype, self._parent, args, kwargs)
        return result


def construct_from(
    cls: "MnemonicaType",
    parent: object | None,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    """Construction entry for the utils (C7: clone/fork/merge).

    Like `of` minus the root-parent check: forking or merging a ROOT
    type re-anchors it onto the given parent (the JS fork `.call(b, ...)`
    path runs InstanceCreator with existentInstance=b even when the type
    is a root), so the result chains onto b.
    """
    parent_type = cls.mn_parent_type
    if (
        parent_type is not None
        and cls.mn_config["strictChain"]
        and not isinstance(parent, parent_type)
    ):
        raise WrongModificationPattern(
            f"{cls.mn_path} should inherit from"
            f" {parent_type.mn_path} but made on {type(parent).__name__}"
        )
    result = _construct(cls, parent, args, kwargs)
    return result


def _construct(
    cls: "MnemonicaType",
    parent: object | None,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    """The one construction pipeline for roots and subtypes.

    Identity first, data second (JS test-map pipeline): the instance and
    its context record exist before the handler runs. Runtime classes
    never declare __slots__, so every instance has __dict__ and the
    parent link always fits; user slot declarations are honoured for
    their own fields. Hook order is C5.2 (see hooks.py): preCreation
    (collection, then type) before the build; a preCreation failure
    aborts and propagates with no creationError hooks. blockErrors
    (C4.2) refuses an errored parent before any hook runs and turns a
    handler failure into an errored instance after creationError hooks.
    """
    config = cls.mn_config
    if config["blockErrors"] and isinstance(parent, BaseException):
        # constructing from an errored instance is refused (C4.2); the
        # refusal is itself an errored instance of the type being made
        raise _make_errored(cls, parent, args, parent)
    _invoke_pre_hooks(cls, parent, args)
    # cls.__new__ may be user-overridden; the cast routes around mypy's
    # type.__new__ overloads, which cannot see this call shape
    new = cast(Callable[..., Any], cls.__new__)
    instance = new(cls)
    setattr(instance, PARENT_SLOT, parent)
    stack = capture_stack() if config["submitStack"] else None
    record = make_record(
        mn_type=cls,
        parent=parent,
        args=args,
        kwargs=kwargs,
        collection=cls.mn_collection,
        subtypes=cls.mn_subtypes,
        stack=stack,
    )
    store_record(instance, record)
    # the handler is READ at every construction, so it can be swapped at
    # runtime via `Type.handler = ...`; existing instances are unaffected
    handler = cls.handler
    if cls.mn_is_async:
        # async type (C6): the call returns an awaitable; the handler
        # coroutine completes on await
        answer = handler(instance, *args, **kwargs)
        coroutine = answer if iscoroutine(answer) else _just(answer)
        result = AsyncChain(cls, instance, coroutine, parent, args, record)
        return result
    try:
        answer = handler(instance, *args, **kwargs)
    except Exception as error:
        if config["blockErrors"]:
            errored = _make_errored(cls, error, args, parent)
            _invoke_post_hooks(cls, parent, args, errored, errored_instance=True)
            raise errored
        # blockErrors off: the failure propagates as-is (C4.2)
        raise
    if iscoroutine(answer):
        # the handler was swapped for an async one at runtime (C1.5):
        # this construction is awaitable from here on
        result = AsyncChain(cls, instance, answer, parent, args, record)
        return result
    # `self` is installed after construction: the JS __self__ cannot exist
    # before the instance is made (FOR_HUMANS internal-properties table)
    install_self(record, instance)
    _invoke_post_hooks(cls, parent, args, instance, errored_instance=False)
    result = instance
    return result


async def _just(value: Any) -> Any:
    """A coroutine resolving to `value` — for handlers swapped from async
    to sync at runtime (C1.5): the construction stays awaitable."""
    result = value
    return result


async def _complete_async(
    cls: "MnemonicaType",
    instance: object,
    coroutine: "Any",
    parent: object | None,
    args: tuple[Any, ...],
    record: dict[str, Any],
) -> Any:
    """Await the handler coroutine and finish the async construction (C6).

    Result rule (C6.2, adapted to Python): None means "the instance" —
    the Python __init__ convention of returning nothing; returning the
    instance explicitly is honoured; any OTHER value with unchain on
    drops the chain and IS the result; with unchain off it is a
    WrongModificationPattern, the JS "must resolve to its own instance".
    Hooks and blockErrors behave exactly as on the sync path: self is
    installed and postCreation fires only now, after the await, and a
    handler failure becomes an errored instance (creationError first)
    when blockErrors is on.
    """
    config = cls.mn_config
    try:
        returned = await coroutine
    except Exception as error:
        if config["blockErrors"]:
            errored = _make_errored(cls, error, args, parent)
            _invoke_post_hooks(cls, parent, args, errored, errored_instance=True)
            raise errored
        raise
    if returned is None or returned is instance:
        resolved: Any = instance
    elif config["unchain"]:
        # unchain (C6.2): the chain is dropped, the value IS the result
        resolved = returned
    else:
        raise WrongModificationPattern(
            f"async constructor {cls.mn_path} must resolve to its own"
            " instance (`return this`), got"
            f" {type(returned).__name__}"
        )
    if resolved is instance:
        install_self(record, instance)
        _invoke_post_hooks(cls, parent, args, instance, errored_instance=False)
    result = resolved
    return result


def _resolve_subtype(entity_type: "MnemonicaType", name: str) -> "MnemonicaType":
    """Subtype resolution for async chains — C4.1 point 1, as in
    MnemonicaType.__get__: direct subtypes always resolve; ancestor
    subtypes resolve only when the entity's type allows it."""
    direct = entity_type.mn_subtypes.get(name)
    if direct is not None:
        result = direct
        return result
    if entity_type.mn_config["strictChain"]:
        raise AttributeError(name)
    node = entity_type.mn_parent_type
    while node is not None:
        found = node.mn_subtypes.get(name)
        if found is not None:
            result = cast(MnemonicaType, found)
            return result
        node = node.mn_parent_type
    raise AttributeError(name)


class AsyncChain:
    """The awaitable an async construction returns (C6).

    Reading a subtype from the pending chain queues the next
    construction and returns self, so a whole chain unwraps with a
    single await (C6.3). Only subtype names resolve; dunders are refused
    so copy/pickle probes stay intact.
    """

    __slots__ = (
        "_args",
        "_cls",
        "_coroutine",
        "_instance",
        "_parent",
        "_pending_type",
        "_record",
        "_steps",
    )

    def __init__(
        self,
        cls: "MnemonicaType",
        instance: object,
        coroutine: Any,
        parent: object | None,
        args: tuple[Any, ...],
        record: dict[str, Any],
    ) -> None:
        self._cls = cls
        self._instance = instance
        self._coroutine = coroutine
        self._parent = parent
        self._args = args
        self._record = record
        self._pending_type = cls
        self._steps: list[tuple[MnemonicaType, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        subtype = _resolve_subtype(self._pending_type, name)

        def bound(*args: Any, **kwargs: Any) -> "AsyncChain":
            # queue the next construction; the parent is decided when the
            # chain is awaited (the previous step's result)
            self._steps.append((subtype, args, kwargs))
            self._pending_type = subtype
            result: AsyncChain = self
            return result

        result: Any = bound
        return result

    def __await__(self) -> Any:
        return self._run().__await__()

    async def _finish_first(self) -> Any:
        result = await _complete_async(
            self._cls,
            self._instance,
            self._coroutine,
            self._parent,
            self._args,
            self._record,
        )
        return result

    async def _run(self) -> Any:
        """Complete the first construction, then every queued step in
        order; each step's result is the next step's parent."""
        cls = self._cls
        current: Any = await self._finish_first()
        for subtype, args, kwargs in self._steps:
            if get_props(current) is None:
                raise WrongModificationPattern(
                    f"cannot construct {subtype.mn_path} from a non-instance"
                    f" result of {cls.mn_path} (the chain was dropped)"
                )
            made = _construct(subtype, current, args, kwargs)
            if isinstance(made, AsyncChain):
                current = await made._finish_first()
            else:
                current = made
            cls = subtype
        result = current
        return result


def _invoke_pre_hooks(
    cls: "MnemonicaType",
    parent: object | None,
    args: tuple[Any, ...],
) -> None:
    """preCreation hooks: collection first, then type (C5.2).

    A failure here aborts construction and propagates unwrapped — the JS
    preCreation hooks have no throwModificationError; the same is true here.
    """
    hook_data: dict[str, Any] = {
        "type": cls,
        "TypeName": cls.mn_name,
        "existentInstance": parent,
        "args": args,
    }
    invoke_hooks(cls.mn_collection.mn_hooks, PRE_CREATION, hook_data)
    invoke_hooks(cls.mn_hooks, PRE_CREATION, hook_data)


def _invoke_post_hooks(
    cls: "MnemonicaType",
    parent: object | None,
    args: tuple[Any, ...],
    instance: object,
    *,
    errored_instance: bool,
) -> None:
    """postCreation (success) or creationError (errored) hooks (C5.2).

    Type hooks first, then collection hooks — the JS invokePostHooks
    calls type.invokeHook before collection.invokeHook.
    """
    hook_type = CREATION_ERROR if errored_instance else POST_CREATION

    def throw_modification_error(error: BaseException) -> NoReturn:
        # the JS hookData.throwModificationError: raise an errored
        # instance carrying this construction
        raise _make_errored(cls, error, args, parent)

    hook_data: dict[str, Any] = {
        "type": cls,
        "TypeName": cls.mn_name,
        "existentInstance": parent,
        "inheritedInstance": instance,
        "args": args,
        "throwModificationError": throw_modification_error,
    }
    invoke_hooks(cls.mn_hooks, hook_type, hook_data)
    invoke_hooks(cls.mn_collection.mn_hooks, hook_type, hook_data)


def _make_errored(
    cls: "MnemonicaType",
    error: BaseException,
    args: tuple[Any, ...],
    parent: object | None,
) -> ErroredInstance:
    """The errored instance of blockErrors (C4.2).

    An error object whose construction data lives in its context record
    (getProps), mirroring the JS throwModificationError: exceptionReason,
    reasons, surplus, args, originalError, instance. The parent link is
    installed so the chain below the failure stays walkable.
    """
    errored = ErroredInstance(f"creation of [ {cls.mn_path} ] failed: {error}")
    setattr(errored, PARENT_SLOT, parent)
    record: dict[str, Any] = {
        "type": cls,
        "parent": parent,
        "args": args,
        # the full construction context: an errored instance exports its
        # own lineage graph like any instance (the Go parity: the errored
        # instance is a node of its own graph)
        "collection": cls.mn_collection,
        "subtypes": cls.mn_subtypes,
        "exceptionReason": error,
        "reasons": [error],
        "surplus": [],
        "originalError": error,
        "instance": errored,
    }
    init_record(errored, record)
    result = errored
    return result


def _namespace_from(shell: type) -> dict[str, Any]:
    """Copy a shell class's namespace for the runtime subclass (form A).

    __slots__ is not copied: the shell already lays those slots out, and
    re-declaring them in the subclass conflicts. Zero-arg super() in form
    A methods still refers to the shell class — form B is the form for
    classes that use super().
    """
    skip = {"__dict__", "__weakref__", "__slots__"}
    result = {key: value for key, value in vars(shell).items() if key not in skip}
    return result


def _set_type_attrs(
    runtime: "MnemonicaType",
    *,
    name: str,
    path: str,
    parent_type: "MnemonicaType | None",
    collection: "TypesCollection",
    handler: Callable[..., Any],
    config: dict[str, bool],
    is_async: bool,
) -> None:
    runtime.mn_name = name
    runtime.mn_path = path
    runtime.mn_parent_type = parent_type
    runtime.mn_collection = collection
    runtime.mn_subtypes = {}
    runtime.mn_handler = handler
    runtime.mn_config = config
    runtime.mn_hooks = make_registry()
    runtime.mn_is_async = is_async


def _bind_subtype(
    parent_type: "MnemonicaType",
    name: str,
    runtime: "MnemonicaType",
) -> None:
    """Store the subtype on its parent class.

    __set_name__ needs no manual call: type.__new__ fires it for the
    runtime class of forms A and C, and the class statement fires it for
    form B (pinned by test_set_name_is_called_when_binding).
    """
    setattr(parent_type, name, runtime)


def _check_handler(handler: object, context: str) -> Callable[..., Any]:
    if handler is None:
        raise MissingCallbackArgument(f"{context}: handler is required")
    if not callable(handler):
        raise HandlerMustBeAFunction(f"{context}: handler must be callable")
    result = cast(Callable[..., Any], handler)
    return result


def _handler_from_shell(shell: type) -> tuple[Callable[..., Any], bool]:
    """The (handler, is_async) pair for a class-form definition.

    ONLY the subtype's own __init__ runs at construction (the parent is
    already constructed) — an inherited __init__ must not re-run, so a
    shell without its own __init__ gets the no-op, not User.__init__.

    Async (C6): an own `async def __ainit__` makes the type awaitable and
    takes precedence over __init__ (an __ainit__ that is not a coroutine
    function is a definition error, like the JS define-time shape
    errors). An own `async def __init__` is honoured the same way.
    """
    own_ainit = shell.__dict__.get("__ainit__")
    if own_ainit is not None:
        if not iscoroutinefunction(own_ainit):
            raise WrongTypeDefinition(
                f"{shell.__name__}.__ainit__ must be declared with async def"
            )
        result = (cast(Callable[..., Any], own_ainit), True)
        return result
    own_init = shell.__dict__.get("__init__")
    if own_init is None:
        result = (_noop_handler, False)
        return result
    is_async = iscoroutinefunction(own_init)
    result = (cast(Callable[..., Any], own_init), is_async)
    return result


def _make_runtime_class(
    name: str, bases: tuple[type, ...], namespace: dict[str, Any]
) -> Any:
    """Create a class object with the MnemonicaType metaclass.

    The one fully dynamic spot in define: checkers cannot model "a fresh
    class object" (mypy cannot match type.__new__'s overloads through the
    metaclass call at all), so the callee and result are Any by design.
    """
    maker = cast(Any, MnemonicaType)
    result = maker(name, bases, namespace)
    return result


@overload
def define(
    name: str,
    handler: Callable[..., Any],
    config: object = None,
    /,
    *,
    collection: "TypesCollection | None" = None,
) -> MnemonicaType: ...


@overload
def define[T](
    cls: type[T],
    handler: None = None,
    /,
    *,
    config: Mapping[str, Any] | None = None,
    collection: "TypesCollection | None" = None,
) -> type[T]: ...


def define(
    name_or_cls: object,
    handler: object = None,
    config: object = None,
    *,
    collection: "TypesCollection | None" = None,
) -> "MnemonicaType | type[Any]":
    """Declare a root type (C1.2); forms in types.py's module docstring."""
    from .collection import default_collection

    coll = collection if collection is not None else default_collection()
    if isinstance(name_or_cls, str):
        name = name_or_cls
        fn = _check_handler(handler, f"define({name!r})")
        if name in coll.mn_roots:
            raise AlreadyDeclared(f"{name} is already declared")
        resolved = resolve_options(config, coll.mn_config)
        namespace: dict[str, Any] = {
            "__init__": fn,
            "__module__": getattr(fn, "__module__", "mnemonica"),
        }
        runtime = cast(MnemonicaType, _make_runtime_class(name, (Mnemonic,), namespace))
        _set_type_attrs(
            runtime,
            name=name,
            path=name,
            parent_type=None,
            collection=coll,
            handler=fn,
            config=resolved,
            is_async=iscoroutinefunction(fn),
        )
        coll.mn_roots[name] = runtime
        result = runtime
        return result
    if not isinstance(name_or_cls, type):
        raise TypenameMustBeAString("define: the type name must be a string")
    shell = name_or_cls
    if handler is not None:
        raise WrongTypeDefinition(
            "define: the class form takes no handler;"
            " use define(name, handler) for that"
        )
    name = shell.__name__
    if name in coll.mn_roots:
        raise AlreadyDeclared(f"{name} is already declared")
    resolved = resolve_options(config, coll.mn_config)
    namespace = _namespace_from(shell)
    runtime = cast(
        MnemonicaType, _make_runtime_class(name, (shell, Mnemonic), namespace)
    )
    type_handler, is_async = _handler_from_shell(shell)
    _set_type_attrs(
        runtime,
        name=name,
        path=name,
        parent_type=None,
        collection=coll,
        handler=type_handler,
        config=resolved,
        is_async=is_async,
    )
    coll.mn_roots[name] = runtime
    result = runtime
    return result
