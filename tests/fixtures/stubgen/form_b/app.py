"""Form B fixture: explicit bases, nested subtypes, async, plain classes."""

from dataclasses import dataclass

from mnemonica import Mnemonic, createTypesCollection

collection = createTypesCollection()


@dataclass
class Config:
    debug: bool


@settings()
class Tuned:
    pass


class MyError(Exception):
    def __init__(self, code: int) -> None:
        self.code = code


class PlainBox:
    def __init__(self, size: int) -> None:
        self.size = size


def boxed_handler(self, label: str) -> None:
    self.label = label


Boxed = PlainBox.define("Boxed", boxed_handler)


@collection.define
class User(Mnemonic):
    def __init__(self, name: str) -> None:
        self.name = name

    def greet(self) -> str:
        return f"hi {self.name}"


@User.define
class Admin(User):
    def __init__(self, role: str, level: int = 1) -> None:
        self.role: str = role
        self.level = level

    @staticmethod
    def make() -> "Admin":
        raise NotImplementedError


@Admin.define
class SuperAdmin(Admin):
    def __init__(self, clearance: int) -> None:
        self.clearance = clearance


@User.define
class AsyncAdmin(User):
    async def __ainit__(self, role: str) -> None:
        self.role = role


@User.define
class Guest(User):
    pass


def helper(x: int) -> str:
    return str(x)
