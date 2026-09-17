# Camera Management B′ migration

## Scope

Revision `0007` is expand-only: it adds `credential_profile`, `location_group`,
and `stream_source`, then nullable camera references. Legacy camera host, path,
location, and identity fields remain live during this rollout.

Revision `0008` makes `alert.camera_id` nullable and rebinds the
`event.camera_id` / `alert.camera_id` foreign keys to `ON DELETE SET NULL`, so
deleting a camera keeps its historical event and alert rows (camera link is
cleared instead of blocking the delete). Rollback note: `0008` downgrade
requires orphan-free camera references before restoring the NOT NULL column.

Credential profiles store a reference only. Set the referenced secret in the
service environment; never put a password in the API, import file, database,
or command history.

```dotenv
CAMERA_CREDENTIAL_NVR_A=replace-in-service-environment
```

Use `env:CAMERA_CREDENTIAL_NVR_A` as `secret_ref`. `env:CAM_PASSWORD` remains
only for the temporary legacy-global fallback.

## Preconditions

1. Obtain explicit authorization for the target server and maintenance window.
2. Stop or drain camera configuration writes.
3. Record the current revision and make a database snapshot before changing it:

   ```sh
   cd backend
   alembic current
   pg_dump "$DATABASE_URL" > camera-management-before-0007.sql
   ```

4. Deploy the code containing revision `0007`, management APIs, resolver, and
   backfill script before running the migration.

## Cutover

1. Apply the expand migration:

   ```sh
   cd backend
   alembic upgrade 0007
   ```

2. Preview the backfill; this writes nothing:

   ```sh
   python scripts/camera_management_migrate.py --preview
   ```

   Record `camera_count`, `source_count`, `location_group_count`, and
   `credential_profile_count`. `ambiguous` must be empty. Resolve any reported
   duplicate `(host:port, rtsp_main)` identity before continuing.

3. Confirm the preview counts and apply:

   ```sh
   python scripts/camera_management_migrate.py --apply
   ```

   Expected output has `applied: true`, `ambiguous: []`, and reports only newly
   created source, group, and credential-profile rows. The operation fills only
   missing references; an existing source or location group is preserved.

4. Verify camera reads, an exact-path probe, go2rtc refresh, and edge config
   publication from the deployed service. Confirm API responses contain no
   password, resolved RTSP URL, or credential secret.

5. Keep legacy fields and dual-read/dual-write behavior enabled. Their removal
   is a separate, explicitly approved contract migration after operational
   proof.

## Rollback

Before the backfill, roll back code and schema only if no new management data
has been written:

```sh
cd backend
alembic downgrade 0006
```

After any backfill or production management write, stop the service, restore
`camera-management-before-0007.sql`, deploy the prior application revision,
and run `alembic downgrade 0006` only against the restored database. Do not
run the downgrade against live backfilled data: it drops the new tables and
reference columns.
