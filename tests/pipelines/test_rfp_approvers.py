import pytest

from data.pipelines.rfp_produce.approvers import (
    actor_for_user,
    department_for_actor,
    parse_approvers,
)

RAW = "tom.callahan=Tom@HealthCore.test, marcus.reid=marcus@healthcore.test ,claire.whitfield=claire@healthcore.test"


def test_parse_is_case_insensitive_and_trims():
    mapping = parse_approvers(RAW)
    assert mapping["tom@healthcore.test"] == "tom.callahan"
    assert len(mapping) == 3


def test_user_without_mapping_has_no_identity():
    mapping = parse_approvers(RAW)
    assert actor_for_user({"email": "other@healthcore.test"}, mapping) is None
    assert actor_for_user({"email": None}, mapping) is None
    assert actor_for_user({"email": "TOM@healthcore.test"}, mapping) == "tom.callahan"
    assert actor_for_user({"email": "tom@healthcore.test"}, {}) is None  # fails closed


def test_unknown_actor_or_bad_entry_is_loud():
    with pytest.raises(ValueError, match="unknown approver"):
        parse_approvers("bob.smith=bob@x.test")
    with pytest.raises(ValueError, match="invalid entry"):
        parse_approvers("tom.callahan")


def test_department_for_actor():
    assert department_for_actor("claire.whitfield") == "compliance"
    assert department_for_actor("marcus.reid") == "clinical"
    assert department_for_actor(None) is None
