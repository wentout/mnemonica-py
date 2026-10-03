"""C8 — every error is a distinct, checkable kind.

The hook- and options-related kinds exist as kinds now; their raise paths
arrive with P2 (hooks, config) and are tested there. Nothing here fakes a
path to reach them (contract, C8 note).
"""

from mnemonica import (
    AlreadyDeclared,
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


def test_all_kinds_share_the_base() -> None:
    kinds = [
        TypenameMustBeAString,
        HandlerMustBeAFunction,
        WrongTypeDefinition,
        WrongInstanceInvocation,
        WrongModificationPattern,
        AlreadyDeclared,
        WrongArgumentsUsed,
        WrongHookType,
        MissingHookCallback,
        MissingCallbackArgument,
        OptionsError,
    ]
    for kind in kinds:
        assert issubclass(kind, MnemonicaError)
        assert issubclass(kind, Exception)


def test_kinds_are_distinct() -> None:
    first = AlreadyDeclared("a")
    second = WrongInstanceInvocation("a")
    assert type(first) is AlreadyDeclared
    assert not isinstance(first, WrongInstanceInvocation)
    assert isinstance(second, WrongInstanceInvocation)


def test_kinds_are_catchable_by_name() -> None:
    try:
        raise AlreadyDeclared("dup")
    except MnemonicaError as exc:
        assert isinstance(exc, AlreadyDeclared)
    else:  # pragma: no cover - the raise above always fires
        raise AssertionError("unreachable")
