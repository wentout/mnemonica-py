"""Form A fixture: bare classes decorated with @Parent.define.

The types live in the package __init__.py itself.
"""

from mnemonica import Mnemonic, createTypesCollection

collection = createTypesCollection()


@collection.define
class User(Mnemonic):
    def __init__(self, name: str) -> None:
        self.name = name


@User.define
class Admin:
    def __init__(self, role: str) -> None:
        self.role = role


@collection.define
class AsyncUser(Mnemonic):
    async def __ainit__(self, name: str) -> None:
        self.name = name
