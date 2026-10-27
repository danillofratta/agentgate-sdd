# Portfolio finalization — evidence and archive readiness

Date: 2026-10-27 (America/Sao_Paulo). Branch:
`docs/agentgate-portfolio-finalization`. Starting main was clean at
`add4688991d09d82a776f6d00831ba59ae54070e`, which merged the UX redesign in #27.
One maintenance change, `finalize-agentgate-portfolio`, contains proposal, design,
scenario specification and tasks. No commit, push, PR, merge or archive occurred.

## Delivered files

| Status | Files |
| --- | --- |
| Modified | `README.md`, `.github/workflows/ci.yml`, `.gitignore`, `docs/architecture.md`, `docs/interactive_lab.md`, `docs/interactive_lab_ux_acceptance.md`, `docs/milestone_c_verification.md`, `openspec/changes/add-interactive-lab/tasks.md` |
| Added | This report; `docs/sqlite_http_development.md`; `docs/media/README.md`; the three JPEGs below; `openspec/changes/finalize-agentgate-portfolio/{.openspec.yaml,proposal.md,design.md,tasks.md,specs/portfolio-guide/spec.md}` |
| Deleted with `git rm` | `ci-error.txt` |

No application/domain/financial/MCP behavior, tests, database schemas, dependency
manifest or lockfile changed. The removed 96-line log recorded an obsolete
missing `.lab-secrets/llm_api_key` bind-mount failure. No build, script or existing
documentation depended on it; current CI provisions the empty optional file and
subsequent main CI passed. `.gitignore` now ignores only `/ci-error.txt` in
addition to its existing patterns; legitimate fixtures/evidence remain tracked.

The README now presents the browser demo, simulation warning, real screenshots,
runtime and import-direction diagrams, security controls, approval/replay and
Docker/PostgreSQL onboarding. Lengthy SQLite/HTTP commands were preserved in the
secondary guide. Detailed architecture corrects the distinction between three
MCP tools and four model-facing functions. Historical verification reports are
attributed to their original sessions; new follow-ups identify current evidence.

## Visual assets and local demonstration

Real, visually inspected 1440 × 1080 optimized JPEGs:

- [Dashboard](media/dashboard.jpg)
- [AI Assistant with simulated operation](media/assistant.jpg)
- [Independent human approval](media/human-approval.jpg)

See [capture provenance and byte sizes](media/README.md). No generated mockups,
GIF, credentials or browser session identifiers are included. Synthetic operation
UUIDs and prior simulation balances are visible. The explicit deterministic test
LLM is labeled; the SDK MCP client, server, FastAPI and PostgreSQL are real.

The browser skill's required execution tool was unavailable. The existing
project-supported Playwright 1.56.0 / headless Edge path worked. The existing
image's static assets did not match source, so a temporary read-only source
mount served checked-out code without a build. HTML/CSS/JS equality was verified
after line-ending normalization. Only the frontend was temporarily recreated;
the default Compose frontend configuration was restored after QA. No data volume
was reset or deleted. The checks added synthetic operations and simulated
transfers to the existing local database.

Current-source QA passed five prompts; balance execution; explicit $1
execution/replay; $100.01 independent review then execution; denied $1,000.01;
last-operation inspection; shared operation panel; completed-ID reload;
Escape/focus restoration; 1440/820/390 widths without horizontal overflow; and
no JavaScript errors. The first older-image attempt failed the existing script's
hidden-reference assertion and is not counted as a passing run. A temporary
capture runner used the actual hidden element's text content for comparison.

## GitHub metadata

Updated through authenticated `gh` with repository ADMIN access, then read back:

> Secure AI agent execution with MCP, deterministic policies, human approval,
> idempotency and auditable simulated financial operations.

Topics: `ai-agents`, `model-context-protocol`, `mcp`, `agent-security`,
`human-in-the-loop`, `spec-driven-development`, `python`, `fastapi`,
`hexagonal-architecture`, `postgresql`. Homepage remains empty.

Reproduction (already applied; no further publication needed):

```powershell
gh repo edit danillofratta/agentgate-sdd --description 'Secure AI agent execution with MCP, deterministic policies, human approval, idempotency and auditable simulated financial operations.' --add-topic ai-agents --add-topic model-context-protocol --add-topic mcp --add-topic agent-security --add-topic human-in-the-loop --add-topic spec-driven-development --add-topic python --add-topic fastapi --add-topic hexagonal-architecture --add-topic postgresql
gh repo view danillofratta/agentgate-sdd --json description,repositoryTopics,homepageUrl
```

## Milestone C and archive-readiness review

[The criterion-level matrix](milestone_c_verification.md) supports C tasks 3.1
and 3.2; both are checked, and OpenSpec reports `add-interactive-lab` 9/9.
Prompt-injection assertions refer to concrete tested attacks, not universal
immunity. The user-reported Groq demonstration remains distinct from mocked
wire-contract tests and from an unrun automated live-provider smoke.

| Active change | Tracked state | Ready for archival? |
| --- | --- | --- |
| `agentgate-core` | 32/32, unchanged | Ready for separate review based on historical [clean quality gates](final_quality_gates.md), [end-to-end acceptance](final_e2e_acceptance.md) and current regression pass. |
| `add-interactive-lab` | 9/9, C evidence reconciled | Ready for separate review on the documented simulation scope. Optional live-provider and C-specific container-restart smoke remain unrun here; hosted A/B restart evidence is identified separately. |
| `redesign-interactive-lab-ux` | 6/6, existing checkboxes unchanged | Conditional: tracked implementation is complete, but full real-browser keyboard/accessibility and failure-injection checklist evidence remains incomplete. Resolve or explicitly review those acceptance gaps before unconditional archival. |
| `finalize-agentgate-portfolio` | 7/7; local gates and evidence complete | Ready for separate review after local verification. Hosted execution of the new action pins requires a later authorized push; it is not claimed by local validation. |

No change was archived, no main specs were synchronized, and no task was marked
complete based only on the Groq anecdote or a green CI badge.

## CI pins and compatibility

Each exact release tag was resolved through the official repository's
`git/ref/tags/<version>` API to a commit (not an annotated tag object), and the
pinned `action.yml` was inspected. All selected actions declare `node24`.

| Action | Previous version / full SHA | Selected version / full SHA |
| --- | --- | --- |
| `actions/checkout` (both jobs) | v4.3.1 / `34e114876b0b11c390a56381ad16ebd13914f8d5` | v7.0.1 / `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `actions/setup-node` | v4.4.0 / `49933ea5288caeca8642d1e84afbd3f7d6820020` | v7.1.0 / `949feb2413d6458794dcd2491c4babbbce0c15c1` |
| `astral-sh/setup-uv` (both jobs) | v6.8.0 / `d0cc045d04ccac9d8b7881df0226f9e82c39688e` | v10.3.2 / `07a047e608db84b3d8c06cd9a7c7dcc9c355c18e` |

Official pinned sources:
[checkout metadata](https://github.com/actions/checkout/blob/3d3c42e5aac5ba805825da76410c181273ba90b1/action.yml),
[checkout migration notes](https://github.com/actions/checkout/blob/3d3c42e5aac5ba805825da76410c181273ba90b1/README.md),
[setup-node metadata](https://github.com/actions/setup-node/blob/949feb2413d6458794dcd2491c4babbbce0c15c1/action.yml),
[setup-node migration notes](https://github.com/actions/setup-node/blob/949feb2413d6458794dcd2491c4babbbce0c15c1/README.md),
[setup-uv metadata](https://github.com/astral-sh/setup-uv/blob/07a047e608db84b3d8c06cd9a7c7dcc9c355c18e/action.yml),
[setup-uv v7](https://github.com/astral-sh/setup-uv/releases/tag/v7.0.0),
[v8](https://github.com/astral-sh/setup-uv/releases/tag/v8.0.0),
[v9](https://github.com/astral-sh/setup-uv/releases/tag/v9.0.0) and
[v10 migration notes](https://github.com/astral-sh/setup-uv/releases/tag/v10.0.0).

Compatibility review:

- Node 24 Actions require runner v2.327.1 or newer. Hosted `ubuntu-24.04` is
  retained. Checkout's authenticated container-action Git requires v2.329.0;
  this workflow does not use that pattern. `persist-credentials: false` remains
  in both jobs. New fork restrictions target `pull_request_target`/`workflow_run`;
  this workflow uses ordinary `pull_request` and main `push`.
- Setup-node's ESM migration and removal of dummy `NODE_AUTH_TOKEN` need no
  workflow change: no registry authentication or registry-url is configured.
  `package-manager-cache: false` explicitly prevents new automatic npm caching.
  Node **22.16.0** remains the installed OpenSpec toolchain; it is independent
  of the action's internal Node **24** runtime.
- Setup-uv v7 removes unused `server-url`, v8 removes a deprecated manifest and
  floating major/minor tags, v9 changes cache pruning and v10 cache auto-policy.
  This workflow uses none of the removed inputs, pins full SHAs, sets
  `enable-cache: false`, explicitly pins uv 0.12.5 and Python 3.12.14, and retains
  locked installation. The action's newer default uv resolution is not used.
- Read-only `contents` permission, timeout limits and every Python, frontend,
  PostgreSQL, MCP and Docker gate are preserved. No suppression, optional failure,
  unsafe Node override or extra permission was introduced.

## Validation and remaining gaps

| Check | Local result |
| --- | --- |
| `uv sync --locked --python 3.12` | PASS; 50 resolved, 49 checked; lockfile unchanged |
| `uv run --locked pytest` | PASS; 1,055 tests in 45.34 s on Python 3.12.14 Windows |
| `node --test tests/frontend/console.test.cjs` | PASS; 43 tests |
| `uv run --locked ruff check .` | PASS |
| `uv run --locked ruff format --check .` | PASS; 316 files already formatted on the final run (314 before temporary verification tooling) |
| `uv run --locked mypy --strict src` | PASS; 199 source files |
| `openspec validate --all --strict` | PASS; four active changes |
| `git diff --check` and staged deletion check | PASS |
| Mermaid 11.12.0 parser | PASS; four diagrams across README and architecture |
| actionlint 1.7.12 | PASS; official Windows release SHA256 checked; embedded shellcheck/pyflakes integrations unavailable/disabled |

All 86 local documentation links and anchors across eight relevant Markdown files
passed verification. Remote link
availability is not exhaustively crawled. Official action release/pin metadata
and main's hosted run were queried independently.

Hosted CI evidence is [main run 40502942749](https://github.com/danillofratta/agentgate-sdd/actions/runs/40502942749),
whose quality and PostgreSQL/Docker/MCP jobs passed at the starting revision.
**No hosted CI run for this uncommitted diff exists.** No Docker build, new
PostgreSQL integration run, service-restart smoke or real-provider call was
performed in this maintenance increment. Full real-browser keyboard/screen-reader,
zoom/reduced-motion and live failure-injection checks remain open in the
[UX checklist](interactive_lab_ux_acceptance.md). A normal image rebuild is needed
later to serve current-source assets permanently; the original image was restored.

Git remains on the single requested branch with modified/new documentation,
action pins and OpenSpec evidence; only the requested `git rm` deletion is staged.
Temporary verification tools, scripts and npm packages live under ignored
`.lab-artifacts/`; none are project dependencies or tracked deliverables.
