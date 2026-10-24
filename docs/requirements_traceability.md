# Requirements traceability

Scope: every `#### Scenario:` in the three active `agentgate-core` specs, not
every possible security property. IDs below are local review labels; scenario
titles are copied exactly. Backticked test references are exact Pytest node IDs,
including selected parameter cases. Run a node with `uv run --locked pytest
'<node ID>'`; the full suite runs all parameter cases. Documentation checks are
explicitly labeled D1–D5 and do not imply an automated behavioral test exists.

Specs: [development-harness](../openspec/changes/agentgate-core/specs/development-harness/spec.md),
[operation-authorization](../openspec/changes/agentgate-core/specs/operation-authorization/spec.md),
[execution-control](../openspec/changes/agentgate-core/specs/execution-control/spec.md).

## Development harness

| ID | Scenario | Existing tests or documentation check |
| --- | --- | --- |
| DH01 | Clean environment verification | D1; `tests/infrastructure/test_request_storage.py::test_network_and_subprocess_guards` |
| DH02 | Quality gate failure | D2 (workflow configuration and local failing-gate check; hosted CI failure not exercised) |
| DH03 | Forbidden dependency is detected | D3; `tests/architecture/test_cqrs.py::test_tool_dispatch_cannot_bypass_the_execution_harness[endpoint]` |
| DH04 | Domain purity and inward imports | D3; `tests/architecture/test_boundaries.py::test_actual_package_dependencies_point_inward` |
| DH05 | Composition exception is narrow | D3; `tests/architecture/test_dependency_injection.py::test_adapter_construction_is_allowed_only_at_the_composition_root` |
| DH06 | Endpoint placement and handler purity | D3; `tests/architecture/test_boundaries.py::test_feature_local_http_grouping_and_endpoint_are_allowed`; `tests/architecture/test_boundaries.py::test_no_obsolete_or_centralized_endpoint_directories` |
| DH07 | Repository ownership and domain organization | D3; `tests/architecture/test_boundaries.py::test_organization_positive_fixtures` |
| DH08 | Domain tested without adapters | `tests/domain/test_entity_invariants.py::test_account_transfer_conserves_funds_and_is_immutable`; `tests/domain/test_entity_invariants.py::test_operation_initial_states_and_transition_graph`; `tests/domain/test_domain_facts.py::test_entity_fact_generation_needs_no_io_environment_clock_or_random_ids` |
| DH09 | Slice boundaries and request contracts | D3; `tests/architecture/test_boundaries.py::test_dependency_cycle_is_rejected`; `tests/architecture/test_cqrs.py::test_mixed_command_and_query_in_one_use_case_is_rejected` |
| DH10 | Handler isolation and dependency injection | `tests/architecture/test_dependency_injection.py::test_request_handler_uses_only_the_injected_ports`; `tests/application/test_approve_operation_handler.py::test_fake_ports_decide_without_accounts_or_tools[APPROVE]`; `tests/application/test_list_audit_handler.py::test_approver_uses_only_read_contract_and_default_page` |
| DH11 | Hidden dependency resolution is rejected | D3; `tests/architecture/test_dependency_injection.py::test_hidden_dependency_resolution_and_framework_di_are_rejected[container = dict()]` |
| DH12 | Acceptance coverage review | D4: exact scenario enumeration, reference/passing-result check and relative-link check |
| DH13 | Demonstration walkthrough | D5; `tests/api/test_full_api_integration.py::test_transfer_full_lifecycle_replay_restart_and_funds[10001]`; `tests/api/test_full_api_integration.py::test_nonexecutable_lifecycles_never_dispatch[deny]`; `tests/api/test_request_endpoint.py::test_endpoint_decisions_and_no_transfer[1-ALLOW-READY]` |

## Operation authorization

| ID | Scenario | Existing tests or documentation check |
| --- | --- | --- |
| OA01 | Agent impersonates an approver | `tests/api/test_adversarial_api.py::test_forged_identity_and_policy_fields[role-APPROVER]`; `tests/api/test_full_api_integration.py::test_identity_ownership_missing_and_invalid_ids`; `tests/api/test_full_api_integration.py::test_queries_are_read_only_even_after_expiry_and_audit_is_paginated` |
| OA02 | Missing or invalid authentication | `tests/api/test_request_endpoint.py::test_authentication_and_role[None-401]`; `tests/api/test_request_endpoint.py::test_authentication_and_role[invalid-401]`; `tests/api/test_full_api_integration.py::test_identity_ownership_missing_and_invalid_ids`; D3 security suite checks every route |
| OA03 | Alternate adapter cannot bypass authorization | `tests/application/test_approve_operation_handler.py::test_direct_handler_cannot_self_approve[False]`; `tests/application/test_execute_operation_handler.py::test_direct_handler_authorization[change1-NotFound]`; `tests/application/test_secure_transfer_handler.py::test_execution_revalidation_denies_without_consuming_approval[tool]`; `tests/application/test_secure_transfer_handler.py::test_execution_revalidation_denies_without_consuming_approval[source]`; `tests/application/test_list_audit_handler.py::test_direct_handler_denies_agent_before_repository_access` |
| OA04 | Transport validation is bypassed | `tests/domain/test_request_values.py::test_invariants_do_not_depend_on_api`; `tests/domain/test_entity_invariants.py::test_approval_cannot_be_reused_for_changed_binding`; `tests/domain/test_entity_invariants.py::test_approval_exact_expiry_for_pending_and_granted[0]`; D3 domain suite checks all invalid values and repeated decisions |
| OA05 | Policy evaluation is a side-effect-free query | `tests/application/test_request_handler.py::test_internal_query_is_pure` |
| OA06 | Malicious or malformed input | `tests/api/test_request_endpoint.py::test_currency_and_missing_key_and_malformed_json`; `tests/api/test_strict_input.py::test_actual_streamed_byte_boundary_with_misleading_content_length[1-16385-413]`; D3 security suite covers forbidden fields, shell/path/SQL-like strings, noninteger/boolean/negative/zero amounts and unsupported currency |
| OA07 | Exact amount boundaries | `tests/domain/test_request_values.py::test_exact_policy_boundaries[1-ALLOW]`; `tests/domain/test_request_values.py::test_exact_policy_boundaries[10000-ALLOW]`; `tests/domain/test_request_values.py::test_exact_policy_boundaries[10001-REQUIRE_APPROVAL]`; `tests/domain/test_request_values.py::test_exact_policy_boundaries[100000-REQUIRE_APPROVAL]`; `tests/domain/test_request_values.py::test_exact_policy_boundaries[100001-DENY]` |
| OA08 | Authorization uncertainty fails closed | `tests/application/test_request_handler.py::test_missing_account_facts_fail_closed`; `tests/api/test_request_endpoint.py::test_policy_exception_secret_is_absent_from_all_output`; D3 application suite exercises invalid/throwing policy ports |
| OA09 | Tool and account permissions are enforced | `tests/infrastructure/test_secure_transfer_execution.py::test_current_sqlite_facts_deny_without_approval_consumption[tools]`; `tests/infrastructure/test_secure_transfer_execution.py::test_current_sqlite_facts_deny_without_approval_consumption[source_accounts]`; `tests/infrastructure/test_secure_transfer_execution.py::test_current_sqlite_facts_deny_without_approval_consumption[funds]`; `tests/api/test_request_endpoint.py::test_request_balance_checks_ownership`; D3 policy/security suites cover unknown accounts |
| OA10 | Approval then explicit execution | `tests/api/test_full_api_integration.py::test_transfer_full_lifecycle_replay_restart_and_funds[10001]`; `tests/application/test_secure_transfer_handler.py::test_fresh_principal_and_policy_are_loaded_inside_transaction` |
| OA11 | Rejection expiry and repeated decisions | `tests/api/test_full_api_integration.py::test_nonexecutable_lifecycles_never_dispatch[reject]`; `tests/api/test_full_api_integration.py::test_nonexecutable_lifecycles_never_dispatch[expired]`; `tests/api/test_full_api_integration.py::test_nonexecutable_lifecycles_never_dispatch[granted_expired]`; `tests/api/test_full_api_integration.py::test_transfer_full_lifecycle_replay_restart_and_funds[10001]`; `tests/domain/test_entity_invariants.py::test_approval_exact_expiry_for_pending_and_granted[0]` |
| OA12 | Approval cannot authorize a changed operation | `tests/api/test_full_api_integration.py::test_identity_ownership_missing_and_invalid_ids`; `tests/application/test_secure_transfer_handler.py::test_execution_revalidation_denies_without_consuming_approval[changed_arguments]`; `tests/application/test_secure_transfer_handler.py::test_execution_revalidation_denies_without_consuming_approval[stale]`; D3 security suite checks HTTP rewrite/transplant attempts |
| OA13 | Secret and injection containment | `tests/api/test_security_sentinels.py::test_exception_messages_are_contained_across_channels[submission]`; `tests/api/test_security_sentinels.py::test_exception_messages_are_contained_across_channels[execution]`; `tests/api/test_security_sentinels.py::test_sqlite_sensitive_errors_preserve_rollback_and_recovery[audit_rollback]`; `tests/api/test_security_sentinels.py::test_success_and_rejection_audit_sentinels_and_read_only_inspection`; D3 security suite checks every sentinel case |
| OA14 | Unsafe startup credentials | `tests/infrastructure/test_request_storage.py::test_environment_missing_credentials_prevents_startup`; D3 startup suite checks absent, duplicate, short, sample and low-diversity credentials without embedding fixture tokens here |

## Execution control

| ID | Scenario | Existing tests or documentation check |
| --- | --- | --- |
| EC01 | Local-only execution | `tests/infrastructure/test_request_storage.py::test_network_and_subprocess_guards`; `tests/api/test_full_api_integration.py::test_balance_execution_and_inspection`; `tests/api/test_full_api_integration.py::test_transfer_full_lifecycle_replay_restart_and_funds[10001]`; all tests use the autouse offline fixture |
| EC02 | Request approval and inspection cannot dispatch | `tests/api/test_request_endpoint.py::test_endpoint_decisions_and_no_transfer[10001-REQUIRE_APPROVAL-PENDING_APPROVAL]`; `tests/application/test_approve_operation_handler.py::test_fake_ports_decide_without_accounts_or_tools[APPROVE]`; `tests/api/test_full_api_integration.py::test_queries_are_read_only_even_after_expiry_and_audit_is_paginated`; D3 dispatch placement gate |
| EC03 | Repeated reads preserve state | `tests/api/test_full_api_integration.py::test_queries_are_read_only_even_after_expiry_and_audit_is_paginated` |
| EC04 | Concurrent identical requests | `tests/infrastructure/test_request_storage.py::test_concurrent_submissions_have_one_atomic_record`; `tests/infrastructure/test_concurrent_execution_recovery.py::test_same_operation_concurrently_commits_one_transfer[False]`; `tests/infrastructure/test_concurrent_execution_recovery.py::test_same_operation_concurrently_commits_one_transfer[True]` (creation and execution races tested separately; see limitations) |
| EC05 | Conflict restart and principal isolation | `tests/api/test_request_endpoint.py::test_endpoint_idempotency_json_order_and_conflict`; `tests/api/test_full_api_integration.py::test_transfer_full_lifecycle_replay_restart_and_funds[10001]`; `tests/infrastructure/test_request_storage.py::test_principal_scoped_keys`; `tests/api/test_full_api_integration.py::test_identity_ownership_missing_and_invalid_ids` |
| EC06 | State changes after authorization | `tests/infrastructure/test_secure_transfer_execution.py::test_current_sqlite_facts_deny_without_approval_consumption[funds]`; `tests/infrastructure/test_secure_transfer_execution.py::test_current_sqlite_facts_deny_without_approval_consumption[tools]`; `tests/application/test_secure_transfer_handler.py::test_fresh_principal_and_policy_are_loaded_inside_transaction` |
| EC07 | Pending and terminal execution | `tests/api/test_full_api_integration.py::test_nonexecutable_lifecycles_never_dispatch[pending]`; `tests/api/test_full_api_integration.py::test_transfer_full_lifecycle_replay_restart_and_funds[10001]` |
| EC08 | Audit write failure | `tests/infrastructure/test_secure_transfer_execution.py::test_every_write_failure_rolls_back_entire_transfer[audit-True]`; `tests/api/test_full_api_integration.py::test_storage_failure_is_sanitized_and_rolls_back` |
| EC09 | Concurrent insufficient funds | `tests/infrastructure/test_concurrent_execution_recovery.py::test_competing_transfers_revalidate_funds_under_write_lock[False]`; `tests/infrastructure/test_concurrent_execution_recovery.py::test_competing_transfers_revalidate_funds_under_write_lock[True]` |
| EC10 | Adapter boundaries preserve one transaction | `tests/infrastructure/test_secure_transfer_execution.py::test_every_write_failure_rolls_back_entire_transfer[consumption-True]`; `tests/infrastructure/test_secure_transfer_execution.py::test_every_write_failure_rolls_back_entire_transfer[result-True]`; `tests/infrastructure/test_secure_transfer_execution.py::test_every_write_failure_rolls_back_entire_transfer[second_account-True]`; `tests/infrastructure/test_transactional_persistence.py::test_repository_contracts_share_uncommitted_connection_and_reopen`; `tests/infrastructure/test_balance_execution.py::test_adapters_have_no_transaction_or_io_capability` |
| EC11 | Deadline prevents a late write | `tests/infrastructure/test_execution_deadline_retry.py::test_timeout_rolls_back_every_effect_and_closes_connection[commit]`; `tests/infrastructure/test_execution_deadline_retry.py::test_progress_interrupt_rolls_back_and_stops_statement`; `tests/api/test_full_api_integration.py::test_terminal_http_result_is_durable_and_replayed[TIMED_OUT]` |
| EC12 | Retry budget and classification | `tests/infrastructure/test_execution_failure_recovery.py::test_evidence_precedes_each_attempt_and_exact_2_2_1_counts[retry_success-2]`; `tests/infrastructure/test_execution_failure_recovery.py::test_evidence_precedes_each_attempt_and_exact_2_2_1_counts[locks_exhausted-2]`; `tests/infrastructure/test_execution_failure_recovery.py::test_evidence_precedes_each_attempt_and_exact_2_2_1_counts[nonretryable-1]`; `tests/infrastructure/test_execution_deadline_retry.py::test_second_attempt_still_expires_at_original_deadline` |
| EC13 | Uncertain commit is not retried blindly | `tests/infrastructure/test_execution_deadline_retry.py::test_uncertain_commit_never_retried_even_if_lock_shaped[False]`; `tests/infrastructure/test_execution_deadline_retry.py::test_uncertain_commit_never_retried_even_if_lock_shaped[True]`; `tests/api/test_full_api_integration.py::test_uncertain_commit_returns_503_then_durable_execution` |
| EC14 | Lifecycle evidence survives restart | `tests/infrastructure/test_secure_transfer_execution.py::test_atomic_transfer_reopen_terminal_replay_and_idempotent_submission[True]`; `tests/infrastructure/test_balance_execution.py::test_existing_audit_http_adapter_can_render_execution_evidence`; D3 approval walkthrough checks human identity and ordered sanitized decision evidence |
| EC15 | Audit least privilege and bounded output | `tests/api/test_full_api_integration.py::test_queries_are_read_only_even_after_expiry_and_audit_is_paginated`; `tests/application/test_list_audit_handler.py::test_direct_handler_denies_agent_before_repository_access` |

## Reproducible documentation checks

**D1 — Installation and gates.** Follow [README installation](../README.md#install-and-verify)
in a fresh checkout with the documented interpreter/tool versions. Expect every
command to exit zero. `uv sync --locked` must leave the lockfile unchanged.
This release-doc verification used the existing local locked environment; it
does not claim a clean-machine or hosted CI run (task 7.1 remains pending).

**D2 — CI configuration and failure propagation.** Inspect
[ci.yml](../.github/workflows/ci.yml): push/PR on main, read-only permissions,
pinned actions, Python 3.12.14, locked sync, pinned OpenSpec, all five gates,
ten-minute timeout, no `continue-on-error`. A local gate failure probe, without
editing tracked source, is:

```powershell
$probe = Join-Path ([IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N') + '.py')
try {
    Set-Content -LiteralPath $probe -Value 'import os' -Encoding utf8
    uv run --locked ruff check --no-cache --isolated --select F401 $probe
    if ($LASTEXITCODE -ne 1) { throw 'Expected failing lint gate' }
} finally { Remove-Item -LiteralPath $probe }
```

Expect F401 and exit 1 from Ruff. This demonstrates a failing local gate;
inspection verifies the workflow invokes it normally. A deliberately failing
hosted PR/check and repository branch protection have not been verified here.

**D3 — Focused existing suites.** These commands exercise all positive/negative
fixtures and parameter cases, beyond the representative exact IDs in the table:

```powershell
uv run --locked pytest tests/architecture tests/domain tests/application
uv run --locked pytest tests/api/test_adversarial_api.py tests/api/test_strict_input.py tests/api/test_security_sentinels.py
uv run --locked pytest tests/infrastructure/test_request_storage.py tests/infrastructure/test_human_approval_walkthrough.py
```

Expect all to pass; the complete Pytest command includes these suites. Inspect
assertions as well as results: an existing green test is evidence only for the
behaviors it asserts.

**D4 — Scenario, node, result and relative-link integrity.** Run from repository
root (the report path is ignored by Git):

```powershell
uv run --locked pytest --junitxml=.pytest_cache/release-docs.xml
uv run --locked python docs/verify_release.py --junit .pytest_cache/release-docs.xml
```

The checker compares all scenario titles with table rows, verifies exact node IDs
against successful report entries and checks relative Markdown file/heading
links in README and docs. It rejects missing/duplicate scenarios, failed or
unreported nodes, missing links and unused/missing check definitions. It does
not certify the meaning of assertions or automatically execute prose checks.
Review the matrix and checks above for semantic coverage. The architecture
constructor example can be extracted and executed without opening storage.

**D5 — Public demo.** Follow the README's setup, server, HTTP and balance blocks
in order on a fresh database. Expect the three decisions, one grant, one actual
simulated transfer of 10,001 cents, unchanged result on duplicate execution and
submission, one success event and balances 989,999 / 1,010,001 (total 2,000,000).
Expected conflict/forbidden examples are explained after the executable blocks.
This checks documentation commands, not final restart acceptance (task 7.2).

## Coverage limits and verification record

All 42 scenarios are enumerated: 13 development, 14 authorization and 15 execution.
None is unmapped. Documentation checks are allowed scenario evidence, not a
claim that every scenario has one comprehensive automated test. In particular:

- Concurrent identical creation and concurrent execution are separate tests;
  there is no single synchronized submit-then-execute race test mapped here.
- Restart evidence uses closed/reopened connections and reconstructed components;
  it does not demonstrate abrupt OS process termination or power-loss durability.
- Lifecycle audit/approver identity is verified by complementary tests; there is
  no single test asserting the entire remote HTTP walkthrough after process restart.
- Clean-machine acceptance, hosted CI failure behavior, later Python versions
  and final restarted manual demo remain unverified here. Tasks 7.1/7.2 stay open.
- Sentinel coverage is not an application-owned structured logging pipeline,
  production distributed-transaction proof or comprehensive security certification.

On 2026-10-24, Python 3.12.14 locked sync and the full existing suite passed:
924 tests, with one Starlette/HTTPX deprecation warning. Ruff lint/format, strict
Mypy (151 source files) and strict OpenSpec validation passed. No business code,
dependency or framework was added for release documentation.

Release-documentation checks also passed: 42 scenario rows, 86 exact passing
test references, all five documentation-check definitions and 71 relative links.
The constructor example executed without opening storage. CI configuration was
inspected and the temporary Ruff F401 probe returned the expected exit 1.
README setup/server/HTTP/balance blocks executed against a disposable database:
ALLOW, DENY, REQUIRE_APPROVAL, GRANTED, SUCCEEDED, identical execution replay,
idempotent submission, one correlated success and the expected conserved balances.
Repeated approval and conflicting submission returned 409; denied execution
returned 403. The demo job was stopped and its database removed. No service
restart, clean-machine acceptance, hosted workflow run, commit or push was performed.
