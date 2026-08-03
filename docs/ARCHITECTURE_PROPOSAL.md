# Backend Architecture Proposal — HealthCore

## 1. Business Context and Backend Goals

HealthCore is a multi-clinic ambulatory healthcare provider operating under a hub-and-spoke model across the United States and the United Kingdom, founded in 2011 by Dr. Elena Marsh and Raj Whitfield. The company's core differentiator is **data continuity between clinics**: a patient's history, treatment records, and care team notes must be consistently available regardless of which spoke clinic they visit, while the hub retains oversight and governance.

This operating model creates specific backend requirements:

- **Multi-role access control**: clinicians, front-desk staff, clinic administrators, and hub-level administrators each need different views and permissions over the same underlying data.
- **Cross-clinic data consistency**: records created at one spoke must be reliably visible and consistent at the hub and at other spokes, without duplication or drift.
- **Operational workflows**: appointment scheduling, patient intake, and care coordination span multiple clinics and roles, so the backend must model these as first-class business processes, not just CRUD endpoints.
- **Audit and compliance requirements**: because HealthCore operates in both the US and the UK, the backend must support traceability of who accessed or modified clinical data and when, in a way that can satisfy regulatory expectations in both jurisdictions (e.g., HIPAA-style access logging and UK data protection obligations).

The backend's primary goal is to provide a single, coherent API that all HealthCore frontends (public website, backoffice, and future clinic-facing dashboards) can rely on, while keeping business rules centralized, testable, and independent from how each frontend chooses to present them.

## 2. Chosen Architectural Pattern and Justification

**Chosen pattern: Layered (domain-oriented) architecture**, with a single centralized FastAPI service rather than microservices at this stage.

Justification, tied directly to HealthCore's context:

- **Separation of concerns matches the compliance need.** Because clinical data access must be auditable, business logic (who is allowed to do what, and when an action must be logged) cannot live inside route handlers. A layered approach forces access rules and audit logging into a services layer that every entry point goes through, so nothing bypasses them.
- **A single backend fits HealthCore's current scale.** HealthCore's operational complexity today comes from *roles and workflows*, not from independent scaling needs of different subsystems. Microservices would add deployment and consistency overhead (e.g., keeping patient data consistent across services) without solving a problem HealthCore actually has yet.
- **Domain orientation mirrors how the business already thinks.** HealthCore's own processes are organized around domains — patients, appointments, clinics, staff/roles, audit — so structuring the backend around those same domains keeps the code aligned with how stakeholders describe the business, which reduces translation errors between requirements and implementation.
- **Testability supports the audit requirement.** Business rules isolated in a services layer, independent of FastAPI request/response objects, can be unit-tested directly — important when those rules are the ones responsible for enforcing access control and compliance behavior.

Trade-off acknowledged: a layered monolith means all domains deploy together. This is accepted deliberately for now; the module boundaries below are designed so that a domain could be extracted into its own service later if a specific scaling or team-ownership need arises.

## 3. Backend Structure Proposal (Folders/Modules/Domains)

Backend lives under `services/api` in the monorepo, following the template's convention of one centralized FastAPI service.

```
services/api/
  app/
    api/                  # routers per domain (HTTP layer only)
      v1/
        patients.py
        appointments.py
        clinics.py
        staff.py
        auth.py
        audit.py
    services/              # business use-cases, one module per domain
      patients_service.py
      appointments_service.py
      clinics_service.py
      staff_service.py
      auth_service.py
      audit_service.py
    repositories/           # DB access layer, one module per domain
      patients_repository.py
      appointments_repository.py
      clinics_repository.py
      staff_repository.py
    schemas/                # Pydantic request/response contracts
      patients.py
      appointments.py
      clinics.py
      staff.py
      auth.py
    core/                   # config, security, logging, dependency wiring
      config.py
      security.py
      logging.py
      dependencies.py
    main.py                 # FastAPI app instantiation, router registration
  tests/
    services/
    repositories/
    api/
```

Responsibility boundaries:

- **`api/`** only parses requests, calls a service, and formats the response. It never contains business rules or direct DB queries.
- **`services/`** owns business rules: who can perform an action, what constitutes a valid appointment, when an audit entry must be written. Services depend on repositories, never the other way around.
- **`repositories/`** is the only layer that talks to the database. Swapping the persistence technology later should only require changes here.
- **`schemas/`** defines the contract exposed to clients and is kept separate from internal domain models so that API changes and DB changes can move independently.
- **`core/`** centralizes cross-cutting concerns (settings, auth/security primitives, logging, dependency injection wiring) so they are configured once and reused everywhere instead of duplicated per domain.

## 4. FastAPI Endpoint and Router Organization

- One router file per domain (`patients`, `appointments`, `clinics`, `staff`, `auth`, `audit`), each mounted under a versioned prefix: `/api/v1/<domain>`. Versioning is included from the start so future breaking changes don't force all frontends to migrate simultaneously.
- Routers are grouped by **public vs. protected** access:
  - `auth` endpoints are the only public-by-default group (login, token refresh).
  - All other routers require an authenticated dependency (`get_current_user`) applied via FastAPI's dependency injection, and role-checking dependencies (e.g., `require_role("clinic_admin")`) are composed on top where a domain needs stricter access (for example, only hub-level admins can view cross-clinic reports).
- Shared dependencies (DB session, current user, pagination parameters) live in `core/dependencies.py` and are injected into routers rather than re-implemented per endpoint.
- Every write operation that touches clinical or staff data triggers an audit log entry through the `audit_service`, called from the relevant domain service — not duplicated in each router.
- Pydantic schemas in `schemas/` define request and response bodies explicitly for every endpoint; internal service/repository objects are never returned directly to clients.

This keeps the router layer thin and predictable, and means adding a new domain later (e.g., billing) means adding one router file, one service module, one repository module, and its schemas — without touching existing domains.

**Source of these conventions**: this router-per-domain structure, the use of `APIRouter` with prefixes and tags, and the separation between path operations and business logic follow the official FastAPI documentation's guidance on structuring larger applications ("Bigger Applications - Multiple Files", fastapi.tiangolo.com), which recommends splitting routes into modules under a package instead of a single `main.py` file as an application grows.

## 5. Frontend-Backend Separation Strategy

- **Contract-first integration**: schemas in `app/schemas` are treated as the source of truth for the API contract. Frontend teams (website, backoffice, future clinic dashboards) build against these contracts rather than against backend implementation details.
- **Explicit CORS policy by environment**: allowed origins are defined per environment (local, staging, production) in `core/config.py`, rather than a permissive wildcard, since HealthCore's frontends are known and finite.
- **`.env` strategy**: each environment (local/staging/production) has its own `.env` file (not committed) with a corresponding `.env.example` committed to the repo documenting required variables. Secrets (DB credentials, JWT signing keys) are never hardcoded.
- **Monorepo vs. split repositories — decision**: keep backend and frontends in the same monorepo (`services/api` alongside `uis/website` and `uis/backoffice`), consistent with the template's structure and with the requirement to keep all HealthCore milestones in a single repository. This keeps context (like `CONTEXT.md`) shared and avoids version-drift between frontend and backend during the academy project's pace of change. The trade-off — coarser-grained deploys — is acceptable at this stage since there is no operational need yet to deploy frontend and backend independently.

## 6. Risks and Attention Points with Mitigations

- **Domain boundaries not enforced → duplicated logic and coupling.** Without discipline, a router or service could start reaching into another domain's repository directly. *Mitigation*: services only import repositories from their own domain; cross-domain data needs go through the other domain's service function, never its repository, and this rule is documented in `AGENTS.md`/contribution notes so it's enforced in code review (human or AI-assisted).
- **Business rules inside routers → low testability and maintenance debt.** It's easy to add a quick `if` check directly in a route handler under deadline pressure. *Mitigation*: routers are kept intentionally thin by convention, and unit tests target `services/` directly, which creates a natural pressure to keep logic there rather than in `api/`.
- **Environment drift → configuration-related production incidents.** Given HealthCore operates across US and UK environments, mismatched settings (CORS origins, DB URLs, feature flags) between staging and production is a realistic failure mode. *Mitigation*: all configuration is read through `core/config.py` using a typed settings object (e.g., Pydantic settings), with `.env.example` kept up to date, so missing or malformed variables fail fast at startup instead of causing silent bugs later.
- **Audit logging gaps → compliance exposure.** If audit calls are added inconsistently per endpoint, some sensitive actions could go unlogged. *Mitigation*: audit writes are triggered from within domain services (not routers) for every mutating action on patient, staff, or clinic data, so the audit behavior travels with the business rule instead of depending on each router remembering to call it.

## 7. Initial Technical Decisions and Next Steps

Initial decisions:

- Single centralized FastAPI service under `services/api`, layered architecture as described above.
- API versioned from day one under `/api/v1`.
- PostgreSQL as the target database (fits relational, multi-clinic patient/appointment data with referential integrity needs), accessed only through the repository layer.
- JWT-based authentication with role claims, checked via FastAPI dependencies.

Next steps:

1. Scaffold the `services/api` folder structure defined in Section 3.
2. Define the initial Pydantic schemas for `patients`, `appointments`, and `clinics` (the domains needed for the core hub-and-spoke workflow).
3. Implement the `auth` domain first, since every other router depends on its dependencies for access control.
4. Set up `core/config.py` with environment-based settings and commit a `.env.example`.
5. Add a minimal audit logging mechanism in `audit_service` before implementing other mutating endpoints, so the pattern is established from the first domain onward.