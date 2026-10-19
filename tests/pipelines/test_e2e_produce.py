from pathlib import Path

from data.pipelines.rfp_produce.fixtures import approve, seed_ticket


def test_e2e_us_meridian_with_restart_between_decisions(env):
    store, build, tmp = env
    seed_ticket(store, "T1", "meridian")
    build().start("T1")
    build().submit_decision("T1", approve("revenue"))   # process 2
    build().submit_decision("T1", approve("clinical"))  # process 3
    assert store.get_status("T1") == "waiting_for_approval"
    out = build().submit_decision("T1", approve("compliance"))  # process 4
    assert out["status"] == "done"
    doc = Path(out["final_document"])
    text = doc.read_text()
    assert "USD" in text and "BAA" in text
    for who in ("tom.callahan", "marcus.reid", "claire.whitfield"):
        assert who in text


def test_e2e_uk_uses_gbp_and_dpa(env):
    store, build, _ = env
    seed_ticket(store, "T2", "thames")
    wf = build()
    wf.start("T2")
    for d in ("compliance", "clinical", "revenue"):
        out = wf.submit_decision("T2", approve(d))
    text = Path(out["final_document"]).read_text()
    assert "GBP" in text and "UK GDPR" in text and "Business Associate" not in text


def test_reject_path_never_synthesizes(env):
    store, build, _ = env
    seed_ticket(store, "T1")
    wf = build(hook=None)
    wf.start("T1")
    wf.submit_decision("T1", approve("revenue"))
    wf.submit_decision("T1", approve("clinical"))
    out = wf.submit_decision(
        "T1", {"department": "compliance", "decision": "reject", "actor": "claire.whitfield",
               "comment": "Not acceptable."},
    )
    assert out["status"] != "done" and out["final_document"] is None
    assert store.get_final_document("T1") is None


def test_trace_is_ordered_complete_and_free_of_content(env):
    store, build, _ = env
    seed_ticket(store, "T1")
    wf = build()
    wf.start("T1")
    for d in ("revenue", "clinical", "compliance"):
        wf.submit_decision("T1", approve(d))
    events = wf.trace("T1")
    agents = [e.agent for e in events]
    assert agents.count("approval_prepare") == 3
    assert {"human:tom.callahan", "human:marcus.reid", "human:claire.whitfield"} <= set(agents)
    assert agents[-1] == "ultimate_synthesizer"
    assert [e.ts for e in events] == sorted(e.ts for e in events)
    blob = " ".join(e.input_ref + e.output_ref for e in events)
    assert "covered population" not in blob and "Pricing proposal" not in blob


def test_start_is_idempotent_and_requires_valid_status(env):
    import pytest
    store, build, _ = env
    seed_ticket(store, "T1")
    wf = build()
    wf.start("T1")
    wf.start("T1")
    assert sorted(wf.status("T1")["pending_approvals"]) == ["clinical", "compliance", "revenue"]
    assert len([e for e in wf.trace("T1") if e.agent == "approval_prepare"]) == 3
    seed_ticket(store, "T9", status="intake")
    with pytest.raises(ValueError):
        wf.start("T9")
