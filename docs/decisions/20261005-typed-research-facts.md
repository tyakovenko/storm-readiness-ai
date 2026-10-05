# Research facts follow a typed contract fixed by their metric

**Status:** Accepted 2026-10-05 (Taya: "the data it passes in raw needs to adhere to the data types required for processing and computation")

## Context
Published facts feed computation: shelter demand vs beds, sums across shelters, comparisons with past storms. The first schema checked only shapes: `value` was any float, dates were free text, and an unknown metric or unit was kept with a note. Downstream code would have to guess types, or fail late.

## Decision
`research/schema.py` enforces the contract at construction. The researcher's `submit_fact` builds through the same models, so a bad field is refused right away, with the validation message returned to the model.

| Field | Rule |
|---|---|
| `metric` | must be in `policy.METRICS`, which is closed |
| `unit` | must equal the metric's unit |
| `value` | the metric's `dtype`. Counts: whole numbers stored as `int`. `usd`: `float`. Range `[min, max]` (≥ 0) |
| `value_raw` | required with a value (by reference, ADR numbers-by-reference) |
| `as_of`, `published` | `YYYY`, `YYYY-MM` or `YYYY-MM-DD`, and a real date |
| `retrieved` | ISO date/datetime |
| `source_url` | http(s) |
| `qualifier` | enum (exact, over, at_least, about, up_to, range_low, range_high) |
| Draft level | `storm_id` in the target's storms; `place` the county or a listed city |

## Rejected
- **Typed only at publish time:** the researcher would never learn why a fact failed, and drafts would carry facts that can't be used.
- **Open vocabulary with "kept, non-key":** a metric no code knows the unit or type of can't be computed with.

## Consequences
- Adding a metric means adding it to `policy.METRICS` with its unit, type and definition. That is deliberate.
- Drafts written before this ADR still validate (checked on the Harris draft); their facts have no `subject`, which the fixed checks report as not run.
