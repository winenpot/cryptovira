# Interview modules

This rewrite has two goals: a working, professional codebase, and a developer who can defend every
decision in it. These modules are the second goal.

Each module covers the concepts introduced by one roadmap step. The questions are the kind asked in
senior backend interviews; the answers are grounded in **this repository**, so revising them is the
same activity as understanding the code.

| Module                                     | Roadmap step | Topics                                                        |
| ------------------------------------------ | ------------ | ------------------------------------------------------------- |
| [01 — Foundations](01-foundations.md)       | Step 1       | Packaging, config, containers, brokers, health checks, CI, typing |
| 02 — Auth & API design *(pending)*          | Step 2       | Custom user models, JWT vs sessions, permissions, throttling  |
| 03 — Data modelling & the ORM *(pending)*   | Step 3       | Indexes, N+1, transactions, locking, time-series storage      |
| 04 — Concurrency & correctness *(pending)*  | Step 5–6     | Idempotency, retries, race conditions, isolation levels       |

## How to use them

1. Read the question. Answer out loud, from memory, before reading on.
2. Compare with the model answer — the **bold** phrases are the ones an interviewer listens for.
3. Follow the *"In this repo"* pointer and read the actual code. An answer you can attach to a file
   you wrote is worth three you memorised.
4. Attempt the *drill* at the end of each section. They are small, real changes to this codebase.

## Reference banks

Two broader question banks live at the repository root and are not tied to a roadmap step:

- [`Claude-int-Qs.md`](../../Claude-int-Qs.md) — 100 Django/DRF questions with model answers,
  including exchange- and money-specific sections.
- [`GPT-interview-Q.md`](../../GPT-interview-Q.md) — a shorter, question-only bank for self-testing.

Use them for breadth; use these modules for depth on what you have actually built.
