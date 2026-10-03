"""Smoke test: the public surface imports and exposes every export."""

import mnemonica


def test_public_surface() -> None:
    names = [
        "AlreadyDeclared",
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
    ]
    for name in names:
        assert hasattr(mnemonica, name), name
    result = mnemonica.__doc__
    assert result is not None
