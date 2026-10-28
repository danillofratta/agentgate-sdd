# Proposal

## Why

The Python project currently owns browser assets and all deployment processes share a build context. Explicit ownership will let the existing console and modular monolith build independently while retaining financial and transport safeguards.

## What Changes

- Relocate the single Python project to `backend/services/agentgate/`; keep API, Lab BFF and MCP as separate processes of that project.
- Extract the existing vanilla JavaScript console to `frontend/apps/lab-console/`, served by Nginx with same-origin `/lab/*` proxying to the credential-holding BFF.
- Relocate seven domain StrEnums to `domain/enums/`; retain genuine value objects, feature DTOs and CQRS requests/results in their current architectural roles.
- Move cross-application verification to `tests/e2e/`, keep root Compose entrypoints and preserve existing volumes, secret paths, HTTP and MCP contracts.
- Update scripts, CI, contributor guidance and documentation for independently verifiable phases A, B and C.

## Capabilities

### New Capabilities

- `lab-delivery`: independent browser and backend builds, same-origin local lab delivery and retained security boundaries. No main specs exist; existing behavior requirements remain in the four active completed changes.

### Modified Capabilities

None. Existing business authorization, execution, chat and persistence contracts remain unchanged. Internal relocation and enum organization do not create new business requirements.

## Impact

All Python source/tests/packaging paths, browser assets/tests, Docker contexts, Compose, CI and repository scripts/docs. The development Python working directory changes. Static routes move from BFF to Nginx; public browser and JSON URLs remain stable. No database migration, financial behavior change, paid model invocation, new framework, commit, push or archive.
