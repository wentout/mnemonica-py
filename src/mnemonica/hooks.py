"""Lifecycle hooks (C5).

Three hook types: preCreation, postCreation, creationError, registered on a
type or on a collection (C5.1). Order (C5.2, from the JS InstanceCreator):

- preCreation: collection hooks first, then type hooks; a failure aborts
  construction and the error propagates as-is — no creationError hooks run;
- then the instance is built and the handler runs;
- postCreation (success) or creationError (an errored instance, C4.2):
  type hooks first, then collection hooks — the JS invokePostHooks calls
  type.invokeHook before collection.invokeHook. (rules-hooks.md says
  "collection first" for post hooks; the code is authoritative — the
  discrepancy is recorded in docs/conformance.md.)

The hook data carries the JS key names (type, TypeName, existentInstance,
inheritedInstance, args, throwModificationError) because hooks are the
contract-facing surface: FOR_HUMANS documents exactly these names.
throwModificationError is present only in postCreation / creationError data;
calling it raises an errored instance (C4.2) for the type being made.
"""

from collections.abc import Callable
from typing import Any, cast

from .errors import MissingHookCallback, WrongHookType

PRE_CREATION = "preCreation"
POST_CREATION = "postCreation"
CREATION_ERROR = "creationError"

# the JS registerHook rejects anything outside this list (C5.3)
HOOK_TYPES = (PRE_CREATION, POST_CREATION, CREATION_ERROR)

HookCallback = Callable[[dict[str, Any]], Any]
HookRegistry = dict[str, list[HookCallback]]


def make_registry() -> HookRegistry:
    """A fresh hook store for a type or a collection."""
    result: HookRegistry = {}
    return result


def register_hook(registry: HookRegistry, hook_type: object, callback: object) -> None:
    """Register a callback under a known hook type (C5.1, C5.3)."""
    if hook_type not in HOOK_TYPES:
        raise WrongHookType(f"unknown hook type: {hook_type!r}")
    if not callable(callback):
        raise MissingHookCallback(f"{hook_type}: hook callback is required")
    callbacks = registry.setdefault(hook_type, [])
    callbacks.append(cast(HookCallback, callback))


def invoke_hooks(
    registry: HookRegistry, hook_type: str, hook_data: dict[str, Any]
) -> None:
    """Run every callback registered for the hook type, in registration order."""
    for callback in registry.get(hook_type, ()):
        callback(hook_data)
