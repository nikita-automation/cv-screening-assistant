"""Measure an extractor against hand-labelled documents.

Scoring per field: exact match for scalars (names compared without titles and case), F1 over the set of
items for list fields (two empty lists score 1.0). The overall score is the mean over fields and documents.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Tuple

from .schema import normalize

SCALARS = ("name", "email", "phone", "postal_code", "city", "forklift_licence", "salary", "available_from")
SETS = ("languages", "driving_licence", "skills", "shift_available", "shift_unavailable")
FIELDS = SCALARS + SETS
_TITLES = {"dr", "prof", "mag", "herr", "frau"}


def _name_key(name: Any) -> Any:
    if not isinstance(name, str):
        return None
    tokens = [t for t in re.findall(r"\w+", name.casefold()) if t not in _TITLES]
    return tuple(sorted(tokens)) or None


def _items(field: str, value: Any) -> set:
    if field == "languages":
        return {(item["language"], item["level"]) for item in value or []}
    return set(value or [])


def score_field(field: str, got: Any, expected: Any) -> float:
    if field in SETS:
        a, b = _items(field, got), _items(field, expected)
        if not a and not b:
            return 1.0
        hits = len(a & b)
        if not hits:
            return 0.0
        precision, recall = hits / float(len(a)), hits / float(len(b))
        return 2 * precision * recall / (precision + recall)
    if field == "name":
        return float(_name_key(got) == _name_key(expected))
    if field in ("email", "city"):
        return float((got or "").casefold() == (expected or "").casefold() if (got or expected) else True)
    if field == "salary":
        if got is None or expected is None:
            return float(got is None and expected is None)
        same = (got["unit"] == expected["unit"] and got["currency"] == expected["currency"]
                and abs(got["amount_min"] - expected["amount_min"]) < 0.005
                and abs(got["amount_max"] - expected["amount_max"]) < 0.005)
        return float(same)
    return float(got == expected)


class EvalResult:
    def __init__(self) -> None:
        self.per_document: Dict[str, Dict[str, float]] = {}
        self.mismatches: List[Tuple[str, str, Any, Any]] = []
        self.errors: Dict[str, str] = {}

    def field_scores(self) -> Dict[str, float]:
        count = max(len(self.per_document), 1)
        return {f: sum(doc[f] for doc in self.per_document.values()) / count for f in FIELDS}

    @property
    def overall(self) -> float:
        scores = self.field_scores()
        return sum(scores.values()) / len(scores) if self.per_document else 0.0

    @property
    def perfect_documents(self) -> int:
        return sum(1 for doc in self.per_document.values() if all(v == 1.0 for v in doc.values()))


def evaluate(extract: Callable[[str], Dict[str, Any]], documents_dir: str, gold_path: str) -> EvalResult:
    with open(gold_path, encoding="utf-8") as handle:
        gold = json.load(handle)
    result = EvalResult()
    for name in sorted(gold):
        path = os.path.join(documents_dir, name)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        try:
            got = normalize(extract(text))
        except Exception as exc:                       # one failing document must not hide the others
            result.errors[name] = "%s: %s" % (type(exc).__name__, exc)
            result.per_document[name] = {field: 0.0 for field in FIELDS}
            continue
        expected = normalize(gold[name])
        result.per_document[name] = {}
        for field in FIELDS:
            score = score_field(field, got.get(field), expected.get(field))
            result.per_document[name][field] = score
            if score < 1.0:
                result.mismatches.append((name, field, got.get(field), expected.get(field)))
    return result


def format_result(result: EvalResult, title: str = "") -> str:
    lines = []
    if title:
        lines += [title, ""]
    lines.append("%-18s %s" % ("field", "score"))
    for field, score in result.field_scores().items():
        lines.append("%-18s %5.1f%%  %s" % (field, 100 * score, "#" * int(round(score * 20))))
    lines.append("")
    lines.append("overall %.1f%% over %d documents, %d documents without any error"
                 % (100 * result.overall, len(result.per_document), result.perfect_documents))
    if result.mismatches or result.errors:
        lines += ["", "Mismatches:"]
        for name, message in result.errors.items():
            lines.append("  %s  ERROR %s" % (name, message))
        for name, field, got, expected in result.mismatches:
            lines.append("  %s  %s: got %s, expected %s"
                         % (name, field, json.dumps(got, ensure_ascii=False), json.dumps(expected, ensure_ascii=False)))
    return "\n".join(lines) + "\n"
