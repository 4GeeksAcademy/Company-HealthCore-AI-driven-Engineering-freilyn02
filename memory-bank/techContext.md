# Tech Context — HealthCore

## Repository structure
This is a monorepo built from the `ai-engineering-company-project-monorepo` template. It carries all HealthCore projects (Milestones 1-4 and onward) in a single repository, not one repo per milestone.

## Frontend — `uis/`
- Stack: Next.js (App Router) + TypeScript
- `uis/website` — public-facing site
- `uis/backoffice` — internal admin app, imports and displays the TypeScript script built in Milestone 2
- `uis/talent-pipeline-tracker` — candidate management app (Milestone 3), built with Next.js + TypeScript + Tailwind, no external state management libraries (hooks only)

## Backend — `services/`
- Stack: Python + FastAPI
- A single centralized FastAPI app for the whole company, organized by domain routers (e.g. locations, menus, sales, telemetry) rather than separate microservices
- Add new endpoints to the same app; only extract a separate worker/service if truly necessary

## Data — `data/`
- `data/raw/` — untouched source data
- `data/pipelines/` — ETL/ELT jobs
- `data/process/` — cleaned/intermediate outputs
- `data/eval/` — evaluation datasets and metrics

## AI infrastructure
- `agents/` — AI agents, one subfolder per agent
- `skills/` — reusable capabilities for agents (each with a SKILL.md)
- `mcps/` — Model Context Protocol servers for live tool/data access
- `workflows/` — n8n / automation flows

## Shared code
- `packages/` — versioned shared libraries (e.g. `packages/shared` → `@repo/shared-types`)
- `shared/` — schemas, templates, static assets not packaged as a library

## Constraints
- Every app/service/agent added gets its own subfolder + README
- Nothing goes loose in the repo root
- All domain terminology must match `CONTEXT.md` (HealthCore), never generic