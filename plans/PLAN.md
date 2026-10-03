# mnemonica for Python — the port plan

WHAT to build is in the shared contract:
`/code/mnemonica/plan/core-ports-contract.md` (C1–C9, the gates, the phases).
This file is HOW, in Python. Author: claude (viktor asked for claude's own
design; he does not write Python). Questions go to the room, not guesses.

## Design — the central decision: subtypes ARE subclasses

In JavaScript the parent instance becomes the child's prototype. Python has
no per-object prototype, but it has two things that together give the same
result, and give it TYPED:

1. **Every mnemonica type is a real Python class.** A subtype is a real
   SUBCLASS of its parent type. So `isinstance(admin, User)` is native,
   methods of `User` are callable on an `Admin`, and mypy/pyright understand
   it with no code generation.
2. **Every instance links to its parent INSTANCE** (a slot, `_mn_parent`).
   `__getattr__` — which Python calls only when normal lookup MISSES — walks
   that link: own `__dict__` → class attributes (methods) → parent instance →
   its parent … This is C2.3 read-through. Writes go into the instance's own
   `__dict__` (C2.4 write-local for free).

```python
from mnemonica import define

@define
class User:
    name: str
    def __init__(self, name: str) -> None:
        self.name = name

@User.define
class Admin:                      # becomes a subclass of User
    role: str
    def __init__(self, role: str) -> None:
        self.role = role

user = User("ada")
admin = user.Admin("root")        # constructed FROM user (C2.2)
admin.name                        # "ada" — read through to the parent (C2.3)
isinstance(admin, User)           # True — nominal (C2.5)
admin.name = "eve"                # lands on admin; user.name stays "ada" (C2.4)
```

How the pieces work:
- `define` / `Type.define` is a decorator (also callable as
  `define("User", handler)` with a plain function, like JS). It builds the
  class through the metaclass `MnemonicaType`, registers the path in the
  collection, and fails with `AlreadyDeclared` on a duplicate path (C1.3).
- **`user.Admin` binding:** the metaclass implements `__get__`, so a subtype
  class stored on its parent class behaves like a method: reading it from an
  instance returns a constructor bound to that instance.
- **The user's `__init__` is the handler.** The metaclass's `__call__`
  creates the object WITHOUT running the parent class's `__init__` (the
  parent is already constructed — it is the parent instance), writes the
  context record (C3), runs hooks (C5), then runs ONLY the subtype's own
  handler. The handler is stored on the type and read at every construction
  (C1.5), so it can be swapped at runtime.
- **Typed construction without codegen:** besides `user.Admin(...)` (dynamic,
  typed as `Any` by checkers until P5), offer `Admin.of(user, "root")` — a
  classmethod with full static types (`parent: User`, returns `Admin`).
- **Context record (C3):** a `weakref.WeakKeyDictionary` keyed by instance,
  read via `get_props(instance)`; nothing user-visible on the instance except
  the one parent slot.
- **Known deviation, to record in the matrix:** lookup order. JS: own →
  Admin methods → parent instance fields → User methods. Here: own → Admin
  methods → User methods → parent instance fields. It differs only when an
  instance FIELD and a METHOD share a name. Write a test that pins the Python
  order and say it in the docs.
- **Things to PROBE before building on them** (P1, experiments folder):
  - metaclass `__get__` for binding a class attribute to an instance —
    works with `@define` decorated classes, `__slots__`, dataclasses?
  - `__getattr__` + `__init_subclass__` + `__set_name__` interplay;
  - does pyright/mypy accept the subclass that the decorator creates (the
    decorator must be typed so `Admin` is seen as a `User` subclass — likely
    via a `Protocol`/overload; if impossible, users write
    `class Admin(User)` explicitly and the decorator VERIFIES it — decide
    from the probe, report it);
  - cost of a `__getattr__` hop at depth 1/10/100.

## Async (C6, phase P4)

Python cannot have `async def __init__`. Design: a type may define
`async def __ainit__(self, ...)`; construction then returns an awaitable,
`admin = await user.Admin("root")`. `unchain` as in C6.2. A single await for
a chain (C6.3) via an awaitable proxy that queues subtype constructions —
probe first; if it cannot be made clean, mark `adapted`/`N/A` with reason.

## Static typing aid (P5)

`user.Admin(...)` is invisible to checkers. P5 builds `mnemonica-stubgen`:
reads the package with `ast` (stdlib), writes `.pyi` stubs that declare each
subtype as a typed attribute of its parent class. The Python analogue of
tactica. Until then `Admin.of(user, ...)` is the typed path.

## Later (separate plans, not now)

- **pydantic integration** — adoption in Python goes through pydantic models
  (see the cross-language report): models that remember what they were made
  from.
- **OpenTelemetry** — instances carry the span context of their creation.

## Toolchain

- Python ≥ 3.12 (3.12.12 installed). Project managed with **uv**
  (`uv init --lib`, `uv add --dev …`); `pyproject.toml` only, `src/` layout:
  `src/mnemonica/`.
- Tests: **pytest**, **pytest-cov** with branch coverage,
  `--cov-fail-under=100`; property tests for the laws: **hypothesis**.
- Types: **mypy --strict** AND **pyright strict** — both, zero errors. `Any`
  only at the documented dynamic boundary (`__getattr__`), never elsewhere.
- Lint + format: **ruff** (`ruff check`, `ruff format --check`). PEP 8
  layout (spaces) — idiomatic Python wins over the JS tab rule.
- `scripts/check` — runs all of the above; exit 0 = green.
- Benchmarks: `pytest-benchmark` or plain `timeit`; raw output to
  `/code/experiments/<date>-py-bench/`, summary in `docs/performance.md`.
- Package name `mnemonica` (import name). Publishing to PyPI is viktor's
  decision — do not publish, do not register names.

## Layout

```
core-python/
  AGENTS.md                 rules for agents
  pyproject.toml
  scripts/check
  src/mnemonica/            __init__.py, types.py, collection.py, props.py,
                            hooks.py, errors.py, utils/…, py.typed
  tests/                    one module per contract area; laws in test_laws.py
  docs/conformance.md       the matrix (contract §3)
  docs/performance.md
  README.md                 for humans (P6)
  plans/PLAN.md             this file
```

## Phase checklist

- **P0** skeleton, uv project, `scripts/check` green on an empty package with
  one smoke test, `docs/conformance.md` with every contract row `open`.
  Probes listed under Design → report → STOP.
- **P1** C1–C3, C8 + the deviation test. STOP.
- **P2** C4, C5. STOP.
- **P3** C7 (each util with its JS doc example ported as a test). STOP.
- **P4** C6. STOP.
- **P5** stub generator + its own tests at 100%. STOP.
- **P6** laws (hypothesis), benchmarks, README. STOP.
