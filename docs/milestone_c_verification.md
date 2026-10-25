# Milestone C verification

Scope: `add-interactive-lab`, Milestone C only, on the existing
`feat/llm_and_chat` branch (explicitly authorized in this session). No branch,
commit, push or archive is created. Business policy and financial handlers are
unchanged. Money remains simulated.

## Delivered boundaries

`chat_turn/endpoint.py` accepts a strict message or explicit UI control under the
lab's existing Host/Origin/session-CSRF protection. `ChatTurnHandler` is a
framework-free command handler with injected model, MCP, sessions and ID ports.
`dependencies.py` constructs concrete collaborators. No sibling feature imports,
database access or direct API/tool dispatch exists in the orchestrator.

The server-side provider gateway uses the configured OpenAI-compatible Chat
Completions contract. A harmless forced `capability_probe` verifies function
calling for the configured model before any business proposal. It is an internal
provider probe, never a fourth MCP business tool. Unsupported models fail closed.
The three allowed MCP schemas are discovered by the official installed SDK.
The model-facing submission schema omits the server-owned idempotency key;
the original discovered wire schema still includes it. No fake MCP responses or
direct FastAPI calls are used by the agent.

The MCP adapter owns initialization, discovery, invocation and closure of real
Streamable HTTP sessions. Internal Docker addressing uses a fixed accepted Host
header; the server's existing exact Host/Origin allowlist remains intact.
No new public port or database is introduced.

Financial execution requires a separate UI command for an operation already
returned to that conversation. The model gets a one-use grant for that exact ID;
additional or changed executions are blocked. Text such as “I approve” carries
no grant. AgentGate still decides ALLOW/DENY/REQUIRE_APPROVAL and enforces owner,
funds, expiry, immutable approval and durable replay. Independent human approval
uses the existing credential-holding manual proxy, outside the agent ports.
Balance execution is permitted automatically because it has no financial effect.

Only validated MCP state populates operation cards and the invocation timeline.
Model prose is explicitly labeled unverified. Unknown tool fields, errors and
instructions are dropped; arguments, IDs and result fields are validated. Provider
errors never echo response bodies, authentication headers or exception details.

## Reproducible verification

Mandatory offline tests use deterministic fake providers, fake MCP failure ports,
and real official-SDK protocol exchanges over in-memory ASGI HTTP transports.
Network and subprocess blocking remain enabled for all ordinary Pytest tests.

```powershell
uv sync --locked --python 3.12
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy --strict src
openspec validate --all --strict
```

The explicit test-only Compose overlay injects a deterministic fake LLM and mounts
verification scripts read-only. Every business call still crosses actual MCP,
FastAPI, the harness and PostgreSQL. It is not the default app or an automatic
fallback when a provider is unavailable.

```powershell
.\scripts\start_lab.ps1
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
uv run --locked python scripts/smoke_lab.py
uv run --locked python scripts/smoke_mcp.py
docker compose -f compose.yaml -f compose.chat-test.yaml up -d --wait frontend
uv run --locked --with playwright python scripts/browser_chat_smoke.py
uv run --locked python scripts/smoke_chat.py
docker compose up -d --wait frontend
```

The browser smoke exercises the five requested example prompts, balance execution,
ALLOW, DENY, pending independent approval, explicit MCP execution, replay, last
operation inspection, HTTP status, invocation timeline and audit. Screenshots
are stored under ignored `.lab-artifacts/`. The persistence smoke verifies funds
and a single success before and after container restarts without resetting data.

## Real-provider evidence

No provider or model was used in this session. No OpenAI/Groq key or model was
configured, and the local provider-key file was absent/empty. The opt-in command
returned `SKIP: no real provider credential; interoperability remains unverified`.
The real-provider smoke was not represented as a pass. After configuring a valid
key and a tool-capable model, run the separate billable check:

```powershell
uv run --locked python scripts/smoke_agent.py --real-provider
```

This checks the configured provider capability, real natural-language balance
interpretation and actual MCP balance submission/execution; it prints only the
provider/model and sanitized operation evidence. It creates a synthetic balance
operation and audit, with no transfer. Browser interoperability with a paid model
must also be checked locally after configuration; deterministic UI evidence does
not establish real-model quality or reliability.

The provider contract follows the official [OpenAI function-calling guide](https://developers.openai.com/api/docs/guides/function-calling)
and [Chat Completions reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).
Groq's compatible endpoint and token/tool parameters are described in its
[API reference](https://console.groq.com/docs/api-reference) and
[tool-use guide](https://console.groq.com/docs/tool-use/overview).

## Limits

This is a trusted-host local educational lab with one synthetic agent and human
identity, not multi-user OAuth. The model has no approval port; the proxy process
also hosts independent human controls and remains trusted. Chat memory is bounded
to 64 sessions, one active turn per session, one-hour idle TTL, 32 operation cards,
configured history length and tool-call budget, and finite per-request/turn waits.
The provider response is capped at 64 KiB and output tokens are bounded. Input is
at most 2,000 characters. There is no recursive or parallel model execution.

Chat text and its in-memory recovery intent do not survive frontend restart or
expiry. Business data and approved/completed operations do survive in PostgreSQL;
retain operation IDs and inspect/replay them through the existing manual dashboard.
Never repeat an uncertain transfer as a new proposal after losing a session:
inspect persisted state first. Within a live session, pending I/O retains the
identical payload/key across timeout, cancellation, disconnection and explicit
Resume. No uncertain mutation is automatically retried with a fresh key.

Provider messages and sanitized operation context leave the host only when the
operator configures a real provider. Costs and retention follow that account's
settings. Do not enter real personal data, financial data or credentials. Model
prose can still be incorrect; the UI never treats it as financial evidence.
Production isolation, per-user rate limits, TLS and tamper-proof external audit
remain outside this local simulation.

## Recorded results

| Gate | Observed result |
| --- | --- |
| Locked Python 3.12 sync | PASS; existing lockfile retained |
| Offline Pytest | 1,029 passed, including 47 new C tests and all architecture/A/B regressions |
| Ruff check / format | PASS; 304 Python files formatted |
| Strict Mypy | PASS; 199 source files |
| Strict OpenSpec validation | Both active changes valid |
| Disposable PostgreSQL integration | 17 passed |
| Docker manual smoke | PASS: all decisions, independent approval/rejection, execution/replay, conservation and PostgreSQL/API restart persistence |
| Docker MCP smoke | PASS: official SDK discovery/invocation, protocol negotiation, human-only approval, concurrency, immutable bindings and restart replay |
| Real Edge manual lab | PASS: full workflow, paginated audit, inspector, mobile 390 px without overflow, no JavaScript errors |
| Real Edge C chat | Partial: real MCP balance, $1 explicit execution/replay and $100.01 pending card verified; Docker engine stopped before human review completed |
| C chat PostgreSQL/restart smoke | Pending: Docker Linux engine became unavailable before this check |
| Real provider | SKIP: no configured credential/model; live interoperability unverified |

The first manual smoke timed out while Docker was building concurrently. A later
API restart also encountered a transient PostgreSQL startup connection failure;
recovery and a separate complete rerun passed without resetting funds. The browser
verification script now pages through existing audit history rather than assuming
the current operation appears in the first page. After the successful A/B checks,
the Docker Linux engine disappeared during C browser QA. The CLI reported an
unavailable engine; `docker desktop start` said Desktop was already running and
the subsequent restart had not recovered it at the time of this record. C tasks
remain unchecked until remaining Docker/chat acceptance is verified.

Verified A/B operation evidence:

- Manual restart/replay: `c200b0b2-878c-40ec-a8f9-b9425a90063d`.
- MCP concurrent approved operation/restart: `33e329ca-601a-4297-a9cb-55f299767d53`.
- Manual browser approved operation: `37b77035-74ce-49c7-bffb-c1265ddd76c7`.

## Changed-file inventory

| Area | Files |
| --- | --- |
| Chat slice | `src/agentgate/features/chat_turn/{__init__,command,endpoint,handler,models,result,validation}.py` |
| Application contracts/state | `src/agentgate/application/chat_conversation.py`, `application/exceptions/agent_unavailable.py`, `application/ports/{agent_mcp_gateway,chat_sessions_gateway,llm_gateway}.py` |
| Adapters/configuration | `src/agentgate/infrastructure/gateways/{openai_chat_gateway,sdk_agent_mcp_gateway}.py`, `infrastructure/runtime/chat_sessions.py`, `infrastructure/security/llm_settings.py` |
| Composition/frontend | `src/agentgate/{dependencies,lab}.py`, `features/demo_lab/static/{app.js,index.html,style.css}` |
| Docker/startup | `compose.yaml`, `compose.chat-test.yaml`, `scripts/start_lab.ps1` |
| Verification | `scripts/{browser_chat_smoke,browser_smoke,smoke_agent,smoke_chat,verify_chat_app}.py`, `tests/agent_support.py`, `tests/api/test_agent_chat.py`, `tests/application/test_agent_safety.py`, `tests/infrastructure/test_agent_integrations.py` |
| Documentation | `README.md`, `docs/{architecture,interactive_lab,milestone_c_verification}.md` |
| Existing OpenSpec change | `openspec/changes/add-interactive-lab/{proposal,design,tasks}.md`, `specs/{agent-chat,mcp-ingress}/spec.md` |

No business policy, financial handler, repository, database schema or dependency
lockfile was changed. Secret files and browser artifacts remain ignored locally.
