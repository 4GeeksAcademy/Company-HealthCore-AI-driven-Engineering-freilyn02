"""Explicit arbitration (CONTEXT section 7) - deterministic, never an LLM.

Triggers are detected on STRUCTURED state (flags, clause ids, numbers), and every
trigger maps to a FIXED arbiter and a resolution rule written in code:

| trigger id               | fixed arbiter                                    | rule                                            |
| phi-detected             | Claire Whitfield (compliance)                    | redact + force revision, synthesizer blocked    |
| baa-dpa-mismatch         | Claire Whitfield (compliance)                    | force revision until country-correct instrument |
| capacity-vs-population   | Tom Callahan (revenue), after PHI check is clear | force revision on revenue and clinical          |

Agents may *surface* a conflict (by writing structured facts into their section); they
can never *resolve* it by free-form consensus. Compliance always wins on PHI and
regulatory triggers, so `capacity-vs-population` is deferred while PHI is active.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .models import (
    CLAUSE_BAA,
    CLAUSE_DPA_UK,
    ApprovalStatus,
    RFPMeta,
    SectionRecord,
)
from .store import TicketStore
from .trace import record

PHI_DETECTED = "phi-detected"
BAA_DPA_MISMATCH = "baa-dpa-mismatch"
CAPACITY_VS_POPULATION = "capacity-vs-population"


@dataclass(frozen=True)
class Trigger:
    id: str
    arbiter: str  # normalized id of the fixed arbiter
    arbiter_department: str
    rule: str


TRIGGERS: dict[str, Trigger] = {
    PHI_DETECTED: Trigger(
        PHI_DETECTED, "claire.whitfield", "compliance", "PHI_HARD_STOP_REDACT_AND_REVISE"
    ),
    BAA_DPA_MISMATCH: Trigger(
        BAA_DPA_MISMATCH,
        "claire.whitfield",
        "compliance",
        "COUNTRY_CORRECT_INSTRUMENT_REQUIRED",
    ),
    CAPACITY_VS_POPULATION: Trigger(
        CAPACITY_VS_POPULATION,
        "tom.callahan",
        "revenue",
        "REDUCE_POPULATION_OR_ADD_SITES",
    ),
}


# --------------------------------------------------------------------------- #
# Detection (pure functions over structured state)
# --------------------------------------------------------------------------- #


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def detect_conflicts(meta: RFPMeta, sections: list[SectionRecord]) -> list[dict[str, Any]]:
    """Return the conflicts that currently fire. `detail` never contains content."""
    by_dept = {s.department_id: s for s in sections}
    conflicts: list[dict[str, Any]] = []

    # 1) phi-detected -------------------------------------------------------- #
    phi_depts = sorted(s.department_id for s in sections if s.phi_flagged)
    if phi_depts:
        conflicts.append(
            {
                "conflict_id": PHI_DETECTED,
                "departments": phi_depts,
                "detail": "section flagged contains_phi",
            }
        )

    # 2) baa-dpa-mismatch ---------------------------------------------------- #
    required = CLAUSE_BAA if meta.client_country == "US" else CLAUSE_DPA_UK
    wrong = CLAUSE_DPA_UK if meta.client_country == "US" else CLAUSE_BAA
    compliance = by_dept.get("compliance")
    offenders: set[str] = set()
    if compliance is None or required not in compliance.effective_clauses():
        offenders.add("compliance")
    for section in sections:
        if wrong in section.effective_clauses():
            offenders.add(section.department_id)
    if offenders:
        conflicts.append(
            {
                "conflict_id": BAA_DPA_MISMATCH,
                "departments": sorted(offenders),
                "detail": f"{meta.client_country} client requires {required}; wrong instrument: {wrong}",
            }
        )

    # 3) capacity-vs-population --------------------------------------------- #
    revenue, clinical = by_dept.get("revenue"), by_dept.get("clinical")
    if revenue and clinical:
        population = _number(revenue.structured.get("covered_population"))
        capacity = _number(clinical.structured.get("committed_capacity"))
        # Missing numbers are never invented: no numbers -> no detectable conflict.
        if population is not None and capacity is not None and capacity < population:
            conflicts.append(
                {
                    "conflict_id": CAPACITY_VS_POPULATION,
                    "departments": ["clinical", "revenue"],
                    "detail": f"committed_capacity {int(capacity)} < covered_population {int(population)}",
                }
            )
    return conflicts


# --------------------------------------------------------------------------- #
# Resolution planning (deterministic rules)
# --------------------------------------------------------------------------- #


def plan_resolutions(
    conflicts: list[dict[str, Any]], sections: list[SectionRecord]
) -> dict[str, Any]:
    """Turn conflicts into resolutions + a merged list of per-department actions.

    Only sections that are PENDING or APPROVED are acted on: a section already in
    `changes_requested` (revision in flight) or terminally `rejected` is left alone, so
    a persisting conflict can never burn revision cycles twice.
    """
    by_dept = {s.department_id: s for s in sections}
    fired = {c["conflict_id"]: c for c in conflicts}
    phi_active = PHI_DETECTED in fired

    actions: dict[str, dict[str, Any]] = {}

    def add_action(dept: str, kind: str, reason: str, redact: bool = False) -> None:
        section = by_dept.get(dept)
        if section is None:
            return
        if section.approval_status in (ApprovalStatus.CHANGES_REQUESTED, ApprovalStatus.REJECTED):
            return
        current = actions.get(dept)
        if current is None:
            actions[dept] = {"department": dept, "kind": kind, "reason": reason, "redact": redact}
            return
        if kind == "request_changes":
            current["kind"] = "request_changes"
        if reason not in current["reason"]:
            current["reason"] += f" | {reason}"
        current["redact"] = current["redact"] or redact

    resolutions: list[dict[str, Any]] = []

    for conflict in conflicts:
        trigger = TRIGGERS[conflict["conflict_id"]]
        departments = conflict["departments"]
        res: dict[str, Any] = {
            "conflict_id": trigger.id,
            "departments": departments,
            "arbiter": trigger.arbiter,
            "rule": trigger.rule,
            "deferred": False,
            "resolution": "",
            "next": [],
        }

        if trigger.id == PHI_DETECTED:
            for dept in departments:
                add_action(
                    dept,
                    "request_changes",
                    "Remove every patient identifier / PHI (real or illustrative).",
                    redact=True,
                )
            compliance = by_dept.get("compliance")
            # Compliance must re-review if it had already signed off.
            if (
                compliance is not None
                and "compliance" not in departments
                and compliance.approval_status is ApprovalStatus.APPROVED
            ):
                add_action("compliance", "reopen", "Re-review after PHI hard stop.")
            res["resolution"] = (
                "Hard stop: block + redact flagged content, force request_changes, "
                "synthesizer must not run"
            )

        elif trigger.id == BAA_DPA_MISMATCH:
            for dept in departments:
                add_action(
                    dept,
                    "request_changes",
                    "Use the country-correct instrument (US: BAA; UK: DPA referencing UK GDPR).",
                )
            res["resolution"] = (
                "Force request_changes on compliance (and any section embedding the wrong "
                "clause) until country-correct"
            )

        else:  # CAPACITY_VS_POPULATION
            if phi_active:
                res["deferred"] = True
                res["resolution"] = (
                    "Deferred: Compliance must confirm no PHI issue before the capacity arbitration runs"
                )
            else:
                for dept in departments:
                    add_action(
                        dept,
                        "request_changes",
                        "Clinical capacity cannot cover the contract volume: reduce covered "
                        "population or add sites.",
                    )
                res["resolution"] = "Force revision on revenue and clinical (reduce population or add sites)"

        res["next"] = [
            f"{a['kind']}:{a['department']}"
            for a in actions.values()
            if a["department"] in departments and not res["deferred"]
        ]
        resolutions.append(res)

    return {"resolutions": resolutions, "actions": list(actions.values())}


# --------------------------------------------------------------------------- #
# Graph node
# --------------------------------------------------------------------------- #

# (ticket_id, department, action_dict) -> result string
ApplyAction = Callable[[str, str, dict[str, Any]], str]


def make_arbitration_node(store: TicketStore, apply_action: ApplyAction):
    """Dedicated arbitration node for the closing graph."""

    def arbitration(state: dict[str, Any]) -> dict[str, Any]:
        ticket_id = state["ticket_id"]
        sections = store.list_sections(ticket_id)
        plan = plan_resolutions(state.get("conflicts", []), sections)

        events: list[dict[str, Any]] = []
        results: dict[str, str] = {}
        for action in plan["actions"]:
            results[action["department"]] = apply_action(
                ticket_id, action["department"], action
            )

        for res in plan["resolutions"]:
            events += record(
                store,
                ticket_id=ticket_id,
                agent=f"arbitration:{res['arbiter']}",
                input_ref=f"conflict:{res['conflict_id']}:{','.join(res['departments'])}",
                output_ref=(
                    f"{res['rule']}:deferred"
                    if res["deferred"]
                    else f"{res['rule']}:{'|'.join(res['next']) or 'no_action'}"
                ),
            )
        return {
            "resolutions": plan["resolutions"],
            "action_results": results,
            "outcome": "arbitrated",
            "trace": events,
        }

    return arbitration


__all__ = [
    "BAA_DPA_MISMATCH",
    "CAPACITY_VS_POPULATION",
    "PHI_DETECTED",
    "TRIGGERS",
    "detect_conflicts",
    "make_arbitration_node",
    "plan_resolutions",
]
