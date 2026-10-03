"""Typed usage of the form_b stubs (must pass mypy --strict / pyright strict)."""

import asyncio

from app import Admin, SuperAdmin, User


def sync_part() -> None:
    user = User("ada")
    admin: Admin = user.Admin("root")
    typed_admin: Admin = Admin.of(user, "root")
    super_admin: SuperAdmin = admin.SuperAdmin(5)
    print(
        admin.level,
        typed_admin.role,
        super_admin.clearance,
        user.greet(),
        user.name,
    )


async def async_part() -> None:
    user = User("ada")
    async_admin = await user.AsyncAdmin("root")
    print(async_admin.role)


asyncio.run(async_part())
sync_part()
