"""Worked, CI-tested end-to-end examples for the llmsim engine.

Each subpackage is a self-contained domain model that consumes only the public
llmsim API (no engine edits) and exposes a module-level, importable factory so
the same code runs on the thread, interpreter, and process backends. The
examples double as the final API dogfooding pass before the 1.0 freeze
(``specs/roadmap.md`` Phase 5).
"""
