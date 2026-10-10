"""Live pass-rate eval: row building and summary, on a faked agent turn (no model, no data)."""

from agent import registry
from evals import live_pass_rate as lpr


def _check(name, passed, blocking=True, detail=""):
    return {"name": name, "passed": passed, "blocking": blocking, "detail": detail}


def _turn(status):
    bad = [_check("numbers_match_tools", False, detail="Numbers not found in any tool output: 14"),
           _check("required_steps", True)]
    good = [_check("numbers_match_tools", True), _check("required_steps", True)]
    attempts = {"passed": [good], "regenerated": [bad, good], "blocked": [bad, bad]}[status]
    final = attempts[-1] + [_check("actionable", status != "blocked" or None, blocking=False)]
    return {"status": status, "answer": None if status == "blocked" else "ok",
            "attempts": [{"text": f"draft {i}", "checks": c} for i, c in enumerate(attempts)],
            "checks": final, "tool_calls": [{"name": "get_storm_alert", "arguments": {}}]}


def test_run_one_records_first_draft_failures(monkeypatch):
    monkeypatch.setattr(registry, "chat", lambda agent_id, q, history, judge: _turn("regenerated"))
    row = lpr.run_one("dallas-winter", "Where should trucks go?", None)
    assert row["status"] == "regenerated"
    assert row["first_draft_failed"] == ["numbers_match_tools"]
    assert row["final_failed"] == []
    assert row["actionable"] is True
    assert row["tool_calls"] == ["get_storm_alert"]
    assert row["blocked_draft"] is None


def test_blocked_row_keeps_the_draft(monkeypatch):
    monkeypatch.setattr(registry, "chat", lambda *a: _turn("blocked"))
    row = lpr.run_one("dallas-winter", "q", None)
    assert row["final_failed"] == ["numbers_match_tools"]
    assert row["actionable"] is None  # blocked answers aren't graded
    assert row["blocked_draft"] == "draft 1"


def test_summary_counts_and_rates(monkeypatch):
    rows = []
    for status in ("passed", "passed", "regenerated", "blocked"):
        monkeypatch.setattr(registry, "chat", lambda *a, s=status: _turn(s))
        rows.append(lpr.run_one("dallas-winter", status, None))
    rows.append({"question": "x", "error": "ClientError: 429 RESOURCE_EXHAUSTED"})
    s = lpr.summarize(rows)
    assert (s["questions"], s["errors"]) == (4, 1)
    assert (s["passed"], s["regenerated"], s["blocked"]) == (2, 1, 1)
    assert s["first_try_pass_pct"] == 50.0
    assert s["shown_pct"] == 75.0
    assert s["first_draft_failures"] == {"numbers_match_tools": 2}
    assert s["actionable_pct"] == 100.0
    md = lpr.to_markdown({"agent": "dallas-winter", "model": "m", "judge": None, "started": "t"}, s, rows)
    assert "| 4 | 2 (50.0%) | 1 | 1 | 75.0% |" in md
    assert "error: ClientError" in md


def test_rate_limited_row():
    assert lpr.is_rate_limited_row({"error": "ClientError: 429 RESOURCE_EXHAUSTED"})
    assert not lpr.is_rate_limited_row({"error": "KeyError: x"})
    assert not lpr.is_rate_limited_row({"status": "passed"})


def test_question_sets_cover_both_templates():
    assert len(lpr.QUESTIONS["winter"]) >= 15 and len(lpr.QUESTIONS["hurricane"]) >= 10
    assert not any("trust demo" in c["q"].lower() for cs in lpr.QUESTIONS.values() for c in cs)
    for kind in ("winter", "hurricane"):
        cats = {c["cat"] for c in lpr.QUESTIONS[kind]}
        assert {"out_of_scope", "false_premise", "false_certainty", "unknown_entity", "follow_up"} <= cats
        # every adversarial case says what right looks like, or nothing grades it
        assert all(c.get("expect") for c in lpr.QUESTIONS[kind] if c["cat"] not in
                   {"core", "what_if", "history", "estimate"})
    assert "near_miss" in {c["cat"] for c in lpr.QUESTIONS["hurricane"]}


def test_cases_fill_in_the_county():
    cases = lpr.cases_for("hurricane", "Harris County")
    assert not any("{county}" in c["q"] or "{county}" in c.get("expect", "") for c in cases)
    assert any("Harris County" in c["q"] for c in cases)


class _Grader:
    model = "fake"

    def __init__(self, met):
        self.met, self.calls = met, []

    def grade(self, question, answer, expect):
        self.calls.append((question, answer, expect))
        return {"met": self.met, "reason": "because"}


def test_follow_up_sends_earlier_turns_as_history(monkeypatch):
    seen = []

    def chat(agent_id, q, history, judge):
        seen.append((q, history))
        return _turn("passed")

    monkeypatch.setattr(registry, "chat", chat)
    case = {"cat": "follow_up", "turns": ["first?"], "q": "second?", "expect": "uses the first answer"}
    grader = _Grader(False)
    row = lpr.run_one("dallas-winter", case, None, grader)
    assert seen == [("first?", []), ("second?", [{"role": "user", "content": "first?"},
                                                 {"role": "assistant", "content": "ok"}])]
    assert (row["category"], row["behavior_met"], row["behavior_reason"]) == ("follow_up", False, "because")
    assert grader.calls == [("second?", "ok", "uses the first answer")]


def test_blocked_or_unexpected_cases_are_not_graded(monkeypatch):
    grader = _Grader(True)
    monkeypatch.setattr(registry, "chat", lambda *a: _turn("blocked"))
    assert lpr.run_one("dallas-winter", {"cat": "false_premise", "q": "q", "expect": "e"}, None, grader)["behavior_met"] is None
    monkeypatch.setattr(registry, "chat", lambda *a: _turn("passed"))
    assert lpr.run_one("dallas-winter", {"cat": "core", "q": "q"}, None, grader)["behavior_met"] is None
    assert grader.calls == []


def test_summary_by_category(monkeypatch):
    monkeypatch.setattr(registry, "chat", lambda *a: _turn("passed"))
    rows = [lpr.run_one("dallas-winter", {"cat": "false_premise", "q": "a", "expect": "e"}, None, _Grader(m))
            for m in (True, False)]
    rows.append(lpr.run_one("dallas-winter", {"cat": "core", "q": "b"}, None, None))
    s = lpr.summarize(rows)
    assert s["by_category"]["false_premise"]["behavior_met_pct"] == 50.0
    assert s["by_category"]["core"]["behavior_graded"] == 0
    assert (s["behavior_graded"], s["behavior_met_pct"]) == (2, 50.0)
    md = lpr.to_markdown({"agent": "x", "model": "m", "judge": None, "started": "t"}, s, rows)
    assert "**missed**: because" in md and "| false_premise | 2 |" in md
