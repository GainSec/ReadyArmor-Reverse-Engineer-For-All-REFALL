# Execution capabilities

The capability broker compares presented action requests with stored operator grants and applicable scope conditions.
Requests declare their action class, target, command, and effects.
A specialist must not authorize its own live action.
Specialists must request operator authority for live actions.
Missing capabilities create requests for operator action.

Backend loop launch obeys broker refusal before process release.
The general authorization endpoint returns a decision without executing the action.
Direct specialist tools do not automatically pass through this route.
Grant and revoke authentication requires the configured operator token file.
Its unset default retains caller-supplied identity fields.
Read [Control in depth](../../control-in-depth.md) for the actual enforcement boundaries and defaults.

Read [Evidence requirements](../../evidence.md) and [API reference](../../api.md) for the operating contract.
