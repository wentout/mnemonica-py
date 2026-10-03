"""Construction context records (C3).

Every mnemonica instance carries a side record in a WeakKeyDictionary —
nothing user-visible on the instance itself except the one parent slot.
The record holds: type, parent, args, kwargs, timestamp, creator,
collection, subtypes, and self (installed after construction, mirroring
the JS __self__ which cannot exist before the instance does).

`creator` is the record itself: the JS __creator__ is the
InstanceCreatorContext of this construction, and our record IS that
context. It may differ from `type` in chained (async) construction, P4.

`stack` is added by the submitStack option (C4.3); the record carries the
key only when the option is on, as in JS (`__stack__` is conditional).
`__proto_proto__` has no Python analogue — it is a prototype-chain
implementation detail of the JS core; marked N/A in the matrix.
"""

import time
import traceback
import weakref
from collections.abc import Mapping
from typing import Any

from .errors import MnemonicaError

# Records are keyed by the instance, so instances stay garbage-collectable
# and attribute enumeration on the instance stays clean.
_records: weakref.WeakKeyDictionary[object, dict[str, Any]] = (
    weakref.WeakKeyDictionary()
)


def make_record(
    *,
    mn_type: type,
    parent: object | None,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    collection: object,
    subtypes: dict[str, Any],
    stack: list[str] | None = None,
) -> dict[str, Any]:
    """Create the context record for one construction."""
    record: dict[str, Any] = {
        # the contract names this key `type`
        "type": mn_type,
        "parent": parent,
        "args": args,
        "kwargs": kwargs,
        # JS records milliseconds since epoch
        "timestamp": int(time.time() * 1000),
        "collection": collection,
        # live view: reflects subtypes declared after the instance exists
        "subtypes": subtypes,
    }
    if stack is not None:
        # submitStack (C4.3): the key exists only when the option is on
        record["stack"] = stack
    # the creator context of this construction is this construction's
    # record itself (see module docstring)
    record["creator"] = record
    result = record
    return result


def capture_stack() -> list[str]:
    """The construction stack for submitStack (C4.3)."""
    result = traceback.format_stack()
    return result


def install_self(record: dict[str, Any], instance: object) -> None:
    """Install the `self` entry after construction completes.

    Held as a WEAK reference: the record lives in a WeakKeyDictionary
    keyed by the instance, and a value that strongly referenced its own
    key would anchor the instance forever (the entry can never be
    collected). getProps materializes the reference on read.
    """
    record["self"] = weakref.ref(instance)


def store_record(instance: object, record: dict[str, Any]) -> None:
    """Attach a construction record to its instance."""
    _records[instance] = record


def init_record(instance: object, record: dict[str, Any]) -> None:
    """Create a context record on an object the pipeline did not build.

    Used for errored instances (C4.2): the error object is assembled
    outside the normal construction path, so its record is stored directly.
    """
    _records[instance] = record


def get_props(instance: object) -> dict[str, Any] | None:
    """The instance's context record, or None for non-mnemonica objects."""
    try:
        result = _records.get(instance)
    except TypeError:
        # not weakref-able (e.g. plain object()) → not a mnemonica instance
        result = None
    return result


def getProps(instance: object) -> dict[str, Any] | None:
    """Public: the instance's construction context (C3).

    Materializes the weak `self` reference installed at construction, so
    `getProps(x)["self"] is x` holds for the record's live dict.
    """
    record = get_props(instance)
    if record is not None:
        self_ref = record.get("self")
        if isinstance(self_ref, weakref.ReferenceType):
            record["self"] = self_ref()
    result = record
    return result


def setProps(instance: object, values: Mapping[str, Any]) -> None:
    """Merge values into the instance's context record (rare, advanced)."""
    try:
        record = _records.get(instance)
    except TypeError:
        record = None
    if record is None:
        raise MnemonicaError("setProps: instance has no construction context")
    record.update(values)
