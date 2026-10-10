"""Intent router: decides, from the question alone, which source(s) to use.

The output is a STRUCTURED `RouteDecision` (not free text), and the graph's
conditional edges read ONLY that object. The user never says which source to use.

Why rules and not an LLM call? The router runs on every question, so it must be
fast, free and deterministic: the same question always takes the same path, which
is exactly what the routing evals need to assert. If the rules ever stop being
enough, replace `classify_question` with an LLM call that returns the same
`RouteDecision` schema; nothing else in the graph would change.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

Route = Literal["rag", "tool", "both"]

# "ticket 482", "incident #482", "ticket number 482", "#482"
TICKET_ID_RE = re.compile(
    r"(?:\b(?:ticket|incident)s?\s*(?:number|no\.?|id)?\s*#?\s*(\d+)\b|#(\d+)\b)",
    re.IGNORECASE,
)

# Asking about tickets/incidents in aggregate AND about their live state,
# e.g. "how many open tickets are there?"
TICKET_WORD_RE = re.compile(r"\b(tickets?|incidents?)\b", re.IGNORECASE)
LIVE_STATE_RE = re.compile(
    r"\b(status|state|how many|open|in[ -]progress|resolved|discarded|closed|"
    r"right now|currently|latest|pending)\b",
    re.IGNORECASE,
)

INVENTORY_RE = re.compile(
    r"\b(in stock|stock|inventory|units? (?:of|left|available)|supply levels?|supplies)\b",
    re.IGNORECASE,
)

# Stable knowledge (policies, procedures, coverage...) lives in the RAG.
KNOWLEDGE_RE = re.compile(
    r"\b(policy|policies|procedure|protocol|guideline|coverage|insurance|medicare|"
    r"medicaid|nhs|refund|fee|fees|no-show|how do i|how to|how can i|explain)\b",
    re.IGNORECASE,
)

STATUS_WORDS = {
    "in_progress": re.compile(r"in[ -]progress", re.IGNORECASE),
    "resolved": re.compile(r"\b(resolved|closed)\b", re.IGNORECASE),
    "discarded": re.compile(r"\bdiscarded\b", re.IGNORECASE),
    "open": re.compile(r"\bopen\b", re.IGNORECASE),
}

# "stock of nitrile gloves", "inventory for syringes"
INVENTORY_TERM_PATTERNS = [
    re.compile(r"\b(?:stock|inventory|units?)\s+(?:of|for|on)\s+(.+?)[?.!]*$", re.IGNORECASE),
    re.compile(
        r"\b(?:do we have|have we got|is there|are there)\s+(?:any\s+)?(.+?)"
        r"(?:\s+in stock)?[?.!]*$",
        re.IGNORECASE,
    ),
]


class RouteDecision(BaseModel):
    route: Route
    tools: list[Literal["ticket", "inventory"]] = []
    ticket_id: str | None = None
    ticket_status: str | None = None
    inventory_query: str | None = None
    rationale: str


def _extract_ticket_id(question: str) -> str | None:
    match = TICKET_ID_RE.search(question)
    if not match:
        return None
    return match.group(1) or match.group(2)


def _extract_status(question: str) -> str | None:
    for status, pattern in STATUS_WORDS.items():
        if pattern.search(question):
            return status
    return None


def _extract_inventory_term(question: str) -> str | None:
    for pattern in INVENTORY_TERM_PATTERNS:
        match = pattern.search(question.strip())
        if match:
            term = match.group(1).strip()
            return term or None
    return None


def classify_question(question: str) -> RouteDecision:
    ticket_id = _extract_ticket_id(question)
    ticket_status = _extract_status(question)
    asks_ticket_state = bool(TICKET_WORD_RE.search(question) and LIVE_STATE_RE.search(question))
    asks_inventory = bool(INVENTORY_RE.search(question))
    asks_knowledge = bool(KNOWLEDGE_RE.search(question))

    tools: list[str] = []
    reasons: list[str] = []

    if ticket_id:
        tools.append("ticket")
        reasons.append(f"mentions ticket id {ticket_id}")
    elif asks_ticket_state:
        tools.append("ticket")
        reasons.append("asks for live ticket state")
    if asks_inventory:
        tools.append("inventory")
        reasons.append("asks for live stock")
    if asks_knowledge:
        reasons.append("asks for policy/procedure knowledge")

    if tools and asks_knowledge:
        route: Route = "both"
    elif tools:
        route = "tool"
    else:
        route = "rag"
        reasons.append("no live-data signal, answer from the knowledge base")

    return RouteDecision(
        route=route,
        tools=tools,  # type: ignore[arg-type]
        ticket_id=ticket_id,
        ticket_status=ticket_status if "ticket" in tools and not ticket_id else None,
        inventory_query=_extract_inventory_term(question) if "inventory" in tools else None,
        rationale="; ".join(reasons),
    )