"""The real-time notification path must not call any AI model, agent or LLM.

"Notification path" here means everything between the moment a ticket row is saved and the moment
the browser shows the toast:

  - services/api/events/      the in-process bus and GET /events/stream
  - routers.rfp               only the publish statement and the payload builder (the same route
                              later schedules the AI pipeline, which is NOT part of this path)
  - uis/backoffice            the SSE client, parser, hook and the two notification components

Four independent checks, from cheapest to strongest:

  1. static: the import closure of events.bus / events.sse (following first-party imports) pulls in
     no AI library and none of the repository's AI packages (agents/, mcps/, data.pipelines, ...)
  2. static: no call to a known pipeline/LLM entry point inside the events package
  3. static: the publish call in `upload_rfp` runs before the AI pipeline is scheduled and takes only
     a plain field-copy payload
  4. runtime: a clean interpreter that imports the events modules ends up with no AI library loaded
  5. frontend grep: the notification client code never mentions a model provider or an LLM endpoint
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = REPO_ROOT / "services" / "api"
EVENTS_DIR = API_DIR / "events"
BACKOFFICE = REPO_ROOT / "uis" / "backoffice"

# Third-party AI / LLM / agent libraries (matched as the module or any of its submodules).
FORBIDDEN_EXTERNAL = {
    "anthropic",
    "openai",
    "langchain",
    "langchain_core",
    "langchain_anthropic",
    "langchain_openai",
    "langchain_mcp_adapters",
    "langgraph",
    "litellm",
    "google.generativeai",
    "google.genai",
    "vertexai",
    "cohere",
    "mistralai",
    "ollama",
    "transformers",
    "llama_index",
    "instructor",
    "dspy",
    "crewai",
    "autogen",
    "mcp",
}
# First-party packages of this monorepo that hold AI pipelines, agents or tools.
FORBIDDEN_FIRST_PARTY = {"agents", "mcps", "skills", "workflows", "data.pipelines"}
# Entry points that start the AI work for a ticket (or call a model).
FORBIDDEN_CALLS = {"run_ticket", "get_workflow", "invoke", "ainvoke", "generate_content"}

FRONTEND_NOTIFICATION_FILES = [
    BACKOFFICE / "lib" / "sse.ts",
    BACKOFFICE / "lib" / "sseParser.ts",
    BACKOFFICE / "lib" / "useSse.ts",
    BACKOFFICE / "components" / "RealtimeStatus.tsx",
    BACKOFFICE / "components" / "RfpNewTicketToasts.tsx",
]
FRONTEND_FORBIDDEN = re.compile(
    r"anthropic|openai|langchain|langgraph|\bllm\b|\bgpt\b|claude|completions|embedding|/agents?\b|/chat\b",
    re.IGNORECASE,
)


def _matches(name: str, banned: set[str]) -> bool:
    return any(name == b or name.startswith(b + ".") for b in banned)


# --- import closure --------------------------------------------------------


def _module_file(name: str) -> Path | None:
    parts = name.split(".")
    for base in (API_DIR, REPO_ROOT):
        package = base.joinpath(*parts)
        if (package / "__init__.py").is_file():
            return package / "__init__.py"
        if package.with_suffix(".py").is_file():
            return package.with_suffix(".py")
    return None


def _imports_of(path: Path, module_name: str) -> list[str]:
    """Absolute dotted names imported by a file (plus `pkg.name` candidates for `from pkg import name`)."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    is_package = path.name == "__init__.py"
    package = module_name if is_package else module_name.rpartition(".")[0]
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = package.split(".") if package else []
                base_parts = base_parts[: len(base_parts) - (node.level - 1)]
                base = ".".join(base_parts + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            if base:
                names.append(base)
                names.extend(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
    return names


def import_closure(roots: list[str]) -> tuple[set[str], set[str]]:
    """Returns (first-party modules reached, external modules imported) starting from `roots`."""
    first_party: set[str] = set()
    external: set[str] = set()
    pending = list(roots)
    while pending:
        name = pending.pop()
        path = _module_file(name)
        if path is None:
            external.add(name)
            continue
        if name in first_party:
            continue
        first_party.add(name)
        pending.extend(_imports_of(path, name))
        # Importing a.b.c also runs the __init__.py of a and a.b.
        parts = name.split(".")
        pending.extend(".".join(parts[:i]) for i in range(1, len(parts)))
    return first_party, external


def test_import_closure_of_the_event_modules_has_no_ai_library_or_pipeline():
    first_party, external = import_closure(["events.bus", "events.sse"])

    # Guard against a vacuous pass: the walk really reached the auth dependency chain.
    assert {"events.bus", "events.sse", "app.core.deps"} <= first_party

    ai_libraries = sorted(name for name in external if _matches(name, FORBIDDEN_EXTERNAL))
    ai_packages = sorted(name for name in first_party if _matches(name, FORBIDDEN_FIRST_PARTY))
    assert ai_libraries == []
    assert ai_packages == []


def test_the_import_closure_walker_does_detect_ai_imports(tmp_path, monkeypatch):
    """Self-check: the closure test above would fail if a module imported an AI library."""
    (tmp_path / "leaky.py").write_text("import helper\n")
    (tmp_path / "helper.py").write_text("from langgraph.graph import StateGraph\nfrom data.pipelines import rag\n")
    monkeypatch.setattr(sys.modules[__name__], "API_DIR", tmp_path)

    first_party, external = import_closure(["leaky"])

    assert "helper" in first_party
    assert any(_matches(name, FORBIDDEN_EXTERNAL) for name in external)
    assert any(_matches(name, FORBIDDEN_FIRST_PARTY) for name in first_party | external)


def _called_names(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


@pytest.mark.parametrize("path", sorted(EVENTS_DIR.glob("*.py")), ids=lambda p: p.name)
def test_events_package_never_calls_a_pipeline_or_model_entry_point(path):
    called = _called_names(ast.parse(path.read_text(encoding="utf-8-sig")))

    assert called & FORBIDDEN_CALLS == set()


# --- the publish site in the router ----------------------------------------


def _router_tree() -> ast.Module:
    return ast.parse((API_DIR / "routers" / "rfp.py").read_text(encoding="utf-8-sig"))


def _function(tree: ast.Module, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in routers/rfp.py")


def test_payload_builder_only_copies_fields_and_formats_the_date():
    called = _called_names(_function(_router_tree(), "_ticket_created_payload"))

    assert called <= {"isoformat"}


def test_ticket_created_is_published_before_the_ai_pipeline_is_scheduled():
    upload = _function(_router_tree(), "upload_rfp")
    lines: dict[str, int] = {}
    publish_call: ast.Call | None = None
    for node in ast.walk(upload):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "create_ticket":
            lines["create_ticket"] = node.lineno
        elif isinstance(func, ast.Attribute) and func.attr == "publish":
            lines["publish"] = node.lineno
            publish_call = node
        elif isinstance(func, ast.Attribute) and func.attr == "add_task":
            lines["add_task"] = node.lineno

    assert set(lines) == {"create_ticket", "publish", "add_task"}
    # saved -> announced -> only then is the (slow, AI-backed) pipeline queued in the background
    assert lines["create_ticket"] < lines["publish"] < lines["add_task"]

    assert publish_call is not None
    event_name, payload = publish_call.args
    assert isinstance(event_name, ast.Name) and event_name.id == "RFP_TICKET_CREATED_EVENT"
    assert isinstance(payload, ast.Call) and getattr(payload.func, "id", None) == "_ticket_created_payload"


# --- runtime ---------------------------------------------------------------


def test_importing_the_event_modules_loads_no_ai_library():
    """A clean interpreter imports events.bus and events.sse; no AI package may end up loaded."""
    code = (
        "import sys, json\n"
        "import events.bus, events.sse\n"
        f"banned = {sorted(FORBIDDEN_EXTERNAL)!r}\n"
        "loaded = sorted(m for m in sys.modules if any(m == b or m.startswith(b + '.') for b in banned))\n"
        "print(json.dumps(loaded))\n"
    )
    env = {
        **os.environ,
        "SECRET_KEY": os.environ.get("SECRET_KEY", "test-only-secret-key-not-used-anywhere-else"),
        "PYTHONPATH": os.pathsep.join([str(API_DIR), str(REPO_ROOT)]),
    }

    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=API_DIR, env=env, capture_output=True, text=True, timeout=60
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == "[]"


# --- frontend --------------------------------------------------------------


@pytest.mark.parametrize("path", FRONTEND_NOTIFICATION_FILES, ids=lambda p: p.name)
def test_frontend_notification_code_mentions_no_model_provider_or_llm_endpoint(path):
    assert path.is_file(), f"{path} is missing: update FRONTEND_NOTIFICATION_FILES"

    hits = FRONTEND_FORBIDDEN.findall(path.read_text(encoding="utf-8-sig"))

    assert hits == []


def test_the_sse_client_talks_only_to_the_events_stream():
    client = (BACKOFFICE / "lib" / "sse.ts").read_text(encoding="utf-8-sig")
    rfp_lib = (BACKOFFICE / "lib" / "rfp.ts").read_text(encoding="utf-8-sig")

    assert len(re.findall(r"\bfetch\(", client)) == 1  # one request, built from the caller's path
    assert 'RFP_EVENTS_PATH = "/events/stream"' in rfp_lib
