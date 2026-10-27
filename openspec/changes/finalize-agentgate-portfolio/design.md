# Design

## Context

See proposal.md. Clean local main is add4688 (#27), the merged UX redesign; hosted run 40502942749 succeeded. C tasks remain unchecked and their report records an interrupted Docker session. Main specifications are empty; requirements remain in active changes. OpenSpec 1.14.3 uses spec-driven artifacts.

## Goals / Non-Goals

Goals: evidence-backed public documentation, source-grounded diagrams, precise closure and reproducible maintenance review.
Non-goals: financial, policy, approval, MCP or execution changes; real-provider calls; Docker builds; publication or archival.

## Decisions

1. Keep the README focused on the browser lab; preserve the detailed SQLite/HTTP procedure in a linked guide rather than deleting useful commands. Separate runtime control flow from inward source dependencies so arrows do not imply the model can access SQL.
2. Capture only real synthetic UI state. Prefer the supplied browser skill; if its execution tool is unavailable, inspect the existing local Playwright support. Do not use provider chat for screenshots; any deterministic provider must be explicitly test-only and labeled. Report unavailable capture rather than supply mockups.
3. Evaluate C against its actual mandatory criteria, using exact test names and hosted job steps. Treat previous Docker reports as historical evidence. Optional provider/browser checks are not silently converted to automated passes. Add only the smallest offline check if an actual mandatory gap exists.
4. Resolve current maintained action releases with the official GitHub API, inspect pinned action metadata/readmes and retain runtime-independent Node 22.16.0 for OpenSpec. Explicitly disable setup-node implicit package caching. Keep setup-uv's uv 0.12.5 and cache disabled even if its action version changes.
5. Update About only through the authenticated repository account, with readback. No homepage is supplied. Use a narrow ci-error.txt ignore rule after checking references and the full log.

## Risks / Trade-offs

- Existing frontend image may predate source → compare served assets with checkout before attributing screenshots to the redesign.
- Historical provider anecdotes cannot prove interoperability → label user-reported evidence and leave the billable automated check unrun.
- New action majors have runner/input changes → inspect official pinned metadata and migration notes, validate YAML and retain hosted execution as pending until a later authorized push.
- Optional browser/keyboard checks may remain unrun → readiness report distinguishes task completion from outstanding visual acceptance.

## Migration Plan

Review and strictly validate artifacts, apply documentation and CI changes, run offline gates and inspect diffs. Reverting documentation/action pins restores prior repository behavior; there is no database migration. No commit, push, PR, merge or archive in this execution.
