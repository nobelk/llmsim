"""Every public symbol appears in the mkdocstrings API reference (Phase 4.5).

The 1.0 API-freeze audit requires no silent gaps between the public surface and
the generated reference. This test diffs the public surface -- ``llmsim.__all__``
plus the ``llmsim.rt`` / ``llmsim.trace`` / ``llmsim.parallel.pdes`` submodule
``__all__``s the audit tracks -- against the ``::: identifier`` directives under
``docs/reference/``, in both directions:

* every public symbol has a reference directive, and
* every reference directive resolves to a real object (no dead pages after a
  rename).

``mkdocs build --strict`` separately guarantees each documented symbol carries a
docstring; ``tests/test_import.py`` pins ``__all__`` to the exact contract. This
test closes the loop to the published reference.
"""

import functools
import importlib
import re
from pathlib import Path
from typing import Any

import llmsim
from llmsim import rt, trace
from llmsim.parallel import pdes

REFERENCE_DIR = Path(__file__).resolve().parents[2] / "docs" / "reference"

# Public submodules whose members the audit covers beyond the top-level
# re-exports (the spec names the ``rt`` / ``trace`` / ``parallel`` surfaces).
# Each declares its own ``__all__``, so the expected symbols are derived rather
# than transcribed -- adding a public name to any of these modules automatically
# requires a matching reference directive.
SUBMODULE_SURFACES = (rt, trace, pdes)

_DIRECTIVE = re.compile(r"^:::\s+(\S+)\s*$", re.MULTILINE)


@functools.cache
def _documented_identifiers() -> frozenset[str]:
    """Collect every ``::: identifier`` directive under docs/reference/."""
    identifiers: set[str] = set()
    for page in REFERENCE_DIR.glob("*.md"):
        identifiers.update(_DIRECTIVE.findall(page.read_text(encoding="utf-8")))
    return frozenset(identifiers)


def _resolve(identifier: str) -> Any:
    """Resolve a dotted identifier to its object, or raise on a dead reference."""
    try:
        return importlib.import_module(identifier)  # a bare module, e.g. llmsim.rt
    except ImportError:
        module_path, _, attr = identifier.rpartition(".")
        return getattr(importlib.import_module(module_path), attr)


def _identifier_for(name: str) -> str:
    """Map a top-level ``__all__`` name to its fully qualified identifier."""
    obj = getattr(llmsim, name)
    module = getattr(obj, "__module__", None)
    qualname = getattr(obj, "__qualname__", None)
    if module is not None and qualname is not None:
        return f"{module}.{qualname}"
    # A re-exported submodule (e.g. ``rt``) has no __qualname__.
    return getattr(obj, "__name__", f"llmsim.{name}")


def test_every_public_symbol_has_a_reference_directive() -> None:
    """Each top-level re-export is documented in the API reference."""
    documented = _documented_identifiers()
    missing = []
    for name in llmsim.__all__:
        obj = getattr(llmsim, name)
        if isinstance(obj, type(importlib)):  # a re-exported module, e.g. rt
            if not any(d.startswith(f"{obj.__name__}.") for d in documented):
                missing.append(f"{name} (module {obj.__name__})")
            continue
        identifier = _identifier_for(name)
        if identifier not in documented:
            missing.append(f"{name} -> {identifier}")
    assert not missing, f"public symbols absent from the reference: {missing}"


def test_public_submodule_surfaces_are_documented() -> None:
    """Every member of a public submodule's ``__all__`` appears in the reference.

    Matched by object identity rather than by path string, so a directive may
    document a symbol under either its re-export path or its canonical defining
    path (e.g. ``pdes`` re-exports ``ShardedSim`` from ``pdes.shard``, and
    ``RunMode`` is a ``typing.Literal`` alias with no ``llmsim`` module of its
    own).
    """
    resolved = {
        identifier: _resolve(identifier) for identifier in _documented_identifiers()
    }
    missing = []
    for module in SUBMODULE_SURFACES:
        for name in module.__all__:
            target = getattr(module, name)
            if not any(obj is target for obj in resolved.values()):
                missing.append(f"{module.__name__}.{name}")
    assert not missing, f"public submodule members absent from reference: {missing}"


def test_reference_directives_resolve() -> None:
    """No reference page points at a symbol that no longer exists."""
    for identifier in sorted(_documented_identifiers()):
        assert identifier.startswith("llmsim."), identifier
        obj = _resolve(identifier)
        assert obj is not None, f"reference directive does not resolve: {identifier}"
