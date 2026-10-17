"""Links logged-in API users to the named department approvers (CONTEXT 2.1).

The user table only has `email` and `role`, so the link is configuration:

    RFP_APPROVERS="tom.callahan=tom@example.com,marcus.reid=marcus@example.com,claire.whitfield=claire@example.com"

Fails closed: a user whose email is not listed has NO approver identity and cannot decide.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

from .models import DEPARTMENT_OWNERS

ENV_VAR = "RFP_APPROVERS"

_ACTOR_TO_DEPARTMENT = {
    actor: department for department, owners in DEPARTMENT_OWNERS.items() for actor in owners
}


def parse_approvers(raw: str | None) -> dict[str, str]:
    """'actor=email,actor=email' -> {email(lower): actor}. Unknown actors are a loud error."""
    mapping: dict[str, str] = {}
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        actor, sep, email = item.partition("=")
        actor, email = actor.strip().lower(), email.strip().lower()
        if not sep or not actor or not email:
            raise ValueError(f"{ENV_VAR}: invalid entry {item!r}; expected actor=email")
        if actor not in _ACTOR_TO_DEPARTMENT:
            raise ValueError(
                f"{ENV_VAR}: unknown approver {actor!r}; valid: {sorted(_ACTOR_TO_DEPARTMENT)}"
            )
        mapping[email] = actor
    return mapping


def load_approvers(env: Mapping[str, str] | None = None) -> dict[str, str]:
    return parse_approvers((env if env is not None else os.environ).get(ENV_VAR))


def actor_for_user(user: Mapping[str, Any], mapping: Mapping[str, str] | None = None) -> str | None:
    email = str(user.get("email") or "").strip().lower()
    if not email:
        return None
    return (mapping if mapping is not None else load_approvers()).get(email)


def department_for_actor(actor: str | None) -> str | None:
    return _ACTOR_TO_DEPARTMENT.get(actor or "")
