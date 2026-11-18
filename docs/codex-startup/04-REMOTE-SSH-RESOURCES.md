# Remote SSH resources

Remote resources supply a host operating system, service, device, or execution environment.
`REFALL_SSH_RESOURCE_ALIASES` selects aliases from the configured allowlist.
The current allowlist contains `sectortw` and `sectortl`.
Set an empty value to disable remote resources.

1. Configure the SSH alias on the execution host.
2. Verify the host identity and access.
3. Mount the required SSH configuration in the agent container.
4. Assign the remote resource to the subject task.
5. Run the task with `ssh <alias> <command>`.
6. Record the alias, command, evidence references, and limitations in the submission.

Grok is an optional worker controlled by the host manager.
It is not an SSH resource.
Keep host credentials outside its sandbox.
