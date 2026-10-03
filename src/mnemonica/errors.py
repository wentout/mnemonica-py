"""Error kinds (C8).

Every error is a distinct, checkable class named after the JS core error
codes, so the conformance matrix maps 1:1. All kinds derive from
MnemonicaError; catching it catches every mnemonica error.
"""


class MnemonicaError(Exception):
    """Base of every mnemonica error kind."""


class TypenameMustBeAString(MnemonicaError):
    """define() received a type name that is not a string."""


class HandlerMustBeAFunction(MnemonicaError):
    """define() received a handler that is not callable."""


class WrongTypeDefinition(MnemonicaError):
    """A type definition violates the shape of the thing it defines."""


class WrongInstanceInvocation(MnemonicaError):
    """A type was constructed without the parent instance it requires."""


class WrongModificationPattern(MnemonicaError):
    """A construction violated the modification rules (chain/flow)."""


class AlreadyDeclared(MnemonicaError):
    """A type with this path is already declared in the collection."""


class WrongArgumentsUsed(MnemonicaError):
    """Construction arguments are wrong for the type being made."""


class WrongHookType(MnemonicaError):
    """A hook was registered under an unknown hook type."""


class MissingHookCallback(MnemonicaError):
    """A hook registration came without a callback."""


class MissingCallbackArgument(MnemonicaError):
    """define() was asked to build a type without its handler."""


class OptionsError(MnemonicaError):
    """A type configuration option is invalid."""


class ErroredInstance(MnemonicaError):
    """The errored instance of blockErrors (C4.2): what a failed construction
    raises when the failure is blocked instead of propagated. It is an
    ordinary exception, so `isinstance(errored, BaseException)` is the
    errored-parent check, and the failed construction data (originalError,
    args, instance, exceptionReason, reasons, surplus) lives in its context
    record, readable via getProps — mirroring the JS errored instance whose
    data lives in the WeakMap, never on the object itself."""
