"""Typed usage of the form_c stubs (must pass mypy --strict / pyright strict)."""

import asyncio

from app import Admin, ManagerT, SuperAdmin, User


def sync_part() -> None:
    user = User("ada")
    admin: Admin = user.Admin("root")
    typed_admin: Admin = Admin.of(user, "root")
    super_admin: SuperAdmin = admin.SuperAdmin(3)
    manager: ManagerT = user.Manager("team")
    print(admin.role, typed_admin.role, super_admin, manager.team)


async def async_part() -> None:
    user = User("ada")
    async_admin = await user.AsyncAdmin("root")
    print(async_admin.role)


asyncio.run(async_part())
sync_part()
