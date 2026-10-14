from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.graph import run_agent
from agent.harness import observability

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentQuery(BaseModel):
    question: str


@router.post("/query")
def agent_query(body: AgentQuery):
    run_id, state = run_agent(body.question)
    error = state.get("error")
    if error == "empty_question":
        raise HTTPException(status_code=400, detail="The question cannot be empty.")
    if error:
        stage = "retrieval" if error == "retrieval_failed" else "generation"
        raise HTTPException(
            status_code=502,
            detail=f"Agent failed during {stage}. Check trace {run_id}.",
        )
    response = {"answer": state["answer"], "trace_id": run_id}
    guard = state.get("guard_decision") or {}
    if guard.get("action", "allow") != "allow":
        # Tells the client the guardrail layer intervened (block or casual redirect).
        response["guardrail"] = {
            "action": guard["action"],
            "guardrail": guard["guardrail"],
            "failure_type": guard["failure_type"],
        }
    return response


@router.get("/guardrails/summary")
def guardrails_summary():
    """How many times each guardrail fired since the API started (SEC-114)."""
    return observability.summary()
