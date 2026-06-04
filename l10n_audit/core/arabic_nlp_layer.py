#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Arabic NLP Layer — optional CAMeL Tools backend wrapper.

This module is the single integration point between the CAMeL Shadow Review
Layer and the `camel-tools` library.  The only public symbol consumers need is:

    result = analyze_arabic_text(text, enable_dialect=False)

``result`` is a plain ``dict`` with exactly 8 string keys that map 1-to-1 to
the ``camel_*`` review-queue columns:

    camel_available          — "yes" | "no"
    camel_reason             — short human-readable status note
    camel_mixed_script       — "yes" | "no" | ""
    camel_unknown_count      — int-as-string, e.g. "0", "3"
    camel_unknown_tokens     — space-joined list of unknown tokens
    camel_pos_summary        — space-joined unique POS tags, e.g. "NOUN VERB PRON"
    camel_dialect            — dialect label, e.g. "MSA" / "EGY" / "unknown"
    camel_normalized_preview — first 120 chars of normalised text

The function is **always callable** — it never raises.  When ``camel-tools``
is not installed a lightweight pure-Python fallback runs instead:

* ``camel_available``         → "no"
* ``camel_reason``            → descriptive note
* ``camel_mixed_script``      → detected via Unicode range scan (reliable)
* ``camel_unknown_count``     → "" (not computable without the library)
* ``camel_unknown_tokens``    → "" (ditto)
* ``camel_pos_summary``       → "" (ditto)
* ``camel_dialect``           → "" (ditto)
* ``camel_normalized_preview``→ Unicode NFKC + Arabic diacritic strip

Optional backend
----------------
When ``camel-tools`` **is** installed the real backend activates automatically.
Feature support depends on which CAMeL data packs are present; each feature is
individually guarded so a missing data file disables just that feature, leaving
all other fields intact.

Install the library (not a runtime requirement of the toolkit itself):

    pip install camel-tools          # core
    python -m camel_tools.cli.data download  # data packs (optional)
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# ---------------------------------------------------------------------------
# 1. Detect whether camel-tools is available at import time
# ---------------------------------------------------------------------------

_CAMEL_TOOLS_AVAILABLE = False
_CAMEL_TOOLS_VERSION: str = ""

try:
    import camel_tools  # noqa: F401 — availability probe
    _CAMEL_TOOLS_AVAILABLE = True
    _CAMEL_TOOLS_VERSION = getattr(camel_tools, "__version__", "unknown")
except ImportError:
    pass

# ---------------------------------------------------------------------------
# 2. Arabic / Latin Unicode ranges used by the fallback
# ---------------------------------------------------------------------------

# Arabic Unicode block: U+0600–U+06FF (including extended variants)
_RE_ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
_RE_ARABIC_LETTERS = re.compile(r"[\u0621-\u064A]")
# Basic Latin letters (A–Z, a–z)
_RE_LATIN = re.compile(r"[A-Za-z]")
# Arabic diacritics (harakat) — safe to strip for a normalised preview
_RE_HARAKAT = re.compile(r"[\u064B-\u065F\u0670]")
# Tatweel (elongation character)
_RE_TATWEEL = re.compile(r"\u0640")
# Arabic-Indic digits → Western digits mapping
_ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# ---------------------------------------------------------------------------
# 3. Pure-Python helpers (always available, no data deps)
# ---------------------------------------------------------------------------

_ARABIC_ALEF_VARIANTS = re.compile(r"[إأآا]")
_ARABIC_TEH_MARBUTA = re.compile(r"ة")
_ARABIC_ALEF_MAKSURA = re.compile(r"ى")


def _detect_mixed_script(text: str) -> str:
    """Return 'yes' if text mixes Arabic and Latin characters, else 'no'."""
    if not text:
        return ""
    has_arabic = bool(_RE_ARABIC.search(text))
    has_latin = bool(_RE_LATIN.search(text))
    return "yes" if (has_arabic and has_latin) else "no"


def _normalize_arabic_text(text: str, max_preview: int = 120) -> str:
    """Return a normalised preview of Arabic text using pure Python.

    Steps applied (in order):
    1. Unicode NFKC normalisation
    2. Strip diacritics (harakat)
    3. Remove tatweel
    4. Normalise Alef variants → bare Alef
    5. Normalise Teh Marbuta → Heh
    6. Normalise Alef Maksura → Yeh
    7. Translate Arabic-Indic digits → Western digits
    8. Collapse multiple spaces
    9. Truncate to ``max_preview`` characters
    """
    if not text or not text.strip():
        return ""
    result = unicodedata.normalize("NFKC", text)
    result = _RE_HARAKAT.sub("", result)
    result = _RE_TATWEEL.sub("", result)
    result = _ARABIC_ALEF_VARIANTS.sub("ا", result)
    result = _ARABIC_TEH_MARBUTA.sub("ه", result)
    result = _ARABIC_ALEF_MAKSURA.sub("ي", result)
    result = result.translate(_ARABIC_INDIC)
    result = re.sub(r"\s+", " ", result).strip()
    return result[:max_preview]


def _is_arabic_text(text: str) -> bool:
    """Return True when the text contains at least one Arabic letter."""
    return bool(text) and bool(_RE_ARABIC_LETTERS.search(text))


# ---------------------------------------------------------------------------
# 4. Fallback result (no camel-tools)
# ---------------------------------------------------------------------------

def _fallback_result(text: str, reason: str) -> dict[str, str]:
    """Produce the best possible result without the CAMeL Tools library."""
    return {
        "camel_available": "no",
        "camel_reason": reason,
        "camel_mixed_script": _detect_mixed_script(text),
        "camel_unknown_count": "",
        "camel_unknown_tokens": "",
        "camel_pos_summary": "",
        "camel_dialect": "",
        "camel_normalized_preview": _normalize_arabic_text(text),
    }


# ---------------------------------------------------------------------------
# 5. Real CAMeL Tools backend (only active when camel-tools is installed)
# ---------------------------------------------------------------------------

def _camel_analyze(text: str, enable_dialect: bool) -> dict[str, str]:
    """Run the real CAMeL Tools pipeline.

    Each feature is individually try/except guarded.  A missing data pack
    (e.g. the dialect-ID model) disables only that feature; the rest of the
    fields are still filled.

    Returns a fully populated result dict.
    """
    result: dict[str, str] = {
        "camel_available": "yes",
        "camel_reason": "camel-tools-ok",
        "camel_mixed_script": _detect_mixed_script(text),
        "camel_unknown_count": "",
        "camel_unknown_tokens": "",
        "camel_pos_summary": "",
        "camel_dialect": "",
        "camel_normalized_preview": "",
    }

    # 5a. Normalisation — always possible, no data pack needed
    try:
        from camel_tools.utils.normalize import (
            normalize_unicode,
            normalize_alef,
            normalize_teh_marbuta,
            normalize_alef_maksura,
        )
        norm = normalize_unicode(text)
        norm = normalize_alef(norm)
        norm = normalize_teh_marbuta(norm)
        norm = normalize_alef_maksura(norm)
        norm = _RE_HARAKAT.sub("", norm)
        norm = _RE_TATWEEL.sub("", norm)
        norm = re.sub(r"\s+", " ", norm).strip()
        result["camel_normalized_preview"] = norm[:120]
    except Exception:
        result["camel_normalized_preview"] = _normalize_arabic_text(text)

    # 5b. Simple word tokenisation (no data needed)
    tokens: list[str] = []
    try:
        try:
            from camel_tools.tokenizers.word import simple_word_tokenize
        except ImportError:
            from camel_tools.tokenize.word import simple_word_tokenize
        tokens = simple_word_tokenize(text)
    except Exception:
        tokens = text.split() if text else []

    # 5c. Morphological analysis — requires camel_tools data DB
    #     We use the 'r13' database which ships with newer camel-tools.
    unknown_tokens: list[str] = []
    pos_tags: list[str] = []
    try:
        from camel_tools.morphology.database import MorphologyDB
        from camel_tools.morphology.analyzer import Analyzer

        try:
            db = MorphologyDB.builtin_db(flags="a")
        except Exception:
            db = MorphologyDB.builtin_db(flags="+a")
        analyzer = Analyzer(db)

        for token in tokens:
            if not _RE_ARABIC.search(token):
                continue  # skip non-Arabic tokens
            analyses = analyzer.analyze(token)
            if not analyses:
                unknown_tokens.append(token)
            else:
                pos = str(analyses[0].get("pos", "")).upper()
                if pos:
                    pos_tags.append(pos)
    except Exception:
        # No data pack or import error — leave unknown/pos empty
        pass

    result["camel_unknown_count"] = str(len(unknown_tokens))
    result["camel_unknown_tokens"] = " ".join(unknown_tokens)
    # Unique POS tags in encounter order
    seen: set[str] = set()
    unique_pos: list[str] = []
    for tag in pos_tags:
        if tag not in seen:
            seen.add(tag)
            unique_pos.append(tag)
    result["camel_pos_summary"] = " ".join(unique_pos)

    # 5d. Dialect identification — optional, requires dialect-ID data pack
    if enable_dialect:
        try:
            from camel_tools.dialectid import DialectIdentifier
            di = DialectIdentifier.pretrained()
            predictions = di.predict([text])
            if predictions:
                result["camel_dialect"] = str(predictions[0].top)
        except Exception:
            result["camel_dialect"] = ""
    else:
        result["camel_dialect"] = ""

    return result


# ---------------------------------------------------------------------------
# 6. Public API
# ---------------------------------------------------------------------------

_EMPTY_RESULT: dict[str, str] = {
    "camel_available": "",
    "camel_reason": "",
    "camel_mixed_script": "",
    "camel_unknown_count": "",
    "camel_unknown_tokens": "",
    "camel_pos_summary": "",
    "camel_dialect": "",
    "camel_normalized_preview": "",
}

RESULT_FIELDS: tuple[str, ...] = tuple(_EMPTY_RESULT.keys())


def analyze_arabic_text(
    text: Any,
    enable_dialect: bool = False,
) -> dict[str, str]:
    """Analyse Arabic text and return a dict of ``camel_*`` column values.

    Parameters
    ----------
    text:
        The Arabic string to analyse.  Non-string values are coerced to ``str``.
        ``None`` and empty strings are handled without error.
    enable_dialect:
        When ``True`` and ``camel-tools`` is installed with the dialect-ID data
        pack, attempt dialect identification.  Defaults to ``False`` because the
        data pack is heavy and optional.

    Returns
    -------
    dict[str, str]:
        Always contains all 8 ``camel_*`` keys.  All values are strings.
        Never raises — any internal failure produces ``""`` for that field.
    """
    # Coerce to str safely
    try:
        text_str = str(text) if text is not None else ""
    except Exception:
        return dict(_EMPTY_RESULT)

    if not text_str.strip():
        return {
            "camel_available": "yes" if _CAMEL_TOOLS_AVAILABLE else "no",
            "camel_reason": "empty-text",
            "camel_mixed_script": "",
            "camel_unknown_count": "0",
            "camel_unknown_tokens": "",
            "camel_pos_summary": "",
            "camel_dialect": "",
            "camel_normalized_preview": "",
        }

    if not _is_arabic_text(text_str):
        return {
            "camel_available": "yes" if _CAMEL_TOOLS_AVAILABLE else "no",
            "camel_reason": "not-arabic-text",
            "camel_mixed_script": _detect_mixed_script(text_str),
            "camel_unknown_count": "",
            "camel_unknown_tokens": "",
            "camel_pos_summary": "",
            "camel_dialect": "",
            "camel_normalized_preview": "",
        }

    if not _CAMEL_TOOLS_AVAILABLE:
        return _fallback_result(text_str, "camel-tools-unavailable")

    try:
        return _camel_analyze(text_str, enable_dialect)
    except Exception as exc:
        return _fallback_result(
            text_str,
            f"camel-tools-error: {type(exc).__name__}",
        )
