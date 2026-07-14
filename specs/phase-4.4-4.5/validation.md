# Validation — Phase 4.4 (docs site) + 4.5 (1.0 API freeze audit)

## Success criteria

- `uv run mkdocs build --strict` passes with the full nav (all pages
  reachable, no broken internal links) and is a **required** PR gate.
- The GitHub Pages deploy workflow runs green end-to-end on `main` and the
  published site is reachable, with reference pages and chart artifacts
  rendering correctly.
- The 4.5 API audit document is committed and reviewed, with **every**
  public symbol covered and each finding either fixed or filed as a
  follow-up issue — no silent gaps.

## Checklist

- [ ] All `docs/*.md` pages present in `mkdocs.yml` nav;
      `mkdocs build --strict` clean.
- [ ] Docs CI job listed among required PR checks.
- [ ] API reference generated for every symbol re-exported in
      `llmsim/__init__.py` plus public `rt` / `trace` / parallel surfaces;
      no mkdocstrings "missing docstring" warnings on public symbols.
- [ ] User guide pages exist for: getting started, core concepts,
      resources, replications, PDES, offload, real-time, tracing.
- [ ] `parallelism-decision-tree.md` is the parallel section's landing
      page in the nav.
- [ ] Scaling-curve chart artifacts committed; each page states the
      measurement setup and slowdown regimes (matches recorded benchmark
      data — no unmeasured numbers).
- [ ] Deploy workflow green on `main`; published site spot-checked
      (nav, reference, charts, decision tree).
- [ ] `Documentation` URL in `pyproject.toml` and README point at the
      published site.
- [ ] `api-audit.md` covers every public symbol × (annotated, documented,
      named consistently, in reference); `__all__` consistency verified by
      script/test.
- [ ] Deprecation policy page merged.
- [ ] Existing gates stay green: ruff (incl. format --check), mypy
      --strict, pyright, pytest, benchmarks.
- [ ] `specs/roadmap.md` updated (4.4 ticked; 4.5 annotated
      audit-complete, tag/publish pending Phase 5).

## Done when

The docs deploy workflow is green on `main` with `mkdocs build --strict`
in the required-checks set, and the reviewed `api-audit.md` is merged with
zero unresolved (unfixed and unfiled) findings.
