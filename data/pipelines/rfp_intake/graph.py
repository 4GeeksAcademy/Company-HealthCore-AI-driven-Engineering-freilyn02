"""Dedicated `rfp_intake` LangGraph (NOT attached to the CX / knowledge graph).

    convert -> phi guard -> metrics -> classify --(not RFP)--> END
                                          \\--(RFP)--> extract -> orchestrate
                                                   --> worker x N (parallel) --> synthesize --> END

The graph has no database access: persistence is done by service.py, so the
graph stays easy to test and the routers never own it.
The PHI guard runs right after conversion: no agent ever reads unredacted text.
"""
import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .agents.classifier import classify_rfp
from .agents.extractor import extract_rfp_metadata
from .agents.orchestrator import plan_workstreams
from .agents.synthesizer import synthesize
from .agents.workers import failed_result, run_worker
from .convert import pdf_to_markdown, write_markdown
from .metrics import basic_metadata, readability_scores
from .phi import scan_and_redact


class IntakeState(TypedDict, total=False):
    pdf_path: str
    markdown: str  # raw right after convert_node, REDACTED from phi_node on
    markdown_path: str
    phi: dict[str, Any]  # {"contains_phi": bool, "findings": {type: count}}
    metadata: dict[str, Any]  # document stats
    readability: dict[str, Any]
    classification: dict[str, Any]
    rfp_fields: dict[str, Any]  # client_name, client_country, program_type, ...
    workstreams: list[dict[str, Any]]
    unknown_departments: list[str]
    # Parallel workers append here; the reducer merges their outputs.
    worker_results: Annotated[list[dict[str, Any]], operator.add]
    synthesis: dict[str, Any]


def convert_node(state: IntakeState) -> dict:
    return {"markdown": pdf_to_markdown(state["pdf_path"])}


def phi_node(state: IntakeState) -> dict:
    redacted, phi = scan_and_redact(state["markdown"])
    md_path = write_markdown(state["pdf_path"], redacted)  # only redacted text is saved
    return {"markdown": redacted, "markdown_path": str(md_path), "phi": phi}


def metrics_node(state: IntakeState) -> dict:
    return {
        "metadata": basic_metadata(state["markdown"]),
        "readability": readability_scores(state["markdown"]),
    }


def classify_node(state: IntakeState) -> dict:
    return {"classification": classify_rfp(state["markdown"]).model_dump()}


def after_classify(state: IntakeState) -> str:
    return "extract" if state["classification"]["is_rfp"] else END


def extract_node(state: IntakeState) -> dict:
    return {"rfp_fields": extract_rfp_metadata(state["markdown"])}


def orchestrate_node(state: IntakeState) -> dict:
    workstreams, unknown = plan_workstreams(state["markdown"], state["metadata"])
    return {"workstreams": workstreams, "unknown_departments": unknown}


def fan_out(state: IntakeState):
    workstreams = state.get("workstreams") or []
    if not workstreams:
        return "synthesize"
    worker_metadata = {**state["metadata"], **(state.get("rfp_fields") or {})}
    return [
        Send(
            "worker",
            {
                "department": w["department"],
                "context": w["prompt_context"],
                "metadata": worker_metadata,
                "phi": state.get("phi"),
            },
        )
        for w in workstreams
    ]


def worker_node(payload: dict) -> dict:
    """One failing worker must not kill the whole ticket: partial failure is recorded."""
    try:
        result = run_worker(
            payload["department"], payload["metadata"], payload["context"], phi=payload.get("phi")
        )
    except Exception as exc:
        result = failed_result(payload["department"], type(exc).__name__, payload["metadata"], payload.get("phi"))
    return {"worker_results": [result]}


def synthesize_node(state: IntakeState) -> dict:
    return {
        "synthesis": synthesize(
            state["metadata"],
            state.get("readability") or {},
            state.get("worker_results") or [],
            state.get("unknown_departments") or [],
            phi=state.get("phi"),
            rfp_fields=state.get("rfp_fields"),
        )
    }


def build_graph():
    graph = StateGraph(IntakeState)
    graph.add_node("convert", convert_node)
    graph.add_node("phi_guard", phi_node)
    graph.add_node("metrics", metrics_node)
    graph.add_node("classify", classify_node)
    graph.add_node("extract", extract_node)
    graph.add_node("orchestrate", orchestrate_node)
    graph.add_node("worker", worker_node)
    graph.add_node("synthesize", synthesize_node)

    graph.add_edge(START, "convert")
    graph.add_edge("convert", "phi_guard")
    graph.add_edge("phi_guard", "metrics")
    graph.add_edge("metrics", "classify")
    graph.add_conditional_edges("classify", after_classify, {"extract": "extract", END: END})
    graph.add_edge("extract", "orchestrate")
    graph.add_conditional_edges("orchestrate", fan_out, ["worker", "synthesize"])
    graph.add_edge("worker", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


def run_intake(pdf_path: str) -> IntakeState:
    return build_graph().invoke({"pdf_path": pdf_path, "worker_results": []})
