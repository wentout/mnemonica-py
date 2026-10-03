"""mnemonica core for Python.

Subtypes are real subclasses; every instance keeps a live link to the
instance it was made from. Reads fall through the link to the ancestors;
writes stay local.
"""

from . import utils as utils
from .collection import (
    TypesCollection,
    createTypesCollection,
    default_collection,
)
from .errors import (
    AlreadyDeclared,
    ErroredInstance,
    HandlerMustBeAFunction,
    MissingCallbackArgument,
    MissingHookCallback,
    MnemonicaError,
    OptionsError,
    TypenameMustBeAString,
    WrongArgumentsUsed,
    WrongHookType,
    WrongInstanceInvocation,
    WrongModificationPattern,
    WrongTypeDefinition,
)
from .hooks import HOOK_TYPES
from .props import getProps, setProps
from .types import AsyncChain, Mnemonic, MnemonicaType, define

__all__ = [
    "HOOK_TYPES",
    "AlreadyDeclared",
    "AsyncChain",
    "ErroredInstance",
    "HandlerMustBeAFunction",
    "MissingCallbackArgument",
    "MissingHookCallback",
    "Mnemonic",
    "MnemonicaError",
    "MnemonicaType",
    "OptionsError",
    "TypenameMustBeAString",
    "TypesCollection",
    "WrongArgumentsUsed",
    "WrongHookType",
    "WrongInstanceInvocation",
    "WrongModificationPattern",
    "WrongTypeDefinition",
    "createTypesCollection",
    "default_collection",
    "define",
    "getProps",
    "lookup",
    "setProps",
    "utils",
]


def lookup(path: str) -> MnemonicaType | None:
    """Resolve a dotted path in the default collection (C1.4)."""
    result = default_collection().lookup(path)
    return result
