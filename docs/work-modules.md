# REFALL AB work modules

A work module declares a bounded research pass.
The declaration identifies the work type, target source, prerequisites, selection rules, and additional objective.
The scheduler evaluates modules against each target's current state.

## Target sources

| Source value | Target | Typical use |
| --- | --- | --- |
| `subject` | The whole subject. | Identification, background research, source-tool execution, or synthesis. |
| `coverage_units` | A file, symbol, or line-range unit. | Characterization, decomposition, review, or harness creation. |
| `findings` | A finding record. | Reproduction, verification, or patch proposals. |

A subject pass normally runs once for the subject.
A later unit pass can run once for each eligible characterized unit.
A finding pass can run once for each eligible finding.
These selection paths use `once_per_target` and active-target tracking to prevent duplicate concurrent dispatch.
Fresh characterization has a separate coverage-claim path.

## Built-in packs

| Pack | Modules | Purpose |
| --- | --- | --- |
| `baseline` | `characterize` | Describe units with source anchors. |
| `reverse_engineering` | `re_identify`, `re_decompose`, `re_review` | Identify the subject, explain components, and review the decomposition. |
| `security_assessment` | `sec_recon`, `sec_review`, `sec_verify` | Identify attack surfaces, examine candidate issues, and verify findings. |
| `research` | `res_research`, `res_synthesis` | Research the target class and compile the results. |
| `development` | `dev_harness`, `dev_patch` | Draft harnesses and propose fixes for findings. |
| `dynamic_testing` | `dyn_harness`, `dyn_verify` | Build an approved harness and record its runtime behavior. |
| `static_analysis` | `sa_toolchain`, `sa_review` | Produce source-tool outputs and examine their meaning. |

The default executable selection is `security_assessment`.
Dependency resolution also adds its required characterization module.
Select `baseline` explicitly for a characterization-only run.
Packs can be combined.
A pack is a convenience group rather than a global execution phase.

## Dependencies and order

The `after` list refers to modules completed on the same target.
For example, `re_review` depends on `re_decompose` for that unit.
It does not require decomposition of the whole repository.

The registry resolves missing built-in dependencies across packs.
It rejects unknown dependencies and dependency cycles.
Subject selection applies dependencies, completion tracking, active-target tracking, and module concurrency limits.
Later unit selection also applies path rules to the recorded unit path.
Finding selection applies path rules when a finding path is available.
Lower numerical priority runs first within the relevant selection.

Fresh breadth uses coverage claims rather than the module eligibility function.
The loop attaches the first active breadth module and always dispatches the `characterize` task class.
That task receives the module objective and a limit of 30 iterations.
The global loop concurrency limit controls these tasks.
Breadth selection does not apply module path filters or per-module concurrency limits.
Use dependency-free coverage modules for characterization.
Use modules with an `after` dependency for filtered later passes.

The standing loop adds a broader dispatch order:

1. Claim pending actions and requested threat-model work.
2. Select eligible subject modules.
3. Claim fresh coverage units for breadth.
4. Select finding-specific modules.
5. Select later passes on characterized units.

Fresh breadth takes precedence over repeated deep work on an initial subset.
Finding verification and later unit work continue after fresh units are exhausted.

## Configure a subject

Store the configuration in the workbench `refall_modules` custom field.
The loader accepts an object or a JSON string.
The workbench metadata API represents custom field values as strings.
Use JSON text when updating this field through that API.

A combined source-research configuration is:

```json
{
  "packs": [
    "reverse_engineering",
    "security_assessment",
    "static_analysis"
  ],
  "overrides": {
    "sec_review": {
      "path_globs": ["src/**", "lib/**"],
      "exclude_globs": ["**/generated/**"],
      "max_parallel": 2
    }
  }
}
```

This selects subject identification, decomposition, review, source analysis, security review, and finding verification.
It limits the security review pass to selected paths and two concurrent tasks.

A custom subject pass can be added as follows:

```json
{
  "packs": ["baseline", "reverse_engineering"],
  "modules": [
    {
      "id": "interface_catalog",
      "task_class": "research",
      "source": "subject",
      "priority": 25,
      "max_parallel": 1,
      "objective": "Catalog documented interfaces and anchor each entry to the subject material."
    }
  ]
}
```

The custom objective becomes part of a bounded task.
The module uses the normal context, evidence, persistence, and result-processing path.
Its task class must exist in the router.
A declaration does not install a new tool or execution service.

## Select targets and limits

| Field | Meaning |
| --- | --- |
| `id` | Stable module identifier. |
| `task_class` | Router task class. |
| `source` | Subject, coverage units, or findings. |
| `after` | Prerequisites on the same target. |
| `unit_state` | State predicate for eligibility callers that supply the target state. |
| `path_globs` | Included paths for later unit passes and findings with a recorded path. |
| `exclude_globs` | Excluded paths for those same selection paths. |
| `priority` | Numerical ordering value. |
| `max_parallel` | Module concurrency limit for subject, finding, and later unit selection. |
| `objective` | Additional specialist instructions. |
| `enabled` | Whether the module participates. |
| `once_per_target` | Whether completed targets remain excluded. |
| `pack` | Module group label. |

The later unit scheduler draws targets from its characterized-unit collection.
It does not supply `unit_state` to the eligibility function.
Its target collection and module dependencies establish that path's progress requirements.

The `disabled` list can disable selected module identifiers.
The `overrides` map can adjust a built-in declaration.
Review dependencies when disabling prerequisite modules.

## Adapt the research objective

For architecture mapping, select baseline and reverse-engineering modules.
Use facts, leads, flows, and saved diagrams as the principal outputs.
The `refall_no_findings` field selects the available mapping-oriented output contract and report behavior.

For a security campaign, combine security assessment with research or static analysis when useful.
For remediation work, add development modules and supply the required write authority.
For runtime examination, supply a subject harness and the necessary capability grants.

## Preserve prior work

The scheduler stores progress in `.refall/module_progress.json`.
It records completed module identifiers, characterized units, and known findings.
Later unit objectives tell workers to read prior determinations, findings, shared notes, and saved analysis artifacts.
A successful later pass extends the evidence without submitting the characterization result again.

Subject modules must produce durable facts, leads, findings, or flows.
A pass without canonical output creates an ingestion-review action and remains unfinished.
This requirement keeps a completed task from becoming an empty progress marker.

Sources: [WorkModule](../ref_all_executor/work_modules.py#L46), [registry](../ref_all_executor/work_modules.py#L211), [scheduler](../ref_all_executor/work_modules.py#L386), [dispatch order](../ref_all_executor/standing_loop.py#L590).
