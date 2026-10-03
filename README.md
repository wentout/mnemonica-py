# mnemonica for Python

**Instance lineage: subtypes are real subclasses, and every instance
remembers the instance it was made from.**

mnemonica is an inheritance system where inheritance happens at the
instance level. A subtype is constructed FROM a parent instance —
`user.Admin("root")` — and the new instance keeps a live link to that
specific parent. Reads fall through the link to the ancestors; writes
stay local: ancestors are history. The chain from any instance back to
the root records what it was made from, with which arguments, in which
order — readable at any time with `getProps()`.

```python
from mnemonica import define, getProps

@define
class User:
    name: str
    def __init__(self, name: str) -> None:
        self.name = name

@User.define
class Admin(User):
    role: str
    def __init__(self, role: str) -> None:
        self.role = role

user = User("ada")
admin = user.Admin("root")

admin.name          # "ada" — read through to the parent instance
admin.role          # "root" — own field
isinstance(admin, User)   # True — subtypes are real subclasses

admin.name = "eve"  # lands on admin; user.name stays "ada"
```

## Install

```bash
pip install mnemonica
```

Requires Python ≥ 3.12.

## Defining types

There are three definition forms. **Form B (explicit base) is the
primary, documented form** — write the base class yourself and the
decorator verifies it:

```python
from mnemonica import Mnemonic, define

@define                     # or @collection.define / @User.define
class User(Mnemonic):       # form B: you write the base
    def __init__(self, name: str) -> None:
        self.name = name

@User.define
class Admin(User):
    def __init__(self, role: str) -> None:
        self.role = role
```

- **Form A** — `@User.define` on a bare class (`class Admin:`): the
  decorator builds the real subclass. Works, but zero-argument `super()`
  inside form A methods still refers to the undecorated shell class, so
  classes that use `super()` should be written in form B.
- **Form C** — the function form, like the JS core:
  `Admin = User.define("Admin", handler)`.

Declare the `Mnemonic` base (form B) to make the class-level API
visible to type checkers.

## Constructing: `parent.Sub(...)` and `Sub.of(parent, ...)`

A subtype is always constructed from a parent instance:

```python
user = User("ada")
admin = user.Admin("root")     # the dynamic path
admin = Admin.of(user, "root") # the always-typed path
```

Reading a subtype from an instance returns a constructor bound to that
instance; calling a subtype class directly raises
`WrongInstanceInvocation`.

**Typed construction requires the generated stubs.** Run
`mnemonica-stubgen` over your package to emit `.pyi` files that declare
each subtype as a typed attribute of its parent; without them, checkers
cannot see attributes bound at runtime, and constructor calls are
silently untyped (`Any`) — pyright routes them through the metaclass,
whose `__call__` returns the async awaitable for async types and cannot
be precisely typed.

```bash
python -m mnemonica.stubgen <package-dir>   # or: mnemonica-stubgen
```

## The construction record: `getProps` / `setProps`

Every instance carries a side record — never stored as user-visible
fields:

```python
props = getProps(admin)
props["type"]       # the Admin type
props["parent"]     # the user instance
props["args"]       # ("root",)
props["timestamp"]  # milliseconds since epoch
```

## Configuration (per type, collection defaults)

```python
from mnemonica import createTypesCollection

collection = createTypesCollection({"blockErrors": False})


class Audited(User):
    def __init__(self, actor: str) -> None:
        self.actor = actor


# config is keyword-only on the class forms: call the descriptor directly
Audited = User.define(Audited, config={"submitStack": True})
```

- `strictChain` (default `true`) — only the type's own direct subtypes
  may be constructed from its instances; `false` allows subtypes found
  up the chain and parents of another kind.
- `blockErrors` (default `true`) — a failure inside a constructor
  produces an **errored instance** (an `ErroredInstance` whose record
  carries `originalError`, `args`, … via `getProps`); constructing from
  an errored instance is refused. `false`: failures propagate as-is.
- `submitStack` (default `false`) — record the construction stack.
- `unchain` (async only) — see below.

## Hooks

```python
User.registerHook("postCreation", lambda data: print(data["TypeName"]))
collection.registerHook("preCreation", lambda data: ...)
```

`preCreation` fires before construction (collection hooks first, then
type hooks); a failure there aborts and propagates. `postCreation`
fires after success, `creationError` when an errored instance was
produced (type hooks first, then collection hooks — the JS call order).
Hook data carries the JS key names: `type`, `TypeName`,
`existentInstance`, `inheritedInstance`, `args`, and (post hooks)
`throwModificationError`.

## Async constructors

A type whose handler is `async def __ainit__` (or an `async def`
handler in the function form) makes construction awaitable:

```python
@User.define
class AsyncAdmin(User):
    async def __ainit__(self, role: str) -> None:
        self.role = role

admin = await user.Admin("root")
```

`await` returns the instance. The `unchain` option (default `false`)
lets an async constructor end the chain in a plain value: with
`unchain: true`, a returned non-instance value IS the result. Reading a
subtype from a pending construction queues the next step, so a whole
chain unwraps with a single await:

```python
result = await User("ada").Admin("root").SuperAdmin(3)
```

Hooks and `blockErrors` behave exactly as on the sync path.

## Utilities

```python
from mnemonica import utils

utils.extract(admin)                # flat user fields along the chain
utils.pick(admin, "name", "role")   # specific fields
utils.parent(admin)                 # the parent instance
utils.parent(admin, "User")         # nearest ancestor by type name
utils.parent(admin, "Org.User")     # dotted: contiguous match upwards
utils.clone(admin)                  # same parent, same args
utils.fork(admin)("new-args")       # fork from the same parent
utils.fork(admin).call(other, "x")  # fork onto another parent (DAG)
utils.sibling(admin)("OtherRoot")   # sibling root types of the collection
utils.merge(a, b, *args)            # a's type, chained onto b
utils.parse(admin)                  # {name, props, self, parent}
utils.toJSON(admin)                 # extracted fields as a JSON object
utils.collectConstructors(admin)    # constructor names along the chain
utils.exception(admin, error, *args)  # an error carrying the instance
```

## Lineage export (the cross-language contract)

`utils.deepParse(instance)` is the multi-level `parse` — one-level
snapshots from the instance to the root. `utils.lineage(instances, *,
args=False, props=None)` exports the lineage graph in the shared lethe
format (version `"1"`, `heads`, `nodes` keyed by instance id): every
reachable instance deduplicated at any depth, own fields per level,
parent links, and `{ "$ref": id }` for fields holding other instances.
Values JSON cannot carry (functions, NaN, infinities, complex numbers,
cycles, non-string map keys, …) export as `{ "$mnemonica": "unsupported",
"kind": … }` placeholders — never an error. Instance ids are
implementation-specific (a per-process random prefix plus a counter,
held lazily and weakly — nothing is retained).

```python
graph = utils.lineage([super_admin, other_admin])
graph["heads"]   # ids of the exported instances, in argument order
graph["nodes"]   # every reachable instance, deduplicated, keyed by id
```

`type.collection` records the collection's name: the default collection
is `"defaultTypes"`, custom collections can set one with
`createTypesCollection({"name": "fixture"})`, and unnamed custom
collections get automatic unique `collection_1`, `collection_2`, …
names. A `name` in a type's define config is rejected with
`OptionsError`.

## Errors

Every error is a distinct class under `MnemonicaError`, named after the
JS core codes: `AlreadyDeclared`, `WrongInstanceInvocation`,
`WrongModificationPattern`, `WrongArgumentsUsed`, `WrongHookType`,
`MissingHookCallback`, `MissingCallbackArgument`, `OptionsError`,
`TypenameMustBeAString`, `HandlerMustBeAFunction`,
`WrongTypeDefinition`, `ErroredInstance`.

## Known deviations from the JS core

- **Lookup order:** own fields → subtype methods → parent methods →
  parent instance fields (JS checks parent instance fields before
  parent methods). Differs only when a field and a method share a name.
- **`toJSON` always produces valid JSON:** the JS core returns `"{"`
  for a fieldless instance and does not escape keys — both are bugs,
  reported upstream; not ported.
- **`None` covers both no-parent cases:** a root's parent is `None`
  (the JS `undefined`/`null` distinction does not exist in Python).
- **Async result rule:** an `__ainit__` returning `None` means "the
  instance" (Python's constructor convention); only an explicit
  non-instance result drops the chain with `unchain: true`.

## Development

```bash
scripts/check    # the one quality gate: tests (100% line+branch
                 # coverage), mypy --strict, pyright strict, ruff
```
