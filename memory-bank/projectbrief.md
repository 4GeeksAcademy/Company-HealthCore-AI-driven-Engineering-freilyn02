# Project Brief — HealthCore

## What is HealthCore
HealthCore is an outpatient healthcare clinic network operating 12 clinics across the United States and the United Kingdom. Founded in 2011 by Dr. Elena Marsh and Raj Whitfield, HealthCore uses a "hub-and-spoke" model of small, fully-staffed outpatient clinics connected by a shared digital backbone, rather than large centralized hospitals.

HealthCore Digital is the internal technology unit responsible for building and maintaining every software tool used across the network — from clinical operations to patient-facing services and internal hiring.

## Problem this project solves
This monorepo builds the software systems HealthCore Digital needs to operate the clinic network efficiently across two regions. So far it includes:
- A public-facing website presenting HealthCore to prospective patients and clinics
- An internal backoffice used by HealthCore Digital staff
- A Talent Pipeline Tracker (People & Talent) for managing candidate recruitment across clinics

## Why an AI agent works in this repo
This project is being actively developed with the help of an AI coding agent (Cursor). This memory bank, along with AGENTS.md and .agents/, exists so the agent always has accurate, up-to-date context about HealthCore's domain, the current state of the project, and the rules it must follow — instead of relying on assumptions or generic scaffolding.

## Scope
- `uis/website` — public-facing site (Next.js + TypeScript)
- `uis/backoffice` — internal admin app (Next.js + TypeScript)
- `uis/talent-pipeline-tracker` — candidate management app (Next.js + TypeScript, built in Milestone 3)
- `services/` — centralized company API (Python + FastAPI)