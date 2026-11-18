# Source file index

This index locates the first-party implementation files behind the product.

It groups files by source directory and lists selected declared interfaces.

The table gives line totals, declaration counts, and selected interface names.

The index contains 149 implementation files.

Python definition counts include module functions, classes, and their declared methods.

Other file types list explicit function and class declarations where available.

The interface column shows up to twelve definitions for each file.


## ref_all_executor

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [ref_all_executor/__init__.py](../ref_all_executor/__init__.py#L1) | 1 | 0 | Module declarations or executable statements |
| [ref_all_executor/__main__.py](../ref_all_executor/__main__.py#L1) | 6 | 0 | Module declarations or executable statements |
| [ref_all_executor/agent_profiles.py](../ref_all_executor/agent_profiles.py#L1) | 30 | 2 | `HeadProfile`, `head_profile` |
| [ref_all_executor/agent_workspace.py](../ref_all_executor/agent_workspace.py#L1) | 218 | 9 | `AgentWorkspaceError`, `sync_agent_canvas_workspace`, `_safe_subject_name`, `_source_snapshot`, `_read_marker`, `_existing_source_mount`, `_marker_matches`, `_remove_existing_workspace`, `_run` |
| [ref_all_executor/arcticbase_client.py](../ref_all_executor/arcticbase_client.py#L1) | 252 | 46 | `ArcticBaseClient`, `ArcticBaseClient.__init__`, `ArcticBaseClient._req`, `ArcticBaseClient._raw`, `ArcticBaseClient._req_once`, `ArcticBaseClient.create_subject`, `ArcticBaseClient.get_workbench`, `ArcticBaseClient.patch_workbench`, `ArcticBaseClient.list_subjects`, `ArcticBaseClient.mirror_subject`, `ArcticBaseClient.ops_status`, `ArcticBaseClient.ops_agents`; 34 additional definitions |
| [ref_all_executor/artifact_store.py](../ref_all_executor/artifact_store.py#L1) | 67 | 1 | `save_artifact` |
| [ref_all_executor/auto_client.py](../ref_all_executor/auto_client.py#L1) | 108 | 19 | `_urllib_transport`, `AutoClient`, `AutoClient.__init__`, `AutoClient.api_key`, `AutoClient._req`, `AutoClient.cron`, `AutoClient.event`, `AutoClient.create_prompt_automation`, `AutoClient.create_code_automation`, `AutoClient.upload_tarball`, `AutoClient.dispatch`, `AutoClient.list_runs`; 7 additional definitions |
| [ref_all_executor/cleanup.py](../ref_all_executor/cleanup.py#L1) | 150 | 13 | `RefallCleanup`, `RefallCleanup.__init__`, `RefallCleanup.run`, `RefallCleanup._mark_stop`, `RefallCleanup._active_cids_path`, `RefallCleanup._read_active_cids`, `RefallCleanup._stop_conversations`, `RefallCleanup._cmd`, `RefallCleanup._stop_containers`, `RefallCleanup._pgrep`, `RefallCleanup._lsof_port`, `RefallCleanup._parse_pids`; 1 additional definitions |
| [ref_all_executor/cli.py](../ref_all_executor/cli.py#L1) | 278 | 2 | `_parse_process_patterns`, `main` |
| [ref_all_executor/config.py](../ref_all_executor/config.py#L1) | 280 | 16 | `_private_lan_ipv4`, `resolve_public_base`, `session_api_key`, `local_workspace`, `remote_workspace`, `_ssh_resource_aliases`, `_build_hosts`, `ssh_resource_instructions`, `subject_workspace`, `subject_agent_workspace`, `prepare_subject_agent_workspace`, `agent_workspace_host_path`; 4 additional definitions |
| [ref_all_executor/context_fingerprint.py](../ref_all_executor/context_fingerprint.py#L1) | 161 | 7 | `fingerprint_directory`, `_sha256`, `_file_probe`, `_needs_binwalk`, `_binwalk_probe`, `_canonical`, `_identity_manifest` |
| [ref_all_executor/contract_payloads.py](../ref_all_executor/contract_payloads.py#L1) | 46 | 2 | `_now`, `task_result_submit` |
| [ref_all_executor/coverage_client.py](../ref_all_executor/coverage_client.py#L1) | 199 | 28 | `_urllib_transport`, `CoverageClient`, `CoverageClient.__init__`, `CoverageClient._prefix`, `CoverageClient._req`, `CoverageClient.enumerate`, `CoverageClient.claim_next`, `CoverageClient.submit`, `CoverageClient.coverage`, `CoverageClient.gate`, `CoverageClient.search`, `CoverageClient.plan_progress`; 16 additional definitions |
| [ref_all_executor/doctor.py](../ref_all_executor/doctor.py#L1) | 213 | 15 | `doctor`, `_network_checks`, `_filesystem_checks`, `_arcticbase_subject_checks`, `_secret_checks`, `_allowed_providers`, `_provider_command`, `_base_url`, `_openhands_base`, `_subject_root`, `_http_get`, `_add`; 3 additional definitions |
| [ref_all_executor/entrypoint.py](../ref_all_executor/entrypoint.py#L1) | 99 | 6 | `Task`, `Clients`, `_workspace_for`, `_objective`, `execute_task`, `run_pass` |
| [ref_all_executor/estimate.py](../ref_all_executor/estimate.py#L1) | 92 | 5 | `estimate_subject`, `_estimated_open_units`, `_missing_prerequisites`, `_dynamic_testing_state`, `_optional` |
| [ref_all_executor/evidence_graph.py](../ref_all_executor/evidence_graph.py#L1) | 18 | 1 | `graph_from_deltas` |
| [ref_all_executor/head_orchestrator.py](../ref_all_executor/head_orchestrator.py#L1) | 141 | 7 | `HeadCycleResult`, `RefallHeadOrchestrator`, `RefallHeadOrchestrator.__init__`, `RefallHeadOrchestrator.run_cycle`, `RefallHeadOrchestrator._provided_wishlist`, `RefallHeadOrchestrator._coverage_context`, `_objective` |
| [ref_all_executor/http_retry.py](../ref_all_executor/http_retry.py#L1) | 58 | 1 | `with_retry` |
| [ref_all_executor/infra.py](../ref_all_executor/infra.py#L1) | 210 | 19 | `RefallInfra`, `RefallInfra.__init__`, `RefallInfra.status`, `RefallInfra.up`, `RefallInfra.down`, `RefallInfra.restart`, `RefallInfra._cmd`, `RefallInfra._tmux_available`, `RefallInfra._tmux_has_session`, `RefallInfra._tmux_start`, `RefallInfra._port_pids`, `RefallInfra._coverage_status`; 7 additional definitions |
| [ref_all_executor/loop_manager.py](../ref_all_executor/loop_manager.py#L1) | 203 | 8 | `RefallLoopManager`, `RefallLoopManager.__init__`, `RefallLoopManager.start`, `RefallLoopManager.update`, `RefallLoopManager.closeout`, `RefallLoopManager._record`, `RefallLoopManager._require_context`, `launch_standing_loop` |
| [ref_all_executor/oh_client.py](../ref_all_executor/oh_client.py#L1) | 156 | 15 | `_urllib_transport`, `OHClient`, `OHClient.__init__`, `OHClient.api_key`, `OHClient.request`, `OHClient._transport_with_retry`, `OHClient.start_conversation`, `OHClient.run`, `OHClient.execution_status`, `OHClient.conversation_info`, `OHClient.conversation_probe`, `OHClient.wait_until_done`; 3 additional definitions |
| [ref_all_executor/projection.py](../ref_all_executor/projection.py#L1) | 108 | 3 | `project_runtime_events`, `_observation_from_event`, `_delta_from_observation` |
| [ref_all_executor/prompts.py](../ref_all_executor/prompts.py#L1) | 31 | 1 | `build_prompt` |
| [ref_all_executor/report_assemble.py](../ref_all_executor/report_assemble.py#L1) | 338 | 15 | `assemble_report`, `render_enriched_report`, `_row`, `_lead`, `_fact_section`, `_runtime_section`, `_runtime_observation_row`, `_pending_action_row`, `_capability_rows`, `_capability_row`, `_capability_decision_row`, `_disposition_transition_row`; 3 additional definitions |
| [ref_all_executor/report_draft.py](../ref_all_executor/report_draft.py#L1) | 1545 | 51 | `_req`, `_optional_req`, `draft_report`, `_sev`, `_finding_sort_key`, `_finding_refs`, `_panel`, `_exec_summary_section`, `_fstr`, `_flist`, `_finding_articles_section`, `_architecture_section`; 39 additional definitions |
| [ref_all_executor/report_enrich.py](../ref_all_executor/report_enrich.py#L1) | 345 | 15 | `enrich_findings`, `_is_garbage`, `_finding_canonical_key`, `_related_locations_from_entry`, `_merge_related_locations`, `_source_anchor_path`, `_severity`, `_normalize_title`, `_resolve_lead_status`, `_group_facts_into_sections`, `_runtime_facts`, `_visual_artifacts`; 3 additional definitions |
| [ref_all_executor/router.py](../ref_all_executor/router.py#L1) | 53 | 2 | `RouteDecision`, `route` |
| [ref_all_executor/runtime_invocation.py](../ref_all_executor/runtime_invocation.py#L1) | 151 | 5 | `InvocationOutcome`, `classify_invocation`, `record_retry_failure`, `_submit_failure`, `_status_failure_class` |
| [ref_all_executor/runtime_state.py](../ref_all_executor/runtime_state.py#L1) | 184 | 13 | `runtime_root`, `runtime_db_path`, `connect_runtime`, `append_event`, `list_events`, `list_artifacts`, `list_observations`, `list_deltas`, `_event_row`, `_observation_row`, `_delta_row`, `_load`; 1 additional definitions |
| [ref_all_executor/source_inventory.py](../ref_all_executor/source_inventory.py#L1) | 192 | 6 | `build_source_inventory`, `_relative`, `_file_kind`, `_line_count`, `_file_facts`, `_symlink_observation` |
| [ref_all_executor/standing_loop.py](../ref_all_executor/standing_loop.py#L1) | 4006 | 150 | `StandingLoopConfig`, `AgentTask`, `DispatchedConversation`, `PollResult`, `ParsedOutput`, `read_conversation_agent_text`, `_with_resource_context`, `_with_workspace_context`, `AgentCanvasDispatcher`, `AgentCanvasDispatcher.__init__`, `AgentCanvasDispatcher.start`, `AgentCanvasDispatcher.poll`; 138 additional definitions |
| [ref_all_executor/structured_submit.py](../ref_all_executor/structured_submit.py#L1) | 199 | 9 | `SubmitParseResult`, `SubmitParseResult.valid`, `backfill_submission_envelope`, `parse_refall_submissions`, `primary_submission`, `_validate`, `validate_submission_contract`, `_validate_transition_receipt`, `coverage_paths_from_submission` |
| [ref_all_executor/supervisor.py](../ref_all_executor/supervisor.py#L1) | 796 | 33 | `SupervisorConfig`, `SupervisorConfig.paths`, `resolve_binary`, `watchdog_active_agents`, `_run`, `loop_process_pids`, `RefallSupervisor`, `RefallSupervisor.__init__`, `RefallSupervisor._state`, `RefallSupervisor._save_state`, `RefallSupervisor.hold_active`, `RefallSupervisor._log`; 21 additional definitions |
| [ref_all_executor/usage.py](../ref_all_executor/usage.py#L1) | 34 | 2 | `_summary`, `record_and_delete` |
| [ref_all_executor/verify.py](../ref_all_executor/verify.py#L1) | 51 | 3 | `TaskResult`, `assign_tier`, `run_verifier` |
| [ref_all_executor/watchdog.py](../ref_all_executor/watchdog.py#L1) | 1393 | 54 | `Thresholds`, `WatchdogConfig`, `WatchdogConfig.paths`, `WatchdogConfig.thresholds`, `_env_int`, `_env_float`, `_env_bool`, `thresholds_from_env`, `iso_now`, `append_jsonl`, `append_text`, `request_json`; 42 additional definitions |
| [ref_all_executor/wishlist.py](../ref_all_executor/wishlist.py#L1) | 28 | 2 | `format_provided_wishlist`, `provided_wishes_from` |
| [ref_all_executor/work_modules.py](../ref_all_executor/work_modules.py#L1) | 535 | 31 | `ModuleError`, `WorkModule`, `WorkModule.validate`, `WorkModule.to_dict`, `WorkModule.from_dict`, `_m`, `pack_names`, `builtin_module`, `ModuleRegistry`, `ModuleRegistry.from_config`, `ModuleRegistry.validate`, `ModuleRegistry._assert_acyclic`; 19 additional definitions |
| [ref_all_executor/workbench.py](../ref_all_executor/workbench.py#L1) | 66 | 7 | `_urllib_transport`, `Workbench`, `Workbench.__init__`, `Workbench._post`, `Workbench.write_finding`, `Workbench.log_run`, `Workbench.delete` |

## coverage_service

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [coverage_service/__init__.py](../coverage_service/__init__.py#L1) | 1 | 0 | Module declarations or executable statements |
| [coverage_service/__main__.py](../coverage_service/__main__.py#L1) | 6 | 0 | Module declarations or executable statements |
| [coverage_service/app.py](../coverage_service/app.py#L1) | 493 | 51 | `_list_subjects`, `EnumReq`, `ClaimReq`, `SubmitReq`, `enumerate_ep`, `SurfaceReq`, `surface_ep`, `claim_ep`, `submit_ep`, `release_ep`, `dead_ep`, `FindingReq`; 39 additional definitions |
| [coverage_service/binary.py](../coverage_service/binary.py#L1) | 167 | 6 | `_r2`, `classify`, `dangerous_present`, `import_callers`, `build_investigations`, `seed_binary` |
| [coverage_service/dashboard.py](../coverage_service/dashboard.py#L1) | 194 | 1 | `render` |
| [coverage_service/db.py](../coverage_service/db.py#L1) | 115 | 3 | `connect`, `_migrate`, `init_schema` |
| [coverage_service/enumerate.py](../coverage_service/enumerate.py#L1) | 46 | 2 | `partition_file`, `build_units` |
| [coverage_service/extract.py](../coverage_service/extract.py#L1) | 50 | 3 | `total_lines`, `extract_python`, `extract_dir` |
| [coverage_service/ids.py](../coverage_service/ids.py#L1) | 6 | 1 | `unit_id` |
| [coverage_service/project.py](../coverage_service/project.py#L1) | 132 | 6 | `_state_path`, `_get`, `_h`, `_finding_rows`, `build_report`, `publish` |
| [coverage_service/seeds.py](../coverage_service/seeds.py#L1) | 167 | 5 | `path_penalty`, `scan_source`, `scan_dir`, `summarize`, `seeds_to_investigations` |
| [coverage_service/store.py](../coverage_service/store.py#L1) | 493 | 40 | `_now`, `_decode`, `Store`, `Store.__init__`, `Store.upsert_units`, `Store.set_surface`, `Store.claim_next`, `Store.submit`, `Store.mark_dead`, `Store._resolve`, `Store.release`, `Store.sweep`; 28 additional definitions |
| [coverage_service/tools/__init__.py](../coverage_service/tools/__init__.py) | 0 | 0 | Empty module marker |
| [coverage_service/tools/final_visual.py](../coverage_service/tools/final_visual.py#L1) | 34 | 4 | `_content_type`, `verify_rendered_html`, `publish_final_visual`, `publish_coverage_visual` |
| [coverage_service/tools/report_findings.py](../coverage_service/tools/report_findings.py#L1) | 263 | 12 | `_get`, `_clip`, `_first_sentence`, `_repro_sentence`, `_runtime_viability`, `_attacker_input`, `_trace_steps`, `_trace_html`, `_poc_pack_html`, `_card`, `build`, `publish` |
| [coverage_service/tools/seed_binary.py](../coverage_service/tools/seed_binary.py#L1) | 40 | 1 | `main` |
| [coverage_service/tools/seed_subject.py](../coverage_service/tools/seed_subject.py#L1) | 41 | 1 | `main` |
| [coverage_service/tools/vendor_disclosure.py](../coverage_service/tools/vendor_disclosure.py#L1) | 416 | 22 | `_get`, `_maybe_get`, `_clip`, `_public_text`, `_esc`, `_first`, `_quoted_subject`, `_generated_at`, `_severity_key`, `_sentence`, `_extract_command_block`, `_trace_nodes`; 10 additional definitions |

## arcticbase/backend/src

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [arcticbase/backend/src/arctic_base/__init__.py](../arcticbase/backend/src/arctic_base/__init__.py#L1) | 1 | 0 | Module declarations or executable statements |
| [arcticbase/backend/src/arctic_base/__main__.py](../arcticbase/backend/src/arctic_base/__main__.py#L1) | 24 | 1 | `main` |
| [arcticbase/backend/src/arctic_base/api/__init__.py](../arcticbase/backend/src/arctic_base/api/__init__.py#L1) | 49 | 0 | Module declarations or executable statements |
| [arcticbase/backend/src/arctic_base/api/agent.py](../arcticbase/backend/src/arctic_base/api/agent.py#L1) | 736 | 16 | `agent_landing`, `conventions`, `BootstrapBody`, `BootstrapChecklistItem`, `BootstrapResponse`, `_slugify`, `bootstrap`, `SelfTestStep`, `SelfTestResult`, `self_test`, `ActivityResponse`, `activity`; 4 additional definitions |
| [arcticbase/backend/src/arctic_base/api/deps.py](../arcticbase/backend/src/arctic_base/api/deps.py#L1) | 10 | 1 | `get_storage` |
| [arcticbase/backend/src/arctic_base/api/errors.py](../arcticbase/backend/src/arctic_base/api/errors.py#L1) | 41 | 2 | `_problem`, `install_error_handlers` |
| [arcticbase/backend/src/arctic_base/api/objects.py](../arcticbase/backend/src/arctic_base/api/objects.py#L1) | 320 | 13 | `ObjectCreate`, `ObjectPatch`, `_read_meta_json`, `list_objects`, `create_object`, `get_object`, `ObjectReorderBody`, `reorder_objects`, `patch_object`, `delete_object`, `get_object_content`, `ContentPutResponse`; 1 additional definitions |
| [arcticbase/backend/src/arctic_base/api/refall_capabilities.py](../arcticbase/backend/src/arctic_base/api/refall_capabilities.py#L1) | 201 | 10 | `require_capability_operator`, `CapabilityGrantReq`, `CapabilityRequestReq`, `list_capabilities`, `request_capability`, `grant_capability`, `revoke_capability`, `revoke_capability_compat`, `authorize_execution`, `_request_row` |
| [arcticbase/backend/src/arctic_base/api/refall_closeout.py](../arcticbase/backend/src/arctic_base/api/refall_closeout.py#L1) | 54 | 3 | `CloseoutOverrideReq`, `get_closeout_gate`, `override_closeout_gate` |
| [arcticbase/backend/src/arctic_base/api/refall_coverage.py](../arcticbase/backend/src/arctic_base/api/refall_coverage.py#L1) | 721 | 51 | `EnumerateReq`, `SurfaceReq`, `ClaimReq`, `SubmitReq`, `ReleaseReq`, `PlanReq`, `ContextReq`, `FindingReq`, `FindingValidationReq`, `WishlistReq`, `AttackPatternReq`, `ClassCoverageReq`; 39 additional definitions |
| [arcticbase/backend/src/arctic_base/api/refall_disposition.py](../arcticbase/backend/src/arctic_base/api/refall_disposition.py#L1) | 111 | 5 | `TransitionReq`, `transition_finding`, `list_finding_transitions`, `list_disposition_refusals`, `_source_root_for_transition` |
| [arcticbase/backend/src/arctic_base/api/refall_ledger.py](../arcticbase/backend/src/arctic_base/api/refall_ledger.py#L1) | 55 | 4 | `append_ledger_entry`, `list_ledger_entries`, `get_ledger_entry`, `ledger_stats` |
| [arcticbase/backend/src/arctic_base/api/refall_ops.py](../arcticbase/backend/src/arctic_base/api/refall_ops.py#L1) | 219 | 12 | `require_ops`, `infra_checks`, `status_payload`, `get_status`, `get_agents`, `get_infra`, `get_subjects`, `active_refall_agents`, `_subject_roots`, `_active_from_loop_state`, `_active_from_event_log`, `_read_jsonl_tail` |
| [arcticbase/backend/src/arctic_base/api/refall_ops_commands.py](../arcticbase/backend/src/arctic_base/api/refall_ops_commands.py#L1) | 2013 | 77 | `CommandReq`, `GenerateContextReq`, `SaveContextReq`, `require_ops_commands`, `run_command`, `generate_context`, `save_context`, `_execute_named_command`, `_audit`, `_require_subject_arg`, `_start_subject`, `_update_subject`; 65 additional definitions |
| [arcticbase/backend/src/arctic_base/api/refall_ops_context.py](../arcticbase/backend/src/arctic_base/api/refall_ops_context.py#L1) | 302 | 15 | `get_debug`, `get_debug_conversation`, `get_debug_live`, `_read_jsonl_tail`, `_discover_logs`, `_subject_roots`, `_agent_log_roots`, `_event_log_paths`, `_find_conversation_events`, `_active_conversations`, `_active_from_loop_state`, `_recent_conversation_events`; 3 additional definitions |
| [arcticbase/backend/src/arctic_base/api/refall_ops_sse.py](../arcticbase/backend/src/arctic_base/api/refall_ops_sse.py#L1) | 54 | 4 | `record_event`, `push_event`, `feed_history`, `feed` |
| [arcticbase/backend/src/arctic_base/api/refall_pending_actions.py](../arcticbase/backend/src/arctic_base/api/refall_pending_actions.py#L1) | 178 | 10 | `PendingActionReq`, `ClaimReq`, `ResolveReq`, `list_pending_actions`, `create_pending_action`, `claim_pending_action`, `resolve_pending_action`, `defer_pending_action`, `cancel_pending_action`, `_finish` |
| [arcticbase/backend/src/arctic_base/api/refall_reports.py](../arcticbase/backend/src/arctic_base/api/refall_reports.py#L1) | 76 | 5 | `spec_index`, `spec_bundle`, `spec_file`, `report_template`, `current_report` |
| [arcticbase/backend/src/arctic_base/api/refall_runtime.py](../arcticbase/backend/src/arctic_base/api/refall_runtime.py#L1) | 447 | 28 | `RuntimeEventReq`, `RuntimeArtifactReq`, `RuntimeManifestReq`, `RuntimeCheckpointReq`, `ResumePreflightReq`, `list_runtime_runs`, `put_runtime_manifest`, `get_runtime_manifest`, `put_runtime_checkpoint`, `get_runtime_checkpoints`, `runtime_resume_preflight`, `append_runtime_event`; 16 additional definitions |
| [arcticbase/backend/src/arctic_base/api/refall_subjects.py](../arcticbase/backend/src/arctic_base/api/refall_subjects.py#L1) | 96 | 5 | `SubjectCreate`, `SubjectCreateResponse`, `MirrorResponse`, `create_subject`, `mirror_workbench` |
| [arcticbase/backend/src/arctic_base/api/render.py](../arcticbase/backend/src/arctic_base/api/render.py#L1) | 262 | 5 | `_make_md`, `build_theme_style_block`, `build_bridge_script`, `_inject_into_html`, `render_object` |
| [arcticbase/backend/src/arctic_base/api/responses.py](../arcticbase/backend/src/arctic_base/api/responses.py#L1) | 124 | 6 | `ResponseAppend`, `list_responses`, `latest_response`, `latest_payload`, `export_responses`, `append_response` |
| [arcticbase/backend/src/arctic_base/api/templates_data.py](../arcticbase/backend/src/arctic_base/api/templates_data.py#L1) | 617 | 3 | `TemplateMeta`, `list_templates`, `get_template` |
| [arcticbase/backend/src/arctic_base/api/theme.py](../arcticbase/backend/src/arctic_base/api/theme.py#L1) | 136 | 8 | `ThemeRawBody`, `get_theme`, `get_theme_raw`, `put_theme`, `list_theme_assets`, `get_theme_asset`, `put_theme_asset`, `delete_theme_asset` |
| [arcticbase/backend/src/arctic_base/api/workbenches.py](../arcticbase/backend/src/arctic_base/api/workbenches.py#L1) | 608 | 33 | `WorkbenchCreate`, `WorkbenchPatch`, `_slugify`, `list_workbenches`, `create_workbench`, `get_workbench`, `WorkbenchReorderBody`, `reorder_workbenches`, `patch_workbench`, `ArchiveResponse`, `archive_workbench`, `TrashEntry`; 21 additional definitions |
| [arcticbase/backend/src/arctic_base/config.py](../arcticbase/backend/src/arctic_base/config.py#L1) | 179 | 5 | `_is_private_lan_ipv4`, `_detect_private_lan_ipv4`, `Settings`, `Settings.derive_refall_paths`, `get_settings` |
| [arcticbase/backend/src/arctic_base/logging_setup.py](../arcticbase/backend/src/arctic_base/logging_setup.py#L1) | 125 | 8 | `ActivityRecord`, `get_recent_activity`, `JsonFormatter`, `JsonFormatter.format`, `configure_logging`, `RequestIdMiddleware`, `RequestIdMiddleware.__init__`, `RequestIdMiddleware.__call__` |
| [arcticbase/backend/src/arctic_base/main.py](../arcticbase/backend/src/arctic_base/main.py#L1) | 89 | 2 | `_seed_if_empty`, `create_app` |
| [arcticbase/backend/src/arctic_base/models.py](../arcticbase/backend/src/arctic_base/models.py#L1) | 183 | 14 | `BannerKind`, `Banner`, `WorkbenchMeta`, `WorkbenchMeta._drop_computed_inputs`, `WorkbenchMeta.view_url`, `ObjectKind`, `ObjectMeta`, `ResponseKind`, `Submitter`, `ResponseEvent`, `TypographyStyle`, `LayoutTokens`; 2 additional definitions |
| [arcticbase/backend/src/arctic_base/refall/__init__.py](../arcticbase/backend/src/arctic_base/refall/__init__.py#L1) | 1 | 0 | Module declarations or executable statements |
| [arcticbase/backend/src/arctic_base/refall/artifact_store.py](../arcticbase/backend/src/arctic_base/refall/artifact_store.py#L1) | 67 | 1 | `save_artifact` |
| [arcticbase/backend/src/arctic_base/refall/capabilities.py](../arcticbase/backend/src/arctic_base/refall/capabilities.py#L1) | 11 | 2 | `grant`, `authorize` |
| [arcticbase/backend/src/arctic_base/refall/closeout_gate.py](../arcticbase/backend/src/arctic_base/refall/closeout_gate.py#L1) | 432 | 14 | `evaluate_closeout_gate`, `_accepted_transition_finding_ids`, `_check`, `_report_check`, `_subject_path`, `_runtime_records`, `_visual_evidence_available`, `_toolchain_has_run`, `_vendor_cna_report`, `_external_scope_blockers`, `_informational_checks`, `_latest_entry_time`; 2 additional definitions |
| [arcticbase/backend/src/arctic_base/refall/contracts.py](../arcticbase/backend/src/arctic_base/refall/contracts.py#L1) | 278 | 21 | `stable_id`, `_utc_now`, `RefallContract`, `EvidenceReceipt`, `EvidenceReceipt.require_material`, `ContextPackage`, `ContextPackage.set_id`, `SourceInventoryPackage`, `SourceInventoryPackage.set_id`, `ScopeOverlay`, `ScopeOverlay.set_id`, `ThreatModelPackage`; 9 additional definitions |
| [arcticbase/backend/src/arctic_base/refall/coverage_db.py](../arcticbase/backend/src/arctic_base/refall/coverage_db.py#L1) | 171 | 3 | `connect`, `init_schema`, `_ensure_column` |
| [arcticbase/backend/src/arctic_base/refall/coverage_store.py](../arcticbase/backend/src/arctic_base/refall/coverage_store.py#L1) | 1881 | 95 | `_now`, `_json`, `_load_json`, `_now_id`, `_receipt_has_evidence`, `_receipt_stale_reasons`, `_normalize_sha256`, `_source_anchor_path`, `_receipt_summary`, `_finding_has_visual_or_proof_artifact`, `_pending_identity`, `_scope_list`; 83 additional definitions |
| [arcticbase/backend/src/arctic_base/refall/disposition.py](../arcticbase/backend/src/arctic_base/refall/disposition.py#L1) | 17 | 2 | `transition_finding`, `list_transitions` |
| [arcticbase/backend/src/arctic_base/refall/evidence_graph.py](../arcticbase/backend/src/arctic_base/refall/evidence_graph.py#L1) | 18 | 1 | `graph_from_deltas` |
| [arcticbase/backend/src/arctic_base/refall/ledger.py](../arcticbase/backend/src/arctic_base/refall/ledger.py#L1) | 113 | 6 | `ledger_path`, `append_entry`, `list_entries`, `get_entry`, `stats`, `_read_entries` |
| [arcticbase/backend/src/arctic_base/refall/pending_actions.py](../arcticbase/backend/src/arctic_base/refall/pending_actions.py#L1) | 23 | 2 | `create`, `list_actions` |
| [arcticbase/backend/src/arctic_base/refall/projection.py](../arcticbase/backend/src/arctic_base/refall/projection.py#L1) | 106 | 3 | `project_runtime_events`, `_observation_from_event`, `_delta_from_observation` |
| [arcticbase/backend/src/arctic_base/refall/promotion_gates.py](../arcticbase/backend/src/arctic_base/refall/promotion_gates.py#L1) | 182 | 14 | `evaluate_finding_candidate`, `_source_refs`, `_location_refs`, `_artifact_refs`, `_evidence_items`, `_freeform_refs`, `_inventory_paths`, `_source_path`, `_external_hosts`, `_url_host`, `_external_host_allowed`, `_claims_validation`; 2 additional definitions |
| [arcticbase/backend/src/arctic_base/refall/runtime_state.py](../arcticbase/backend/src/arctic_base/refall/runtime_state.py#L1) | 465 | 23 | `runtime_root`, `connect_runtime`, `append_event`, `list_events`, `list_nonfatal_errors`, `list_artifacts`, `list_observations`, `list_deltas`, `put_manifest`, `get_latest_manifest`, `put_checkpoint`, `list_checkpoints`; 11 additional definitions |
| [arcticbase/backend/src/arctic_base/refall/source_inventory.py](../arcticbase/backend/src/arctic_base/refall/source_inventory.py#L1) | 180 | 6 | `build_source_inventory`, `_relative`, `_file_kind`, `_line_count`, `_file_facts`, `_symlink_observation` |
| [arcticbase/backend/src/arctic_base/refall/subjects.py](../arcticbase/backend/src/arctic_base/refall/subjects.py#L1) | 193 | 6 | `SubjectBootstrap`, `slugify_subject`, `bootstrap_subject`, `_create_subject_layout`, `_create_or_update_workbench`, `_merge_tags` |
| [arcticbase/backend/src/arctic_base/storage/__init__.py](../arcticbase/backend/src/arctic_base/storage/__init__.py#L1) | 53 | 25 | `Storage`, `Storage.list_workbenches`, `Storage.get_workbench`, `Storage.create_workbench`, `Storage.update_workbench`, `Storage.archive_workbench`, `Storage.restore_workbench`, `Storage.list_trash`, `Storage.get_theme`, `Storage.get_theme_raw`, `Storage.put_theme`, `Storage.list_theme_assets`; 13 additional definitions |
| [arcticbase/backend/src/arctic_base/storage/errors.py](../arcticbase/backend/src/arctic_base/storage/errors.py#L1) | 23 | 6 | `StorageError`, `NotFound`, `AlreadyExists`, `StaleETag`, `StaleETag.__init__`, `InvalidTheme` |
| [arcticbase/backend/src/arctic_base/storage/filesystem.py](../arcticbase/backend/src/arctic_base/storage/filesystem.py#L1) | 698 | 64 | `_utcnow`, `_hash`, `_slug_ok`, `_atomic_write`, `_dump_model`, `_flock`, `FilesystemStorage`, `FilesystemStorage.__init__`, `FilesystemStorage._wb_dir`, `FilesystemStorage._wb_lock`, `FilesystemStorage._wb_manifest`, `FilesystemStorage._theme_md`; 52 additional definitions |
| [arcticbase/backend/src/arctic_base/theme.py](../arcticbase/backend/src/arctic_base/theme.py#L1) | 81 | 4 | `parse_theme_md`, `serialize_theme`, `_split`, `_validate_required` |

## arcticbase/frontend/src

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [arcticbase/frontend/src/App.svelte](../arcticbase/frontend/src/App.svelte#L1) | 192 | 2 | `loadEditor`, `loadThemeEditor` |
| [arcticbase/frontend/src/lib/api.ts](../arcticbase/frontend/src/lib/api.ts#L1) | 679 | 2 | `HttpError`, `req` |
| [arcticbase/frontend/src/lib/bridge.ts](../arcticbase/frontend/src/lib/bridge.ts#L1) | 133 | 4 | `isIncoming`, `isRemoteSub`, `poll`, `installBridge` |
| [arcticbase/frontend/src/lib/chrome/Blueprints.svelte](../arcticbase/frontend/src/lib/chrome/Blueprints.svelte#L1) | 178 | 0 | Module declarations or executable statements |
| [arcticbase/frontend/src/lib/chrome/Dashboard.svelte](../arcticbase/frontend/src/lib/chrome/Dashboard.svelte#L1) | 651 | 8 | `deriveStats`, `fmtBytes`, `fmtAgo`, `pad`, `rpad`, `load`, `create`, `buttonLabel` |
| [arcticbase/frontend/src/lib/chrome/Editor.svelte](../arcticbase/frontend/src/lib/chrome/Editor.svelte#L1) | 197 | 7 | `lang`, `pickImage`, `handlePaste`, `handleDrop`, `uploadAndInsert`, `save`, `reload` |
| [arcticbase/frontend/src/lib/chrome/FileBrowser.svelte](../arcticbase/frontend/src/lib/chrome/FileBrowser.svelte#L1) | 121 | 3 | `load`, `upload`, `fmt` |
| [arcticbase/frontend/src/lib/chrome/ImageViewer.svelte](../arcticbase/frontend/src/lib/chrome/ImageViewer.svelte#L1) | 55 | 0 | Module declarations or executable statements |
| [arcticbase/frontend/src/lib/chrome/ResponsesHistory.svelte](../arcticbase/frontend/src/lib/chrome/ResponsesHistory.svelte#L1) | 152 | 3 | `load`, `toggle`, `fmt` |
| [arcticbase/frontend/src/lib/chrome/Settings.svelte](../arcticbase/frontend/src/lib/chrome/Settings.svelte#L1) | 945 | 24 | `load`, `loadActivity`, `openEdit`, `createSnapshot`, `restoreSnapshotPrompt`, `deleteSnapshotPrompt`, `runSelfTest`, `fmtBytes`, `addCustomField`, `removeCustomField`, `closeEdit`, `saveEdit`; 12 additional definitions |
| [arcticbase/frontend/src/lib/chrome/StatusBar.svelte](../arcticbase/frontend/src/lib/chrome/StatusBar.svelte#L1) | 73 | 0 | Module declarations or executable statements |
| [arcticbase/frontend/src/lib/chrome/TopNav.svelte](../arcticbase/frontend/src/lib/chrome/TopNav.svelte#L1) | 194 | 0 | Module declarations or executable statements |
| [arcticbase/frontend/src/lib/mini-md.ts](../arcticbase/frontend/src/lib/mini-md.ts#L1) | 45 | 2 | `renderMiniMd`, `inline` |
| [arcticbase/frontend/src/lib/refall/OpsTerminal.svelte](../arcticbase/frontend/src/lib/refall/OpsTerminal.svelte#L1) | 89 | 0 | Module declarations or executable statements |
| [arcticbase/frontend/src/lib/refall/WorkbenchOpsPanel.svelte](../arcticbase/frontend/src/lib/refall/WorkbenchOpsPanel.svelte#L1) | 1408 | 43 | `load`, `runCommand`, `runDoctor`, `runEstimate`, `generateContext`, `saveContext`, `saveScopeOverlay`, `saveThreatModel`, `requestThreatModel`, `projectRuntime`, `claimPending`, `finishPending`; 31 additional definitions |
| [arcticbase/frontend/src/lib/router.ts](../arcticbase/frontend/src/lib/router.ts#L1) | 38 | 3 | `parse`, `navigate`, `match` |
| [arcticbase/frontend/src/lib/theme.ts](../arcticbase/frontend/src/lib/theme.ts#L1) | 17 | 1 | `themeToCssVars` |
| [arcticbase/frontend/src/lib/themed/HtmlViewer.svelte](../arcticbase/frontend/src/lib/themed/HtmlViewer.svelte#L1) | 49 | 0 | Module declarations or executable statements |
| [arcticbase/frontend/src/lib/themed/MdViewer.svelte](../arcticbase/frontend/src/lib/themed/MdViewer.svelte#L1) | 45 | 0 | Module declarations or executable statements |
| [arcticbase/frontend/src/lib/themed/RunbookViewer.svelte](../arcticbase/frontend/src/lib/themed/RunbookViewer.svelte#L1) | 385 | 9 | `load`, `persist`, `setStatus`, `setBlocker`, `addStep`, `removeStep`, `moveStep`, `statusGlyph`, `nextStatus` |
| [arcticbase/frontend/src/lib/themed/ThemeEditor.svelte](../arcticbase/frontend/src/lib/themed/ThemeEditor.svelte#L1) | 151 | 1 | `save` |
| [arcticbase/frontend/src/lib/themed/ThemeWrapper.svelte](../arcticbase/frontend/src/lib/themed/ThemeWrapper.svelte#L1) | 21 | 0 | Module declarations or executable statements |
| [arcticbase/frontend/src/lib/themed/WorkbenchDashboard.svelte](../arcticbase/frontend/src/lib/themed/WorkbenchDashboard.svelte#L1) | 547 | 13 | `loadAll`, `reloadObjects`, `togglePin`, `toggleArchive`, `bannerSrc`, `clickObject`, `deleteObject`, `viewResponses`, `enableRefallFromWorkbench`, `setRefallSourcePath`, `moveWithinDrawer`, `persistOrder`; 1 additional definitions |
| [arcticbase/frontend/src/main.ts](../arcticbase/frontend/src/main.ts#L1) | 18 | 0 | Module declarations or executable statements |

## toolchain/bin

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [toolchain/bin/codebadger-service](../toolchain/bin/codebadger-service#L1) | 210 | 14 | `usage`, `die`, `require_cmd`, `env_value`, `mcp_port`, `ensure_checkout`, `ensure_env`, `ensure_stack`, `deploy`, `health`, `status`, `down`; 2 additional definitions |
| [toolchain/bin/jedi-symbol-index](../toolchain/bin/jedi-symbol-index#L1) | 90 | 0 | Module declarations or executable statements |
| [toolchain/bin/lizard-to-codecharta](../toolchain/bin/lizard-to-codecharta#L1) | 176 | 0 | Module declarations or executable statements |
| [toolchain/bin/module-import-index](../toolchain/bin/module-import-index#L1) | 75 | 0 | Module declarations or executable statements |
| [toolchain/bin/render-dot-graphs](../toolchain/bin/render-dot-graphs#L1) | 48 | 0 | Module declarations or executable statements |

## toolchain/install.sh

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [toolchain/install.sh](../toolchain/install.sh#L1) | 387 | 14 | `record`, `have_python_package`, `have_npm_package`, `run_logged`, `sha256_matches`, `have_codebase_memory`, `install_codebase_memory`, `install_codebadger`, `apt_update_once`, `apt_install_package`, `ensure_deb_package`, `install_semgrep_report_viewer`; 2 additional definitions |

## toolchain/run.sh

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [toolchain/run.sh](../toolchain/run.sh#L1) | 156 | 3 | `usage`, `steps`, `run_step` |

## toolchain/ctl.sh

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [toolchain/ctl.sh](../toolchain/ctl.sh#L1) | 392 | 24 | `usage`, `die`, `require_registry`, `service_names`, `autostart_service_names`, `service_exists`, `selected_services`, `service_json`, `service_field`, `pid_file`, `service_log_file`, `service_port`; 12 additional definitions |

## deploy/cron

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [deploy/cron/refall-supervisor.sh](../deploy/cron/refall-supervisor.sh#L1) | 45 | 0 | Module declarations or executable statements |
| [deploy/cron/refall-watchdog-cron.sh](../deploy/cron/refall-watchdog-cron.sh#L1) | 102 | 1 | `cleanup_tmp` |

## drive_context.py

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [drive_context.py](../drive_context.py#L1) | 65 | 2 | `_objective`, `run` |

## drive_characterize.py

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [drive_characterize.py](../drive_characterize.py#L1) | 188 | 8 | `log`, `_objective`, `_dex`, `ensure_l1`, `_run_agent`, `run`, `status`, `kill` |

## drive_research.py

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [drive_research.py](../drive_research.py#L1) | 201 | 4 | `_objective`, `_run_agent`, `run`, `research_status` |

## drive_binresearch.py

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [drive_binresearch.py](../drive_binresearch.py#L1) | 204 | 5 | `_objective`, `_run_agent`, `ensure_r2`, `run`, `research_status` |

## drive_binreview.py

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [drive_binreview.py](../drive_binreview.py#L1) | 144 | 4 | `run_validation`, `_objective`, `_run_agent`, `run` |

## drive_binvalidate.py

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [drive_binvalidate.py](../drive_binvalidate.py#L1) | 230 | 4 | `needs_validation`, `_objective`, `_run_agent`, `run` |

## refall_infra.py

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [refall_infra.py](../refall_infra.py#L1) | 10 | 0 | Module declarations or executable statements |

## refall_down.py

| File | Lines | Definitions | Selected interfaces |
| --- | --- | --- | --- |
| [refall_down.py](../refall_down.py#L1) | 10 | 0 | Module declarations or executable statements |

## Read a source location

1. Select a file from the relevant subsystem.
2. Read its imports, declarations, and named interfaces.
3. Use the architecture and workflow guides to identify its callers and stored records.
4. Compare an observed result with the relevant decision and state change.

