"""Document text chunking for cold-start memory import.

Splits document text into chunks suitable for memory storage.
Uses paragraph boundaries when possible, falls back to sentence/char splits.
"""

from __future__ import annotations

import re

DEFAULT_CHUNK_SIZE = 500
DEFAULT_OVERLAP = 50


def chunk_text(
    text: str,
    max_chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    """Split text into chunks respecting paragraph boundaries.

    Returns list of non-empty chunks, each <= max_chunk_size characters.
    Adjacent chunks share `overlap` characters for context continuity.
    """
    if not text or not text.strip():
        return []

    paragraphs = _split_paragraphs(text)
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(para) > max_chunk_size:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_long_paragraph(para, max_chunk_size))
            continue

        if current and len(current) + len(para) + 1 > max_chunk_size:
            chunks.append(current)
            if overlap > 0 and len(current) > overlap:
                tail = current[-overlap:]
                candidate = tail + "\n" + para
                if len(candidate) <= max_chunk_size:
                    current = candidate
                else:
                    current = para
            else:
                current = para
        else:
            current = current + "\n" + para if current else para

    if current.strip():
        chunks.append(current)

    return [c.strip() for c in chunks if c.strip()]


def _split_paragraphs(text: str) -> list[str]:
    """Split by double-newline or single-newline when paragraphs are short."""
    parts = re.split(r"\n{2,}", text)
    if len(parts) <= 1:
        parts = text.split("\n")
    return parts


def _split_long_paragraph(text: str, max_size: int) -> list[str]:
    """Break a single long paragraph by sentence boundaries, then by chars."""
    sentences = re.split(r"(?<=[。！？.!?\n])", text)
    if len(sentences) <= 1:
        return _split_by_chars(text, max_size)

    chunks: list[str] = []
    current = ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if current and len(current) + len(sent) + 1 > max_size:
            chunks.append(current)
            current = sent
        else:
            current = current + sent if current else sent

    if current.strip():
        chunks.append(current)

    final: list[str] = []
    for chunk in chunks:
        if len(chunk) > max_size:
            final.extend(_split_by_chars(chunk, max_size))
        else:
            final.append(chunk)
    return final


def _split_by_chars(text: str, max_size: int) -> list[str]:
    """Hard split by character count as last resort."""
    return [text[i : i + max_size] for i in range(0, len(text), max_size)]
