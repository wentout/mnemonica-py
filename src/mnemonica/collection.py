"""Type collections (C1.1, C1.4) and collection-level defaults + hooks.

A collection holds the root types of one type tree. There is a default
collection; `createTypesCollection(config?)` makes more. `lookup(path)`
walks a dotted path (`User.Admin`) through roots and subtypes; an unknown
path returns None — the lookup itself never raises.

A collection also carries the config defaults its types inherit (C4):
strictChain, blockErrors, submitStack, unchain (unchain is async-only, C6 —
the name is accepted and stored here, its semantics land in P4). JS
collection semantics: only known option keys are applied; a value whose
type does not match the option's default falls back to that default.
"""

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, cast, overload

from .errors import OptionsError
from .hooks import make_registry, register_hook

if TYPE_CHECKING:
    from .types import MnemonicaType

# the JS defaultOptions (constants/index.ts): every option is a boolean
DEFAULT_OPTIONS: dict[str, bool] = {
    "strictChain": True,
    "blockErrors": True,
    "submitStack": False,
    # async-only (C6); accepted and stored now, semantics arrive in P4
    "unchain": False,
}


def resolve_options(given: object, base: Mapping[str, bool]) -> dict[str, bool]:
    """Overlay `given` onto `base` with the JS filtering rules (C4).

    Unknown keys are silently dropped; a value that is not a boolean falls
    back to the base value for that key. `name` is a COLLECTION option
    (handled by TypesCollection before this call): it is rejected here so
    a type's define config cannot sneak it in.
    """
    if given is None:
        result = dict(base)
        return result
    if not isinstance(given, Mapping):
        raise OptionsError("config must be a mapping of option names to booleans")
    options = cast(Mapping[str, Any], given)
    if "name" in options:
        raise OptionsError(
            '"name" is a collection option: pass it to createTypesCollection'
            " config, not to a type's define config"
        )
    merged = dict(base)
    for key in DEFAULT_OPTIONS:
        value = options.get(key)
        if isinstance(value, bool):
            merged[key] = value
    result = merged
    return result


# the default collection's name (decided for all ports; the lineage
# export records it as type.collection)
DEFAULT_COLLECTION_NAME = "defaultTypes"

_auto_collection_counter = 0


def _auto_collection_name() -> str:
    """A unique name for an unnamed custom collection, in creation order."""
    global _auto_collection_counter
    _auto_collection_counter += 1
    result = f"collection_{_auto_collection_counter}"
    return result


class TypesCollection:
    """A registry of root types (C1.1) with config defaults and hooks."""

    def __init__(self, config: object = None, *, is_default: bool = False) -> None:
        # insertion-ordered: lookup results and error messages stay stable
        self.mn_roots: dict[str, MnemonicaType] = {}
        self.mn_hooks = make_registry()
        name: str | None = None
        bool_config: object = config
        if isinstance(config, Mapping):
            config_map = cast(Mapping[str, Any], config)
            candidate = config_map.get("name")
            if candidate is not None:
                if not isinstance(candidate, str):
                    raise OptionsError('collection "name" must be a string')
                name = candidate
                # name is consumed here: it must not reach the boolean
                # option filter (which rejects it as a type option)
                rest = {
                    key: value for key, value in config_map.items() if key != "name"
                }
                bool_config = rest
        if is_default:
            resolved_name: str = DEFAULT_COLLECTION_NAME
        elif name is not None:
            resolved_name = name
        else:
            resolved_name = _auto_collection_name()
        self.mn_name = resolved_name
        self.mn_config = resolve_options(bool_config, DEFAULT_OPTIONS)

    @property
    def name(self) -> str:
        """This collection's name (recorded as type.collection in lineage)."""
        result = self.mn_name
        return result

    @property
    def config(self) -> dict[str, bool]:
        """This collection's config defaults, live (C4)."""
        result = self.mn_config
        return result

    def registerHook(self, hook_type: object, callback: object) -> None:
        """Register a hook for all types in this collection (C5.1)."""
        register_hook(self.mn_hooks, hook_type, callback)

    @overload
    def define(
        self,
        name: str,
        handler: Callable[..., Any],
        config: object = None,
        /,
    ) -> "MnemonicaType": ...

    @overload
    def define[T](
        self,
        cls: type[T],
        handler: None = None,
        /,
        *,
        config: "Mapping[str, Any] | None" = None,
    ) -> type[T]: ...

    def define[T](
        self,
        name_or_cls: "str | type[T]",
        handler: object = None,
        config: object = None,
    ) -> "MnemonicaType | type[T]":
        """Declare a root type in this collection (C1.2)."""
        from mnemonica.types import define

        result = cast(
            "MnemonicaType | type[T]",
            define(
                cast(Any, name_or_cls),
                cast(Any, handler),
                config,
                collection=self,
            ),
        )
        return result

    def lookup(self, path: str) -> "MnemonicaType | None":
        """Resolve a dotted path to a type; unknown path → None (C1.4)."""
        head, _, rest = path.partition(".")
        node = self.mn_roots.get(head)
        while node is not None and rest:
            head, _, rest = rest.partition(".")
            node = node.subtypes.get(head)
        result = node
        return result


_default_collection = TypesCollection(is_default=True)


def createTypesCollection(config: object = None) -> TypesCollection:
    """A fresh, empty types collection (C1.1); config = default options (C4)."""
    result = TypesCollection(config)
    return result


def default_collection() -> TypesCollection:
    """The process-wide default collection (C1.1)."""
    result = _default_collection
    return result
