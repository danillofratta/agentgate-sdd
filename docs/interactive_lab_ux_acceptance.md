# Guided console: verification and acceptance

## Portfolio verification follow-up — 2026-10-27

The historical implementation-session record below remains for attribution.
Current-source Edge QA now verifies all five prompts with the explicit test LLM
and real MCP/API/PostgreSQL, separate review/execution/replay, one shared operation
panel, completed-ID reload, Escape/focus restoration, widths 1440/820/390 without
horizontal overflow and no JavaScript errors. Real current screenshots are in
[media](media/README.md); [C verification](milestone_c_verification.md) describes
the temporary read-only source mount and restoration of the default frontend.

This focused pass does not complete every item in the manual checklist below:
200% zoom, reduced motion, complete Tab/Enter/focus trapping and screen-reader
review, plus live injected transport/storage failures remain unverified in a
real browser. Their deterministic frontend regressions pass. The existing
optional browser script failed a hidden-reference assertion against an older
image; its entire run is not claimed as passing. No production behavior changed.

## What changed

The former lab exposed raw cents, repeated chat operation cards, a second manual
workflow and always-visible technical output. Approval was hard to discover and
the next action required moving between unrelated panels.

Dashboard, AI Assistant and Operations now share one active operation panel.
The five-stage stepper maps persisted policy/approval/operation state. Independent
human review opens a separate confirmation dialog; approval never executes.
USD entry parses decimal strings into exact safe integer cents. Submitted drafts
are immutable. Execution/replay refresh the original ID first; chat-associated
execution retains MCP. Deadlines, failures, uncertainty, provider/MCP availability
and session renewal have explicit guidance. Technical output is collapsed and
allowlisted. No business logic or API contract changed.

## Files delivered

- `openspec/changes/redesign-interactive-lab-ux/`: proposal, design, specification,
  task tracking and CLI metadata; existing changes are untouched.
- `src/agentgate/features/demo_lab/static/{index.html,style.css,app.js}`: console,
  shared workflow, independent review, safe chat and recovery.
- `tests/frontend/console.test.cjs`: offline Node behavior tests with a minimal DOM
  adapter and deterministic API responses. This is not a browser layout engine.
- `tests/api/test_interactive_lab.py`: actual protected proxy/API/SQLite lifecycle,
  deliberate approval without financial effect, renewal, expiry and safe replay.
- `scripts/browser_smoke.py`, `scripts/browser_chat_smoke.py`: optional updated
  real-browser checks; not executed in this session.
- `.github/workflows/ci.yml`: run offline frontend checks in the existing quality job.
- `docs/interactive_lab.md` and this checklist: workflow and verification limits.

Pre-existing edits to chat handlers, validation, agent tests and
`scripts/verify_chat_app.py` were preserved. No branches, commits, pushes or
archival were performed.

## Recorded automated verification — 2026-10-26

- `uv sync --locked --python 3.12`: passed (50 packages resolved; 49 checked).
- `uv run --locked pytest tests/api/test_interactive_lab.py tests/api/test_agent_chat.py tests/application/test_agent_safety.py tests/infrastructure/test_agent_integrations.py tests/architecture -q`: 214 passed.
- `node --test tests/frontend/console.test.cjs`: 43 passed; offline checks for exact
  cents, state guards, shared panel, safe formatting, inspector redaction,
  duplicate locks, CSRF renewal without replay, uncertainty, independent review,
  invalid IDs, original-key recovery, reload and explicit MCP execution grant.
- `uv run --locked ruff check .`: passed.
- `uv run --locked ruff format --check .`: passed (309 files).
- `uv run --locked mypy --strict src`: passed (199 source files).
- `openspec validate --all --strict`: passed (all three active changes).

No Docker/Compose/build command, real model call, full integration suite or
PostgreSQL instance was executed. Application tests use temporary SQLite storage,
fake clocks/providers and in-process real MCP/API boundaries; network and
subprocesses remain blocked. The focused selection is not the entire Pytest suite.

## Review corrections and regression evidence

| Finding | Root cause | Correction and evidence |
| --- | --- | --- |
| CSRF discarded original intent | Broad submission catch treated session renewal as permission to discard recovery data | Persist exact proposal/key or original operation ID before I/O; renewal never resends or discards unresolved identity; regressions include repeated rejection, failed renewal, reload and successful same-key reconciliation |
| Incomplete uncertainty guard | Independent flags and chat success could unlock unrelated financial state | One identity-bound recovery record and shared mutation lease guard controls, commands and HTTP; concurrent sends, unrelated reads and delayed owner responses cannot clear it |
| Audit failure changed financial state | Auxiliary audit retrieval shared the financial exception boundary | Audit-only failure status and retry preserve confirmed business state and continuation; timeout/HTTP regressions cover submission and original-ID inspection |
| Saved-ID error disappeared | Startup overwrote the restoration notice with readiness | Retain restoration failure through provider/audit initialization; malformed, missing and unavailable IDs are tested across reload |
| Chat kept Processing | Request exceptions bypassed the chat completion branch | Every chat request failure ends processing with nearby sanitized guidance; network, timeout, HTTP and confirmed-provider failure regressions retain identity or allow safe manual mode as appropriate |

The frontend suite now has 23 additional regression cases. The API suite adds a
real in-process proxy/API/SQLite scenario with three CSRF renewals, the same
idempotency key and operation, separate approval, explicit execution and replay,
verifying one debit/credit and one success audit. Browser behavior remains unrun.

Recovery storage is required before financial mutations. With blocked storage,
the console refuses the mutation and retains the in-memory original. A known
original operation ID uses read-only reconciliation; an unknown manual proposal
uses only an explicit identical-key submission. No arbitrary inspected ID can
unlock another request. If a chat session is lost before returning any original
operation reference, the existing process-local chat contract cannot reconstruct
the original server-owned key. The console remains blocked and identifies that
limitation instead of claiming recovery or generating a replacement operation.
This change does not introduce backend contracts or durable chat persistence.

## Manual browser acceptance — pending

No visual browser test was run. Playwright is not installed in the locked
environment. Responsive CSS and DOM behavior have been checked as source/logic;
actual layout, dialog focus trapping and rendering remain unverified. Existing
screenshots predate this redesign and are not evidence for it.

Run the following against persisted local simulation state, with synthetic data
only. Keep account balances sufficient for the selected scenarios.

1. At 1440px, 820px and 390px, verify readable typography, restrained colors,
   visible navigation, no horizontal page overflow and reachable next actions.
   Check 200% zoom and reduced motion.
2. Tab from the skip link through navigation, forms and next actions. Verify
   visible focus, screen-reader names, loading announcements and disabled controls.
   Open Review with Enter, cancel with Escape and check focus returns to Review.
   Verify dialog focus trapping and focus after approval/rejection.
3. Ask “What is Alice’s balance?” with the configured fake-provider test overlay.
   Verify the stored USD balance, readable messages and distinct unverified model
   text. No exposed bold markers or executable model HTML should appear.
4. Ask for a $1 transfer. Verify Authorized — not executed and unchanged balances.
   Explicitly execute, view receipt, inspect audit, replay and verify one debit
   and one success event. Check the MCP timeline for the exact operation ID.
5. Ask for $100.01. Review agent context, accounts, exact amount, original policy
   and deadline. Approval must require confirmation; balance must remain unchanged
   until Execute approved transfer is clicked.
6. Submit another pending operation and reject. Submit $1,000.01 and observe
   policy denial. Neither offers execution. Check New operation behavior.
7. Let approval expire, both pending and already granted. Confirm no active
   approval/execution action remains. Local deadline guidance must not falsely
   claim inspection persisted an EXPIRED transition.
8. Switch between Assistant and Operations. Confirm one operation panel and
   unchanged ID/immutable intent. Return to Dashboard and resume a recent row.
9. Reload and restart frontend/API while retaining data. Resume by saved ID and
   replay success; verify no second debit. Chat history/association must not be
   described as durable. Invalid/missing IDs must produce sanitized guidance.
10. Restart frontend between a GET and mutation. Verify explicit CSRF rejection
    renews the session without replay. Repeat deliberately after reviewing state.
11. Disable provider, disconnect MCP and interrupt a transfer response. Verify
    sanitized errors, no silent retry, loading locks, original-call recovery and
    state reconciliation. After unconfirmed chat and reload, reconcile the retained
    original ID; inspecting an unrelated operation must not unlock new proposals.
    If no original ID/context is recoverable, verify explicit blocked guidance.
    Manual mode must work when no call is uncertain.
12. Interrupt manual submission, reload, then reconcile explicitly. Verify the
    retained key/payload and only one operation. Editing a new draft must never
    alter an existing persisted intent.
13. Inject model text claiming denied transfers succeeded and containing HTML or
    links. Persisted policy stays authoritative and injected HTML never runs.
    Check HTTP/MCP/audit for absence of credentials, CSRF, rejected raw input,
    provider secrets, arbitrary errors and conversation text.
14. Page through audit until the active operation is visible. Confirm original
    policy, independent approver, execution and one success. Check failure/timeout
    guidance with existing deterministic fixtures; do not invent frontend balances.
15. Lose a submission response, restart the frontend, trigger LAB_FORBIDDEN and
    repeat reconciliation failures. Reload and verify the identical original
    payload/key and accessible global recovery action; renewal must not POST again.
16. Fail audit retrieval after confirming a request or inspecting the original ID.
    Verify continuation remains enabled and Retry audit retrieval sends only GETs.
17. Restore malformed/nonexistent IDs and verify startup preserves the specific
    failure. Interrupt chat and verify Processing is replaced by useful nearby
    guidance, with original recovery identity retained if effects are unknown.

Optional scripts (not run):

```powershell
uv run --locked --with playwright==1.56.0 python scripts/browser_smoke.py
# Requires the explicitly configured fake-provider chat test environment:
uv run --locked --with playwright==1.56.0 python scripts/browser_chat_smoke.py
```

## Rebuild only the affected frontend service

With the existing lab provisioned and API/MCP/database running:

```powershell
docker compose build frontend
docker compose up -d --no-deps frontend
```

These are instructions only; they were not executed. They retain volumes/secrets
and do not rebuild or restart API/MCP/PostgreSQL. Open `http://127.0.0.1:8080` and
refresh. Rollback restores the former assets and rebuilds frontend; no database
migration is involved.
