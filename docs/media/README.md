# Real AgentGate browser captures

Captured on 2026-10-27 with headless Microsoft Edge and Playwright 1.56.0 at
1440 × 1080, JPEG quality 82. These show the actual application with synthetic
accounts and simulated USD. No working secrets, provider keys, browser session
identifiers or private data are visible.

| Asset | What it shows | Bytes |
| --- | --- | ---: |
| [dashboard.jpg](dashboard.jpg) | Live synthetic balances, navigation and recent-operation references | 93,448 |
| [assistant.jpg](assistant.jpg) | A $1 proposal authorized but awaiting explicit execution | 118,512 |
| [human-approval.jpg](human-approval.jpg) | Independent review of the immutable $100.01 request; approval checkbox unchecked | 97,803 |

The existing `compose.chat-test.yaml` test-only factory supplied a deterministic
`VerificationLlm`. The SDK MCP client, MCP server, FastAPI and PostgreSQL were
real. No billable provider was called. The test model is visibly labeled in chat;
screenshots establish UI/workflow behavior, not live AI comprehension.

The existing image had older assets, so a temporary read-only source mount served
the current checkout without a Docker build. Served HTML/CSS/JS matched local
source after newline normalization. The normal frontend configuration was
restored after capture. Balances reflect previous local simulations and were not
reset. Visible UUIDs identify synthetic operations, not authentication sessions.

Visual inspection confirmed readable dashboard, authoritative intent and human
review, with the inspector collapsed and no secret values. See
[C evidence](../milestone_c_verification.md) for verification scope and
[UX acceptance](../interactive_lab_ux_acceptance.md) for remaining manual checks.
