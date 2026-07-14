"""Snippet-sync: migration-guide excerpts match their source regions (4.3).

Every Python fence in ``docs/migration-from-simpy.md`` must be immediately
preceded by a ``<!-- snippet: path#region -->`` marker and be byte-identical
(after dedent) to the region delimited in the named source file by
``# --8<-- [start:region]`` / ``# --8<-- [end:region]`` comments — the
mkdocs-material "snippets" syntax, so step 4.4 can switch to native includes
without touching the markers.
"""

import functools
import re
import textwrap
from pathlib import Path
from typing import NamedTuple

import pytest

from tests.docs.guide_support import GUIDE_PATH, REPO_ROOT

SNIPPET_MARKER = re.compile(
    r"^<!--\s*snippet:\s*(?P<path>[\w./-]+)#(?P<region>[\w-]+)\s*-->\s*$"
)
FENCE_OPEN = re.compile(r"^```\s*py(thon)?\b")
FENCE_CLOSE = "```"


class Snippet(NamedTuple):
    """A marked Python fence in the guide and the source region it mirrors."""

    line_number: int
    source_path: str
    region: str
    body: str


def _parse_guide(guide_text: str) -> tuple[list[Snippet], list[int]]:
    """Return the guide's marked snippets and unmarked-Python-fence lines."""
    snippets: list[Snippet] = []
    unmarked_fence_lines: list[int] = []
    lines = guide_text.splitlines()
    index = 0
    while index < len(lines):
        if FENCE_OPEN.match(lines[index]):
            fence_line = index
            index += 1
            body_lines: list[str] = []
            while index < len(lines) and lines[index] != FENCE_CLOSE:
                body_lines.append(lines[index])
                index += 1
            assert index < len(lines), (
                f"unterminated Python fence at guide line {fence_line + 1}"
            )
            marker = SNIPPET_MARKER.match(lines[fence_line - 1]) if fence_line else None
            if marker is None:
                unmarked_fence_lines.append(fence_line + 1)
            else:
                snippets.append(
                    Snippet(
                        line_number=fence_line + 1,
                        source_path=marker["path"],
                        region=marker["region"],
                        body="\n".join(body_lines),
                    )
                )
        index += 1
    return snippets, unmarked_fence_lines


@functools.cache
def _source_lines(source_path: Path) -> tuple[str, ...]:
    """Read a snippet source file once for all excerpts drawn from it."""
    return tuple(source_path.read_text(encoding="utf-8").splitlines())


def _extract_region(source_path: Path, region: str) -> str:
    """Return the dedented text between a region's start/end markers.

    Blank edge lines are ignored so the code formatter may pad around the
    marker comments without changing the excerpt.
    """
    source_lines = _source_lines(source_path)

    def unique_marker_line(marker: str) -> int:
        matches = [
            number for number, line in enumerate(source_lines) if line.strip() == marker
        ]
        assert len(matches) == 1, (
            f"expected exactly one {marker!r} in {source_path}, found {len(matches)}"
        )
        return matches[0]

    start = unique_marker_line(f"# --8<-- [start:{region}]")
    end = unique_marker_line(f"# --8<-- [end:{region}]")
    assert start < end, f"region {region!r} markers are out of order in {source_path}"
    region_lines = list(source_lines[start + 1 : end])
    while region_lines and not region_lines[0].strip():
        del region_lines[0]
    while region_lines and not region_lines[-1].strip():
        del region_lines[-1]
    return textwrap.dedent("\n".join(region_lines))


GUIDE_TEXT = GUIDE_PATH.read_text(encoding="utf-8")
SNIPPETS, UNMARKED_FENCE_LINES = _parse_guide(GUIDE_TEXT)


def test_guide_contains_marked_excerpts() -> None:
    """The guide ships worked examples, so marked fences must exist."""
    assert SNIPPETS, f"no marked Python fences found in {GUIDE_PATH}"


def test_every_python_fence_has_a_snippet_marker() -> None:
    """An unmarked excerpt cannot slip into the guide unsynced."""
    assert not UNMARKED_FENCE_LINES, (
        "Python fences without a preceding <!-- snippet: ... --> marker at "
        f"guide lines {UNMARKED_FENCE_LINES}"
    )


def test_every_snippet_marker_precedes_a_python_fence() -> None:
    """A marker that drifts away from its fence is a broken excerpt."""
    lines = GUIDE_TEXT.splitlines()
    orphaned = [
        number + 1
        for number, line in enumerate(lines)
        if SNIPPET_MARKER.match(line)
        and (number + 1 >= len(lines) or not FENCE_OPEN.match(lines[number + 1]))
    ]
    assert not orphaned, (
        f"snippet markers not immediately followed by a ```python fence at "
        f"guide lines {orphaned}"
    )


@pytest.mark.parametrize(
    "snippet",
    SNIPPETS,
    ids=[f"{snippet.source_path}#{snippet.region}" for snippet in SNIPPETS],
)
def test_excerpt_matches_source_region(snippet: Snippet) -> None:
    """Each marked fence is byte-identical (after dedent) to its region."""
    source_path = REPO_ROOT / snippet.source_path
    assert source_path.is_file(), (
        f"guide line {snippet.line_number}: snippet marker points at missing "
        f"file {snippet.source_path}"
    )
    region_text = _extract_region(source_path, snippet.region)
    assert snippet.body == region_text, (
        f"guide line {snippet.line_number}: excerpt differs from region "
        f"{snippet.region!r} of {snippet.source_path}"
    )
