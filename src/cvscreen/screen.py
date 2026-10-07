"""Compare profiles with a job's requirements and explain every verdict.

Each requirement is judged `met`, `not_met` or `unknown` - missing information is never treated as a "no".
The verdict is a *suggestion for a recruiter* (qualified / check manually / does not meet), with the reasons
attached; it is not an automated decision about a person.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .schema import CEFR

MET, NOT_MET, UNKNOWN = "met", "not_met", "unknown"


def _language(profile: Dict[str, Any], language: str, minimum: str) -> Tuple[str, str]:
    for item in profile["languages"]:
        if item["language"] == language:
            level = item["level"]
            if level == "native":
                return MET, "%s: native" % language
            if level in CEFR:
                ok = CEFR.index(level) >= CEFR.index(minimum)
                return (MET if ok else NOT_MET), "%s: %s (needs %s)" % (language, level, minimum)
            if level is None:
                return UNKNOWN, "%s mentioned without a level" % language
            return UNKNOWN, "%s level given as '%s', not CEFR" % (language, level)
    return UNKNOWN, "%s not mentioned" % language


def _requirement(profile: Dict[str, Any], kind: str, wanted: Any) -> List[Tuple[str, str]]:
    if kind == "forklift_licence":
        value = profile["forklift_licence"]
        if value is None:
            return [(UNKNOWN, "forklift licence not mentioned")]
        return [(MET if value == wanted else NOT_MET, "forklift licence: %s" % ("yes" if value else "no"))]
    if kind == "languages":
        return [_language(profile, item["language"], item["min_level"]) for item in wanted]
    if kind == "shift":
        out = []
        for shift in wanted:
            if shift in profile["shift_available"]:
                out.append((MET, "%s shift: available" % shift))
            elif shift in profile["shift_unavailable"]:
                out.append((NOT_MET, "%s shift: not possible" % shift))
            else:
                out.append((UNKNOWN, "%s shift: not stated" % shift))
        return out
    if kind == "driving_licence":
        have = set(profile["driving_licence"])
        if not have:
            return [(UNKNOWN, "no driving licence stated")]
        missing = sorted(set(wanted) - have)
        return [(NOT_MET, "driving licence %s missing (has %s)" % (", ".join(missing), ", ".join(sorted(have))))
                if missing else (MET, "driving licence %s" % ", ".join(sorted(wanted)))]
    if kind == "skills":
        have = set(profile["skills"])
        return [((MET if skill in have else UNKNOWN), "skill '%s': %s" % (skill, "yes" if skill in have else "not mentioned"))
                for skill in wanted]
    raise ValueError("unknown requirement type: %s" % kind)


def _salary(profile: Dict[str, Any], limit: Dict[str, Any]) -> Tuple[str, str]:
    salary = profile["salary"]
    if salary is None:
        return UNKNOWN, "no salary expectation stated"
    if salary["unit"] != limit["unit"]:
        return UNKNOWN, "salary given per %s, budget per %s" % (salary["unit"], limit["unit"])
    ok = salary["amount_min"] <= limit["amount"]
    return (MET if ok else NOT_MET), "salary from %g per %s (budget %g)" % (salary["amount_min"], salary["unit"],
                                                                            limit["amount"])


def screen(profile: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    must: List[Tuple[str, str]] = []
    for kind, wanted in job.get("must_have", {}).items():
        must += _requirement(profile, kind, wanted)
    if "max_salary" in job:
        must.append(_salary(profile, job["max_salary"]))
    nice: List[Tuple[str, str]] = []
    for kind, wanted in job.get("nice_to_have", {}).items():
        nice += _requirement(profile, kind, wanted)

    if any(status == NOT_MET for status, _ in must):
        verdict = "does not meet"
    elif any(status == UNKNOWN for status, _ in must):
        verdict = "check manually"
    else:
        verdict = "qualified"
    return {"verdict": verdict, "must_have": must, "nice_to_have": nice,
            "nice_met": sum(1 for status, _ in nice if status == MET)}


_ORDER = {"qualified": 0, "check manually": 1, "does not meet": 2}


def rank(results: Dict[str, Dict[str, Any]]) -> List[str]:
    """Qualified first, then 'check manually', then the rest; more nice-to-haves first inside each group."""
    return sorted(results, key=lambda name: (_ORDER[results[name]["verdict"]], -results[name]["nice_met"], name))
