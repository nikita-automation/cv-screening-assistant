"""The profile every backend must produce, and a validator that does not trust any backend.

The same schema is handed to the language model as a JSON schema (structured output) and used to
validate what the rules backend - or the model - returned. A profile that does not validate is
rejected, never silently repaired.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List

CEFR = ("A1", "A2", "B1", "B2", "C1", "C2")
LEVEL_LABELS = CEFR + ("native", "fluent", "good", "basic")
DRIVING_CLASSES = ("AM", "A1", "A2", "A", "B", "BE", "C1", "C1E", "C", "CE", "D1", "D1E", "D", "DE")
SHIFTS = ("early", "late", "night", "weekend")
SALARY_UNITS = ("hour", "month", "year")

# Controlled vocabulary: the model must pick from it, the rules backend maps synonyms onto it.
SKILLS = ("warehouse", "order picking", "packing", "goods receiving", "shipping", "inventory",
          "customer service", "MS Office", "SAP", "cash handling", "cleaning", "gastronomy")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _nullable(schema: Dict[str, Any]) -> Dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


PROFILE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "email", "phone", "postal_code", "city", "languages", "driving_licence",
                 "forklift_licence", "skills", "shift_available", "shift_unavailable", "salary",
                 "available_from"],
    "properties": {
        "name": _nullable({"type": "string"}),
        "email": _nullable({"type": "string"}),
        "phone": _nullable({"type": "string"}),
        "postal_code": _nullable({"type": "string"}),
        "city": _nullable({"type": "string"}),
        "languages": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False, "required": ["language", "level"],
                "properties": {"language": {"type": "string"},
                               "level": _nullable({"type": "string", "enum": list(LEVEL_LABELS)})},
            },
        },
        "driving_licence": {"type": "array", "items": {"type": "string", "enum": list(DRIVING_CLASSES)}},
        "forklift_licence": _nullable({"type": "boolean"}),
        "skills": {"type": "array", "items": {"type": "string", "enum": list(SKILLS)}},
        "shift_available": {"type": "array", "items": {"type": "string", "enum": list(SHIFTS)}},
        "shift_unavailable": {"type": "array", "items": {"type": "string", "enum": list(SHIFTS)}},
        "salary": _nullable({
            "type": "object", "additionalProperties": False,
            "required": ["amount_min", "amount_max", "unit", "currency"],
            "properties": {"amount_min": {"type": "number"}, "amount_max": {"type": "number"},
                           "unit": {"type": "string", "enum": list(SALARY_UNITS)},
                           "currency": {"type": "string", "enum": ["EUR"]}},
        }),
        "available_from": _nullable({"type": "string"}),
    },
}

# Field-by-field documentation, used in the prompt for the model and in the README.
FIELD_NOTES = {
    "name": "Full name of the applicant exactly as written (keep titles). null if not stated.",
    "email": "E-mail address of the applicant. null if absent.",
    "phone": "Phone number in international form (+49...). null if absent.",
    "postal_code": "German postal code of the place of residence (5 digits). null if absent.",
    "city": "Place of residence. null if absent.",
    "languages": "Every language the applicant says they speak, level as CEFR (A1-C2) or native/fluent/good/basic "
                 "when no CEFR level is given, else null. Language names in English.",
    "driving_licence": "Driving licence classes held (e.g. B, BE, C1). [] if none or not stated.",
    "forklift_licence": "true if the applicant states they hold a forklift/industrial-truck licence or certificate, "
                        "false if they state they do not hold one or only plan to get one, null if not mentioned.",
    "skills": "Skills from the allowed list only.",
    "shift_available": "Shift types the applicant says they CAN work. Past experience alone is not availability.",
    "shift_unavailable": "Shift types the applicant says they can NOT work.",
    "salary": "Salary expectation; a single figure has amount_min == amount_max. null if no figure is given.",
    "available_from": "'immediately' or an ISO date (YYYY-MM-DD) if a full date is given, else null.",
}


def empty_profile() -> Dict[str, Any]:
    return {"name": None, "email": None, "phone": None, "postal_code": None, "city": None, "languages": [],
            "driving_licence": [], "forklift_licence": None, "skills": [], "shift_available": [],
            "shift_unavailable": [], "salary": None, "available_from": None}


def validate(profile: Any) -> List[str]:
    """Return a list of problems (empty list = valid)."""
    problems: List[str] = []
    if not isinstance(profile, dict):
        return ["profile is not an object"]
    expected = set(PROFILE_SCHEMA["required"])
    for key in sorted(expected - set(profile)):
        problems.append("missing field: " + key)
    for key in sorted(set(profile) - expected):
        problems.append("unexpected field: " + key)

    def text_or_null(key: str) -> None:
        value = profile.get(key)
        if value is not None and not isinstance(value, str):
            problems.append("%s must be a string or null" % key)

    for key in ("name", "email", "phone", "postal_code", "city", "available_from"):
        if key in profile:
            text_or_null(key)

    postal = profile.get("postal_code")
    if isinstance(postal, str) and not re.fullmatch(r"\d{5}", postal):
        problems.append("postal_code must be 5 digits")
    available = profile.get("available_from")
    if isinstance(available, str) and available != "immediately" and not _ISO_DATE.match(available):
        problems.append("available_from must be 'immediately' or YYYY-MM-DD")

    forklift = profile.get("forklift_licence", None)
    if forklift is not None and not isinstance(forklift, bool):
        problems.append("forklift_licence must be true, false or null")

    def enum_list(key: str, allowed) -> None:
        value = profile.get(key)
        if key not in profile:
            return
        if not isinstance(value, list):
            problems.append("%s must be a list" % key)
            return
        for item in value:
            if item not in allowed:
                problems.append("%s: %r is not allowed" % (key, item))

    enum_list("driving_licence", DRIVING_CLASSES)
    enum_list("skills", SKILLS)
    enum_list("shift_available", SHIFTS)
    enum_list("shift_unavailable", SHIFTS)
    both = set(profile.get("shift_available") or []) & set(profile.get("shift_unavailable") or [])
    if both:
        problems.append("shift both available and unavailable: " + ", ".join(sorted(both)))

    languages = profile.get("languages")
    if "languages" in profile:
        if not isinstance(languages, list):
            problems.append("languages must be a list")
        else:
            for item in languages:
                if not isinstance(item, dict) or set(item) != {"language", "level"}:
                    problems.append("language entries need exactly 'language' and 'level'")
                    continue
                if not isinstance(item["language"], str) or not item["language"]:
                    problems.append("language name must be a non-empty string")
                if item["level"] is not None and item["level"] not in LEVEL_LABELS:
                    problems.append("language level %r is not allowed" % (item["level"],))

    salary = profile.get("salary")
    if "salary" in profile and salary is not None:
        if not isinstance(salary, dict) or set(salary) != {"amount_min", "amount_max", "unit", "currency"}:
            problems.append("salary needs amount_min, amount_max, unit, currency")
        else:
            for key in ("amount_min", "amount_max"):
                if isinstance(salary[key], bool) or not isinstance(salary[key], (int, float)):
                    problems.append("salary.%s must be a number" % key)
            if salary["unit"] not in SALARY_UNITS:
                problems.append("salary.unit must be one of %s" % ", ".join(SALARY_UNITS))
            if salary["currency"] != "EUR":
                problems.append("salary.currency must be EUR")
            if (isinstance(salary["amount_min"], (int, float)) and isinstance(salary["amount_max"], (int, float))
                    and salary["amount_min"] > salary["amount_max"]):
                problems.append("salary.amount_min is larger than amount_max")
    return problems


def normalize(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Canonical ordering so equal profiles compare and print equal."""
    result = copy.deepcopy(profile)
    for key in ("driving_licence", "skills", "shift_available", "shift_unavailable"):
        result[key] = sorted(set(result.get(key) or []))
    result["languages"] = sorted(result.get("languages") or [], key=lambda item: item["language"])
    return result
