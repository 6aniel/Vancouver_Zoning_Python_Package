"""Layer 2a: assemble paragraph blocks into a numbered clause tree.

Bylaw numbering: 3.1.2.5 then (a) -> (i) -> (A). '(i)' is ambiguous (letter i
vs roman 1); we resolve it from what came before.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..extract.tagged_pdf import Block

SECTION_RE = re.compile(r"^(\d+(?:\.\d+)+)\s+(.*)$")
MARKER_RE = re.compile(r"^\(([a-z]{1,4}|[A-Z])\)\s*(.*)$")
ROMAN = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"]


@dataclass
class RawClause:
    id: str
    text: str
    page: int
    section_title: str | None = None
    parent: RawClause | None = None
    children: list[RawClause] = field(default_factory=list)
    tables: list[Block] = field(default_factory=list)  # tables printed right after this clause

    def descendants(self) -> list[RawClause]:
        out = []
        for c in self.children:
            out.append(c)
            out.extend(c.descendants())
        return out

    def subtree_text(self) -> str:
        return " ".join([self.text] + [d.text for d in self.descendants()])

    def ancestors_text(self) -> str:
        parts, node = [], self
        while node:
            parts.append(node.text)
            node = node.parent
        return " ".join(reversed(parts))

    @property
    def root(self) -> RawClause:
        node = self
        while node.parent:
            node = node.parent
        return node


def _marker_kind(m: str, stack: list[tuple[str, str, RawClause]]) -> str:
    """Return 'lower' | 'roman' | 'upper' for marker text m."""
    if m.isupper():
        return "upper"
    if m not in ROMAN:
        return "lower"
    last_lower = next((v for k, v, _ in reversed(stack) if k == "lower"), None)
    last_roman = next((v for k, v, _ in reversed(stack) if k == "roman"), None)
    is_next_letter = len(m) == 1 and last_lower is not None and ord(m) == ord(last_lower) + 1
    is_next_roman = (last_roman is None and m == "i") or (
        last_roman in ROMAN and ROMAN.index(last_roman) + 1 < len(ROMAN) and ROMAN[ROMAN.index(last_roman) + 1] == m
    )
    if is_next_letter and not (is_next_roman and stack and stack[-1][0] == "roman"):
        return "lower"
    if m == "i" and last_lower is None:
        return "lower"
    return "roman"


_LEVEL = {"lower": 1, "roman": 2, "upper": 3}


def _is_subheading(text: str) -> bool:
    return len(text.split()) <= 6 and not text.rstrip().endswith((".", ",", ";", ":")) and text[:1].isupper()


def build_clauses(blocks: list[Block]) -> list[RawClause]:
    """Flat list of all clauses (roots and sub-clauses) in document order."""
    out: list[RawClause] = []
    root: RawClause | None = None
    stack: list[tuple[str, str, RawClause]] = []  # (kind, marker, clause)
    heading_title: str | None = None
    subheading: str | None = None
    last: RawClause | None = None

    for b in blocks:
        if b.kind == "heading":
            m = SECTION_RE.match(b.text)
            heading_title = b.text
            subheading = None
            if m:
                root = RawClause(m.group(1), "", b.page, section_title=b.text)
                out.append(root)
                stack, last = [], root
            continue
        if b.kind == "table" and last is not None:
            last.tables.append(b)
            continue
        if b.kind != "para":
            continue
        text = b.text
        sec = SECTION_RE.match(text)
        mk = MARKER_RE.match(text)
        if sec:
            root = RawClause(sec.group(1), sec.group(2), b.page, section_title=subheading or heading_title)
            out.append(root)
            stack, last = [], root
        elif mk and root is not None:
            marker = mk.group(1)
            kind = _marker_kind(marker, stack)
            while stack and _LEVEL[stack[-1][0]] >= _LEVEL[kind]:
                stack.pop()
            parent = stack[-1][2] if stack else root
            cid = parent.id + f"({marker})"
            c = RawClause(cid, mk.group(2), b.page, section_title=root.section_title, parent=parent)
            parent.children.append(c)
            out.append(c)
            stack.append((kind, marker, c))
            last = c
        elif _is_subheading(text) and last is not None and (not last.text or last.text.rstrip().endswith((".", ";", ":"))):
            subheading = text
        elif last is not None:
            if not last.text:
                last.text = text  # intro paragraph under a numbered heading
            elif not last.text.rstrip().endswith((".", ",", ";", ":")):
                last.text = f"{last.text} {text}"  # sentence broken across tags/pages
            else:
                # trailing 'except that ...' / 'provided that ...' closes the
                # enumerated list it follows, so attach it one level up.
                owner = last.parent or last
                owner.text = f"{owner.text} [...] {text}"
        # paragraphs before the first numbered clause (intro text) are ignored here
    return out
