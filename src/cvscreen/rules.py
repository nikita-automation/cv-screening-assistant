"""Offline baseline extractor: regular expressions and keyword lists for German and English text.

It is deliberately conservative - when a field is not clearly stated it stays empty (null / []),
and negations ("kein Staplerschein", "no weekends", "Sunday shifts not possible") are respected,
because a wrongly *claimed* licence or availability is worse than a missing one. What it cannot do
(paraphrases such as "certified to operate counterbalance trucks", unusual layouts, lower-case
scrap text) is exactly what the language-model backend is for; `cvscreen eval` measures the gap.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .schema import SKILLS, empty_profile, normalize, validate

# --- vocabulary ---------------------------------------------------------------------------

LANGUAGE_NAMES = {
    "deutsch": "German", "german": "German", "englisch": "English", "english": "English",
    "ukrainisch": "Ukrainian", "ukrainian": "Ukrainian", "russisch": "Russian", "russian": "Russian",
    "türkisch": "Turkish", "tuerkisch": "Turkish", "turkish": "Turkish", "arabisch": "Arabic",
    "arabic": "Arabic", "polnisch": "Polish", "polish": "Polish", "rumänisch": "Romanian",
    "romanian": "Romanian", "spanisch": "Spanish", "spanish": "Spanish", "französisch": "French",
    "franzoesisch": "French", "french": "French", "italienisch": "Italian", "italian": "Italian",
}
_LANG = "(?:%s)" % "|".join(sorted(LANGUAGE_NAMES, key=len, reverse=True))
_LEVEL = (r"(?:[ABC][12]|muttersprache|erstsprache|native|fließend|fliessend|fluent|verhandlungssicher|"
          r"gute?\s+kenntnisse|gut|good|grundkenntnisse|grundlagen|basic|anfänger)")
_LEVEL_MAP = {"muttersprache": "native", "erstsprache": "native", "native": "native", "fließend": "fluent",
              "fliessend": "fluent", "fluent": "fluent", "verhandlungssicher": "fluent", "gut": "good",
              "gute kenntnisse": "good", "good": "good", "grundkenntnisse": "basic", "grundlagen": "basic",
              "basic": "basic", "anfänger": "basic"}

SKILL_PATTERNS: Dict[str, str] = {
    "warehouse": r"\blager(?:arbeit|logistik|helfer\w*|mitarbeiter\w*|ist\w*)?\b|\bwarehouse\b",
    "order picking": r"\bkommissionier\w*|\border\s+picking\b|\bpicking\b",
    "packing": r"\bverpack\w*|\bpacking\b|\bpacker\w*|\bpackerin\b",
    "goods receiving": r"\bwareneingang\b|\bgoods[\s-]+(?:receiving|in)\b",
    "shipping": r"\bwarenausgang\b|\bversand\b|\bshipping\b|\bdispatch\b",
    "inventory": r"\binventur\b|\binventory\b|\bstocktaking\b",
    "customer service": r"\bkundenservice\b|\bkundenberatung\b|\bkundenbetreuung\b|\bcustomer\s+(?:service|support)\b",
    "MS Office": r"\bms[\s-]?office\b|\bmicrosoft\s+office\b|\bexcel\b",
    "SAP": r"\bsap\b",
    "cash handling": r"\bkasse\b|\bkassier\w*|\bcash\s+(?:register|handling)\b",
    "cleaning": r"\breinigung\b|\bcleaning\b",
    "gastronomy": r"\bgastronomie\b|\bservice\s*kraft\b|\bkellner\w*|\bhospitality\b",
}
assert set(SKILL_PATTERNS) == set(SKILLS)

# --- helpers ------------------------------------------------------------------------------

_NEGATION_BEFORE = re.compile(
    r"(?:\bkeine?[nrms]?\b|\bnicht\b|\bohne\b|\bno\b|\bnot\b|\bnever\b|\bcannot\b|\bcan't\b|\bcan\s+not\b|"
    r"\bunable\b|\bkann\s+nicht\b|\bnein\b)\W+(?:\w+\W+){0,3}$", re.IGNORECASE)
_NEGATION_AFTER = re.compile(
    r"^[^.;,\n]{0,25}?(?:nicht\s+möglich|not\s+possible|unavailable|nicht\s+verfügbar|ausgeschlossen|"
    r"geht\s+nicht|not\s+available|nicht\s+machbar|nicht\s+bereit)", re.IGNORECASE)
_PLAN_WORDS = re.compile(
    r"möchte|will\b|plane\b|planning|want\s+to|would\s+like|noch\s+machen|in\s+planung|geplant|"
    r"beabsichtige|anstreben|erwerben|vorhaben|hope\s+to", re.IGNORECASE)
_SENTENCE_START = re.compile(r"[.;!?\n]")
_CLAUSE_START = re.compile(r"[.;,!?\n]|\bbut\b|\baber\b|\bsondern\b", re.IGNORECASE)


def _clause_before(text: str, pos: int) -> str:
    start = 0
    for match in _CLAUSE_START.finditer(text, 0, pos):
        start = match.end()
    return text[start:pos]


def _negated(text: str, start: int, end: int) -> bool:
    before = _clause_before(text, start)
    if _NEGATION_BEFORE.search(before[-40:] + " "):
        return True
    return bool(_NEGATION_AFTER.match(text[end:end + 40]))


def _expand_elisions(text: str) -> str:
    """'Früh-, Spät- und Nachtschicht' -> 'Frühschicht, Spätschicht und Nachtschicht'."""
    return re.sub(r"\b(früh|spät)-(?=\s*(?:,|und\b|oder\b|/|&))", r"\1schicht", text, flags=re.IGNORECASE)


# --- contact ------------------------------------------------------------------------------

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_LABELLED = re.compile(r"(?:tel(?:efon)?|mobil(?:e)?|handy|phone|fon)\.?\s*[:\-]?\s*(\+?[\d(][\d\s()./-]{6,}\d)",
                             re.IGNORECASE)
_PHONE_PLUS = re.compile(r"(\+\d[\d\s()./-]{7,}\d)")
_PHONE_NATIONAL = re.compile(r"(?<![\d.])(0\d{2,4}[\s/-]\d{3,}(?:[\s-]\d{2,})*)")


def _normalize_phone(raw: str) -> str:
    text = re.sub(r"\(0\)", "", raw.strip())
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    if text.lstrip().startswith("+"):
        pass
    elif digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "49" + digits[1:]
    else:
        return ""
    if digits.startswith("490"):
        digits = "49" + digits[3:]
    return "+" + digits if 8 <= len(digits) <= 15 else ""


def _phone(text: str) -> Optional[str]:
    for pattern in (_PHONE_LABELLED, _PHONE_PLUS, _PHONE_NATIONAL):
        for match in pattern.finditer(text):
            number = _normalize_phone(match.group(1))
            if number:
                return number
    return None


_CITY_STOP = {"euro", "eur", "euros", "brutto", "netto", "gross", "net"}
_PLZ_CITY = re.compile(r"\b(\d{5})[ \t]+([A-ZÄÖÜ][a-zäöüß]+(?:[- ][A-ZÄÖÜ][a-zäöüß]+)?)\b")
_CITY_CUE = re.compile(r"(?:wohnort|wohnhaft\s+in|wohne\s+in|lebe\s+in|based\s+in|lives?\s+in|living\s+in|residence)"
                       r"[ \t]*:?[ \t]*(?:(\d{5})[ \t]+)?([A-ZÄÖÜ][\wäöüß-]+(?:[ \t][A-ZÄÖÜ][\wäöüß-]+)?)", re.IGNORECASE)


def _residence(text: str) -> Tuple[Optional[str], Optional[str]]:
    for match in _PLZ_CITY.finditer(text):
        if match.group(2).lower() not in _CITY_STOP:
            return match.group(1), match.group(2)
    match = _CITY_CUE.search(text)
    if match and match.group(2)[0].isupper():
        return match.group(1), match.group(2)
    return None, None


# --- name ---------------------------------------------------------------------------------

_NAME = r"((?:(?:Dr|Prof|Mag)\.?[ \t]+)*[A-ZÄÖÜ][\wäöüß'’-]+(?:[ \t]+[A-ZÄÖÜ][\wäöüß'’-]+){1,3})"
_HEADER_WORDS = {"lebenslauf", "bewerberfragebogen", "curriculum", "vitae", "cv", "resume", "bewerbung",
                 "fragebogen", "application"}
_NAME_LABEL = re.compile(r"^\s*(?:name|vor-?\s*und\s*nachname)\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_NAME_CUES = re.compile(
    r"^\s*(?i:bewerbung\s+von|application\s+(?:from|of)|(?:curriculum\s+vitae|lebenslauf|cv|resume)\s*[-–—:])\s*" + _NAME,
    re.MULTILINE)
_SIGN_OFF = re.compile(
    r"^\s*(?i:gruß|grüße|viele\s+grüße|mit\s+freundlichen\s+grüßen|freundliche\s+grüße|best\s+regards|"
    r"kind\s+regards|regards|sincerely)\s*,?\s*\n\s*" + _NAME + r"\s*$", re.MULTILINE)
_LEADING_NAME = re.compile(r"^\s*" + _NAME)


def _name(text: str) -> Optional[str]:
    match = _NAME_LABEL.search(text)
    if match and _LEADING_NAME.match(match.group(1)):
        return _LEADING_NAME.match(match.group(1)).group(1).strip()
    for pattern in (_NAME_CUES, _SIGN_OFF):
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    for line in [l for l in text.splitlines() if l.strip()][:6]:
        if line.strip().lower() in _HEADER_WORDS:
            continue
        match = _LEADING_NAME.match(line)
        if match:
            return match.group(1).strip()
        break
    return None


# --- languages ----------------------------------------------------------------------------

_LANG_AFTER = re.compile(r"\b(%s)\b([^\n.;,]{0,25}?)\b(%s)\b" % (_LANG, _LEVEL), re.IGNORECASE)
_LANG_BEFORE = re.compile(r"\b(muttersprache|erstsprache|native|fließend|fliessend|fluent|verhandlungssicher)\b"
                          r"\s*(?:in|auf)?\s*\b(%s)\b" % _LANG, re.IGNORECASE)
_LANG_CONTEXT = re.compile(r"sprach|language", re.IGNORECASE)
_LANG_WORD = re.compile(r"\b(%s)\b" % _LANG, re.IGNORECASE)


def _level(raw: str) -> str:
    key = re.sub(r"\s+", " ", raw.lower())
    return raw.upper() if re.fullmatch(r"[abc][12]", key) else _LEVEL_MAP[key]


def _languages(text: str) -> List[Dict[str, Optional[str]]]:
    found: Dict[str, Optional[str]] = {}
    for mention in _LANG_WORD.finditer(text):      # every language gets its own look at the text after it
        match = _LANG_AFTER.match(text, mention.start())
        if match is None or _LANG_WORD.search(match.group(2)):
            continue                       # another language sits in between: the level belongs to that one
        found.setdefault(LANGUAGE_NAMES[match.group(1).lower()], _level(match.group(3)))
    for match in _LANG_BEFORE.finditer(text):
        found.setdefault(LANGUAGE_NAMES[match.group(2).lower()], _level(match.group(1)))
    lines = text.splitlines()
    for index, line in enumerate(lines):
        context = _LANG_CONTEXT.search(line) or (index and _LANG_CONTEXT.search(lines[index - 1])
                                                 and line.strip()[:1] in ("-", "•", "*", ""))
        if context:
            for match in _LANG_WORD.finditer(line):
                found.setdefault(LANGUAGE_NAMES[match.group(1).lower()], None)
    return [{"language": name, "level": level} for name, level in found.items()]


# --- licences -----------------------------------------------------------------------------

_CLASS = r"(?:AM|A1|A2|A|BE|B|C1E|C1|CE|C|D1E|D1|DE|D)"
_LICENCE_CUE = re.compile(r"führerschein(?:klassen?)?|fuehrerschein|fahrerlaubnis|driv(?:er|ing)['’]?s?\s+licen[cs]e",
                          re.IGNORECASE)
_LICENCE_TAIL = re.compile(
    r"^\W*(?:(?:ja|yes|vorhanden|available|held|valid|gültig)\W+)?(?:(?:klasse|class|category|kategorie|kl)\.?\s+)?"
    r"(%s(?:\s*(?:,|/|und|and|&)\s*%s)*)\b" % (_CLASS, _CLASS), re.IGNORECASE)
_LICENCE_BEFORE = re.compile(r"(?:category|class|klasse)\s+(%s)\s+(?:driving|driver)" % _CLASS, re.IGNORECASE)


def _driving(text: str) -> List[str]:
    classes: List[str] = []
    for cue in _LICENCE_CUE.finditer(text):
        tail = text[cue.end():cue.end() + 60]
        match = _LICENCE_TAIL.match(tail)
        if match:
            classes += [c.upper() for c in re.split(r"\s*(?:,|/|und|and|&)\s*", match.group(1), flags=re.IGNORECASE)]
    for match in _LICENCE_BEFORE.finditer(text):
        classes.append(match.group(1).upper())
    return sorted(set(classes))


_FORKLIFT = re.compile(r"stapler|flurförder|flurfoerder|forklift|fork-lift|lift\s+truck", re.IGNORECASE)
_NO_AFTER = re.compile(r"^\w*\W{0,3}(?:licen[cs]e|certificate|schein|zertifikat)?\W{0,15}(?:nein|no|keine?|none|not)\b",
                       re.IGNORECASE)


def _forklift(text: str) -> Optional[bool]:
    """True = states they hold one, False = states they do not (or only plan to), None = not mentioned."""
    claimed = denied = False
    for match in _FORKLIFT.finditer(text):
        sentence_start = max([m.end() for m in _SENTENCE_START.finditer(text, 0, match.start())] or [0])
        following = _SENTENCE_START.search(text, match.end())
        sentence = text[sentence_start:following.start() if following else len(text)]
        before = text[sentence_start:match.start()]
        if (_NEGATION_BEFORE.search(before[-40:] + " ") or _NO_AFTER.match(text[match.end():match.end() + 40])
                or _PLAN_WORDS.search(sentence)):
            denied = True
        else:
            claimed = True
    return True if claimed else (False if denied else None)


# --- skills, shifts, salary, availability -------------------------------------------------

def _skills(text: str) -> List[str]:
    return sorted(skill for skill, pattern in SKILL_PATTERNS.items() if re.search(pattern, text, re.IGNORECASE))


_SHIFT_PATTERNS = [
    ("early", re.compile(r"\bfrüh(?:schicht|dienst)\w*|\b(?:early|morning)\b(?=[^.;\n]{0,25}\bshifts?\b)", re.IGNORECASE)),
    ("late", re.compile(r"\bspät(?:schicht|dienst)\w*|\b(?:late|afternoon)\b(?=[^.;\n]{0,25}\bshifts?\b)", re.IGNORECASE)),
    ("night", re.compile(r"\bnacht(?:schicht|dienst|arbeit)\w*|\bnights?\b", re.IGNORECASE)),
    ("weekend", re.compile(r"\bwochenende\w*|\bsamstag\w*|\bsonntag\w*|\bweekends?\b|\bsaturdays?\b|\bsundays?\b",
                           re.IGNORECASE)),
]
_ALL_SHIFTS = re.compile(r"\balle\s+schichten\b|\bjede\s+schicht\b|\ball\s+shifts\b|\bany\s+shift\b|\bdreischicht\w*",
                         re.IGNORECASE)


def _shifts(text: str) -> Tuple[List[str], List[str]]:
    text = _expand_elisions(text)
    available, unavailable = set(), set()
    for kind, pattern in _SHIFT_PATTERNS:
        for match in pattern.finditer(text):
            (unavailable if _negated(text, match.start(), match.end()) else available).add(kind)
    for match in _ALL_SHIFTS.finditer(text):
        target = unavailable if _negated(text, match.start(), match.end()) else available
        target.update(("early", "late", "night"))
    available -= unavailable
    return sorted(available), sorted(unavailable)


_AMOUNT = r"(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_SALARY_CUE = re.compile(
    r"gehaltsvorstellung\w*|gehaltswunsch|wunschgehalt|wunschlohn|lohnvorstellung|stundenlohn|jahresgehalt|"
    r"monatsgehalt|expected\s+salary|desired\s+salary|salary(?:\s+expectations?)?|verdienst|lohn", re.IGNORECASE)
_SALARY_BODY = re.compile(
    r"(?:(?:€|eur(?:o)?)\s*)?" + _AMOUNT + r"(?:\s*(?:-|–|—|bis|to|und|and)\s*(?:(?:€|eur(?:o)?)\s*)?" + _AMOUNT + r")?"
    r"\s*(€|eur(?:o)?\b)?", re.IGNORECASE)
_UNIT_HOUR = re.compile(r"\b(?:std|stunde|stunden|h|hour|hr|hourly|stündlich)\b", re.IGNORECASE)
_UNIT_MONTH = re.compile(r"\b(?:monat|month|mtl|monatlich|monthly)\b", re.IGNORECASE)
_UNIT_YEAR = re.compile(r"\b(?:jahr|year|annual|annually|jährlich)\b|p\.a\.", re.IGNORECASE)


def _amount(raw: str) -> float:
    """German and English number formats: '2.800' '2,650' '13,50' '12.90' '48.000' '14'."""
    if "," in raw and "." in raw:
        decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        return float(raw.replace(thousands, "").replace(decimal, "."))
    for separator in (",", "."):
        if separator in raw:
            tail = raw.rsplit(separator, 1)[1]
            if len(tail) == 3:                       # money has no three-digit decimals: thousands separator
                return float(raw.replace(separator, ""))
            return float(raw.replace(separator, "."))
    return float(raw)


def _salary(text: str) -> Optional[Dict[str, object]]:
    for cue in _SALARY_CUE.finditer(text):
        line_end = text.find("\n", cue.end())
        segment = text[cue.end():(line_end if line_end != -1 else len(text))][:90]
        body = _SALARY_BODY.search(segment)
        if not body:
            continue
        if not re.search(r"€|eur", segment[:body.end()], re.IGNORECASE):
            continue                                  # a number without a currency is not a salary
        low = _amount(body.group(1))
        high = _amount(body.group(2)) if body.group(2) else low
        tail = segment[body.end():body.end() + 30]
        cue_text = cue.group(0).lower()
        if _UNIT_HOUR.search(tail) or "stunden" in cue_text:
            unit = "hour"
        elif _UNIT_MONTH.search(tail) or "monats" in cue_text:
            unit = "month"
        elif _UNIT_YEAR.search(tail) or "jahres" in cue_text:
            unit = "year"
        elif high < 100:
            unit = "hour"
        elif high <= 15000:
            unit = "month"
        else:
            unit = "year"
        return {"amount_min": min(low, high), "amount_max": max(low, high), "unit": unit, "currency": "EUR"}
    return None


_MONTHS = {"januar": 1, "january": 1, "februar": 2, "february": 2, "märz": 3, "maerz": 3, "march": 3, "april": 4,
           "mai": 5, "may": 5, "juni": 6, "june": 6, "juli": 7, "july": 7, "august": 8, "september": 9,
           "oktober": 10, "october": 10, "november": 11, "dezember": 12, "december": 12}
_FROM_CUE = (r"(?:verfügbar\s+ab(?:\s+dem)?|frühestens\s+ab|eintritt\s+ab|available\s+from|"
             r"available\s+as\s+of|start\s+date:?|ab\s+dem)")
_DATE_NUMERIC = re.compile(_FROM_CUE + r"\s*:?\s*(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})\b", re.IGNORECASE)
_DATE_WORDS = re.compile(_FROM_CUE + r"\s*:?\s*(\d{1,2})\.?\s+([A-Za-zäÄ]+)\s+(\d{4})\b", re.IGNORECASE)
_IMMEDIATELY = re.compile(r"\bab\s+sofort\b|\bsofort\s+verfügbar\b|\bavailable\s+(?:immediately|now)\b|"
                          r"\bimmediately\s+available\b|\bkann\s+sofort\s+anfangen\b", re.IGNORECASE)


def _available_from(text: str) -> Optional[str]:
    match = _DATE_NUMERIC.search(text)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        year += 2000 if year < 100 else 0
        if 1 <= month <= 12 and 1 <= day <= 31:
            return "%04d-%02d-%02d" % (year, month, day)
    match = _DATE_WORDS.search(text)
    if match and match.group(2).lower() in _MONTHS:
        return "%04d-%02d-%02d" % (int(match.group(3)), _MONTHS[match.group(2).lower()], int(match.group(1)))
    if _IMMEDIATELY.search(text):
        return "immediately"
    return None


# --- entry point --------------------------------------------------------------------------

def extract(text: str) -> Dict[str, object]:
    """Extract a profile from one document. The result is always schema-valid."""
    profile = empty_profile()
    email = _EMAIL.search(text)
    profile["email"] = email.group(0).lower() if email else None
    profile["phone"] = _phone(text)
    profile["name"] = _name(text)
    profile["postal_code"], profile["city"] = _residence(text)
    profile["languages"] = _languages(text)
    profile["driving_licence"] = _driving(text)
    profile["forklift_licence"] = _forklift(text)
    profile["skills"] = _skills(text)
    profile["shift_available"], profile["shift_unavailable"] = _shifts(text)
    profile["salary"] = _salary(text)
    profile["available_from"] = _available_from(text)
    problems = validate(profile)
    if problems:                                    # a bug in this module, not in the input
        raise AssertionError("rules extractor produced an invalid profile: " + "; ".join(problems))
    return normalize(profile)
