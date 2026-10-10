import json
import os
from pathlib import Path

TRACE_DIR = Path(os.getenv("AGENT_TRACE_DIR", "data/eval/traces"))


def save_trace(run_id: str, state: dict) -> Path:
    """Persist one run as a JSON file so it can be queried after the run."""
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    path = TRACE_DIR / f"{run_id}.json"
    payload = {
        "run_id": run_id,
        "question": state.get("question"),
        "answer": state.get("answer"),
        "error": state.get("error"),
        "trace_steps": state.get("trace_steps", []),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


def load_trace(run_id: str) -> dict:
    return json.loads((TRACE_DIR / f"{run_id}.json").read_text())
