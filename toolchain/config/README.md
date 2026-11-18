# Toolchain configuration

`services.json` defines service commands and health checks for `../ctl.sh`.
Only entries in `services[]` are active.
Entries in `extension_slots[]` are inactive examples.

The MCP JSON files define agent connections to optional analysis services.
Select the configuration for the service that the subject needs.
Run `../ctl.sh status` to examine service state.
Read [Toolchain](../MANIFEST.md) for installation and operation.
