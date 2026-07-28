# Skill: Add TypeScript types for a new API resource

## Goal
Generate a complete, accurate TypeScript type definition file for a new API resource in this repo, so every app in `uis/` can consume the resource with full type safety — no `any`, no guessed field names.

## Inputs
- The API endpoint(s) for the resource (e.g. `GET /records`, `POST /records`)
- A sample JSON response from the actual API (not assumed — fetch or paste a real response)
- The app that will consume this type (e.g. `uis/backoffice`)

## Steps
1. Fetch or request a real sample response from the given endpoint.
2. Identify every field, its exact name (case-sensitive) and type (string, number, boolean, array, nullable).
3. Create a `types/<resource>.ts` file inside the target app with:
   - An interface for the single resource (e.g. `Candidate`)
   - An interface for any wrapped list response (e.g. `{ data: Candidate[], meta: {...} }`), if the API paginates or wraps results
   - Union types for any enum-like fields (e.g. `status`, `stage`)
4. Run `npx tsc --noEmit` in the target app to confirm there are no type errors.

## Acceptance criteria
- [ ] Every field from the real API response is represented, with the exact field name from the API (not a guessed/renamed one)
- [ ] No `any` types used
- [ ] `npx tsc --noEmit` runs with zero errors after the types are added
- [ ] The type file is saved under `types/` in the correct app, not in a shared location unless explicitly reused by 2+ apps