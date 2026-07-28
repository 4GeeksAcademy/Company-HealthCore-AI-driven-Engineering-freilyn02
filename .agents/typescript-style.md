---
scope: "**/*.ts, **/*.tsx"
---

# TypeScript style rules

- Always use TypeScript types for API data — never `any`. Define types in a dedicated `types/` folder per app (see `uis/talent-pipeline-tracker/types/` for the existing pattern).
- Every data-fetching operation must expose at least 3 UI states: loading, success, and error. Never leave a fetch without visible error handling.
- After any mutation (POST/PUT/PATCH/DELETE), update the UI from the server's response — never assume success and update local state optimistically without confirmation from the API.
- Do not introduce external state management libraries (Redux, Zustand, Jotai). Use React hooks only, consistent with the rest of the repo.
- Match HealthCore terminology from `CONTEXT.md` in all user-facing text — never show raw API values (e.g. show "Personal interview", not "personal_interview").