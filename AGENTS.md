# AGENTS.md — mnemonica for Python

You are porting mnemonica core to Python. Read, in this order:

1. this file;
2. `plans/PLAN.md` — the design and the phases;
3. `/code/mnemonica/plan/core-ports-contract.md` — WHAT the port must do
   (C1–C9), the quality gates, the carried-over rules;
4. the JS reference, as the plan points to it.

## Rule #1 — pause and ask

Stop and ask in the room (your supervisor relays your reply) when: a tool or
command errors (report the error AND any recovery), you are unsure what the
contract means, you catch yourself writing "probably / should work", a tool
constraint conflicts with the plan, or you are about to create a file the
plan does not name. One question is cheaper than a wrong design.

## Self-honesty

- Verify before you state: "green" means `scripts/check` exited 0 just now —
  paste its summary.
- Never present unverified as verified; "I have not checked" is always fine.
- No promises about future behaviour; only mechanisms (tests, gates).

## Working rules

- **Gates:** `scripts/check` = pytest with 100% line + branch coverage,
  mypy --strict, pyright strict, ruff check, ruff format --check. A phase is
  done only when it exits 0 and the conformance matrix is updated.
- **Return via a variable:** `result = …` then `return result` — never
  `return f(x)`.
- **Comments say why.** Never delete a design comment; fix it if it is wrong.
- **No git.** viktor owns git. Do not run any git command that writes.
- **Experiments** (probes, benchmark output, scratch) →
  `/code/experiments/<YYYY-MM-DD>-<topic>/` with a README. Never `/tmp`.
  Never delete experiments.
- **Edits** with your file tools; no `sed -i` / `perl -pi` rewrites.
- **Examples** use neutral names (User/Admin, Widget/Gadget, Job).
- **No changelog, no publishing**, no PyPI name registration.
- **Shipped files** (package, README, docs) never mention local paths
  (`/code/...`, `plans/`, experiments).
- Every phase ends with a STOP: report what was done, how it was verified,
  the `scripts/check` summary — then wait.
