"""Structured invocation log: exactly one JSON line per tool call.

{"timestamp": "...", "client_id": "...", "tool": "...", "input_summary": {...},
 "result": "success" | "error:<ERROR_CODE>", "duration_ms": 145}

`input_summary` is an allow-list on purpose: ticket titles/descriptions can contain
sensitive text (HealthCore forbids patient-identifying data) and must never reach the logs.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastmcp.exceptions import ToolError, ValidationError
from fastmcp.server.middleware import Middleware, MiddlewareContext

from auth import current_client_id
from errors import ErrorCode, ToolFailure

logger = logging.getLogger("company_tools.invocations")

_SAFE_INPUT_FIELDS = ("action", "ticket_id", "status", "product_id", "query")


def summarize_input(arguments: dict[str, Any] | None) -> dict[str, Any]:
    arguments = arguments or {}
    return {k: arguments[k] for k in _SAFE_INPUT_FIELDS if arguments.get(k) is not None}


def _validation_message(exc: Exception) -> str | None:
    """First lines of the validation error: they name the offending field."""
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    # Drop pydantic's trailing documentation link, keep summary + field + reason.
    lines = [line for line in lines if not line.startswith("For further information")]
    return " | ".join(lines[:3])[:300] or None


class InvocationLogMiddleware(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        started = time.perf_counter()
        result = "success"
        try:
            return await call_next(context)
        except ToolFailure as exc:
            result = f"error:{exc.code.value}"
            raise
        except (ToolError, ValidationError) as exc:
            # FastMCP's own input validation (wrong types, missing arguments, ...):
            # re-raise it in the documented JSON shape instead of raw pydantic text.
            result = "error:VALIDATION_ERROR"
            raise ToolFailure(
                ErrorCode.VALIDATION_ERROR,
                tool=context.message.name,
                message=_validation_message(exc),
            ) from exc
        except Exception:
            result = "error:INTERNAL_ERROR"
            raise
        finally:
            logger.info(
                json.dumps(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "client_id": current_client_id(),
                        "tool": context.message.name,
                        "input_summary": summarize_input(context.message.arguments),
                        "result": result,
                        "duration_ms": round((time.perf_counter() - started) * 1000),
                    }
                )
            )
