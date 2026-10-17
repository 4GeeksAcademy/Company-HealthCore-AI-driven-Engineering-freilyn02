import pytest
from pydantic import ValidationError

from data.pipelines.rfp_produce import NoPendingApproval, StaleDraftError, thread_id
from data.pipelines.rfp_produce.fixtures import approve, seed_ticket
from data.pipelines.rfp_produce.models import SectionUpdate


def test_start_opens_one_interrupt_per_department_and_sets_waiting(env):
    store, build, _ = env
    seed_ticket(store, "T1")
    wf = build()
    out = wf.start("T1")
    assert sorted(out["pending_approvals"]) == ["clinical", "compliance", "revenue"]
    assert out["status"] == "waiting_for_approval"
    assert out["final_document"] is None


def test_thread_ids_are_namespaced():
    assert thread_id("T1") == "rfp-T1"
    assert thread_id("T1", "revenue") == "rfp-T1:revenue"
    assert thread_id("T1", "revenue") != thread_id("T2", "revenue")


def test_resume_is_validated_before_entering_graph(env):
    store, build, _ = env
    seed_ticket(store, "T1")
    wf = build()
    wf.start("T1")
    with pytest.raises(ValidationError):  # wrong owner
        wf.submit_decision("T1", {"department": "revenue", "decision": "approve", "actor": "claire.whitfield"})
    with pytest.raises(ValidationError):  # request_changes without text
        wf.submit_decision("T1", {"department": "revenue", "decision": "request_changes", "actor": "tom.callahan"})
    with pytest.raises(ValidationError):  # reject without comment
        wf.submit_decision("T1", {"department": "revenue", "decision": "reject", "actor": "tom.callahan"})
    assert "revenue" in wf.status("T1")["pending_approvals"]


def test_double_resume_is_rejected(env):
    store, build, _ = env
    seed_ticket(store, "T1")
    wf = build()
    wf.start("T1")
    wf.submit_decision("T1", approve("revenue"))
    with pytest.raises(NoPendingApproval):
        wf.submit_decision("T1", approve("revenue"))


def test_stale_draft_is_refused(env):
    store, build, _ = env
    seed_ticket(store, "T1")
    wf = build()
    wf.start("T1")
    section = store.get_section("T1", "revenue")
    section.draft_content += " edited behind the approver's back"
    store.upsert_section(section)
    with pytest.raises(StaleDraftError):
        wf.submit_decision("T1", approve("revenue"))


def test_interrupt_survives_process_restart(env):
    store, build, _ = env
    seed_ticket(store, "T1")
    build().start("T1")
    wf2 = build()  # new checkpointer + graph on the same files = "new process"
    assert sorted(wf2.status("T1")["pending_approvals"]) == ["clinical", "compliance", "revenue"]
    out = wf2.submit_decision("T1", approve("revenue"))
    assert out["departments"]["revenue"]["approval_status"] == "approved"
    assert out["departments"]["revenue"]["approver"] == "tom.callahan"


def test_request_changes_regenerates_and_asks_again(env):
    store, build, _ = env
    seed_ticket(store, "T1")
    wf = build()
    wf.start("T1")
    out = wf.submit_decision(
        "T1",
        {"department": "revenue", "decision": "request_changes", "actor": "tom.callahan",
         "requested_changes": "Lower the PMPM."},
    )
    assert out["departments"]["revenue"]["revision_count"] == 1
    assert "revenue" in out["pending_approvals"]  # new interrupt for the new draft
    assert out["status"] == "waiting_for_approval"
    assert store.get_section("T1", "revenue").requested_changes == "Lower the PMPM."


def test_no_hook_awaits_part2_then_submit_revised_draft(env):
    store, build, _ = env
    seed_ticket(store, "T1")
    wf = build(hook=None)
    wf.start("T1")
    out = wf.submit_decision(
        "T1",
        {"department": "clinical", "decision": "request_changes", "actor": "marcus.reid",
         "requested_changes": "Add a third site."},
    )
    assert out["departments"]["clinical"]["approval_status"] == "changes_requested"
    assert "clinical" not in out["pending_approvals"]
    out = wf.submit_revised_draft(
        "T1", "clinical",
        SectionUpdate(draft_content="Four sites.", structured={"committed_capacity": 900}),
    )
    assert "clinical" in out["pending_approvals"]
    assert out["departments"]["clinical"]["approval_status"] == "pending"
