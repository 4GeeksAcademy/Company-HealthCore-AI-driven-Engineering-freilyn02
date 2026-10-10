import json
import os
from pathlib import Path

TRACE_DIR = Path(os.getenv("AGENT_TRACE_DIR", "data/eval/traces"))

# graph node -> the data source it represents in the trace
SOURCE_BY_NODE = {
    "retrieve": "rag",
    "lookup_ticket": "ticket_tool",
    "lookup_inventory": "inventory_tool",
}


def sources_used(trace_steps: list[dict]) -> list[str]:
    """Which sources ran and in what order, e.g. ["ticket_tool", "rag"]."""
    return [SOURCE_BY_NODE[s["node"]] for s in trace_steps if s["node"] in SOURCE_BY_NODE]


def save_trace(run_id: str, state: dict) -> Path:
    """Persist one run as a JSON file so it can be queried after the run."""
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    path = TRACE_DIR / f"{run_id}.json"
    steps = state.get("trace_steps", [])
    payload = {
        "run_id": run_id,
        "question": state.get("question"),
        "route": state.get("route"),
        "route_rationale": (state.get("route_decision") or {}).get("rationale"),
        "sources_used": sources_used(steps),  # which source(s) ran, in order
        "rag_executed": any(s["node"] == "retrieve" for s in steps),
        "answer": state.get("answer"),
        "error": state.get("error"),
        "trace_steps": steps,  # per-tool HTTP outcome lives in each step's "outcome"
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


def load_trace(run_id: str) -> dict:
    return json.loads((TRACE_DIR / f"{run_id}.json").read_text())