"""Draft-pack schema for the research layer.

The researcher writes a DraftPack; the judge adds one FactReview per fact; a human approves before
anything is published to processed/packs/. Facts carry the exact quote and URL so every check can be
rerun from the source, not from the researcher's memory of it.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, model_validator

from research import policy

_PARTIAL_DATE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")


def _partial_date(v: str | None) -> str | None:
    """YYYY, YYYY-MM or YYYY-MM-DD, and a real date. Sources often give only a year or month."""
    if v is None:
        return None
    m = _PARTIAL_DATE.match(v.strip())
    if not m:
        raise ValueError(f"date {v!r} must be YYYY, YYYY-MM or YYYY-MM-DD")
    y, mo, d = int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1)
    date(y, mo, d)  # raises on 2024-02-30
    if not 1900 <= y <= 2100:
        raise ValueError(f"date {v!r} out of range")
    return v.strip()


def _iso_timestamp(v: str) -> str:
    try:
        datetime.fromisoformat(v)
    except ValueError:
        raise ValueError(f"retrieved {v!r} must be an ISO date or datetime") from None
    return v


def _http_url(v: str) -> str:
    if not re.match(r"^https?://[^\s/]+", v):
        raise ValueError(f"source_url {v!r} must be an http(s) URL")
    return v


def _known_metric(v: str) -> str:
    if v not in policy.METRICS:
        raise ValueError(f"metric {v!r} is not in the vocabulary: {', '.join(policy.METRICS)}")
    return v


PartialDate = Annotated[str | None, AfterValidator(_partial_date)]
Timestamp = Annotated[str, AfterValidator(_iso_timestamp)]
HttpUrl = Annotated[str, AfterValidator(_http_url)]
MetricName = Annotated[str, AfterValidator(_known_metric)]


class Verdict(str, Enum):
    # Order = how much a reviewer can trust it. Only VERIFIED needs no human reading of the source.
    VERIFIED = "verified"            # 2+ independent sources support the value
    SINGLE_SOURCE = "single_source"  # one source supports it, no conflict found
    CONFLICTING = "conflicting"      # sources disagree on the value
    UNSUPPORTED = "unsupported"      # the cited source does not say this
    UNCHECKED = "unchecked"          # a check could not run (fetch failed, PDF, timeout): never silently passed


class Storm(BaseModel):
    id: str
    name: str
    year: int


class Target(BaseModel):
    """What to research: one county x hazard. Aliases and cities widen the jurisdiction check
    (a City of Houston memo is about Harris County)."""
    fips: str = Field(pattern=r"^\d{5}$")
    county: str
    state: str = Field(pattern=r"^[A-Z]{2}$")
    hazard: Literal["hurricane", "winter"]
    aliases: list[str] = []
    cities: list[str] = []
    storms: list[Storm] = []

    def jurisdiction_names(self) -> list[str]:
        base = self.county.removesuffix(" County")
        return [self.county, base, *self.aliases, *self.cities]


Qualifier = Literal["exact", "over", "at_least", "about", "up_to", "range_low", "range_high"]


class FactDraft(BaseModel):
    """What the researcher returns. It cites a number by its span id on the tagged page (value_ref) and
    never writes the value: research.numbers.fact_from_ref builds the Fact (ADR numbers-by-reference)."""
    id: str
    metric: MetricName
    unit: str
    value_ref: str | None = None  # None = the fact states something exists, with no number
    quote: str | None = None      # only for value_ref None; otherwise code takes the sentence around the span
    storm_id: str | None = None
    place: str | None = None      # the county (default) or a city in it, when the figure is the city's
    subject: str                  # whose figure, as named in the source ("Harris County OHSEM", "CenterPoint Energy")
    as_of: PartialDate = None     # date the figure refers to, not the publication date
    source: str                   # title
    source_url: HttpUrl
    publisher: str | None = None
    published: PartialDate = None
    retrieved: Timestamp


class Fact(BaseModel):
    id: str
    metric: MetricName
    # int for count metrics, float for money: the metric's dtype (policy), enforced below.
    value: int | float | None  # None = the source states the thing exists but gives no number
    value_raw: str | None = None  # the number as written on the page ("1.3 million")
    unit: str
    # How the source phrased the number, read by code: "over 200" -> value 200, qualifier "over".
    qualifier: Qualifier = "exact"
    storm_id: str | None = None
    # Whose figure it is: None = the county. A city figure (Houston's shelters) is a fact about the city;
    # stating it as the county's is the scope error the judge rejects.
    place: str | None = None
    # Whose number: "CenterPoint Energy" workers are not county staff. "" = not named (drafts before
    # 2026-10-05 didn't record it); the fixed check reports that rather than passing it.
    subject: str = ""
    as_of: PartialDate = None
    quote: str = Field(min_length=1)
    source: str
    source_url: HttpUrl
    publisher: str | None = None
    published: PartialDate = None
    retrieved: Timestamp

    @model_validator(mode="after")
    def _typed(self):
        """The contract downstream computation relies on: unit and type fixed by the metric."""
        m = policy.metric(self.metric)
        if self.unit != m.unit:
            raise ValueError(f"{self.id}: metric {self.metric} is counted in {m.unit}, not {self.unit}")
        if self.value is None:
            return self
        if not self.value_raw:
            raise ValueError(f"{self.id}: a value needs value_raw (values come from the page, not the model)")
        if m.dtype == "int":
            if float(self.value) != int(self.value):
                raise ValueError(f"{self.id}: {self.metric} is a whole-number count; got {self.value_raw!r}")
            self.value = int(self.value)
        else:
            self.value = float(self.value)
        if self.value < m.min or (m.max is not None and self.value > m.max):
            raise ValueError(f"{self.id}: {self.value} outside {self.metric} range [{m.min}, {m.max}]")
        return self


class Gap(BaseModel):
    metric: str
    reason: str


class Page(BaseModel):
    """A fetched source. `error` set = nothing could be checked against it."""
    url: str
    final_url: str | None = None
    content_type: str | None = None
    text: str = ""
    retrieved: str | None = None
    error: str | None = None


class Check(BaseModel):
    layer: Literal["fixed", "entailment", "corroboration"]
    name: str
    ok: bool | None  # None = not run / not applicable; reported, never counted as a pass
    detail: str
    # "flag" = shown to the reviewer but doesn't change the verdict (e.g. stale): the number may be
    # right for its date; whether it still holds is the reviewer's call.
    severity: Literal["block", "flag"] = "block"


class FactReview(BaseModel):
    fact_id: str
    verdict: Verdict
    checks: list[Check] = []
    corroborating_urls: list[str] = []
    notes: str = ""
    reviewer_decision: Literal["accept", "reject", "edit"] | None = None


class DraftPack(BaseModel):
    target: Target
    run_id: str
    status: Literal["draft"] = "draft"  # publishing is a separate, human step
    built_utc: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    researcher_model: str
    judge_model: str | None = None
    facts: list[Fact] = []
    gaps: list[Gap] = []
    reviews: list[FactReview] = []
    run_log: dict = {}  # model/tool call counts, rejected submissions with reasons, fetch errors, caps hit

    @model_validator(mode="after")
    def _ids(self):
        ids = [f.id for f in self.facts]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate fact ids")
        unknown = {r.fact_id for r in self.reviews} - set(ids)
        if unknown:
            raise ValueError(f"reviews for unknown facts: {sorted(unknown)}")
        storms = {s.id for s in self.target.storms}
        places = {p.casefold() for p in self.target.jurisdiction_names()}
        for f in self.facts:
            if f.storm_id is not None and f.storm_id not in storms:
                raise ValueError(f"{f.id}: storm_id {f.storm_id} is not one of {self.target.county}'s storms")
            if f.place is not None and f.place.casefold() not in places:
                raise ValueError(f"{f.id}: place {f.place} is not {self.target.county} or a listed city")
        return self
