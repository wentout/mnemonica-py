"""Form C fixture: function-form definitions, aliases, exotic signatures."""

import mnemonica.props  # noqa: F401

from mnemonica import createTypesCollection, define  # noqa: F401

collection = createTypesCollection()

handler_ref = None


def user_handler(self, name: str) -> None:
    self.name = name


User = collection.define("User", user_handler)


def admin_handler(self, role: str, active: bool = True) -> None:
    self.role = role


Admin = User.define("Admin", admin_handler)


async def async_admin_handler(self, role: str) -> None:
    self.role = role


AsyncAdmin = User.define("AsyncAdmin", async_admin_handler)


def manager_handler(self, team: str) -> None:
    self.team = team


ManagerT = User.define("Manager", manager_handler)


def varied_handler(self, *args: int, key: str = "k", **kw: str) -> None:
    self.count = len(args)


Varied = User.define("Varied", varied_handler)


def kwonly_handler(self, *, flag: bool) -> None:
    self.flag = flag


KwOnly = User.define("KwOnly", kwonly_handler)


def plain_handler(self, thing) -> None:  # noqa: ANN001
    self.thing = thing


Plain = User.define("Plain", plain_handler)


def multi_handler(self) -> None:
    self.first = self.second = 1
    plain = self.mixed = 2  # noqa: F841


Multi = User.define("Multi", multi_handler)


def free_handler(self, tag: str) -> None:
    self.tag = tag


Free = define("Free", free_handler)

Weird = User.define(some_name)  # noqa: F821

Num = User.define(42, free_handler)

a = b = 1

SuperAdmin = Admin.define("SuperAdmin", lambda self, level: None)

Empty = User.define("Empty")

Orphan = User.define("Orphan", handler_ref)

widget_count = len([1, 2])

ns_value = None


async def module_util(x: int) -> str:
    return str(x)
