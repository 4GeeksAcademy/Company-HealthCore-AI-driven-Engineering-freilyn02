"""Dedicated `rfp_intake` LangGraph (NOT attached to the CX / knowledge graph).

    convert -> metrics -> classify --(not RFP)--> END
                                   \\--(RFP)--> orchestrate --> worker x N (parallel)
                                                                    \\--> synthesize --> END

The graph has no database access: persistence is done by service.py, so the
graph stays easy to test and the routers never own it.
"""
import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .agents.classifier import classify_rfp
from .agents.orchestrator import plan_workstreams
from .agents.synthesizer import synthesize
from .agents.workers import run_worker
from .convert import pdf_to_markdown
from .metrics import basic_metadata, readability_scores


class IntakeState(TypedDict, total=False):
    pdf_path: str
    markdown: str
    markdown_path: str
    metadata: dict[str, Any]
    readability: dict[str, Any]
    classification: dict[str, Any]
    workstreams: list[dict[str, Any]]
    unknown_departments: list[str]
    # Parallel workers append here; the reducer merges their outputs.
    worker_results: Annotated[list[dict[str, Any]], operator.add]
    synthesis: dict[str, Any]


def convert_node(state: IntakeState) -> dict:
    text, md_path = pdf_to_markdown(state["pdf_path"])
    return {"markdown": text, "markdown_path": str(md_path)}


def metrics_node(state: IntakeState) -> dict:
    return {
        "metadata": basic_metadata(state["markdown"]),
        "readability": readability_scores(state["markdown"]),
    }


def classify_node(state: IntakeState) -> dict:
    return {"classification": classify_rfp(state["markdown"]).model_dump()}


def after_classify(state: IntakeState) -> str:
    return "orchestrate" if state["classification"]["is_rfp"] else END


def orchestrate_node(state: IntakeState) -> dict:
    workstreams, unknown = plan_workstreams(state["markdown"], state["metadata"])
    return {"workstreams": workstreams, "unknown_departments": unknown}


def fan_out(state: IntakeState):
    workstreams = state.get("workstreams") or []
    if not workstreams:
        return "synthesize"
    return [
        Send(
            "worker",
            {
                "department": w["department"],
                "context": w["prompt_context"],
                "metadata": state["metadata"],
            },
        )
        for w in workstreams
    ]


def worker_node(payload: dict) -> dict:
    """One failing worker must not kill the whole ticket: partial failure is recorded."""
    try:
        result = run_worker(payload["department"], payload["metadata"], payload["context"])
    except Exception as exc:
        result = {
            "department": payload["department"],
            "key_aspects": [],
            "open_questions": [f"Worker failed, needs manual review: {type(exc).__name__}"],
            "suggested_contact_role": None,
            "failed": True,
        }
    return {"worker_results": [result]}


def synthesize_node(state: IntakeState) -> dict:
    return {
        "synthesis": synthesize(
            state["metadata"],
            state.get("readability") or {},
            state.get("worker_results") or [],
            state.get("unknown_departments") or [],
        )
    }


def build_graph():
    graph = StateGraph(IntakeState)
    graph.add_node("convert", convert_node)
    graph.add_node("metrics", metrics_node)
    graph.add_node("classify", classify_node)
    graph.add_node("orchestrate", orchestrate_node)
    graph.add_node("worker", worker_node)
    graph.add_node("synthesize", synthesize_node)

    graph.add_edge(START, "convert")
    graph.add_edge("convert", "metrics")
    graph.add_edge("metrics", "classify")
    graph.add_conditional_edges("classify", after_classify, {"orchestrate": "orchestrate", END: END})
    graph.add_conditional_edges("orchestrate", fan_out, ["worker", "synthesize"])
    graph.add_edge("worker", "synthesize")
    graph.add_edge("synthesize", END)
    return graph.compile()


def run_intake(pdf_path: str) -> IntakeState:
    return build_graph().invoke({"pdf_path": pdf_path, "worker_results": []})
