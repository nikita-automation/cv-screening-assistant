# Evaluation

## Method

- **Gold labels** are written by hand from the documents, *before* looking at any extractor output
  (`data/sample/gold.json`, `data/heldout/gold.json`).
- **Scoring** per field and document: exact match for scalars (names are compared without titles and case, cities
  and e-mail case-insensitively, salary exactly in all four parts); **F1 over the item set** for list fields
  (`languages` compares `(language, level)` pairs; two empty lists score 1.0). The overall score is the mean over
  all fields and documents.
- **Two sets.**
  - `data/sample` (12 documents): the development set. The rules backend was written while reading these, so its
    score here is optimistic by construction.
  - `data/heldout` (4 documents): written after the rules were frozen, then run **once untuned**. Result: 73.1 %.
    The one regex bug it exposed (a city pattern that swallowed the next line) was fixed afterwards → 75.0 %.
    After that, the set is no longer untouched. (A second bug, a language matcher that skipped a language
    following another one, was found by a unit test and did not change this score.)

## Reading the held-out failures

| Document | Field | What happened | Class |
|---|---|---|---|
| h1 | `name` | `Steckbrief Bewerber` (the title) taken for the name; the real name sits in `Vorname:`/`Nachname:` | layout |
| h1 | `salary` | `Gehalt:` is not among the salary cues | vocabulary |
| h1 | `available_from` | `Eintritt: zum 01.02.2027` is not among the date cues | vocabulary |
| h1 | `languages` | `Muttersprache: Türkisch` (level *before* the language, with a colon) | layout |
| h2 | `postal_code` | `living in Duisburg (47051)` — code after the city | layout |
| h2 | `salary` | `Looking for 2,400 EUR/month` — no cue word | vocabulary |
| h2 | `languages` | Hindi is not in the language list | vocabulary |
| h2 | `driving_licence` | `car licence (class B)` | vocabulary |
| h2 | `skills`, `shift_available` | `picker`, `mornings and evenings` | vocabulary |
| h3 | `available_from` | `Start: ab 01.12.2026 möglich` | vocabulary |
| h3 | `driving_licence` | `Führerschein der Klasse B` — an article between cue and class | layout |
| h3 | `shift_available` | `Wochenenddienste` not matched by the weekend pattern | vocabulary |
| h4 | `name` | questionnaire title `APPLICANT QUESTIONNAIRE` taken for the name | layout |
| h4 | `available_from` | `Earliest start: immediately` | vocabulary |
| h4 | `shift_available`/`_unavailable` | `Which shifts can you NOT work? Night shifts` → night *available* | **semantic, high stakes** |

Most errors are vocabulary and layout — fixable by adding patterns, and each fix would raise the dev-set score
while telling you less and less. The semantic one is not fixable that way: the negation is in a different
sentence than the thing it negates. That is the case for a model-based backend, and the case for keeping
`unknown` ≠ `no` in the screening step.

## Running the same evaluation for the model

```bash
pip install anthropic                         # Python >= 3.10, credentials in the environment
export PYTHONPATH=src
python -m cvscreen eval --backend claude
python -m cvscreen eval --backend claude --docs data/heldout/documents --gold data/heldout/gold.json
```

This sends 12 + 4 short documents to the API and costs money; it is not part of CI. Failed extractions (refusal,
invalid JSON, schema violation) are reported per document and scored as zero, so they cannot hide in an average.
When comparing backends, compare field by field — an overall number can hide that one backend is fine on
addresses and bad on shift availability.

## What a better evaluation would add

- Many more documents, from real distributions (with consent / anonymised), not hand-written ones.
- A second labeller and an agreement score — some labels here are judgement calls (e.g. `nach Absprache`).
- Separate cost/benefit view: score per field against price and latency per document.
