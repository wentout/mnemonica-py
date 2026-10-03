"""Typed usage of the form_a stubs (must pass mypy --strict / pyright strict)."""

import asyncio

from form_a import Admin, AsyncUser, User


def sync_part() -> None:
    user = User("ada")
    admin: Admin = user.Admin("root")
    typed_admin: Admin = Admin.of(user, "root")
    print(admin.role, typed_admin.role, user.name)


async def async_part() -> None:
    async_user = await AsyncUser("grace")
    print(async_user.name)


asyncio.run(async_part())
sync_part()
