import contextlib
import io
import json
import os
import tempfile
import unittest

from cvscreen import rules
from cvscreen.cli import main
from cvscreen.evaluate import FIELDS, evaluate, format_result, score_field
from cvscreen.schema import empty_profile
from cvscreen.screen import MET, NOT_MET, UNKNOWN, rank, screen

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
DEV = (os.path.join(ROOT, "sample", "documents"), os.path.join(ROOT, "sample", "gold.json"))
HELDOUT = (os.path.join(ROOT, "heldout", "documents"), os.path.join(ROOT, "heldout", "gold.json"))
JOB = os.path.join(ROOT, "sample", "job_profile.json")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class ScoreFieldTests(unittest.TestCase):
    def test_scalars(self):
        self.assertEqual(score_field("name", "Dr. Iris Fiktivova", "iris fiktivova"), 1.0)
        self.assertEqual(score_field("name", None, "Anna"), 0.0)
        self.assertEqual(score_field("city", "köln", "Köln"), 1.0)
        self.assertEqual(score_field("city", None, None), 1.0)
        self.assertEqual(score_field("forklift_licence", False, None), 0.0)
        self.assertEqual(score_field("phone", "+49301", "+49301"), 1.0)

    def test_salary(self):
        a = {"amount_min": 13.0, "amount_max": 15.0, "unit": "hour", "currency": "EUR"}
        self.assertEqual(score_field("salary", dict(a), dict(a)), 1.0)
        self.assertEqual(score_field("salary", dict(a, unit="month"), a), 0.0)
        self.assertEqual(score_field("salary", dict(a, amount_min=13.5), a), 0.0)
        self.assertEqual(score_field("salary", dict(a, amount_max=15.5), a), 0.0)
        self.assertEqual(score_field("salary", dict(a, amount_min=13.004), a), 1.0)
        self.assertEqual(score_field("salary", None, a), 0.0)
        self.assertEqual(score_field("salary", None, None), 1.0)

    def test_sets_use_f1(self):
        self.assertEqual(score_field("skills", [], []), 1.0)
        self.assertEqual(score_field("skills", ["SAP"], []), 0.0)
        self.assertEqual(score_field("skills", ["SAP", "warehouse"], ["SAP"]), 2 * 0.5 * 1.0 / 1.5)
        langs = [{"language": "German", "level": "C1"}]
        self.assertEqual(score_field("languages", langs, langs), 1.0)
        self.assertEqual(score_field("languages", [{"language": "German", "level": "B2"}], langs), 0.0)


class EvaluateTests(unittest.TestCase):
    def test_a_perfect_extractor_scores_100_percent(self):
        gold = json.loads(read(DEV[1]))
        texts = {name: read(os.path.join(DEV[0], name)) for name in gold}
        by_text = {texts[name]: gold[name] for name in gold}
        result = evaluate(lambda text: by_text[text], *DEV)
        self.assertEqual(result.overall, 1.0)
        self.assertEqual(result.perfect_documents, len(gold))
        self.assertEqual(result.mismatches, [])

    def test_a_crashing_extractor_is_reported_per_document(self):
        def boom(text):
            raise RuntimeError("no network")
        result = evaluate(boom, *DEV)
        self.assertEqual(result.overall, 0.0)
        self.assertEqual(len(result.errors), len(result.per_document))
        self.assertIn("RuntimeError: no network", format_result(result))

    def test_an_empty_extractor_is_not_scored_as_perfect(self):
        result = evaluate(lambda text: empty_profile(), *DEV)
        self.assertLess(result.overall, 0.6)
        self.assertEqual(set(result.field_scores()), set(FIELDS))


class RulesRegressionTests(unittest.TestCase):
    """Guards against regressions - they are not a quality claim, see the README for what the numbers mean."""

    def test_development_set(self):
        result = evaluate(rules.extract, *DEV)
        self.assertGreaterEqual(result.overall, 0.95)
        known = {(name, field) for name, field, _, _ in result.mismatches}
        self.assertEqual(known, {("06_felix_cv_en_hard.txt", "forklift_licence"),
                                 ("10_jonas_messy.txt", "name"), ("10_jonas_messy.txt", "postal_code"),
                                 ("10_jonas_messy.txt", "city"), ("12_jan_cv_de.txt", "shift_available")})

    def test_held_out_set_stays_honest_and_does_not_collapse(self):
        result = evaluate(rules.extract, *HELDOUT)
        self.assertGreaterEqual(result.overall, 0.70)
        self.assertLess(result.overall, 0.90)       # if this ever passes 90 %, the set no longer is held out


class ScreenTests(unittest.TestCase):
    def profile(self, **changes):
        base = empty_profile()
        base.update(changes)
        return base

    def test_each_requirement_type(self):
        job = {"must_have": {"forklift_licence": True, "languages": [{"language": "German", "min_level": "B1"}],
                             "shift": ["late"], "driving_licence": ["B"]},
               "max_salary": {"amount": 15.0, "unit": "hour"}}
        ok = self.profile(forklift_licence=True, languages=[{"language": "German", "level": "B2"}],
                          shift_available=["late"], driving_licence=["B", "BE"],
                          salary={"amount_min": 14.0, "amount_max": 14.0, "unit": "hour", "currency": "EUR"})
        outcome = screen(ok, job)
        self.assertEqual(outcome["verdict"], "qualified")
        self.assertTrue(all(status == MET for status, _ in outcome["must_have"]))

        bad = self.profile(forklift_licence=False, languages=[{"language": "German", "level": "A2"}],
                           shift_unavailable=["late"], driving_licence=["A"],
                           salary={"amount_min": 18.0, "amount_max": 18.0, "unit": "hour", "currency": "EUR"})
        outcome = screen(bad, job)
        self.assertEqual(outcome["verdict"], "does not meet")
        self.assertTrue(all(status == NOT_MET for status, _ in outcome["must_have"]))

    def test_missing_information_is_unknown_never_a_rejection(self):
        job = {"must_have": {"forklift_licence": True, "languages": [{"language": "German", "min_level": "B1"}],
                             "shift": ["late"], "driving_licence": ["B"]},
               "max_salary": {"amount": 15.0, "unit": "hour"}}
        outcome = screen(self.profile(), job)
        self.assertEqual(outcome["verdict"], "check manually")
        self.assertTrue(all(status == UNKNOWN for status, _ in outcome["must_have"]))

    def test_language_levels(self):
        job = {"must_have": {"languages": [{"language": "German", "min_level": "B1"}]}}
        def verdict(level):
            return screen(self.profile(languages=[{"language": "German", "level": level}]), job)["verdict"]
        self.assertEqual(verdict("native"), "qualified")
        self.assertEqual(verdict("C1"), "qualified")
        self.assertEqual(verdict("B1"), "qualified")
        self.assertEqual(verdict("A2"), "does not meet")
        self.assertEqual(verdict("fluent"), "check manually")       # not a CEFR level: a human decides
        self.assertEqual(verdict(None), "check manually")

    def test_a_salary_exactly_at_the_budget_is_met(self):
        job = {"must_have": {}, "max_salary": {"amount": 15.0, "unit": "hour"}}
        def verdict(amount):
            salary = {"amount_min": amount, "amount_max": amount, "unit": "hour", "currency": "EUR"}
            return screen(self.profile(salary=salary), job)["verdict"]
        self.assertEqual(verdict(15.0), "qualified")
        self.assertEqual(verdict(15.01), "does not meet")

    def test_salary_in_another_unit_is_not_compared(self):
        job = {"must_have": {}, "max_salary": {"amount": 15.0, "unit": "hour"}}
        monthly = self.profile(salary={"amount_min": 2800.0, "amount_max": 2800.0, "unit": "month", "currency": "EUR"})
        self.assertEqual(screen(monthly, job)["verdict"], "check manually")

    def test_unknown_requirement_type_is_rejected(self):
        with self.assertRaises(ValueError):
            screen(self.profile(), {"must_have": {"height": 180}})

    def test_ranking(self):
        results = {"b": {"verdict": "check manually", "nice_met": 3}, "a": {"verdict": "qualified", "nice_met": 0},
                   "c": {"verdict": "qualified", "nice_met": 2}, "d": {"verdict": "does not meet", "nice_met": 5}}
        self.assertEqual(rank(results), ["c", "a", "b", "d"])


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(args))
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def test_eval_and_min_score_exit_code(self):
        code, out, _ = run_cli("eval", "--min-score", "0.95")
        self.assertEqual(code, 0)
        self.assertIn("backend: rules", out)
        self.assertIn("overall 96.8%", out)
        code, _, _ = run_cli("eval", "--min-score", "0.99")
        self.assertEqual(code, 1)

    def test_extract_prints_a_profile(self):
        code, out, _ = run_cli("extract", os.path.join(DEV[0], "01_anna_cv_de.txt"))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["name"], "Anna Beispiel")

    def test_request_prints_the_exact_request_without_network(self):
        code, out, _ = run_cli("request", os.path.join(DEV[0], "01_anna_cv_de.txt"))
        request = json.loads(out)
        self.assertEqual(request["model"], "claude-opus-5-5")
        self.assertIn("Anna Beispiel", request["messages"][0]["content"])
        self.assertEqual(request["extra_body"], {"fallbacks": "default"})

    def test_screen_ranks_and_explains(self):
        code, out, _ = run_cli("screen", DEV[0], "--job", JOB)
        self.assertEqual(code, 0)
        lines = [l for l in out.splitlines() if l.endswith(tuple("0123456789")) and "nice-to-have" in l]
        self.assertTrue(lines[0].split()[1] == "qualified")
        self.assertIn("forklift licence: no", out)

    def test_claude_backend_without_sdk_falls_back_when_asked(self):
        from unittest import mock
        import sys
        with mock.patch.dict(sys.modules, {"anthropic": None}):
            code, out, err = run_cli("extract", os.path.join(DEV[0], "03_clara_questionnaire_de.txt"),
                                     "--backend", "claude", "--fallback", "rules")
        self.assertEqual(code, 0)
        self.assertIn("using the rules backend", err)
        self.assertEqual(json.loads(out)["city"], "Bochum")


if __name__ == "__main__":
    unittest.main()
