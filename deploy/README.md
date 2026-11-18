# REFALL AB deployment

## Docker Compose

Run these commands from the repository directory.

1. Create the deployment environment file.

   ```bash
   cp deploy/refall-arcticbase.env.example deploy/refall-arcticbase.env
   ```

2. Set the storage paths in `deploy/refall-arcticbase.env`.
3. Set the public service URL.
4. Set the Agent Canvas URL and API key path for the deployment.
5. Start the workbench container.

   ```bash
   docker compose --env-file deploy/refall-arcticbase.env -f deploy/docker-compose.refall-arcticbase.yml up -d --build
   ```

6. Read the health response at the configured service URL.

The Compose file builds the bundled backend and frontend.
It mounts persistent workbench storage and the configured subject directory.
Agent Canvas, manager executables, and subject execution resources require separate configuration.
Process launch requires those resources in the execution environment.

## Host deployment

Read [Installation](../BASE-INSTALLATION.md) for a native backend process.
The launchd example is `com.gainpalfam.refall-v10.arcticbase.plist.example`.
Set each path and environment value for the deployment host before you install the service.

## Watchdog

The `cron/` directory contains watchdog scheduling examples.
The watchdog reads subject progress and can request recovery work.
Examine the example command and repository path before you install a schedule.

## Storage

Use persistent storage for workbench data and subject artifacts.
Read [Architecture](../docs/architecture.md) for the state model.
Read [Configuration](../docs/configuration.md) for storage settings.
