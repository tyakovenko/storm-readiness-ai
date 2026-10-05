# Research numbers are parsed by code and cited by reference; the LLM never writes a value

**Status:** Accepted 2026-10-05 (Taya's proposal)

## Context
LLMs handle numbers as text. They miscopy them (1,314 → 1,341), round them ("about 1,300"), drop the scale ("2.26 million" → 2.26) or split them ("1,314" → 1 and 314). They also treat labels as data: in the chat trust layer, "FOX 4", "District 14" and a `threshold_10000` key name were all taken for figures. Layer 1 of the judge (`research/verify.py`) catches a wrong value after the fact. It's better if a wrong value can't be written in the first place.

## Decision
Every fetched page goes through a deterministic number pass (`research/numbers.py`) before any LLM sees it:
- **Spans:** each number becomes `NumberSpan{id, start, end, raw, value, kind, qualifier, scale, range_of}` with offsets into the page text.
- **`kind`:** quantity | money | percent | year | date | time | phone | ordinal | label. Only quantity, money and percent can be used as a fact value. Labels are numbers after words like District, Category, FOX, Route, Zone, Page or Table.
- **`qualifier`:** read from the words before the number ("more than" → over, "at least"/"+" → at_least, "about"/"nearly" → about, "up to" → up_to). Ranges become two linked spans.
- **Scale is applied by code:** 2.26 million → 2,260,000; "twelve" → 12.
- **Researcher input:** the page text with each usable number tagged `⟦N17⟧1,314`.
- **Researcher output:** `value_ref` instead of a value. Code builds the Fact. `value`, `value_raw` and `qualifier` come from the span; `quote` is the sentence(s) that contain it. A value typed by the researcher with no `value_ref` is rejected and counted in the run log.
- **Judge layer 1:** parses its own fetch of the page, finds the quote, and checks there is a usable span inside it with the same value and qualifier. Offsets are never reused between fetches, because pages change.
- **Derived values** (sums, differences) are **out of scope**: a total must be stated in a source. If needed later: `derived: {op, refs}`, computed by code.

## Rejected
- **LLM extracts values, then a check compares them with the page** (the original layer-1 design): catches the error afterwards and costs a review cycle, and the LLM still had to copy the number exactly.
- **Regex over the LLM's quote only** (`trust._numbers_in_text`): no offsets, no kinds, so "FOX 26" counts as evidence for 26.
- **Asking the LLM to label each number's kind:** that is the same trap again.

## Consequences
- Remaining LLM risk is **binding**: picking the wrong number for a metric, e.g. capacity vs occupancy. Judge layer 2 (entailment) checks this with the tagged sentence.
- **PDF tables:** pypdf text loses columns, so a number's row and column headers may not sit in its sentence. Binding is weaker there. Table extraction (pdfplumber) is a future improvement; until then layer 2 sees the raw line.
- Classifying kinds is rule-based and will misfile some numbers. Mistakes in one direction only cost a missed fact (a count filed as a year, or as a label). Mistakes in the other direction (a label filed as a quantity) are caught by layer 2. Both kinds go into the planted-error eval.
