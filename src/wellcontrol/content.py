"""Access to the teaching content in ``content/``.

The chapters are plain markdown, written to be read on GitHub or in an editor.
This module lets them be read programmatically as well -- which is how the
Streamlit app renders them in its Learn page, and how the tests check that
every kill method points at a chapter that actually exists.

Two adjustments are needed before markdown written for GitHub renders sensibly
inside an app:

* **Relative links would 404.** ``[Hydrostatics](02-hydrostatics.md)`` works on
  GitHub because there is a file server behind it. Rendered in an app there is
  not, so those links are reduced to their text.
* **The footer navigation is redundant.** Each chapter ends with a
  "Previous / Next" line whose links are exactly the ones that would break. The
  app provides its own buttons, so the footer is dropped.

The content lives at the repository root rather than inside the package, so it
is found by walking up from this file. Pass an explicit directory to override.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

#: Markdown links pointing at anything other than an absolute URL.
_LOCAL_LINK = re.compile(r"\[([^\]]+)\]\((?!https?://)[^)]*\)")

#: Chapters are numbered so they sort into reading order.
_CHAPTER_GLOB = "[0-9][0-9]-*.md"

#: ``content/`` at the repository root: content.py -> wellcontrol -> src -> root
DEFAULT_CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"


def content_dir(directory: Path | str | None = None) -> Path:
    """The content directory, defaulting to the one at the repository root."""
    return Path(directory) if directory is not None else DEFAULT_CONTENT_DIR


def chapter_files(directory: Path | str | None = None) -> list[str]:
    """Chapter filenames in reading order.

    The index README is excluded -- it is a table of links, which is exactly
    what does not survive rendering outside GitHub. Callers that need a
    contents list should build one from :func:`chapter_title`.
    """
    path = content_dir(directory)
    if not path.is_dir():
        return []
    return sorted(p.name for p in path.glob(_CHAPTER_GLOB))


@lru_cache(maxsize=64)
def _read(path_str: str) -> str:
    return Path(path_str).read_text(encoding="utf-8")


def chapter_title(filename: str, directory: Path | str | None = None) -> str:
    """The chapter's own H1, minus the leading hash.

    Falls back to a readable form of the filename if the file cannot be read
    or has no H1, so a missing chapter degrades to a label rather than an
    exception.
    """
    path = content_dir(directory) / filename
    try:
        text = _read(str(path))
    except OSError:
        return filename.removesuffix(".md").replace("-", " ")
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return filename.removesuffix(".md").replace("-", " ")


def chapter_body(filename: str, directory: Path | str | None = None) -> str:
    """A chapter prepared for rendering inside an app.

    The H1 is dropped (the caller shows the title itself), the footer
    navigation is dropped, and relative links are reduced to their text.
    """
    path = content_dir(directory) / filename
    try:
        text = _read(str(path))
    except OSError as exc:
        return f"*Could not read `{filename}`: {exc}*"

    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    text = "\n".join(lines)

    head, separator, tail = text.rpartition("\n---\n")
    if separator and any(k in tail for k in ("Previous:", "Next:", "Back to")):
        text = head

    return strip_local_links(text).strip()


def strip_local_links(text: str) -> str:
    """Reduce relative markdown links to their link text.

    Absolute ``http(s)`` links are left alone -- those still work anywhere.
    """
    return _LOCAL_LINK.sub(r"\1", text)


def chapter_exists(filename: str, directory: Path | str | None = None) -> bool:
    return (content_dir(directory) / filename).is_file()
