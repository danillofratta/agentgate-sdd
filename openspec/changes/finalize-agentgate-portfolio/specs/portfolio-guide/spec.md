# Spec Delta

## Purpose

Help technical readers discover and reproduce the simulated AgentGate experience while distinguishing implemented controls from verified evidence and remaining limitations.

## ADDED Requirements

### Requirement: Discoverable accurate demonstration
The public guide SHALL explain the simulation, visible workflow, actual architecture and Docker/PostgreSQL onboarding, with secondary local SQLite instructions. Visuals MUST depict the real application without secrets; unavailable captures SHALL be explicitly reported without broken references.

#### Scenario: First-time reader
- **WHEN** a reader opens the README
- **THEN** the introduction identifies the problem, observable demo, security boundaries and simulated money, with working paths to startup and technical details

#### Scenario: Capture unavailable
- **WHEN** a real browser capture cannot be produced
- **THEN** the guide remains usable without fabricated images and the delivery report identifies the missing visual evidence

### Requirement: Attributed closure evidence
Closure documentation SHALL map mandatory milestone criteria to implementation and verification. It MUST distinguish current offline results, historical manual checks, user-reported provider demonstrations and hosted CI. Unsupported criteria SHALL remain open; archive readiness SHALL NOT perform archival.

#### Scenario: Provider demonstration reported
- **WHEN** a user reports a successful Groq demonstration without a reproducible automated run
- **THEN** evidence labels it user-reported and does not claim a provider smoke-test pass or general prompt-injection immunity

### Requirement: Verifiable repository maintenance
Maintenance SHALL retain immutable action pins, least privilege, locked installation and existing quality gates while selecting Node 24-compatible actions. Public metadata MUST describe the simulation accurately without a fabricated hosted URL.

#### Scenario: CI upgrade reviewed
- **WHEN** action versions are upgraded
- **THEN** official version-to-commit resolution, runtime compatibility and local validation are recorded separately from future hosted CI results
