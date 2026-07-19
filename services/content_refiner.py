"""Structure-aware content refinement for search extraction.

DOM blocks → sections → heuristic filter → optional embed filter → markdown.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import structlog

from config import get_settings

logger = structlog.get_logger()
settings = get_settings()

_NOISE_PATTERNS = re.compile(
    r"|".join(
        [
            r"\bdisclaimer\b",
            r"not constitute (financial|investment|legal|tax)",
            r"consult a qualified",
            r"past performance",
            r"leave a reply",
            r"cancel reply",
            r"\brelated stories\b",
            r"\byou may have missed\b",
            r"\btrending now\b",
            r"\bpost navigation\b",
            r"\bskip to content\b",
            r"\bsign in\b",
            r"\bfollow now\b",
            r"^\s*share\s*$",
            r"^\s*aa\s*$",
            r"text size\s*small\s*medium\s*large",
        ]
    ),
    re.IGNORECASE,
)

_NAV_BLOB = re.compile(
    r"^(home|menu|search|subscribe|login|sign in|e-?paper|weather)\b",
    re.IGNORECASE,
)

_SIDEBAR_HEADING = re.compile(
    r"\b(trending stories|trending now|latest posts|popular posts|featured posts|"
    r"author bio|photostories|financial calculators|daily puzzles|related stories|"
    r"you may have missed|join taxguru|connect|tags)\b",
    re.IGNORECASE,
)


def _block_text(block: Dict[str, Any]) -> str:
    btype = block.get("type")
    if btype == "heading":
        return block.get("text", "")
    if btype == "paragraph":
        return block.get("text", "")
    if btype == "quote":
        return block.get("text", "")
    if btype == "list":
        return " ".join(block.get("items") or [])
    if btype == "table":
        rows = block.get("rows") or []
        return " ".join(" ".join(row) for row in rows)
    return ""


def is_noise_block(block: Dict[str, Any]) -> bool:
    text = _block_text(block).strip()
    if not text:
        return True
    if (
        len(text) < settings.search_refine_min_block_chars
        and block.get("type") != "heading"
    ):
        return True
    if _NOISE_PATTERNS.search(text):
        return True
    if block.get("type") == "paragraph" and _NAV_BLOB.match(text) and len(text) < 120:
        return True
    return False


def is_sidebar_section(section: Dict[str, Any]) -> bool:
    heading = (section.get("heading") or "").strip()
    if _SIDEBAR_HEADING.search(heading):
        return True
    if len(heading) <= 4:
        return True
    if heading.lower() in {"toi", "tags:", "connect"}:
        return True
    blocks = section.get("blocks") or []
    if blocks and all(b.get("type") == "list" for b in blocks):
        items = [i for b in blocks for i in (b.get("items") or [])]
        if len(items) >= 6 and sum(len(i) < 40 for i in items) >= 4:
            return True
    return False


def blocks_to_sections(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group ordered blocks into sections keyed by nearest heading."""
    sections: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    for block in blocks:
        if is_noise_block(block):
            continue
        if block.get("type") == "heading":
            level = int(block.get("level") or 2)
            heading = (block.get("text") or "").strip()
            if not heading:
                continue
            current = {"heading": heading, "level": level, "blocks": []}
            sections.append(current)
            continue
        if current is None:
            current = {"heading": "", "level": 2, "blocks": []}
            sections.append(current)
        current["blocks"].append(block)

    return [
        s
        for s in sections
        if (s.get("heading") or s.get("blocks")) and not is_sidebar_section(s)
    ]


def section_plain_text(section: Dict[str, Any]) -> str:
    parts: List[str] = []
    heading = section.get("heading") or ""
    if heading:
        parts.append(heading)
    for block in section.get("blocks") or []:
        parts.append(_block_text(block))
    return " ".join(p for p in parts if p).strip()


def _table_to_markdown(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [r + [""] * (width - len(r)) for r in rows]
    header = norm[0]
    sep = ["---"] * width
    body = norm[1:] if len(norm) > 1 else []
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _block_to_markdown(block: Dict[str, Any]) -> str:
    btype = block.get("type")
    if btype == "paragraph":
        return block.get("text", "")
    if btype == "quote":
        return f"> {block.get('text', '')}"
    if btype == "list":
        items = block.get("items") or []
        prefix = lambda i, t: f"{i + 1}. {t}" if block.get("ordered") else f"- {t}"
        return "\n".join(prefix(i, t) for i, t in enumerate(items))
    if btype == "table":
        return _table_to_markdown(block.get("rows") or [])
    return ""


def sections_to_markdown(title: str, sections: List[Dict[str, Any]], url: str) -> str:
    lines: List[str] = []
    if title:
        lines.extend([f"# {title}", ""])
    for section in sections:
        heading = section.get("heading") or ""
        level = min(max(int(section.get("level") or 2), 2), 4)
        if heading:
            lines.append(f"{'#' * level} {heading}")
            lines.append("")
        for block in section.get("blocks") or []:
            md = _block_to_markdown(block)
            if md:
                lines.append(md)
                lines.append("")
    lines.append(f"*Source: {url}*")
    return "\n".join(lines).strip() + "\n"


async def filter_sections_by_embedding(
    sections: List[Dict[str, Any]],
    query: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Drop sections below cosine similarity threshold; preserve survivors' order."""
    if not sections or not query or not settings.search_refine_embed_enabled:
        return sections, []

    from services.embeddings import _encode_query_and_documents, cosine_similarity

    texts = [section_plain_text(section)[:2000] for section in sections]
    embeddings = await _encode_query_and_documents(query, texts)
    if not embeddings:
        return sections, []
    q_emb, *document_embeddings = embeddings

    scored: List[Tuple[Dict[str, Any], float]] = []
    dropped: List[str] = []
    for section, text, d_emb in zip(sections, texts, document_embeddings):
        if len(text) < settings.search_refine_min_block_chars:
            dropped.append(section.get("heading") or "(short)")
            continue
        score = max(0.0, min(1.0, cosine_similarity(q_emb, d_emb)))
        section["relevance_score"] = round(score, 3)
        scored.append((section, score))
        if score < settings.search_refine_embed_threshold:
            dropped.append(section.get("heading") or text[:60])

    kept = [s for s, score in scored if score >= settings.search_refine_embed_threshold]
    if not kept and scored:
        best_section, _ = max(scored, key=lambda x: x[1])
        kept = [best_section]
        best_heading = best_section.get("heading") or ""
        dropped = [h for h in dropped if h != best_heading]

    return kept, dropped


class ContentRefiner:
    @staticmethod
    async def refine(
        structured: Dict[str, Any],
        *,
        query: Optional[str] = None,
        title: Optional[str] = None,
        url: Optional[str] = None,
    ) -> Dict[str, Any]:
        blocks = structured.get("blocks") or []
        page_title = title or structured.get("title") or ""
        page_url = url or structured.get("url") or ""

        sections = blocks_to_sections(blocks)
        dropped: List[str] = []

        # Drop heading-only shells with no body blocks.
        sections = [
            s for s in sections if s.get("blocks") or len((s.get("heading") or "")) > 80
        ]

        if query and len(sections) > 8:
            sections, dropped = await filter_sections_by_embedding(sections, query)

        markdown = sections_to_markdown(page_title, sections, page_url)
        plain = "\n".join(section_plain_text(s) for s in sections)
        tokens = max(1, len(plain) // 4)

        return {
            "title": page_title,
            "url": page_url,
            "markdown": markdown,
            "sections": sections,
            "dropped_sections": dropped,
            "block_count": len(blocks),
            "section_count": len(sections),
            "chars": len(plain),
            "tokens": tokens,
        }
