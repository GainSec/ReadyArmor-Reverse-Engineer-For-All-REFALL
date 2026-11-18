# Subject lifecycle

1. Create a workbench with `python3 -m ref_all_executor subject create`.
2. Set the subject source path.
3. Create the workbench theme through `PUT /api/workbenches/{slug}/theme` when necessary.
4. Generate the shared context.
5. Examine the context and scope.
6. Run the subject diagnosis command.
7. Obtain the subject-scoped `run_local_command` capability.
8. Start the loop with `python3 -m ref_all_executor loop start`.
9. Examine the ledger and pending actions.

Generate Context before Start Loop.
