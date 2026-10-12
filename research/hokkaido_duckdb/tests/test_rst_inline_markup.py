"""Inline markup must actually be markup.

docutils only recognises an inline start-string when the character before it
is whitespace or punctuation, and an end-string when the character after it
is whitespace or punctuation. A Japanese letter is neither, so

    番号を持つ側を**ファクト表**と呼びます

renders the asterisks literally. **No warning is emitted**, so ``-W`` does not
catch it and it reaches the PDF. The fix is an escaped space, which satisfies
the rule and produces no space of its own::

    番号を持つ側を\\ **ファクト表**\\ と呼びます

Rather than reimplement the delimiter rule and get it subtly wrong, this test
hands each paragraph to docutils and asks whether any marker survived into the
rendered output. A surviving ``**`` or ``\\`\\``` is markup that did not take.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from docutils.core import publish_parts

DOCS = Path(__file__).resolve().parents[1] / "docs"

#: Sphinx roles mean nothing to bare docutils. Replaced by a plain word so the
#: surrounding text still parses; the role's own delimiters are Sphinx's
#: problem and Sphinx does warn about those.
_ROLE = re.compile(r":[a-zA-Z:+-]+:`[^`]*`")

_DIRECTIVE = re.compile(r"^\s*\.\.\s+[a-zA-Z][a-zA-Z0-9_-]*::")
_COMMENT = re.compile(r"^\s*\.\.(\s|$)")
_OPTION = re.compile(r"^\s*:[a-zA-Z][a-zA-Z0-9_-]*:")
_RULE = re.compile(r"^[=\-^~\"'`#*+]+$")


def prose_paragraphs(text: str) -> list[tuple[int, str]]:
    """``(first line number, paragraph)`` for the parts docutils reads as prose.

    Directive bodies and literal blocks are skipped: a marker there is text,
    not markup.
    """
    paragraphs: list[tuple[int, str]] = []
    buffer: list[str] = []
    first = 0
    skip_indent: int | None = None

    def flush() -> None:
        nonlocal buffer, first
        if buffer:
            paragraphs.append((first, "\n".join(buffer)))
        buffer = []

    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        if skip_indent is not None:
            if not stripped or indent > skip_indent:
                continue
            skip_indent = None

        if not stripped:
            flush()
            continue
        if _DIRECTIVE.match(line) or _COMMENT.match(line):
            flush()
            skip_indent = indent
            continue
        if _OPTION.match(line) and not buffer:
            continue
        if _RULE.match(stripped):          # a section underline
            flush()
            continue
        if line.rstrip().endswith("::"):   # literal block follows
            buffer.append(line.rstrip()[:-2])
            flush()
            skip_indent = indent
            continue
        if not buffer:
            first = number
        buffer.append(line)
    flush()
    return paragraphs


def unrendered_markers(paragraph: str) -> list[str]:
    """Markers that survived into the output, i.e. markup that did not take."""
    source = _ROLE.sub("X", paragraph)
    # Definition lists and field bodies need their own context; strip the
    # leading indent so a fragment parses as an ordinary paragraph.
    source = "\n".join(line.strip() for line in source.splitlines())
    body = publish_parts(
        source,
        writer="html5",
        settings_overrides={"report_level": 5, "halt_level": 5,
                            "input_encoding": "unicode"},
    )["body"]
    leftover = []
    for marker in ("``", "**"):
        if marker in body:
            leftover.append(marker)
    return leftover


@pytest.mark.parametrize("path", sorted(DOCS.glob("*.rst")), ids=lambda p: p.name)
def test_inline_markup_is_recognised(path):
    bad = []
    for number, paragraph in prose_paragraphs(path.read_text(encoding="utf-8")):
        leftover = unrendered_markers(paragraph)
        if leftover:
            snippet = " ".join(paragraph.split())[:110]
            bad.append(f"{path.name}:{number}: {'/'.join(leftover)} 未適用 -- {snippet}")
    assert bad == [], "\n".join(bad)


def test_the_check_catches_the_shape_it_is_for():
    bad = "このように、番号を持つ側を**ファクト表**、番号の意味を持つ側を**次元表**と"
    good = "このように、番号を持つ側を\\ **ファクト表**\\ 、番号の意味を持つ側を\\ **次元表**\\ と"
    assert unrendered_markers(bad) == ["**"]
    assert unrendered_markers(good) == []


def test_punctuation_neighbours_are_accepted():
    """Japanese punctuation is a valid delimiter; only letters are not."""
    assert unrendered_markers("（**強調**）と読点、**次**。") == []
    assert unrendered_markers("末尾が ``literal`` で終わる。") == []
    assert unrendered_markers("直前が日本語の``literal``は壊れる。") == ["``"]
