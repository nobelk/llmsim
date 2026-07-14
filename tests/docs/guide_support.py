"""Shared paths for the migration-guide sync tests.

Import as ``from tests.docs import guide_support`` (the repo root is on
``pythonpath`` per ``pyproject.toml``), mirroring ``tests.parallel_support``.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GUIDE_PATH = REPO_ROOT / "docs" / "migration-from-simpy.md"
