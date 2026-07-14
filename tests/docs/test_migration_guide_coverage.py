"""API-coverage audit: the migration guide covers the SimPy 3 surface (4.3).

The checked-in inventory is the union of the required concept list from
``specs/phase-4-migration-guide/requirements.md`` and the SimPy 3 public-API
names exercised by the ported behavioral suite (``tests/behavioral/``, Phase
1.10). Every name must appear in the guide's concept-mapping table or its
"What has no equivalent" section, so an API that reaches the behavioral suite
forces a guide update in the same PR.
"""

import ast
import re

from tests.docs.guide_support import GUIDE_PATH, REPO_ROOT

BEHAVIORAL_DIR = REPO_ROOT / "tests" / "behavioral"

CONCEPT_HEADING = "## Concept mapping"
NO_EQUIVALENT_HEADING = "## What has no equivalent"

# The provenance convention of the ported behavioral suite: each module's
# docstring names the SimPy 3 test file it was ported from.
PROVENANCE_NOTE = "Ported from SimPy 3"

# (a) The required inventory from requirements.md, including every
# "no equivalent" name.
REQUIRED_INVENTORY: frozenset[str] = frozenset(
    {
        "simpy.Environment",
        "env.process",
        "env.timeout",
        "env.now",
        "env.run",
        "env.event",
        "simpy.AllOf",
        "simpy.AnyOf",
        "ExceptionGroup",
        "simpy.Interrupt",
        "simpy.Resource",
        "simpy.PriorityResource",
        "simpy.PreemptiveResource",
        "simpy.Container",
        "simpy.Store",
        "simpy.PriorityStore",
        "simpy.FilterStore",
        "random",
        "sim.rng",
        "BoundClass",
        "StopProcess",
        "env.exit",
        "RealtimeEnvironment",
        "defused",
    }
)

# (b) The SimPy 3 public-API names exercised by each ported behavioral
# module, keyed by module filename. test_exercised_names_track_behavioral_suite
# keeps this mapping in sync with the suite's modules, each of which must
# carry a provenance note naming its SimPy 3 original.
BEHAVIORAL_EXERCISED: dict[str, frozenset[str]] = {
    "test_condition.py": frozenset(
        {"simpy.Condition", "simpy.AllOf", "simpy.AnyOf"}
    ),
    "test_environment.py": frozenset({"simpy.Environment", "env.now", "env.run"}),
    "test_event.py": frozenset({"simpy.Event", "env.event"}),
    "test_exceptions.py": frozenset({"defused"}),
    "test_interrupts.py": frozenset({"simpy.Interrupt"}),
    "test_process.py": frozenset({"simpy.Process", "env.process"}),
    "test_resources.py": frozenset(
        {
            "simpy.Resource",
            "simpy.PriorityResource",
            "simpy.PreemptiveResource",
            "simpy.Container",
            "simpy.Store",
            "simpy.PriorityStore",
            "simpy.FilterStore",
        }
    ),
    "test_timeout.py": frozenset({"simpy.Timeout", "env.timeout"}),
}


def _section_lines(guide_lines: list[str], heading: str) -> list[str]:
    """Return the lines of a ``##`` section, up to the next ``##`` heading."""
    start = guide_lines.index(heading)
    end = next(
        (
            number
            for number in range(start + 1, len(guide_lines))
            if guide_lines[number].startswith("## ")
        ),
        len(guide_lines),
    )
    return guide_lines[start + 1 : end]


def _covers(name: str, text: str) -> bool:
    """Whether *name* appears in *text* as a whole token (dots allowed)."""
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text) is not None


def test_exercised_names_track_behavioral_suite() -> None:
    """The (b) mapping stays in sync with the ported behavioral suite."""
    behavioral_modules = {path.name for path in BEHAVIORAL_DIR.glob("test_*.py")}
    assert behavioral_modules == set(BEHAVIORAL_EXERCISED), (
        "behavioral suite modules and BEHAVIORAL_EXERCISED disagree; update "
        "the mapping (and the guide) for: "
        f"{sorted(behavioral_modules ^ set(BEHAVIORAL_EXERCISED))}"
    )


def test_behavioral_modules_carry_provenance_notes() -> None:
    """Every behavioral module names the SimPy 3 original it ports."""
    missing = [
        path.name
        for path in BEHAVIORAL_DIR.glob("test_*.py")
        if PROVENANCE_NOTE
        not in (ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or "")
    ]
    assert not missing, (
        f"behavioral modules without a {PROVENANCE_NOTE!r} provenance "
        f"docstring: {sorted(missing)}"
    )


def test_concept_table_covers_inventory() -> None:
    """Every inventory name appears in the table or no-equivalent section."""
    guide_lines = GUIDE_PATH.read_text(encoding="utf-8").splitlines()
    table_rows = [
        line
        for line in _section_lines(guide_lines, CONCEPT_HEADING)
        if line.startswith("|")
    ]
    no_equivalent = _section_lines(guide_lines, NO_EQUIVALENT_HEADING)
    covered_text = "\n".join(table_rows + no_equivalent)
    inventory = REQUIRED_INVENTORY.union(*BEHAVIORAL_EXERCISED.values())
    missing = sorted(name for name in inventory if not _covers(name, covered_text))
    assert not missing, (
        "migration guide is missing these concepts from its mapping table / "
        f"no-equivalent section: {', '.join(missing)}"
    )
