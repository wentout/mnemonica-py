# Performance — mnemonica for Python

Numbers only; no "fast" claims. Raw output (all runs) lives in the
experiments folder; this file is the summary.

## Environment

- Machine: Linux went-laptop, x86_64 (Manjaro, kernel 7.2.3-2-MANJARO)
- CPU: AMD Ryzen 5 7530U with Radeon Graphics
- Python: 3.12.12 (CPython)
- Method: `timeit.repeat`, min of 7 repetitions ÷ iterations (sync);
  best of 7 loops of 200 awaited constructions (async). Units: seconds
  per operation. Raw data: `results.json` (recorded 2026-10-02).

## Construction (seconds per operation)

| Operation | depth 1 | depth 10 | depth 100 |
|---|---|---|---|
| mnemonica root construction | 6.1e-06 | 7.4e-06 | 7.7e-06 |
| mnemonica subtype from an instance | 1.36e-05 | 1.72e-05 | 1.68e-05 |
| plain object construction (baseline) | 1.8e-07 | 2.1e-07 | 1.9e-07 |
| async subtype, awaited | 1.39e-05 | 1.78e-05 | 1.80e-05 |
| sync subtype, for comparison | 1.36e-05 | 1.41e-05 | 1.63e-05 |

## Read-through along the chain (seconds per operation)

Reading a root field from the deepest instance, vs the same field on a
plain object:

| Read | depth 1 | depth 10 | depth 100 |
|---|---|---|---|
| chain read-through (root field from leaf) | 4.3e-07 | 1.6e-06 | 9.9e-05 |
| plain object field (baseline) | 2.8e-08 | 3.0e-08 | 2.6e-08 |

Read-through walks the parent-instance links one `__dict__` at a time,
so its cost grows with chain depth; the plain-object baseline is a
single attribute read and has no depth dimension.
