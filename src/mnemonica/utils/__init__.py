"""Utilities (C7).

Standalone versions of the instance introspection/manipulation methods.
The JS names are the primary API (`toJSON`, `collectConstructors`), so the
conformance matrix maps 1:1; snake_case aliases exist only where the plan
or matrix says so (nowhere here).

Adaptations from the JS, each recorded in docs/conformance.md:

- the JS "not an object" guards (`instance !== Object(instance)`) have no
  Python call boundary — everything is an object. A value without
  `__dict__` raises `WrongInstanceInvocation` instead (the closest
  analogue of the JS guard);
- `utils.exception` is a factory function: Python has no `new` keyword,
  so the "must be called with new" check has no analogue, and the wrapped
  error is typed `BaseException`, so the JS `error instanceof Error`
  check is N/A in the typed port;
- `parse` implements the FIXED JS semantics: `parent` is the parent
  INSTANCE — the same object `utils.parent(instance)` returns, None for
  a root. `proto`/`joint` are JS prototype-layer details → N/A;
- `fork(instance)` returns a `ForkConstructor`; its DAG form keeps the JS
  name: `fork(instance).call(otherParent, *args)`;
- `utils.merge` is literally `fork(a).call(b, ...args)`: the new instance
  is of a's type chained onto b; the JS "A wins" field merge is
  type-level only (runtime fields come from the handler args and b's
  chain), so that is what the port does.
"""

import json
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Literal, cast, overload

from ..errors import (
    ErroredInstance,
    WrongArgumentsUsed,
    WrongInstanceInvocation,
    WrongModificationPattern,
)
from ..props import get_props, init_record
from ..types import PARENT_SLOT, MnemonicaType, construct_from

if TYPE_CHECKING:
    from ..collection import TypesCollection

__all__ = [
    "clone",
    "collectConstructors",
    "deepParse",
    "exception",
    "extract",
    "fork",
    "id_of",
    "lineage",
    "merge",
    "parent",
    "parse",
    "pick",
    "sibling",
    "toJSON",
]


def _ensure_object(instance: object, util: str) -> None:
    """The JS `instance !== Object(instance)` guard, Python edition.

    Everything in Python is an object, so the guard cannot fail on
    "primitive-ness"; what can fail is having no __dict__ to read.
    """
    try:
        vars(instance)
    except TypeError:
        raise WrongInstanceInvocation(f"{util}: instance must be an object") from None


def _chain_items(instance: object) -> Iterator[tuple[str, Any]]:
    """(name, value) pairs along the instance chain, nearest first.

    The parent slot is internal wiring and is never exposed. A chain
    node without __dict__ (a DAG parent of an exotic kind) terminates
    the walk.
    """
    node: object | None = instance
    while node is not None:
        try:
            node_vars = vars(node)
        except TypeError:
            return
        for name, value in node_vars.items():
            if name != PARENT_SLOT:
                yield name, value
        node = node_vars.get(PARENT_SLOT)


def _chain_get(instance: object, key: str) -> Any:
    """Nearest-first chain lookup; the parent slot stays internal."""
    if key == PARENT_SLOT:
        result: Any = None
        return result
    for name, value in _chain_items(instance):
        if name == key:
            result = value
            return result
    result = None
    return result


def extract(instance: object) -> dict[str, Any]:
    """Flat user fields along the chain, nearest first (C7).

    Fields the instance shadows stay local (C2.4): the nearest value
    wins, ancestors are history.
    """
    _ensure_object(instance, "extract")
    extracted: dict[str, Any] = {}
    for name, value in _chain_items(instance):
        if name not in extracted:
            extracted[name] = value
    result = extracted
    return result


def pick(instance: object, *args: "str | list[str]") -> dict[str, Any]:
    """Specific fields from the instance and its chain (C7).

    Keys may be spread or given as one list; a key missing along the
    chain lands as None (the JS `undefined`).
    """
    _ensure_object(instance, "pick")
    keys: list[str] = []
    for arg in args:
        if isinstance(arg, list):
            keys.extend(arg)
        else:
            keys.append(arg)
    picked: dict[str, Any] = {}
    for key in keys:
        picked[key] = _chain_get(instance, key)
    result = picked
    return result


def _node_name(node: object) -> str:
    """The JS `constructor.name` of a chain node: the type name for
    mnemonica nodes, the class name otherwise."""
    record = get_props(node)
    if record is not None:
        result = cast(MnemonicaType, record["type"]).mn_name
        return result
    result = type(node).__name__
    return result


def parent(instance: object, path: str | None = None) -> object | None:
    """The parent instance, or the nearest ancestor matching a path (C7).

    A single name matches the nearest ancestor of that type; a dotted
    path must match contiguously upwards, and the instance itself is
    never a candidate. No match (or a non-mnemonica instance) → None —
    the lookup never raises.
    """
    _ensure_object(instance, "parent")
    record = get_props(instance)
    if record is None:
        result: object | None = None
        return result
    current: object | None = record["parent"]
    if path is None or current is None:
        return current
    segments = path.split(".")
    last = len(segments) - 1
    while current is not None:
        if _node_name(current) == segments[last]:
            if last == 0:
                return current
            ancestor: object | None = current
            matched = True
            for i in range(last - 1, -1, -1):
                ancestor_record = get_props(ancestor)
                if ancestor_record is None:
                    matched = False
                    break
                ancestor = ancestor_record["parent"]
                if ancestor is None or _node_name(ancestor) != segments[i]:
                    matched = False
                    break
            if matched:
                return current
        current_record = get_props(current)
        if current_record is None:
            return None
        current = current_record["parent"]
    result = None
    return result


def clone(instance: object) -> Any:
    """A new instance of the same type, same parent, same args (C7)."""
    fork_fn = fork(instance)
    result = fork_fn()
    return result


class ForkConstructor:
    """What `fork(instance)` returns: a constructor for forked instances.

    Called with no arguments it reuses the original construction
    arguments; called with arguments it uses those. The DAG form keeps
    the JS name: `fork(instance).call(otherParent, *args)` makes the
    same type from another parent.
    """

    __slots__ = ("_args", "_kwargs", "_parent", "_type")

    def __init__(self, instance: object) -> None:
        record = get_props(instance)
        if record is None:
            raise WrongInstanceInvocation("fork: instance must be a mnemonica instance")
        self._type = cast(MnemonicaType, record["type"])
        self._parent = record["parent"]
        self._args = record["args"]
        self._kwargs = record["kwargs"]

    def _resolve_args(
        self, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        if args or kwargs:
            result = (args, kwargs)
            return result
        result = (self._args, self._kwargs)
        return result

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Fork from the SAME parent (same args when none are given)."""
        fork_args, fork_kwargs = self._resolve_args(args, kwargs)
        result = construct_from(self._type, self._parent, fork_args, fork_kwargs)
        return result

    def call(self, parent: object, *args: Any, **kwargs: Any) -> Any:
        """The DAG form (the JS `fork(instance).call(thisArg, ...args)`)."""
        fork_args, fork_kwargs = self._resolve_args(args, kwargs)
        result = construct_from(self._type, parent, fork_args, fork_kwargs)
        return result


def fork(instance: object) -> ForkConstructor:
    """A constructor for forking this instance (C7)."""
    result = ForkConstructor(instance)
    return result


class SiblingAccessor:
    """What `sibling(instance)` returns: sibling ROOT types of the same
    collection, by call (`accessor("Name")`) or attribute
    (`accessor.Name`); unknown names → None (the JS undefined)."""

    __slots__ = ("_collection",)

    def __init__(self, instance: object) -> None:
        record = get_props(instance)
        if record is None:
            raise WrongInstanceInvocation(
                "sibling: instance must be a mnemonica instance"
            )
        self._collection = cast("TypesCollection", record["collection"])

    def __call__(self, name: str) -> "MnemonicaType | None":
        result = self._collection.mn_roots.get(name)
        return result

    def __getattr__(self, name: str) -> "MnemonicaType | None":
        # dunders are resolved by the interpreter itself; answering them
        # from the collection corrupts copy/pickle probes (same rule as
        # Mnemonic.__getattr__)
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        result = self._collection.mn_roots.get(name)
        return result


def sibling(instance: object) -> SiblingAccessor:
    """Access sibling root types from the instance's collection (C7)."""
    result = SiblingAccessor(instance)
    return result


def exception(instance: object, error: BaseException, *args: Any) -> ErroredInstance:
    """An error carrying the instance; the data lives in the error's
    context record, readable via getProps (C7): args, originalError,
    instance — plus exceptionReason/reasons/surplus inherited from an
    already-packaged error (the JS exceptionConstructor inheritance).

    Adapted from the JS: a factory function (Python has no `new`), and
    the error chains onto the wrapped error (the JS ExceptionCreator
    uses it as existentInstance).
    """
    record = get_props(instance)
    if record is None:
        raise WrongArgumentsUsed("exception: instance should be a mnemonica instance")
    instance_type = cast(MnemonicaType, record["type"])
    data: dict[str, Any] = {
        "type": instance_type,
        "parent": error,
        "args": args,
        "originalError": error,
        "instance": instance,
    }
    error_record = get_props(error)
    if error_record is not None:
        # the wrapped error was already packaged: inherit its data
        for key in ("exceptionReason", "reasons", "surplus"):
            if key in error_record:
                data[key] = error_record[key]
    exc = ErroredInstance(str(error))
    setattr(exc, PARENT_SLOT, error)
    init_record(exc, data)
    result = exc
    return result


def merge(a: object, b: object, *args: Any) -> Any:
    """`fork(a).call(b, ...args)`: a new instance of a's type chained
    onto b (C7). The JS object-ness checks on A/B have no Python
    analogue; A must be a mnemonica instance (WrongArgumentsUsed)."""
    record = get_props(a)
    if record is None:
        raise WrongArgumentsUsed("A should be a mnemonica instance")
    forked = ForkConstructor(a)
    result = forked.call(b, *args)
    return result


def parse(instance: object) -> dict[str, Any]:
    """A one-level snapshot of the instance (C7).

    FIXED JS semantics: `parent` is the parent INSTANCE — the same
    object `utils.parent(instance)` returns, None for a root. `proto`/
    `joint` are JS prototype-layer details → N/A (see the matrix).
    """
    record = get_props(instance)
    if record is None:
        if isinstance(instance, MnemonicaType):
            raise WrongArgumentsUsed(
                'parse: have to use "instance" itself, not its type'
            )
        raise WrongModificationPattern("parse: instance has no construction context")
    result = {
        "name": cast(MnemonicaType, record["type"]).mn_name,
        "props": extract(instance),
        "self": instance,
        "parent": record["parent"],
    }
    return result


def toJSON(instance: object) -> str:
    """The extracted fields as a JSON object string (C7).

    None values are skipped (the JS null/undefined skip); values that
    cannot be encoded are replaced with a description object, matching
    the JS JSON.stringify catch. Keys are escaped with json.dumps —
    deviation: the JS writes `"${name}"` raw, so a key containing a
    quote produces invalid JSON there; the port always produces valid
    JSON (bugs are not ported). A fieldless instance yields "{}" —
    deviation: JS returns "{" (invalid JSON; bug, reported to viktor).
    """
    extracted = extract(instance)
    body = "{"
    for name, value in extracted.items():
        if value is None:
            continue
        try:
            encoded = json.dumps(value, separators=(",", ":"))
        except (TypeError, ValueError) as error:
            encoded = json.dumps(
                {
                    "description": (
                        "This value type is not supported by JSON.stringify"
                    ),
                    "stack": "",
                    "message": str(error),
                },
                separators=(",", ":"),
            )
        body += f"{json.dumps(name)}:{encoded},"
    body = body.removesuffix(",")
    body += "}"
    result = body
    return result


@overload
def collectConstructors(instance: object, asSequence: Literal[True]) -> list[str]: ...


@overload
def collectConstructors(
    instance: object, asSequence: Literal[False] = False
) -> dict[str, bool]: ...


def collectConstructors(
    instance: object, asSequence: bool = False
) -> "list[str] | dict[str, bool]":
    """Constructor names along the instance chain (C7).

    A mnemonica chain yields its type names from the instance up to the
    root, then the base markers (`Mnemonic`, `Mnemosyne` — the JS
    reaches the MNEMONICA base and appends MNEMOSYNE). A non-mnemonica
    node contributes `Object` and terminates the walk; None contributes
    nothing. As a lookup object every name maps to True.
    """
    names: list[str] = []
    if instance is not None:
        node: object | None = instance
        while True:
            node_record = get_props(node)
            if node_record is None:
                names.append("Object")
                break
            names.append(cast(MnemonicaType, node_record["type"]).mn_name)
            node = node_record["parent"]
            if node is None:
                names.append("Mnemonic")
                names.append("Mnemosyne")
                break
    if asSequence:
        return names
    lookup = {name: True for name in names}
    return lookup


# deepParse / lineage live in their own module (the lethe export); they
# are imported here, at the END, because lineage builds on parse — the
# circular reference resolves only once parse exists
# id_of is the public lazy instance id (a span and a lineage
# graph join on it)
from mnemonica.utils.lineage import deepParse, id_of, lineage
