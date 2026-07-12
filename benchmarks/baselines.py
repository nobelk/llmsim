"""Machine-class baseline storage and regression comparison.

Baselines are keyed by *machine class* -- ``<system>-<machine>`` (e.g.
``Darwin-arm64``, ``Linux-x86_64``) -- because benchmark timings are
hardware-specific and must only be compared like-for-like. A baseline records,
per model, the deterministic KPI (identical on any machine for a given seed)
and a locally-measured mean wall-clock time.

Enforcement policy (Phase 0):

* **KPI** is checked for exact equality whenever a baseline entry exists. It is
  hardware-independent, so this is the substantive correctness gate.
* **Timing** auto-records on first run for a machine class (records, warns, and
  passes) and thereafter fails only on a gross regression beyond
  ``TIMING_TOLERANCE``. The tolerance is deliberately generous: Phase 0 has no
  llmsim implementation to regress against yet, so a tight timing gate would
  only surface shared-runner noise. Later phases tighten it once llmsim models
  exist to compare against these SimPy 3 references.
"""

import json
import platform
from pathlib import Path
from typing import Any

BASELINE_DIR = Path(__file__).parent / "baselines"

# A model may run up to (1 + TIMING_TOLERANCE)x its baseline mean before the
# gate fails. Generous on purpose -- see the module docstring.
TIMING_TOLERANCE = 4.0


def machine_class() -> str:
    """Return the machine-class key for the current runner."""
    return f"{platform.system()}-{platform.machine()}"


def baseline_path(machine_class_key: str | None = None) -> Path:
    """Return the baseline JSON path for a machine class (default: current)."""
    return BASELINE_DIR / f"{machine_class_key or machine_class()}.json"


def load_baseline(machine_class_key: str | None = None) -> dict[str, Any] | None:
    """Load the baseline for a machine class, or ``None`` if none is recorded.

    The ``machine_class`` label stored inside the file is validated against the
    key it is filed under, so a renamed or misfiled baseline fails loudly rather
    than being silently compared against the wrong machine.
    """
    key = machine_class_key or machine_class()
    path = baseline_path(key)
    if not path.exists():
        return None
    baseline: dict[str, Any] = json.loads(path.read_text())
    stored = baseline.get("machine_class")
    if stored is not None and stored != key:
        raise ValueError(
            f"baseline {path.name} records machine_class {stored!r}, expected {key!r}"
        )
    return baseline


def save_baseline(
    baseline: dict[str, Any], machine_class_key: str | None = None
) -> None:
    """Write a baseline for a machine class, creating the directory if needed."""
    path = baseline_path(machine_class_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
