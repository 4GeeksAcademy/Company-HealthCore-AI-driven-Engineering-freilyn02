# AGENTS.md

## Before you start
Before doing any work in this repository, read the following files, in order:
1. `CONTEXT.md` — HealthCore's business context, domain data, field names and constraints
2. `memory-bank/projectbrief.md` — what HealthCore is and what this project solves
3. `memory-bank/techContext.md` — the tech stack and architecture decisions
4. `memory-bank/progress.md` — current state of the project and what's next

All code, terminology, and decisions must be consistent with what these files describe. If a task conflicts with something stated in these files, stop and ask before proceeding.

## Workflow before every commit
Follow these steps, in order, before committing any change:
1. **Re-read `memory-bank/progress.md`** to confirm what you're about to do is the actual next step, not something already done or out of scope.
2. **Implement the change**, following the structure and stack defined in `memory-bank/techContext.md`.
3. **Verify the change**: run the relevant checks for what changed (e.g. `npx tsc --noEmit` for TypeScript apps, or start the FastAPI app and hit the affected endpoint) and confirm it works as expected.
4. **Update `memory-bank/progress.md`** to reflect the new state before committing, so the memory bank never goes stale.

Only commit after all 4 steps are done.

## Restricted areas
Do not modify the following without explicit confirmation from the user first:
- `CONTEXT.md` — the company's source of truth; changes here affect every app and agent in the repo
- Anything under `uis/talent-pipeline-tracker/` — this is a completed, delivered milestone; treat it as read-only reference unless the user explicitly asks to change it
- `.env` / `.env.local` files — never create, edit, or commit real environment values