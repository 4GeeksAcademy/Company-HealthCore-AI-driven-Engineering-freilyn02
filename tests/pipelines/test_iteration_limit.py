from data.pipelines.rfp_produce.fixtures import approve, never_clean_hook, seed_ticket


def _request(dept, actor):
    return {"department": dept, "decision": "request_changes", "actor": actor,
            "requested_changes": "Please fix."}


def test_revision_loop_terminates_at_cap(env):
    store, build, _ = env
    seed_ticket(store, "T1")
    wf = build(max_revisions=2)
    wf.start("T1")
    for i in range(2):
        out = wf.submit_decision("T1", _request("revenue", "tom.callahan"))
        assert out["departments"]["revenue"]["revision_count"] == i + 1
        assert "revenue" in out["pending_approvals"]
    out = wf.submit_decision("T1", _request("revenue", "tom.callahan"))  # over the cap
    assert out["departments"]["revenue"]["approval_status"] == "rejected"
    assert out["blocked"] is True
    assert "revenue" not in out["pending_approvals"]
    assert out["final_document"] is None
    assert out["status"] != "done"


def test_cap_is_enforced_even_for_arbitration_loops(env):
    store, build, _ = env
    seed_ticket(store, "P", "phi")
    wf = build(hook=never_clean_hook, max_revisions=2)
    out = wf.start("P")  # PHI keeps coming back; closing is re-run per decision
    for _ in range(6):
        pending = out["pending_approvals"]
        if not pending:
            break
        d = pending[0]
        out = wf.submit_decision("P", approve(d))
    assert out["status"] != "done"
    assert out["final_document"] is None
    assert max(s.revision_count for s in store.list_sections("P")) <= 2
