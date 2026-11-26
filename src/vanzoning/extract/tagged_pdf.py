"""Layer 1: turn a tagged bylaw PDF into an ordered list of semantic blocks.

City of Vancouver district schedules are exported from InDesign as *tagged*
PDFs. The tag tree already marks headings (H, H1, H2), paragraphs (P) and
tables (Table/TR/TH/TD). Body text is tagged; diagram labels, running headers
and footers are untagged artifacts. Reading the tag tree therefore gives us
clean reading order and real table cells without any layout heuristics.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

HEADING_TAGS = {"H", "H1", "H2", "H3", "H4"}


@dataclass
class Block:
    kind: str  # "heading" | "para" | "table" | "figure"
    page: int  # 1-based
    text: str = ""
    level: int = 0  # heading level (H=0, H1=1, ...)
    rows: list[list[str]] = field(default_factory=list)  # for tables
    header: list[str] = field(default_factory=list)


def _mcids(node: dict) -> set[int]:
    out = set(node.get("mcids") or [])
    for child in node.get("children", []):
        out |= _mcids(child)
    return out


def _mcids_excluding(node: dict, skip: str) -> set[int]:
    out = set(node.get("mcids") or [])
    for child in node.get("children", []):
        if child["type"] != skip:
            out |= _mcids_excluding(child, skip)
    return out


class _PageText:
    """Fast mcid -> text lookup for one page."""

    def __init__(self, page: pdfplumber.page.Page):
        self.page = page
        self._repair_nested_mcids()
        self.captions: list[str] = []
        self._caption_mcids = self._find_captions()

    def _repair_nested_mcids(self) -> None:
        """pdfminer drops the outer MCID after a nested marked-content run
        (e.g. a Link inside a P), leaving chars with mcid=None. Re-attach them
        to the last open MCID, unless we just left an artifact/placed graphic."""
        last = None
        for ch in self.page.chars:
            tag = ch.get("tag")
            if ch.get("mcid") is not None:
                last = ch["mcid"]
            elif tag in ("Artifact", "PlacedPDF"):
                last = None
            elif last is not None:
                ch["mcid"] = last

    def _find_captions(self) -> set[int]:
        """Diagram captions ("Diagram: ...") sit in their own bold MCIDs that
        InDesign anchors inside body paragraphs. Pull them out so they don't
        get spliced into clause text."""
        runs: dict[int, list[dict]] = {}
        for ch in self.page.chars:
            if ch.get("mcid") is not None:
                runs.setdefault(ch["mcid"], []).append(ch)
        caption_ids: set[int] = set()
        order = sorted(runs)
        info = {}
        for mcid in order:
            chars = [c for c in runs[mcid] if c["text"].strip()]
            if not chars:
                continue
            info[mcid] = (
                "".join(c["text"] for c in runs[mcid]).strip(),
                all("Bold" in c["fontname"] for c in chars),
                chars[0]["x0"],
                chars[0]["top"],
            )
        keys = list(info)
        for i, mcid in enumerate(keys):
            txt, _, cx, top = info[mcid]
            if not txt.startswith("Diagram:"):
                continue
            parts, last_top = [txt], top
            caption_ids.add(mcid)
            for nxt in keys[i + 1 : i + 15]:  # continuation lines may interleave
                t2, bold, x2, top2 = info[nxt]
                same_line = abs(top2 - last_top) < 2 and x2 > cx
                next_line = abs(x2 - cx) < 5 and 0 < top2 - last_top < 16
                if bold and (same_line or next_line):
                    parts.append(t2)
                    caption_ids.add(nxt)
                    last_top = top2
            self.captions.append(" ".join(parts))
        self.captions = [c.removeprefix("Diagram:").strip() for c in self.captions]
        return caption_ids

    def text(self, ids: set[int]) -> str:
        ids = ids - self._caption_mcids
        if not ids:
            return ""
        sub = self.page.filter(
            lambda o: o.get("object_type") != "char" or o.get("mcid") in ids
        )
        txt = sub.extract_text() or ""
        return " ".join(txt.split())  # collapse line wraps


def _table_rows(node: dict, pt: _PageText) -> tuple[list[str], list[list[str]]]:
    header: list[str] = []
    rows: list[list[str]] = []

    def walk(n: dict, in_head: bool) -> None:
        if n["type"] == "TR":
            cells: list[str] = []
            for c in n.get("children", []):
                if c["type"] not in ("TD", "TH"):
                    continue
                txt = pt.text(_mcids(c))
                span = int((c.get("attributes") or {}).get("ColSpan", 1) or 1)
                # A value cell spanning several district columns applies to each;
                # a label cell spanning the row leaves the value columns empty.
                cells.append(txt)
                cells.extend(([""] if len(cells) == 1 else [txt]) * (span - 1))
            if in_head and not header:
                header.append(cells)
            else:
                rows.append(cells)
            return
        for c in n.get("children", []):
            walk(c, in_head or n["type"] == "THead")

    walk(node, False)
    return (header[0] if header else []), rows


def _prune_to_page(nodes: list[dict], pno: int) -> list[dict]:
    """Keep only the parts of a document-level structure tree on page `pno`."""
    out = []
    for n in nodes:
        kids = _prune_to_page(n.get("children", []), pno)
        on_page = n.get("page_number") == pno
        if on_page or kids:
            m = dict(n, children=kids)
            if not on_page:
                m.pop("mcids", None)
            out.append(m)
    return out


def page_structure_tree(pdf: pdfplumber.PDF, page: pdfplumber.page.Page, _cache: dict) -> list[dict]:
    """The page's tag tree. Some City PDFs (e.g. R5 p.8) have a parent-tree
    entry without a /P link, which breaks pdfminer's per-page parse; fall back
    to the document-level tree pruned to this page."""
    try:
        return page.structure_tree
    except (KeyError, AssertionError):
        if "doc" not in _cache:
            _cache["doc"] = pdf.structure_tree
        return _prune_to_page(_cache["doc"], page.page_number)


def iter_blocks(pdf_path: str | Path) -> Iterator[Block]:
    with pdfplumber.open(pdf_path) as pdf:
        cache: dict = {}
        for pno, page in enumerate(pdf.pages, start=1):
            pt = _PageText(page)
            yield from _walk(page_structure_tree(pdf, page, cache), pno, pt)
            for cap in pt.captions:
                yield Block("figure", pno, cap)


def _walk(nodes: list[dict], pno: int, pt: _PageText) -> Iterator[Block]:
    for n in nodes:
        t = n["type"]
        if t in HEADING_TAGS:
            level = 0 if t == "H" else int(t[1:])
            yield Block("heading", pno, pt.text(_mcids(n)), level=level)
        elif t == "Table":
            header, rows = _table_rows(n, pt)
            yield Block("table", pno, header=header, rows=rows)
        elif t == "P":
            own = pt.text(_mcids_excluding(n, "Table"))
            if own:
                yield Block("para", pno, own)
            yield from _walk([c for c in n.get("children", []) if c["type"] == "Table"], pno, pt)
        else:  # Document / Art / Sect / Div containers
            yield from _walk(n.get("children", []), pno, pt)


def is_tagged(pdf_path: str | Path) -> bool:
    with pdfplumber.open(pdf_path) as pdf:
        return bool(pdf.pages and pdf.pages[0].structure_tree)
