from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.graph import run_agent

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
    return {"answer": state["answer"], "trace_id": run_id}
