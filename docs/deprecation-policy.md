# Deprecation policy

This page states what a version number promises and how the public API evolves
once llmsim reaches **1.0**. It is the contract the 1.x series is held to.

## Semantic versioning

llmsim follows [Semantic Versioning 2.0.0](https://semver.org/). For a release
`MAJOR.MINOR.PATCH`:

- **PATCH** (`1.0.x`) — bug fixes only. No public API changes, no new public
  symbols, no behavior changes beyond fixing a documented or clearly unintended
  defect.
- **MINOR** (`1.x.0`) — backward-compatible additions: new public symbols, new
  optional parameters, new capabilities. Existing code keeps working unchanged.
- **MAJOR** (`2.0.0`) — the only release allowed to remove or change existing
  public API in a breaking way, and only after the deprecation process below.

Determinism is part of the contract: within a MAJOR series, the same
`(master seed, config, replication)` continues to produce the **same results**.
A change that alters deterministic output for an unchanged model is treated as
breaking and cannot ship in a MINOR or PATCH release. (An explicit,
documented correctness fix to the RNG or ordering is the narrow exception, and
is called out in the changelog when it happens.)

## What "public API" means

The public API is exactly the set of symbols documented in the
[API reference](reference/core.md) — the names re-exported from the top-level
`llmsim` package (its `__all__`) plus the public `llmsim.rt`,
`llmsim.trace`, and `llmsim.parallel` surfaces.

A single leading underscore (`_ok`, `_value`, `_sim`, …) marks a name as
**internal to the package**, not part of the public API, even when it is
imported across modules. Internal names carry no compatibility promise and may
change in any release.

## Deprecation process

Removing or renaming a public symbol follows a fixed path:

1. **Announce** — the symbol is documented as deprecated (in its docstring, the
   API reference, and the changelog) and, where practical, emits a
   `DeprecationWarning` at runtime pointing at the replacement.
2. **Overlap window** — the deprecated symbol and its replacement coexist for a
   **minimum of one full MINOR release** (at least the next `1.x.0`) before
   removal, so downstream code has a released version in which both work.
3. **Remove** — the symbol is removed only in a subsequent **MAJOR** release,
   never in a MINOR or PATCH.

Names re-exported for a phase that has not yet shipped are not part of the
public API until the phase lands and the symbol appears in `__all__`.

## Reporting friction

The 1.0 freeze is preceded by a public-API audit (tracked in the repository
under `specs/phase-4.4-4.5/api-audit.md`) and the Phase 5 example gallery,
which dogfood the API. Naming or ergonomics
findings are filed as issues and resolved **before** the freeze — renames and
deprecations execute in their own follow-up changes, never silently.
