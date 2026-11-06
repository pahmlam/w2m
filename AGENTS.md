# AGENTS.md — W2M

## Project context

W2M is a web app for finding fair, efficient meeting points for four people in Hanoi using travel times on a directed road network. The local MVP uses a Python/FastAPI backend, a Next.js/TypeScript frontend with MapLibre, offline OpenStreetMap graph data, and Docker. NetworkX is the routing reference; SciPy/CSR is the planned production implementation.

## Sources of truth

- For task scope, milestone order, approved clarifications, and acceptance criteria, consult the relevant sections of `W2M-MVP-Plan.md`.
- For algorithms, API contracts, architecture, and constraints, consult the relevant sections of `W2M — Software & Technical Specification v0.2.0.md`. Locate these documents by filename if their repository paths differ.
- Follow any additional `AGENTS.md` that applies to files being edited. Use the MVP plan's explicit clarifications where they supersede the draft specification; flag unresolved conflicts instead of silently inventing a rule.
- Unchecked plan items are **not** implemented or verified merely because they appear in documentation. Inspect the actual repository state.

## Engineering rules

- Keep changes focused on the requested task and current MVP milestone; do not introduce post-MVP features without authorization.
- Preserve directed/one-way routing, snap and access-time accounting, deterministic Pareto-safe OWA ranking, and consistency between route geometry and travel-time results. Never mutate the shared graph during a request. Rerank from valid cached data without rerunning shortest paths.
- Respect coordinate conventions (WGS84 coordinates, GeoJSON `[lon, lat]`, projected distances in EPSG:32648) and the existing API contract.
- Prepare/version OSM graph data offline; do not download OSM during normal requests or routine CI tests. Preserve map attribution. Do not log or persist precise user locations or secrets.
- Reuse established project conventions and commands; do not assume tooling exists before inspecting the repository. Add or update focused tests for behavior changes, especially relevant `FR-*` and `TC-*` cases. Run applicable tests, lint, type checks, and builds; report failures and skipped checks accurately.
- Update relevant documentation and milestone checkboxes only when actual implementation and verification evidence supports the change.

## Code conventions

- **General:** Prefer readable, minimal, task-scoped changes. Follow existing repository formatter, linter, and naming configurations; do not introduce competing styles or unrelated refactors. Use descriptive names, small single-purpose functions, explicit units (for example, `_seconds`, `_meters`), and named configuration instead of unexplained magic numbers. Avoid premature abstractions and duplicated business logic.
- **Python:** Follow [PEP 8](https://peps.python.org/pep-0008/) and [PEP 257](https://peps.python.org/pep-0257/). Use `snake_case` for modules/functions/variables, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Add type hints to new or modified functions, especially public interfaces; write docstrings for public APIs and non-obvious algorithms. Use configured formatting/lint tools if present.
- **TypeScript/React:** Use TypeScript strict typing where configured; prefer `unknown` plus validation over `any` for untrusted data. Use `camelCase` for functions/variables and `PascalCase` for React components/types. Keep components focused; put API calls, data transformation, and domain calculations outside presentation components. Follow the repository's ESLint/formatter settings rather than inventing style choices.
- **Comments:** Write code comments and docstrings in clear English; journals remain in Vietnamese. Explain *why*, mathematical invariants, coordinate order, units, non-obvious edge cases, and trade-offs—not what obvious code does. Keep comments accurate when behavior changes. Do not leave commented-out code, stale TODOs, or redundant line-by-line commentary; make any necessary TODO specific and actionable.
- **Reliability:** Validate inputs at system boundaries; handle failures explicitly. Do not swallow exceptions, conceal type errors, or change API error contracts casually. Keep side effects and shared-state mutations controlled, especially in routing and caching code.
- **Tests:** Add focused, deterministic regression tests for behavior changes and edge cases. Verify numerical/graph invariants against the reference implementation where relevant; do not use live OSM downloads or external services in routine unit tests. Never claim a check passed unless it was run.

## Development journal — mandatory

- **After any coding task that changes repository files, and before the final response, explicitly open, read, and follow `docs/journals/AGENTS.md` in full.** Do not rely on automatic nested-instruction discovery: this is the journal rules file, **not** the output directory.
- Create **exactly one new journal per task** under `docs/journals/`, following that file's naming, Vietnamese writing, structure, and verification requirements. Never append to or modify historical journals unless explicitly requested.
- Do not create a journal for tasks with no actual repository changes or solely for journal maintenance, as specified by the journal rules.
- In the final task response, state the changes, actual verification results, remaining limitations (if any), and the new journal's path. A coding task is not finished until its required journal is written.
- Always tick the checklist in plan file whenever done task.
