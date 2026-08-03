from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

from ..translator import TranslationError, TranslatorProvider
from .caption_downloader import CaptionSegment

logger = logging.getLogger(__name__)

# Caps per batched translate() call — keeps requests well under the free
# backend's practical size limits while still turning many small pieces
# into a handful of requests instead of one each.
_MAX_ITEMS_PER_REQUEST = 50
_MAX_CHARS_PER_REQUEST = 3000

# A context block groups adjacent segments up to the next sentence-ending
# punctuation, so short ASR fragments (e.g. a segment that's just
# "çekiyordu.") get translated with the rest of their sentence instead of
# alone. Capped so a long stretch without punctuation doesn't produce one
# giant block.
_MAX_SEGMENTS_PER_CONTEXT_BLOCK = 8
_MAX_CONTEXT_BLOCK_CHARS = 220
_SENTENCE_END_RE = re.compile(r"[.!?…]\s*$")

# Items are joined into one string as "[[[index]]]\ntext" blocks so the
# translated result can be split back apart by index rather than by
# position. Tolerant of whitespace MT may introduce around the digits.
_MARKER_RE = re.compile(r"\[\[\[\s*(\d+)\s*\]\]\]")


@dataclass(frozen=True)
class _ContextBlock:
    segment_indices: List[int]
    segment_lengths: List[int]
    text: str


def translate_caption_segments(
    segments: List[CaptionSegment],
    translator: TranslatorProvider,
    source_language: str,
    target_language: str,
) -> List[CaptionSegment]:
    """Translate caption text with sentence-level context, timing untouched.

    Short ASR fragments translated in isolation lose sentence context (e.g.
    a segment that's just "çekiyordu." — the tail end of a sentence split
    across two timing cues, mistranslated without the rest of the
    sentence). To fix this, adjacent segments are joined into sentence-
    level "context blocks" before translation; each block is translated as
    one continuous piece of text, then redistributed back across its
    original segments' timings proportionally by character length,
    snapped to word boundaries.

    `source_language`/`target_language` are provider-facing codes (same
    convention as TranslatorProvider.translate) — callers resolve canonical
    codes via language_map before calling this, same as the metadata
    pipeline does.

    Returns one CaptionSegment per input segment, same order, same
    start/duration — only `text` differs. A block that fails translation
    even after per-item fallback keeps its original (untranslated) text
    rather than dropping segments — a caption track missing entries breaks
    playback sync, so structural completeness wins over an all-or-nothing
    translation guarantee.
    """
    if not segments:
        return []

    blocks = _build_context_blocks(segments)

    block_translations: Dict[int, str] = {}
    indexed_block_texts = [(i, block.text) for i, block in enumerate(blocks)]
    for chunk in _chunk_indexed_texts(indexed_block_texts):
        _translate_chunk(chunk, translator, source_language, target_language, block_translations)

    result: List[CaptionSegment] = [None] * len(segments)  # type: ignore[list-item]

    for block_index, block in enumerate(blocks):
        translated_text = block_translations.get(block_index)
        if translated_text is None:
            logger.warning(
                "Context block %d could not be translated; keeping original text.", block_index
            )
            parts = [segments[i].text for i in block.segment_indices]
        else:
            parts = _split_proportionally(translated_text, block.segment_lengths)

        for segment_index, part in zip(block.segment_indices, parts):
            seg = segments[segment_index]
            result[segment_index] = CaptionSegment(start=seg.start, duration=seg.duration, text=part)

    return result


def _build_context_blocks(segments: List[CaptionSegment]) -> List[_ContextBlock]:
    blocks: List[_ContextBlock] = []
    current_indices: List[int] = []
    current_texts: List[str] = []

    def flush() -> None:
        if current_indices:
            blocks.append(
                _ContextBlock(
                    segment_indices=list(current_indices),
                    segment_lengths=[len(t) for t in current_texts],
                    text=" ".join(t for t in current_texts if t).strip(),
                )
            )

    for index, seg in enumerate(segments):
        current_indices.append(index)
        current_texts.append(seg.text)

        joined_len = sum(len(t) for t in current_texts) + max(len(current_texts) - 1, 0)
        ends_sentence = bool(_SENTENCE_END_RE.search(seg.text.strip()))
        hit_cap = (
            len(current_indices) >= _MAX_SEGMENTS_PER_CONTEXT_BLOCK
            or joined_len >= _MAX_CONTEXT_BLOCK_CHARS
        )

        if ends_sentence or hit_cap:
            flush()
            current_indices = []
            current_texts = []

    flush()
    return blocks


def _split_proportionally(translated_text: str, original_lengths: List[int]) -> List[str]:
    """Divide translated_text into len(original_lengths) word-boundary-safe
    pieces, sized proportionally to each original segment's character share
    of the pre-translation block. Approximate by nature — translation
    changes word order and length — but keeps each piece's rough share of
    the sentence aligned with its original timing slot.
    """
    if len(original_lengths) == 1:
        return [translated_text.strip()]

    words = translated_text.split()
    if not words:
        return ["" for _ in original_lengths]

    total_original = sum(original_lengths) or 1
    total_words = len(words)

    parts: List[str] = []
    word_index = 0
    cumulative = 0
    remaining = len(original_lengths)

    for length in original_lengths:
        remaining -= 1
        cumulative += length
        if remaining == 0:
            target = total_words
        else:
            target = round(total_words * (cumulative / total_original))
            target = max(word_index, min(target, total_words - remaining))
        parts.append(" ".join(words[word_index:target]))
        word_index = target

    return parts


def _translate_chunk(
    chunk: List[Tuple[int, str]],
    translator: TranslatorProvider,
    source_language: str,
    target_language: str,
    translations: Dict[int, str],
) -> None:
    batch_text = _build_batch_text(chunk)

    try:
        translated_batch = translator.translate(batch_text, source_language, target_language)
        parsed = _parse_batch_result(translated_batch)
    except TranslationError as exc:
        logger.warning("Batch translation failed (%s); falling back to per-item.", exc)
        parsed = {}

    chunk_indices = {index for index, _ in chunk}
    for index, text in parsed.items():
        if index in chunk_indices:
            translations[index] = text

    missing = [(index, text) for index, text in chunk if index not in translations]
    for index, text in missing:
        try:
            translations[index] = translator.translate(text, source_language, target_language)
        except TranslationError as exc:
            logger.warning("Item %d translation failed: %s", index, exc)


def _chunk_indexed_texts(items: List[Tuple[int, str]]) -> List[List[Tuple[int, str]]]:
    chunks: List[List[Tuple[int, str]]] = []
    current: List[Tuple[int, str]] = []
    current_chars = 0

    for index, text in items:
        if current and (
            len(current) >= _MAX_ITEMS_PER_REQUEST or current_chars + len(text) > _MAX_CHARS_PER_REQUEST
        ):
            chunks.append(current)
            current = []
            current_chars = 0
        current.append((index, text))
        current_chars += len(text)

    if current:
        chunks.append(current)

    return chunks


def _build_batch_text(chunk: List[Tuple[int, str]]) -> str:
    return "\n".join(f"[[[{index}]]]\n{text}" for index, text in chunk)


def _parse_batch_result(translated_text: str) -> Dict[int, str]:
    matches = list(_MARKER_RE.finditer(translated_text))
    result: Dict[int, str] = {}
    for i, match in enumerate(matches):
        index = int(match.group(1))
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(translated_text)
        result[index] = translated_text[start:end].strip()
    return result
