"""Which files a text cites: the one token rule the roadmap's proof panel, its API and its page share.

``citation_corpus.json`` (next to this module) is the rule's text and its cases; ``load_corpus()`` reads it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

#: The only token boundary: ASCII whitespace. WHY not ``str.split()`` / JS ``\\s`` (Codex audit B13): Python splits on
#: U+001C-U+001F and JS on U+FEFF and NBSP, so the page and the API cut the same text differently.
_CITED_BOUNDARY = re.compile(r"[ \t\n\v\f\r]+")
#: What opens and closes a cited path's token (a parenthesis, a quote, a sentence's end): never part of it.
_CITED_LEADING = "([{\"'`<"
_CITED_TRAILING = ")]}.,;:\"'`>"
_CITED_QUOTES = "\"'`"
#: A whole token that is a cited file: an absolute ASCII path with a text suffix, then at most ``:LINE`` or
#: ``:LINE:COL`` (ASCII digits: Python's ``\\d`` would take any Unicode digit).
_CITED_TOKEN = re.compile(
    r"(?P<path>/[A-Za-z0-9._~+@%=/-]+?\.(?:log|txt|md|py|json|jsonl|toml|yaml|yml|cfg|ini|xml))(?::(?P<line>[0-9]+)(?::[0-9]+)?)?")
#: A ``/./`` or ``/../`` spelling, or one ending ``/.`` or ``/..``: never a citation.
_CITED_DOT_SEGMENT = re.compile(r"/\.\.?(?:/|$)")


def cited_tokens(text: str) -> list[tuple[str, int | None]]:
    """The cited files (and lines) in one text, in order; the rule ``citation_corpus.json`` pins.

    WHY quotes are matched as delimiters across tokens (Codex audits B03/C02/D01): in
    ``"/safe/name.txt /safe/proof.txt copy.log"`` the quote opened before the first path closes after the last word,
    so every token inside is part of one quoted name, the middle one too, and none of them is a citation. Each token's
    front quotes open (a stack); its back quotes, innermost first, close the matching open quote, or are stray. A token
    made only of punctuation closes the open quote it matches rather than opening a new one. A token cites a file only
    when no quote is open before it, none is left open after it, and none of its quotes was stray. Quotes never span
    two texts.
    """

    cited: list[tuple[str, int | None]] = []
    stack: list[str] = []
    for raw in _CITED_BOUNDARY.split(text):
        if not raw:
            continue
        core = raw.lstrip(_CITED_LEADING)
        stripped = core.rstrip(_CITED_TRAILING)
        front = [char for char in raw[: len(raw) - len(core)] if char in _CITED_QUOTES]
        back = [char for char in core[len(stripped):] if char in _CITED_QUOTES]
        if not core and stack:  # only punctuation, inside a quote: its quotes close, they do not open
            front, back = [], front
        was_open, stray = bool(stack), False
        stack.extend(front)
        for quote in back:
            if quote in stack:
                del stack[len(stack) - 1 - stack[::-1].index(quote):]
            else:
                stray = True
        if was_open or stack or stray or not stripped.startswith("/"):
            continue
        match = _CITED_TOKEN.fullmatch(stripped)
        if match is not None and not _CITED_DOT_SEGMENT.search(match["path"]):
            cited.append((match["path"], int(match["line"]) if match["line"] else None))
    return cited



def cited_paths(texts: Iterable[str]) -> frozenset[str]:
    """Every absolute evidence-file path written verbatim in any of ``texts`` (e.g. a loop event's evidence or detail).

    WHY the cited words are the allowlist (the proof panel): the proof panel shows the acceptance logs and test files
    the roadmap cited for a status, which live outside the data home (``reports/media/...``, the package's tests).
    Serving exactly the paths written, as they were spelled, opens no file nobody cited; a directory root or a path
    pattern would serve every file under it. A path is cited only with one of the text suffixes, so a cited archive,
    binary or directory is never one.

    WHY one token rule pinned by a corpus (Codex audits A02/A10/B03/B13): the page's proof panel links by the same
    rule, and so does ``bam_roadmap``; ``citation_corpus.json`` is the rule's text and its cases, and every
    implementation runs it. A path with a space or a non-ASCII character cannot be cited.
    """

    cited: set[str] = set()
    for text in texts:
        cited.update(path for path, _line in cited_tokens(text))
    return frozenset(cited)


def load_corpus() -> dict:
    """The shared citation corpus (``citation_corpus.json`` beside this module): ``{schema, rule, cases}``."""

    return json.loads(Path(__file__).with_name("citation_corpus.json").read_text(encoding="utf-8"))
