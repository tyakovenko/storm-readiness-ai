"""Research drafts: local store, read-only API, publish selection. No network (GCS stubbed out)."""

import json
import os

import pytest
from fastapi.testclient import TestClient

from research import publish, store
from research.schema import Check, DraftPack, Fact, FactReview, Gap, Storm, Target, Verdict

TARGET = Target(fips="48201", county="Harris County", state="TX", hazard="hurricane",
                storms=[Storm(id="AL022024", name="Beryl", year=2024)])


def fact(i: str, value: float) -> Fact:
    return Fact(id=i, metric="shelter_capacity", value=value, value_raw=f"{value:,.0f}", unit="people",
                quote=f"Shelters could hold {value:,.0f} people in Harris County.", source="s",
                source_url=f"https://x.gov/{i}", retrieved="2026-10-05")


def draft(run_id="20261005T120000Z", reviewed=True) -> DraftPack:
    facts = [fact("f1", 2000), fact("f2", 1500), fact("f3", 900), fact("f4", 700)]
    verdicts = [Verdict.VERIFIED, Verdict.SINGLE_SOURCE, Verdict.CONFLICTING, Verdict.UNSUPPORTED]
    reviews = [FactReview(fact_id=f.id, verdict=v, checks=[Check(layer="fixed", name="fetch", ok=True, detail="ok")])
               for f, v in zip(facts, verdicts)] if reviewed else []
    return DraftPack(target=TARGET, run_id=run_id, researcher_model="r", judge_model="j" if reviewed else None,
                     facts=facts, reviews=reviews, gaps=[Gap(metric="staging_sites", reason="not published")],
                     run_log={"cap_hit": False})


class _EmptyBucket:
    name = "test"

    def list_blobs(self, prefix):
        return []

    def blob(self, name):
        return type("B", (), {"exists": lambda self: False})()


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOCAL", tmp_path / "drafts")
    monkeypatch.setattr(store, "_bucket", lambda: _EmptyBucket())
    return tmp_path


def test_store_outage_is_503_not_404(local, monkeypatch):
    monkeypatch.setattr(store, "_bucket", lambda: (_ for _ in ()).throw(RuntimeError("GCS down")))
    os.environ["LLM_MODEL"] = "mock"
    from backend.app import app
    with TestClient(app) as c:
        r = c.get("/api/research/hurricane/48201/20991231T000000Z")
        assert r.status_code == 503 and "GCS down" in r.json()["detail"]
        assert c.get("/api/research").status_code == 200  # listing degrades to local drafts, logged


def test_save_list_get(local):
    store.save_local(draft())
    runs = store.list_drafts()
    assert runs[0]["run_id"] == "20261005T120000Z" and runs[0]["verdicts"]["verified"] == 1
    assert store.get_draft("hurricane", "48201", "20261005T120000Z").facts[0].id == "f1"


def test_bad_file_listed_not_hidden(local):
    p = store.LOCAL / "hurricane" / "48201" / "20261005T130000Z.json"
    p.parent.mkdir(parents=True)
    p.write_text("{not json")
    assert "error" in store.list_drafts()[0]


@pytest.mark.parametrize("args", [("hurricane", "../..", "20261005T120000Z"), ("x", "48201", "20261005T120000Z"),
                                  ("hurricane", "48201", "../../etc")])
def test_get_rejects_unsafe_paths(local, args):
    with pytest.raises(KeyError):
        store.get_draft(*args)


def test_api_routes(local):
    store.save_local(draft())
    os.environ["LLM_MODEL"] = "mock"
    from backend.app import app
    with TestClient(app) as c:
        assert c.get("/api/research").json()[0]["facts"] == 4
        d = c.get("/api/research/hurricane/48201/20261005T120000Z").json()
        assert d["reviews"][0]["verdict"] == "verified"
        assert c.get("/api/research/hurricane/48201/20991231T000000Z").status_code == 404


def test_select_accepts_by_verdict_and_overrides():
    out = publish.select(draft(), {"verified", "single_source"}, reject={"f2"}, also={"f3"})
    assert [(f["id"], f["verdict"], f["reviewer_override"]) for f in out] == [("f1", "verified", False),
                                                                             ("f3", "conflicting", True)]


@pytest.mark.parametrize("accept,also,msg", [({"conflicting"}, set(), "--accept may only"),
                                             ({"verified"}, {"f9"}, "unknown fact ids")])
def test_select_refuses(accept, also, msg):
    with pytest.raises(ValueError, match=msg):
        publish.select(draft(), accept, set(), also)


def test_select_needs_reviews():
    with pytest.raises(ValueError, match="no judge reviews"):
        publish.select(draft(reviewed=False), {"verified"}, set(), set())


def test_publish_writes_pack_with_provenance(local, monkeypatch):
    from hurricane import store as packs
    store.save_local(draft())
    packs_dir = local / "packs"
    (packs_dir / "48201").mkdir(parents=True)
    (packs_dir / "48201" / "pack.json").write_text(json.dumps({"county": "Harris County", "facts": []}))
    monkeypatch.setattr(packs, "LOCAL", packs_dir)
    packs.table.cache_clear()
    try:
        out = publish.publish("48201", "20261005T120000Z", "Taya", {"verified"}, set(), set())
        pack = json.loads((packs_dir / "48201" / "pack.json").read_text())
    finally:
        packs.table.cache_clear()
    assert out["facts"] == 1 and pack["facts"][0]["id"] == "f1"
    assert pack["research"]["reviewer"] == "Taya" and pack["research"]["gaps_reported"][0]["metric"] == "staging_sites"
