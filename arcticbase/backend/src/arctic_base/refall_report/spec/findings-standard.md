# REFALL Findings Standard

Each REFALL finding must contain enough evidence for another reviewer to reproduce or reject it.

## Required finding fields

- Stable finding identifier.
- Title and severity.
- Affected component.
- Description.
- Impact and likelihood.
- Source or binary anchors.
- Reproduction steps.
- Proof-of-concept status and `poc` content.
- Validation status.
- Evidence objects or ledger references.
- Deduplication key and canonical finding identifier.
- Related locations for repeated evidence anchors.
- Remediation.
- Current lifecycle status.

## Reproduction and proof of concept

Use `reproduction` for the procedure that confirms the condition.
Static confirmation can trace a code path or run a parser that exposes the flaw.
Keep this procedure separate from the exploit proof of concept (PoC).

Use `poc` for a payload or exploit that demonstrates exploitability and impact.
Under a static-only scope, record the candidate payload or precise PoC design.
Save available PoC files in the workspace.
List those files in `poc_refs`.
Set `poc_status` to identify unverified execution and the required operator grant for a dynamic phase.
Do not describe a static confirmation script as an exploit PoC.

## Disclosure fields

Vendor, CVE, and CNA submissions require the following fields.
A CVE Numbering Authority is an organization that assigns CVE identifiers.

| Field | Required value |
| --- | --- |
| `cwe` | Closest primary Common Weakness Enumeration identifier and name. |
| `cvss_vector` | Common Vulnerability Scoring System version 3.1 base vector. |
| `cvss_score` | Version 3.1 base score calculated from that vector. |
| `affected_product` | Vendor and product or model identity. |
| `affected_versions` | Observed firmware or build versions and affected, fixed, or unknown status. |
| `references` | External advisories or other references; an original finding can have an empty list. |
| `discovery` | Reporter or credit line for the CVE record. |

For example, a weakness identifier can be `CWE-347: Improper Verification of Cryptographic Signature`.
A vector example is `CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H`.
Select the score from the evidence for that finding.

The loop supplies missing `affected_product` and `affected_versions` from the subject manifest or context.
The analyst must supply `cwe`, `cvss_vector`, and `cvss_score` for each finding.
A scoring pass after the run can add these fields.

## Lifecycle status

Valid statuses are `PROVISIONALLY_VALID`, `NEEDS_RESEARCH`, `VALID`, `FALSE_POSITIVE`, `DUPLICATE`, and `CHAINABLE_DEFERRED`.
Use the disposition gate for terminal or suppressive changes.

## Canonical behavior

Merge findings with the same subject, vulnerability class, normalized title, and affected component into the first canonical finding.
Preserve repeated evidence anchors in `related_locations`.
Do not create independent report findings for those anchors.
An explicit duplicate disposition still requires the normal disposition receipt.
