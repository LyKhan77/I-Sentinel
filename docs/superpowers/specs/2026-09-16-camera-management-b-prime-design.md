# Camera Management B′ — Stream Source, Location Group, Credential Profile

**Status:** Chosen architecture; implementation plan pending execution
**Date:** 2026-09-16
**Decision:** B′ — generalized `StreamSource` + `LocationGroup` + `CredentialProfile`

## Goal

Make camera management support all of the following without rewriting RTSP paths or
changing existing camera identities:

- one NVR host with many cameras and arbitrary vendor paths;
- different IP cameras that happen to use the same path;
- different credentials per NVR, camera, or camera override;
- independently editable display names and location groups;
- exact probe, go2rtc, and vision-node URLs derived from one source of truth.

The current 25 camera rows, camera IDs, event references, zone references, go2rtc stream
names, and deployed CCTV import remain valid throughout the rollout.

## Current baseline

The current `camera` row owns `name`, free-text `location`, `host`, `rtsp_main`, `rtsp_sub`,
`node_id`, probe metadata, and status. Credentials are global `CAM_USERNAME`/
`CAM_PASSWORD`. `backend/app/services/probe.py`, `go2rtc.py`, and `config_push.py` each
construct or consume RTSP URLs independently. The existing import reconciles normalized
`(host, rtsp_main)` and is update-only. It must remain compatible during migration.

## Scope

- Add source, location-group, and credential-profile domain records.
- Add nullable references from `camera` while retaining legacy host/path/location columns
  during expand and compatibility rollout.
- Add one effective-endpoint resolver used by exact probe, go2rtc sync, and edge-node
  config publishing.
- Add admin CRUD for stream sources, location groups, and credential profiles.
- Add source/group/credential selection and exact path editing to the camera wizard.
- Upgrade import preview/apply to expose source creation, updates, duplicates, credentials,
  and orphans before mutation.
- Backfill existing rows without changing camera IDs or deleting anything.
- Contract legacy columns only after all callers, imports, and deployed services use the
  new references.

## Non-goals

- ONVIF discovery or blind channel scanning.
- Automatic deletion of cameras absent from an import file.
- Numeric path assumptions such as `101 → 102`.
- Copying credentials into camera GET responses, logs, import payloads, screenshots, or
  go2rtc browser URLs.
- Changing `node_id`: it remains deployment ownership for vision nodes, not NVR identity.
- Moving unrelated repository or ActivityTracking-AI data.

## Domain model

### `StreamSource`

Represents an NVR or one direct IP-camera endpoint.

| Field | Rule |
| --- | --- |
| `id` | Stable primary key. |
| `name` | Admin-facing unique name. |
| `kind` | `nvr`, `ip_camera`, or `unknown` during backfill. |
| `host` | Hostname/IP only; never a URL with credentials. |
| `port` | Integer, default 554. |
| `vendor` | Optional label; informational only. |
| `default_credential_id` | Nullable profile reference. |
| `enabled` | Disabled sources cannot be probed or synced. |

A single source may own many cameras. Different sources may use identical main/sub paths.

### `CredentialProfile`

Represents a reusable credential without returning the secret.

| Field | Rule |
| --- | --- |
| `id` | Stable primary key. |
| `name` | Admin-facing unique name. |
| `username` | Stored/displayed as non-secret metadata. |
| `secret_ref` | Opaque reference resolved only server-side. |
| `enabled` | Disabled profiles cannot produce endpoints. |

The first resolver accepts only an environment-backed reference (for example,
`env:CAMERA_CRED_NVR_MAIN`). The password remains in the server environment/secret store;
the database stores no plaintext password. Unknown or missing references fail closed for
that endpoint and produce a safe error without logging the secret. A later secret provider
can replace the resolver without changing camera rows or API payloads.

### `LocationGroup`

| Field | Rule |
| --- | --- |
| `id` | Stable primary key. |
| `name` | Unique admin-facing label. |
| `sort_order` | Deterministic display order. |
| `enabled` | Disabled groups remain referenced but cannot be newly selected. |

### `Camera` compatibility extension

Add nullable `source_id`, `location_group_id`, and `credential_override_id`. Keep existing
`name` as the display name; do not add a redundant `display_name` column. Keep legacy
`host`, `rtsp_main`, `rtsp_sub`, and `location` nullable until contract. New API responses
expose both compatibility values and source/group summaries during rollout.

The stable `camera.id` remains the identity for events, zones, go2rtc (`cam_<id>` and
`cam_<id>_main`), and external references.

## Effective endpoint contract

One resolver returns an internal endpoint object containing host, port, username,
password, and exact path. It is never serialized directly to an API response.

Resolution precedence:

1. camera credential override;
2. source default credential;
3. legacy global `CAM_USERNAME`/`CAM_PASSWORD` while compatibility mode is enabled.

The resolver joins `source.host + source.port + exact camera path`; it never infers or
rewrites a path. `main_path` and `sub_path` are opaque path/query strings. The resolver is
the only caller allowed to construct credential-bearing RTSP URLs.

- Probe accepts an exact endpoint and returns only stream metadata plus credential-free
  paths.
- go2rtc receives the resolved source URL through the existing sync seam; logs contain
  only camera/stream names and status.
- Server nodes keep local go2rtc URLs (`rtsp://localhost:8554/cam_<id>`).
- Edge nodes receive the resolved substream URL through MQTT config.

## API contract

All mutation endpoints remain admin-only; list/get endpoints require authentication.

- `/api/v1/stream-sources`: list, create, patch, disable; deletion returns `409` while
  cameras reference the source.
- `/api/v1/location-groups`: list, create, patch, disable; deletion returns `409` while
  cameras reference the group.
- `/api/v1/credential-profiles`: list masked metadata, create/update `secret_ref`, disable;
  no endpoint returns a password or resolved URL.
- `/api/v1/cameras`: compatibility fields remain accepted; new fields are source/group/
  credential references and exact paths.
- `/api/v1/cameras/probe`: accepts a camera or explicit source, credential, and exact paths;
  auto-discovery is an explicit suggestion flow only.
- `/api/v1/cameras/import`: preview remains the default. Apply refuses errors and unknown
  sources unless the preview explicitly includes source creation.

## Import contract

Retain the deployed legacy RTSP text parser for existing files, but stop deriving a subpath
by replacing `01` with `02` in the generalized format. New entries carry explicit:

```json
{
  "name": "NVR-CAM-01",
  "source": "NVR-MAIN",
  "location_group": "Lantai 3",
  "credential_profile": "nvr-main",
  "main_path": "/Streaming/Channels/101",
  "sub_path": "/Streaming/Channels/102"
}
```

Preview classifies each row as `MATCHED`, `CREATE`, `UPDATE`, `NEW SOURCE`, `ORPHAN`,
`DUPLICATE`, or `CREDENTIAL`. Matching prefers stable `camera_id` when provided, otherwise
`(source_id, main_path)`. No unmatched or unknown source is silently applied.

## Migration and rollout

1. **Expand:** add new tables, nullable camera references, indexes, and compatibility schemas.
2. **Backfill preview:** report source/group/credential mappings and ambiguity without writes.
3. **Backfill apply:** create one source per distinct host/port, one group per distinct
   non-empty location, and one compatibility credential profile for global credentials;
   update references in one transaction while preserving every legacy field.
4. **Dual-read/dual-write:** new UI/API writes references and legacy fields together; old
   clients continue to work through translation.
5. **Derived cutover:** probe, go2rtc, MQTT config, live view, zones, and events consume the
   endpoint resolver. Verify stable stream names and node payloads.
6. **Contract:** only after deployed callers and import formats no longer need legacy fields,
   remove compatibility writes in a later migration. Legacy columns are not removed in the
   initial rollout.

Every migration has a preview, a database backup requirement, an idempotent apply path, and
an explicit rollback: stop at dual-read/dual-write, restore the pre-migration database, and
restart the previous code version. No camera/event/zone rows are deleted by this feature.

## Acceptance criteria

- One NVR source supports many cameras with arbitrary, exact main/sub paths.
- Two direct IP sources using the same path remain distinct.
- Credential override takes precedence over source default; global credentials remain a
  compatibility fallback only.
- Passwords never appear in camera GET responses, logs, imports, or UI network payloads
  except the write-only secret-reference field.
- Names and location groups are independently editable without changing camera IDs.
- Probe tests the exact selected endpoint; vendor discovery is never silently accepted.
- Existing 25 camera rows, IDs, events, zones, and `cam_<id>` stream names survive unchanged.
- Import preview exposes every create/update/orphan/duplicate/credential decision before apply.
- go2rtc and edge-node config consume the same endpoint resolver.
- Rollback restores the legacy API and data without deleting the new tables or source rows.

## Expected implementation seams

Backend: `models/camera.py`, new `models/stream_source.py`, `location_group.py`, and
`credential_profile.py`; matching schemas/API routers; `services/stream_endpoint.py`,
`probe.py`, `go2rtc.py`, and `config_push.py`; one Alembic expand migration plus an
idempotent backfill script.

Frontend: `api/cameras.ts`, new source/group/credential clients, `CamerasPage.tsx`,
`CameraWizard.tsx`, a source/credential admin panel, and a location-group selector.

Verification: focused backend API/service tests, focused frontend workflow tests, migration
preview/apply against a disposable database, and server smoke tests for live/go2rtc/vision.
