# Proposal

## Why

The lab splits one transfer across competing chat cards, manual controls and technical panels. Users cannot reliably discover independent approval, explicit execution or safe replay. A guided console must make the persisted operation and its next action clear.

## What Changes

- Provide Dashboard, AI Assistant and Operations navigation, with one shared authoritative operation workspace and a collapsed Developer Inspector.
- Translate real policy, approval and execution states into business language and a five-stage stepper. Keep approval and execution deliberately separate.
- Replace cents entry with exact USD parsing, verified policy presets, immutable submitted intent and explicit new-operation actions.
- Restore persisted operation IDs, show recent operations, renew expired browser sessions safely, and handle provider/MCP failures without financial retries.
- Add focused offline UI/application verification, responsive/accessibility requirements, documentation and a manual acceptance checklist.
- Correct all five review findings: retain original recovery identity through CSRF/reload, enforce one mutation eligibility guard, isolate audit-read failures, preserve restoration errors and finish failed chat processing states. Add focused regressions before completing the reopened tasks.

## Capabilities

### New Capabilities

- `guided-operation-console`: navigation, operation lifecycle, independent review, safe chat presentation, recovery and accessible interaction.

### Modified Capabilities

None: main specifications are empty. The active add-interactive-lab artifacts remain unchanged; this adds a UX contract over their existing API and security behavior.

## Impact

Primary scope is demo_lab/static HTML/CSS/JavaScript, focused tests and lab documentation. Preserve existing HTTP/MCP contracts, PostgreSQL/SQLite adapters, policy and runtime harness. No runtime UI framework, backend business changes, credentials in browser, real provider calls, Docker execution, branches, commits, push or archival. The user explicitly authorizes planning followed by implementation in this session.
