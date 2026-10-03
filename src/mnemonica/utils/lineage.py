"""Lineage export — the cross-language contract (@mnemonica/lethe).

`deepParse` is the multi-level version of `parse`: the one-level
snapshots of the instance and every ancestor, instance first, root last,
walking the REAL parent-instance links (the per-type class hops never
appear).

`lineage` exports the lineage graph of the given instances in the lethe
format: version "1", heads (ids in argument order), and nodes keyed by
instance id — every reachable instance deduplicated at any depth. A field
holding another mnemonica instance exports as `{ "$ref": id }`; values
JSON cannot carry export as `{ "$mnemonica": "unsupported", "kind": … }`
placeholders (the schema's enum is the cross-language set — never an
error). `args`/`props` are opt-in.

Instance ids are implementation-specific by contract: a per-process
random prefix plus a process-local counter, held LAZILY in a
WeakKeyDictionary — stable within one process, never reused, nothing
retained (an id'd instance stays collectable), and never compared across
processes or languages (the fixture comparison maps ids 1:1 in
first-encounter order — see the lethe testdata README).
"""

import math
import secrets
import weakref
from collections.abc import Iterable
from typing import Any, cast

from mnemonica.errors import WrongModificationPattern
from mnemonica.props import get_props
from mnemonica.types import PARENT_SLOT, MnemonicaType

# per-process random prefix + process-local counter (the id convention:
# implementation-specific, stable within one process, never reused)
_id_prefix = secrets.token_hex(4)
_id_counter = 0
_instance_ids: weakref.WeakKeyDictionary[object, str] = weakref.WeakKeyDictionary()


def id_of(instance: object) -> str:
    """The instance's id, assigned lazily and retained nowhere."""
    global _id_counter
    known = _instance_ids.get(instance)
    if known is not None:
        result = known
        return result
    _id_counter += 1
    assigned = f"{_id_prefix}:{_id_counter}"
    _instance_ids[instance] = assigned
    result = assigned
    return result


def _unsupported(kind: str) -> dict[str, str]:
    result = {"$mnemonica": "unsupported", "kind": kind}
    return result


def _is_instance(value: object) -> bool:
    if isinstance(value, str | bytes | bytearray):
        return False
    # get_props already returns None for values that cannot be instances
    # (unhashable, not weakref-able)
    found = get_props(value) is not None
    result = found
    return result


def _export_value(value: Any, seen: set[int], graph: "_Graph") -> Any:
    """Export one field value: instances as $ref, JSON-safe values as-is,
    anything else as a tagged placeholder (never an error)."""
    result: Any
    if value is None or isinstance(value, bool | str):
        result = value
        return result
    if isinstance(value, int):
        result = value
        return result
    if isinstance(value, float):
        if math.isnan(value):
            result = _unsupported("nan")
            return result
        if math.isinf(value):
            kind = "+inf" if value > 0 else "-inf"
            result = _unsupported(kind)
            return result
        result = value
        return result
    if _is_instance(value):
        ref = {"$ref": _visit(value, graph)}
        result = ref
        return result
    if isinstance(value, complex):
        result = _unsupported("complex")
        return result
    if callable(value):
        result = _unsupported("func")
        return result
    if isinstance(value, dict):
        identity = id(cast(Any, value))
        if identity in seen:
            result = _unsupported("cycle")
            return result
        seen.add(identity)
        exported: dict[str, Any] = {}
        # cast: isinstance-narrowing an Any leaves Unknown type
        # arguments that pyright strict rejects
        for key, item in cast(dict[Any, Any], value).items():  # type: ignore[redundant-cast]
            if isinstance(key, str):
                name: str = key
            elif isinstance(key, int) and not isinstance(key, bool):
                # the schema allows string-or-integer map keys; JSON
                # object keys are strings (as in Go's json.Marshal)
                name = str(key)
            else:
                seen.discard(identity)
                result = _unsupported("map-keys")
                return result
            exported[name] = _export_value(item, seen, graph)
        seen.discard(identity)
        result = exported
        return result
    if isinstance(value, list | tuple):
        identity = id(cast(Any, value))
        if identity in seen:
            result = _unsupported("cycle")
            return result
        seen.add(identity)
        sequence = cast(list[Any], value)
        exported_list = [_export_value(item, seen, graph) for item in sequence]
        seen.discard(identity)
        result = exported_list
        return result
    # anything else (bytes, sets, modules, ...) — the enum has no finer
    # kind for Python-only shapes
    result = _unsupported("invalid")
    return result


class _Graph:
    """The graph under construction and its dedup/visiting sets."""

    def __init__(self, *, with_args: bool, prop_keys: list[str] | None) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.paths: dict[str, str] = {}
        self.visiting: set[str] = set()
        self.with_args = with_args
        self.prop_keys = prop_keys


def _visit(instance: object, graph: _Graph) -> str:
    """Export one instance (depth first): own fields in declaration order
    FIRST (a $ref target joins at first encounter), then the parent."""
    record = get_props(instance)
    if record is None:
        raise WrongModificationPattern("lineage: instance has no construction context")
    identity = id_of(instance)
    # dedup at any depth; the visiting set also breaks instance-valued
    # field cycles (a field pointing at its own instance)
    if identity in graph.nodes or identity in graph.visiting:
        result = identity
        return result
    graph.visiting.add(identity)

    mn_type = cast(MnemonicaType, record["type"])

    # own fields: this level's own __dict__ only, parent slot excluded —
    # embedded parents and the record never appear here
    own = {
        name: _export_value(value, set(), graph)
        for name, value in vars(instance).items()
        if name != PARENT_SLOT
    }

    node_args: Any = None
    has_args = False
    if graph.with_args:
        node_args = _export_value(record["args"], set(), graph)
        has_args = True

    node_props: dict[str, Any] | None = None
    if graph.prop_keys is not None:
        node_props = {}
        for key in graph.prop_keys:
            node_props[key] = _export_value(record.get(key), set(), graph)

    # then the parent — the type path is the parent's path plus this
    # level's name (names alone collide across levels and collections)
    parent_id: str | None = None
    path = mn_type.mn_name
    parent = record["parent"]
    if parent is not None and _is_instance(parent):
        parent_id = _visit(parent, graph)
        path = f"{graph.paths[parent_id]}.{mn_type.mn_name}"

    node: dict[str, Any] = {
        "type": {"collection": record["collection"].name, "path": path},
        "own": own,
        "parent": parent_id,
    }
    if has_args:
        node["args"] = node_args
    if node_props is not None:
        node["props"] = node_props

    graph.nodes[identity] = node
    graph.paths[identity] = path
    graph.visiting.discard(identity)
    result = identity
    return result


def lineage(
    instances: object | Iterable[object],
    *,
    args: bool = False,
    props: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Export the lineage graph of the given instance(s) in the lethe
    format — what survives when live instances are forgotten."""
    if _is_instance(instances):
        heads_input: list[object] = [instances]
    else:
        heads_input = list(cast(Iterable[object], instances))
    graph = _Graph(with_args=args, prop_keys=list(props) if props is not None else None)
    heads = [_visit(instance, graph) for instance in heads_input]
    result = {"version": "1", "heads": heads, "nodes": graph.nodes}
    return result


def deepParse(instance: object) -> list[dict[str, Any]]:
    """The one-level snapshots along the chain, instance first, root last."""
    from mnemonica.utils import parse

    snapshots: list[dict[str, Any]] = []
    cursor: object | None = instance
    while cursor is not None:
        record = get_props(cursor)
        if record is None:
            break
        snapshots.append(parse(cursor))
        cursor = record["parent"]
    result = snapshots
    return result
