import copy
import unittest

from cvscreen import rules, schema
from cvscreen.schema import PROFILE_SCHEMA, empty_profile, normalize, validate


def good():
    profile = empty_profile()
    profile.update(name="Ann Example", email="ann@example.com", postal_code="45127", city="Essen",
                   languages=[{"language": "German", "level": "C1"}], driving_licence=["B"],
                   forklift_licence=True, skills=["warehouse"], shift_available=["early"],
                   shift_unavailable=["night"], available_from="2026-11-01",
                   salary={"amount_min": 13.0, "amount_max": 15.0, "unit": "hour", "currency": "EUR"})
    return profile


class SchemaConsistencyTests(unittest.TestCase):
    def test_required_fields_match_the_empty_profile(self):
        self.assertEqual(set(PROFILE_SCHEMA["required"]), set(empty_profile()))
        self.assertEqual(set(PROFILE_SCHEMA["properties"]), set(empty_profile()))

    def test_every_skill_has_a_pattern_and_vice_versa(self):
        self.assertEqual(set(rules.SKILL_PATTERNS), set(schema.SKILLS))

    def test_structured_output_schema_is_closed_everywhere(self):
        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertIs(node.get("additionalProperties"), False)
                    self.assertEqual(sorted(node["required"]), sorted(node["properties"]))
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        walk(PROFILE_SCHEMA)


class ValidateTests(unittest.TestCase):
    def test_empty_and_filled_profiles_are_valid(self):
        self.assertEqual(validate(empty_profile()), [])
        self.assertEqual(validate(good()), [])

    def test_each_kind_of_violation_is_reported(self):
        cases = [
            ("name", 5, "name must be a string"),
            ("postal_code", "4512", "postal_code must be 5 digits"),
            ("available_from", "01.11.2026", "available_from must be"),
            ("forklift_licence", "yes", "forklift_licence must be"),
            ("driving_licence", ["Z"], "'Z' is not allowed"),
            ("skills", ["juggling"], "'juggling' is not allowed"),
            ("shift_available", ["dawn"], "'dawn' is not allowed"),
            ("languages", [{"language": "German"}], "exactly 'language' and 'level'"),
            ("languages", [{"language": "German", "level": "C3"}], "level 'C3' is not allowed"),
            ("salary", {"amount_min": 15, "amount_max": 13, "unit": "hour", "currency": "EUR"}, "larger than"),
            ("salary", {"amount_min": 1, "amount_max": 2, "unit": "week", "currency": "EUR"}, "unit must be"),
            ("salary", {"amount_min": 1, "amount_max": 2, "unit": "hour", "currency": "USD"}, "currency must be EUR"),
            ("salary", {"amount_min": True, "amount_max": 2, "unit": "hour", "currency": "EUR"}, "must be a number"),
        ]
        for field, value, expected in cases:
            profile = good()
            profile[field] = value
            self.assertTrue(any(expected in p for p in validate(profile)), msg="%s=%r -> %r" % (field, value, validate(profile)))

    def test_missing_and_unexpected_fields(self):
        profile = good()
        del profile["city"]
        profile["favourite_colour"] = "blue"
        problems = validate(profile)
        self.assertIn("missing field: city", problems)
        self.assertIn("unexpected field: favourite_colour", problems)

    def test_shift_cannot_be_available_and_unavailable(self):
        profile = good()
        profile["shift_unavailable"] = ["early"]
        self.assertTrue(any("both available and unavailable" in p for p in validate(profile)))

    def test_not_an_object(self):
        self.assertEqual(validate([]), ["profile is not an object"])


class NormalizeTests(unittest.TestCase):
    def test_lists_are_sorted_and_deduplicated_without_touching_the_input(self):
        profile = good()
        profile["skills"] = ["warehouse", "SAP", "warehouse"]
        profile["languages"] = [{"language": "German", "level": "C1"}, {"language": "English", "level": None}]
        original = copy.deepcopy(profile)
        result = normalize(profile)
        self.assertEqual(result["skills"], ["SAP", "warehouse"])
        self.assertEqual([item["language"] for item in result["languages"]], ["English", "German"])
        self.assertEqual(profile, original)


if __name__ == "__main__":
    unittest.main()
