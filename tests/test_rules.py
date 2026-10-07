import unittest

from cvscreen import rules


class ContactTests(unittest.TestCase):
    def test_phone_variants_collapse_to_one_number(self):
        for text in ("Tel.: 030 23125 001", "Mobil: +49 (0) 30 23125001", "Telefon 0049 30 23125001",
                     "phone: +49 030 23125001", "ruf mich an: 030 23125 001"):
            self.assertEqual(rules._phone(text), "+493023125001", msg=text)

    def test_phone_length_limits_are_inclusive(self):
        self.assertEqual(rules._phone("Tel: +12345678"), "+12345678")                      # 8 digits
        self.assertIsNone(rules._phone("Tel: +1234567"))                                   # 7
        self.assertEqual(rules._phone("Tel: +123456789012345"), "+123456789012345")        # 15
        self.assertIsNone(rules._phone("Tel: +1234567890123456"))                          # 16

    def test_dates_and_years_are_not_phone_numbers(self):
        self.assertIsNone(rules._phone("Geboren am 05.10.1990, Lager 2019-2024, PLZ 01067 Dresden"))

    def test_postal_code_and_city(self):
        self.assertEqual(rules._residence("Musterstraße 12, 45127 Essen"), ("45127", "Essen"))
        self.assertEqual(rules._residence("Ich wohne in 47051 Duisburg."), ("47051", "Duisburg"))
        self.assertEqual(rules._residence("Wohnort: Bochum"), (None, "Bochum"))
        self.assertEqual(rules._residence("living in Duisburg (47051)"), (None, "Duisburg"))
        self.assertEqual(rules._residence("12345 Bad Salzuflen"), ("12345", "Bad Salzuflen"))

    def test_amounts_are_not_cities_and_cities_do_not_swallow_the_next_line(self):
        self.assertEqual(rules._residence("Gehalt 48000 Euro brutto"), (None, None))
        self.assertEqual(rules._residence("Place of residence: Köln\nDo you have a licence?"), (None, "Köln"))


class NameTests(unittest.TestCase):
    def test_strategies(self):
        self.assertEqual(rules._name("Name: Clara Müller\nE-Mail: x@y.de"), "Clara Müller")
        self.assertEqual(rules._name("Bewerbung von Hasan Beispielmann\nHallo"), "Hasan Beispielmann")
        self.assertEqual(rules._name("CURRICULUM VITAE - Ben Muster\n\nContact"), "Ben Muster")
        self.assertEqual(rules._name("Hallo,\nich suche Arbeit.\nViele Grüße\nDavid Demo\n"), "David Demo")
        self.assertEqual(rules._name("Lebenslauf\n\nAnna Beispiel\nMusterstraße 1"), "Anna Beispiel")
        self.assertEqual(rules._name("Dr. Iris Fiktivova\nBüroring 1"), "Dr. Iris Fiktivova")
        self.assertEqual(rules._name("Gina Probe, based in Münster."), "Gina Probe")
        self.assertEqual(rules._name("Sandra Probe-Fiktiv\nHauptstraße 1"), "Sandra Probe-Fiktiv")

    def test_no_name_rather_than_a_wrong_one(self):
        self.assertIsNone(rules._name("jonas demo 40213 düsseldorf"))
        self.assertIsNone(rules._name(""))


class LanguageTests(unittest.TestCase):
    def langs(self, text):
        return {item["language"]: item["level"] for item in rules._languages(text)}

    def test_formats(self):
        self.assertEqual(self.langs("Deutsch (Muttersprache), Englisch (B2), Ukrainisch (Muttersprache)"),
                         {"German": "native", "English": "B2", "Ukrainian": "native"})
        self.assertEqual(self.langs("English - fluent; German - B1; Turkish - native"),
                         {"English": "fluent", "German": "B1", "Turkish": "native"})
        self.assertEqual(self.langs("Deutsch spreche ich fließend, Arabisch ist meine Muttersprache."),
                         {"German": "fluent", "Arabic": "native"})
        self.assertEqual(self.langs("Muttersprache Ukrainisch, fließend Deutsch"),
                         {"Ukrainian": "native", "German": "fluent"})
        self.assertEqual(self.langs("deutsch b2 englisch a2"), {"German": "B2", "English": "A2"})

    def test_a_level_is_not_given_to_the_language_before_another_one(self):
        self.assertEqual(self.langs("Englisch und Deutsch fließend"), {"German": "fluent"})

    def test_bare_language_only_counts_in_a_language_context(self):
        self.assertEqual(self.langs("Sprachen: Deutsch, Englisch"), {"German": None, "English": None})
        self.assertEqual(self.langs("Ich arbeite bei der Deutsch-Französischen Handelskammer"), {})


class LicenceTests(unittest.TestCase):
    def test_driving_licence_formats(self):
        cases = {
            "Führerschein Klasse B": ["B"],
            "Führerscheinklassen B, BE": ["B", "BE"],
            "Driving licence: B, C1": ["B", "C1"],
            "Führerschein: ja, Klasse B": ["B"],
            "Driving licence? Yes - B": ["B"],
            "I hold a category B driving licence.": ["B"],
            "Driver's licence B.": ["B"],
            "führerschein b deutsch b2": ["B"],
            "Führerschein: keiner.": [],
            "Führerschein vorhanden": [],
            "kein Interesse": [],
        }
        for text, expected in cases.items():
            self.assertEqual(rules._driving(text), expected, msg=text)

    def test_forklift_is_three_valued(self):
        cases = [
            ("Staplerschein (Flurförderzeuge) seit 2023", True),
            ("Gabelstapler (Schein vorhanden)", True),
            ("Forklift licence (counterbalance trucks, valid)", True),
            ("stapler schein ja", True),
            ("Staplerschein: nein", False),
            ("Ich habe leider kein Staplerschein.", False),
            ("No forklift licence yet", False),
            ("Do you have a forklift licence? No", False),
            ("Ich möchte den Staplerschein noch machen.", False),
            ("I want to get a forklift licence.", False),
            ("Lagerhelferin mit Erfahrung", None),
            ("I am certified to operate counterbalance trucks.", None),     # known miss: paraphrase
        ]
        for text, expected in cases:
            self.assertEqual(rules._forklift(text), expected, msg=text)

    def test_a_claim_wins_over_a_plan_elsewhere(self):
        self.assertTrue(rules._forklift("Staplerschein vorhanden. Ich möchte später den Kranschein machen."))


class ShiftTests(unittest.TestCase):
    def shifts(self, text):
        return rules._shifts(text)

    def test_german(self):
        self.assertEqual(self.shifts("Früh- und Spätschicht, auch am Wochenende. Keine Nachtschicht."),
                         (["early", "late", "weekend"], ["night"]))
        self.assertEqual(self.shifts("Keine Nachtschicht, keine Wochenenden möglich. Sonntag nicht möglich."),
                         ([], ["night", "weekend"]))
        self.assertEqual(self.shifts("Ich kann jede Schicht arbeiten."), (["early", "late", "night"], []))
        self.assertEqual(self.shifts("nur Frühschicht"), (["early"], []))

    def test_english(self):
        self.assertEqual(self.shifts("I can work early and late shifts, no weekends."),
                         (["early", "late"], ["weekend"]))
        self.assertEqual(self.shifts("Sunday shifts not possible."), ([], ["weekend"]))
        self.assertEqual(self.shifts("Available for night shifts and weekends."), (["night", "weekend"], []))

    def test_negation_applies_to_its_own_clause_only(self):
        self.assertEqual(self.shifts("I am happy to work late shifts and at the weekend, but I cannot do nights."),
                         (["late", "weekend"], ["night"]))

    def test_words_that_only_look_like_shifts(self):
        self.assertEqual(self.shifts("Frühere Tätigkeit: Lager. Late payment was never a problem."), ([], []))

    def test_a_shift_that_is_both_offered_and_excluded_counts_as_excluded(self):
        self.assertEqual(self.shifts("Nachtschicht ok. Keine Nachtschicht."), ([], ["night"]))

    def test_known_limits(self):
        # experience in all shifts is read as availability; a negation in a preceding question is not seen
        self.assertEqual(self.shifts("Bisher in Schichtarbeit (Früh-, Spät- und Nachtschicht).")[0],
                         ["early", "late", "night"])
        self.assertEqual(self.shifts("Which shifts can you NOT work? Night shifts")[0], ["night"])


class SalaryTests(unittest.TestCase):
    def salary(self, text):
        found = rules._salary(text)
        return None if found is None else (found["amount_min"], found["amount_max"], found["unit"])

    def test_formats_and_units(self):
        cases = {
            "Gehaltsvorstellung: 2.800 € brutto pro Monat.": (2800, 2800, "month"),
            "Gehaltsvorstellung 3.100 EUR brutto.": (3100, 3100, "month"),
            "Gehaltsvorstellung: 13,50 € / Std.": (13.5, 13.5, "hour"),
            "Expected salary: EUR 14.50 per hour.": (14.5, 14.5, "hour"),
            "Salary expectation: 12.90 EUR/hour.": (12.9, 12.9, "hour"),
            "Salary expectation: EUR 2,650 gross per month.": (2650, 2650, "month"),
            "Jahresgehalt: 48.000 € brutto": (48000, 48000, "year"),
            "Mein Wunschlohn ist 15 Euro die Stunde.": (15, 15, "hour"),
            "lohn 14 euro stunde": (14, 14, "hour"),
            "Gehaltsvorstellung: 13–15 € pro Stunde.": (13, 15, "hour"),
            "Salary expectation: between 13 and 15 EUR per hour.": (13, 15, "hour"),
            "Salary expectation: 45000 EUR": (45000, 45000, "year"),
        }
        for text, expected in cases.items():
            self.assertEqual(self.salary(text), expected, msg=text)

    def test_unit_guess_boundaries_when_no_unit_is_given(self):
        self.assertEqual(self.salary("Salary expectation: 99.99 EUR"), (99.99, 99.99, "hour"))
        self.assertEqual(self.salary("Salary expectation: 100 EUR"), (100, 100, "month"))
        self.assertEqual(self.salary("Salary expectation: 15000 EUR"), (15000, 15000, "month"))
        self.assertEqual(self.salary("Salary expectation: 15001 EUR"), (15001, 15001, "year"))

    def test_no_figure_or_no_currency_means_no_salary(self):
        self.assertIsNone(self.salary("Gehaltsvorstellung: leicht über Mindestlohn"))
        self.assertIsNone(self.salary("Gehaltsvorstellung: ab 2026 verfügbar"))
        self.assertIsNone(self.salary("Ich bin 29 Jahre alt."))

    def test_amount_parser(self):
        for raw, expected in (("2.800", 2800), ("2,650", 2650), ("13,50", 13.5), ("12.90", 12.9),
                              ("1.234,56", 1234.56), ("1,234.56", 1234.56), ("14", 14)):
            self.assertEqual(rules._amount(raw), expected, msg=raw)


class AvailabilityTests(unittest.TestCase):
    def test_cases(self):
        cases = {
            "Verfügbar ab sofort.": "immediately",
            "Available immediately": "immediately",
            "Verfügbar ab: 15.11.2026": "2026-11-15",
            "Verfügbar ab dem 01.01.2027.": "2027-01-01",
            "available from 01.11.2026": "2026-11-01",
            "Verfügbar ab 1. November 2026": "2026-11-01",
            "available from 5 January 2027": "2027-01-05",
            "Verfügbar ab 01.12.26": "2026-12-01",
            "I could start in January 2027.": None,
            "Verfügbar ab 31.13.2026": None,
        }
        for text, expected in cases.items():
            self.assertEqual(rules._available_from(text), expected, msg=text)

    def test_a_date_wins_over_a_vague_phrase(self):
        self.assertEqual(rules._available_from("Verfügbar ab sofort, spätestens verfügbar ab 01.02.2027"), "2027-02-01")


class ExtractTests(unittest.TestCase):
    def test_always_returns_a_valid_profile(self):
        from cvscreen.schema import validate
        for text in ("", "   ", "Ö" * 1000, "Name:\n\n\n", "12345 67890 0 0 0"):
            self.assertEqual(validate(rules.extract(text)), [], msg=repr(text[:20]))

    def test_empty_document_gives_an_empty_profile(self):
        from cvscreen.schema import empty_profile
        self.assertEqual(rules.extract(""), empty_profile())


if __name__ == "__main__":
    unittest.main()
