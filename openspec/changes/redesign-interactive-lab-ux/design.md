# Design

## Context

See proposal.md. Existing vanilla assets create independent chat cards and a second manual operation view. The fixed credential-holding proxy exposes session, account/audit reads, request/inspect/approval/execute and chat status/turn. Chat execute goes through MCP; manual execute goes through the same API harness. Inspection includes approval timestamps but no requesting-principal field. Queries do not persist expiration. Existing operation states are DENIED, READY, PENDING_APPROVAL, SUCCEEDED, REJECTED, EXPIRED, FAILED and TIMED_OUT; EXECUTING may appear in sanitized MCP data. Uncertainty is transport context, not a new business state.

## Goals / Non-Goals

Goals: a single operation DOM subtree usable beside chat and in Operations, verified state before actions, understandable amounts and independent review. Non-goals: backend policy/state/schema changes, production human authentication, durable chat memory, runtime dependencies or infrastructure execution. Preserve the user's pre-existing chat changes and add-interactive-lab unchanged.

## Decisions

1. Keep vanilla HTML/CSS/JS and move the same operation panel between view slots. Dashboard lists brief resume links, never parallel action cards. Avoid a framework migration and avoid merely hiding competing workflows. Navigation uses hashes with operation IDs in local storage as recovery hints; all business data is fetched again.
2. Centralize a pure presentation mapping and exact decimal parser in app.js, testable in Node without third-party dependencies. Map real states and approval metadata to labels, stepper and permitted actions; unknown states fail closed. Elapsed deadlines only produce a local warning. Execute refreshes the operation first. Failed/timed-out replay explicitly retrieves the stored outcome, not a financial retry.
3. One persisted recovery record owns mutation eligibility alongside the shared in-flight lock. Its kind (manual proposal, operation action or chat call), unique owner token, original operation ID and exact proposal payload/key replace contradictory uncertainty flags. Capture it before mutation I/O. Check the same guard in controls, command functions and the HTTP mutation boundary; only explicit recovery may reuse the original owner. Reads never unlock another identity. Delayed responses must match the owner token before changing recovery or business presentation. Chat operations are inspected through the API for full approval metadata before display. Preserve MCP for chat-associated execution.
4. Independent review uses a native modal dialog with exact immutable details, explicit confirmation, reject, cancel and focus restoration. It identifies the local synthetic requesting agent while stating the API does not expose its identifier; audit remains the evidence source. Deadline checks run locally and state is refreshed before the final decision.
5. Render model output with text nodes and a small safe inline bold/code formatter; never inject HTML or load remote Markdown. Inspector projects allowlisted technical fields and excludes conversation/rejected payloads. Fixed sanitized error messages replace exception/response text. Keep CSP, Host/Origin and credential isolation unchanged.
6. Session renewal after LAB_FORBIDDEN changes credentials only; preserve the recovery owner, operation ID, payload and key even if renewal/reconciliation fails repeatedly. Never automatically resend a mutation. An explicit recovery of a proposal with no known ID repeats its exact original key/payload through the existing idempotent submission contract; a known ID uses read-only inspection. Persist recovery before mutation; if persistence fails, refuse mutation. Reload migrates legacy pending-proposal/chat markers without generating a new intent. No chat text or credentials are stored. Session rotation loses chat memory: a known original ID remains inspectable; a chat call without any recoverable operation reference stays blocked and explicitly requires recovery of that original reference/server context, rather than accepting an unrelated ID as proof.
7. Neutral/emerald palette, readable type, restrained borders, responsive two-column assistant/workflow and single-column mobile. Navigation remains visible on mobile. Textual stage status, aria-current, busy/live feedback, skip link, focus rings and reduced-motion support are first-class.
8. Scope financial error handling to the mutation and authoritative inspection only. Audit retrieval has its own unavailable message and retry action; retain confirmed operation state, pagination position and continuation controls on timeout/HTTP failure. Initialization preserves restoration errors separately from connection/provider/audit notices, with an accessible restore form. Chat processing is finalized on every exit path; distinguish a confirmed provider rejection from an unconfirmed financial outcome and offer only explicit original-call recovery.

## Review regression acceptance

- Lost proposal/execute/approval response followed by LAB_FORBIDDEN, failed renewal, repeated recovery errors and reload preserves exactly the original identity; no automatic POST occurs during renewal/reload.
- Every mutation entry point, including direct command calls, is rejected while another recovery owns the guard. Concurrent calls cannot share the in-flight lease. Unrelated reads/chat responses and stale owner tokens cannot clear recovery.
- Confirmed submit/inspection followed by audit timeout, HTTP error or retry leaves business state confirmed and continuation available; audit can be retried independently.
- Malformed, missing and temporarily unavailable saved IDs retain their specific initialization error through provider/audit initialization and reload.
- Network/timeout/HTTP provider failure leaves no stale Processing indicator, reports sanitized nearby chat guidance and preserves the original recovery identity when effects are unconfirmed.

## Risks / Trade-offs

- Browser clock drift → local deadline guard is conservative UX only; backend remains authoritative.
- No global operation list endpoint → recent rows use bounded browser IDs/audit IDs and explicitly describe their limited scope.
- Chat memory lost on session rotation/restart → retain persisted operation IDs and allow manual inspection/execution; explain memory limits.
- No installed browser automation dependency → run focused offline Node behavior and real ASGI lifecycle tests; document unrun visual/keyboard browser checks honestly.
- Large persistent audit → retain pagination and operation filtering; do not claim unloaded records are absent.

## Migration Plan

Validate artifacts before code. Replace static assets in the existing frontend service only; no data migration. Run locked sync, focused offline tests, Ruff, formatting, strict Mypy and strict OpenSpec. Rebuild only frontend with Docker instructions supplied but not executed. Rollback restores prior assets/rebuilds frontend, preserving volumes and secrets.
