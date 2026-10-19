from data.pipelines.rfp_produce.fixtures import approve, seed_ticket


def test_approve_b_while_a_is_interrupted(env):
    """Revenue is paused (A); clinical (B) approves and revenue stays paused."""
    store, build, _ = env
    seed_ticket(store, "T1")
    wf = build()
    wf.start("T1")
    out = wf.submit_decision("T1", approve("clinical"))
    assert out["departments"]["clinical"]["approval_status"] == "approved"
    assert out["departments"]["revenue"]["approval_status"] == "pending"
    assert "revenue" in out["pending_approvals"]
    assert out["status"] == "waiting_for_approval"
    assert out["final_document"] is None


def test_concurrent_tickets_do_not_cross(env):
    store, build, _ = env
    seed_ticket(store, "T1")
    seed_ticket(store, "T2", "thames")
    wf = build()
    wf.start("T1")
    wf.start("T2")
    wf.submit_decision("T1", approve("revenue"))
    assert wf.status("T2")["departments"]["revenue"]["approval_status"] == "pending"
    assert wf.status("T1")["departments"]["revenue"]["approval_status"] == "approved"
