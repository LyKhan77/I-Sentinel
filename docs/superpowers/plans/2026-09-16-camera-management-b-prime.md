# Camera Management B′ Implementation Plan

> **For agentic workers:** implement task-by-task using the repository's
> `superpowers:subagent-driven-development` or `superpowers:executing-plans`
> workflow. Each step has a behavior check. Do not skip the migration preview.

**Goal:** Evolve the current camera row into a source-aware management system that supports
shared NVRs, direct IP cameras, arbitrary exact paths, location groups, and per-source or
per-camera credentials without changing existing camera identities.

**Architecture:** Keep the current layered backend and feature-based frontend seams. Add
`StreamSource`, `LocationGroup`, and `CredentialProfile` beside `Camera`; keep legacy camera
host/path/location fields nullable during expand and dual-read/dual-write rollout. One
`stream_endpoint` resolver becomes the only source of credential-bearing RTSP URLs consumed by
probe, go2rtc, and edge-node config publishing.

**Spec:** `docs/superpowers/specs/2026-09-16-camera-management-b-prime-design.md`

## Global constraints

- Work on a new feature branch, for example `feat/camera-management-b-prime`; do not mix
  this work with unrelated UI or runtime-data changes.
- Preserve all existing camera IDs, event/zone foreign keys, `cam_<id>` and
  `cam_<id>_main` stream names, probe metadata, and enabled/status state.
- Expand first, backfill with preview, dual-read/dual-write second, contract last. The first
  migration must not remove or rename legacy camera columns.
- Existing legacy API callers remain functional until the contract phase. New camera writes
  must persist both the new references and compatibility host/path/location fields while the
  compatibility window is open.
- Preview is the default for imports and backfills. Apply must refuse validation errors,
  duplicate identities, unknown sources, or ambiguous credentials; never delete rows absent
  from an import.
- Store only `secret_ref` in `CredentialProfile`; resolve only `env:` references on the
  server. Never return passwords, resolved RTSP URLs, or credential-bearing URLs in API
  responses, logs, tests, screenshots, or import previews.
- Do not add ONVIF discovery, blind channel scanning, path rewriting, or a new secret manager
  in this plan. Vendor candidate discovery remains an explicit suggestion flow.
- Reuse current admin authentication, `go2rtc.py`, `config_push.py`, `CameraWizard`, and
  `CamerasPage` seams. No parallel camera subsystem.
- Do not deploy or alter the server checkout until the local gates and migration dry run pass
  and the user explicitly authorizes the cutover.

---

### Task 1: Add the expandable camera domain schema

**Files:**

- Create: `backend/app/models/stream_source.py`
- Create: `backend/app/models/location_group.py`
- Create: `backend/app/models/credential_profile.py`
- Modify: `backend/app/models/camera.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0007_camera_management_expand.py`
- Create: `backend/tests/test_camera_domain.py`

**Interfaces:**

- `StreamSource(id, name, kind, host, port, vendor, default_credential_id, enabled)`.
- `LocationGroup(id, name, sort_order, enabled)`.
- `CredentialProfile(id, name, username, secret_ref, enabled)`.
- `Camera.source_id`, `Camera.location_group_id`, and `Camera.credential_override_id`, all
  nullable during rollout. Keep `Camera.name` as the display name and keep legacy `host`,
  `rtsp_main`, `rtsp_sub`, and `location` columns.
- Add database indexes/uniqueness for source name, group name, credential name, and the
  non-null camera identity `(source_id, rtsp_main)` without invalidating legacy rows.

- [ ] **Step 1: Write behavior tests for domain invariants**

  Add tests that prove source/group/profile names are unique, camera references can be null
  during compatibility, a camera can reference a source and group, and the camera ID remains
  unchanged when references are added. Do not assert SQLAlchemy implementation details beyond
  observable constraint behavior.

- [ ] **Step 2: Run the focused tests and confirm the missing schema fails**

  ```bash
  cd backend
  pytest tests/test_camera_domain.py
  ```

  Expected: FAIL because the new models and relationships do not exist yet.

- [ ] **Step 3: Implement the models and expand-only Alembic revision**

  Register all models so metadata and Alembic see them. Use string fields for `kind` and
  `secret_ref` rather than database enums so the rollout stays reversible. Add nullable
  foreign keys and indexes; do not populate or delete data inside `0007`.

- [ ] **Step 4: Run the domain and existing camera tests**

  ```bash
  cd backend
  pytest tests/test_camera_domain.py tests/test_cameras_api.py
  ```

  Existing camera create/list/patch/delete/import behavior must remain unchanged before the
  new references are populated.

- [ ] **Step 5: Commit the expand migration**

  ```bash
  git add backend/app/models backend/alembic/versions/0007_camera_management_expand.py backend/tests/test_camera_domain.py
  git commit -m "feat: add camera management domain schema"
  ```

---

### Task 2: Centralize credential resolution and effective endpoints

**Files:**

- Create: `backend/app/services/stream_endpoint.py`
- Modify: `backend/app/services/probe.py`
- Modify: `backend/app/services/go2rtc.py`
- Modify: `backend/app/services/config_push.py`
- Modify: `backend/app/schemas/camera.py`
- Modify: `backend/tests/test_probe.py`
- Modify: `backend/tests/test_go2rtc.py`
- Create: `backend/tests/test_stream_endpoint.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class EffectiveStream:
    host: str
    port: int
    username: str | None
    password: str | None
    main_path: str | None
    sub_path: str | None

def resolve_camera_stream(db, camera: Camera) -> EffectiveStream: ...
def build_rtsp_url(stream: EffectiveStream, path: str | None) -> str | None: ...
```

Resolution precedence is camera credential override, then source default credential, then the
legacy global environment credentials while compatibility mode is enabled. Only the resolver
may construct a credential-bearing URL. The environment adapter accepts `env:NAME` references
and rejects other schemes or missing values without logging the secret.

- [ ] **Step 1: Write failing endpoint behavior tests**

  Cover these observable cases:

  1. one source with two exact paths produces two distinct URLs;
  2. two sources with the same path remain distinct because host/port differ;
  3. camera credential override wins over source default;
  4. missing profile falls back to global credentials only for an un-migrated camera;
  5. unknown/disabled source or credential fails closed;
  6. returned probe metadata contains paths but never username/password;
  7. query strings and non-numeric vendor paths remain byte-for-byte unchanged.

  Assert URLs only in unit tests with synthetic credentials; never print them or place them in
  snapshots/log assertions.

- [ ] **Step 2: Confirm the focused endpoint tests fail**

  ```bash
  cd backend
  pytest tests/test_stream_endpoint.py tests/test_probe.py tests/test_go2rtc.py
  ```

- [ ] **Step 3: Implement the resolver and compatibility adapter**

  Add one resolver that loads source/profile rows, validates `env:` references, applies the
  precedence rules, and returns an internal object. Keep the legacy global path as an explicit
  compatibility fallback, not a second new resolution path.

- [ ] **Step 4: Route integrations through the resolver**

  Update go2rtc sync to derive `cam_<id>` and `cam_<id>_main` from the resolved endpoint.
  Update edge `config_push` to use the resolved substream and preserve server-node local
  go2rtc URLs. Update probe to accept exact source/path input and retain a separate explicit
  candidate-suggestion function for the old vendor guesses.

- [ ] **Step 5: Run endpoint and regression tests**

  ```bash
  cd backend
  pytest tests/test_stream_endpoint.py tests/test_probe.py tests/test_go2rtc.py tests/test_cameras_api.py
  ```

  Existing global-credential tests and stream naming tests must remain green.

- [ ] **Step 6: Commit the resolver cutover**

  ```bash
  git add backend/app/services backend/app/schemas/camera.py backend/tests/test_stream_endpoint.py backend/tests/test_probe.py backend/tests/test_go2rtc.py
  git commit -m "feat: centralize camera stream endpoint resolution"
  ```

---

### Task 3: Build the idempotent backfill and source/group/profile APIs

**Files:**

- Create: `backend/scripts/camera_management_migrate.py`
- Create: `backend/app/schemas/stream_source.py`
- Create: `backend/app/schemas/location_group.py`
- Create: `backend/app/schemas/credential_profile.py`
- Create: `backend/app/api/stream_sources.py`
- Create: `backend/app/api/location_groups.py`
- Create: `backend/app/api/credential_profiles.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_camera_management_migrate.py`
- Create: `backend/tests/test_camera_reference_api.py`

**Interfaces:**

- Backfill command: `python scripts/camera_management_migrate.py --preview` and
  `python scripts/camera_management_migrate.py --apply`; apply requires an explicit flag and
  runs in one transaction.
- `GET/POST/PATCH /api/v1/stream-sources`; source deletion returns `409` while referenced.
- `GET/POST/PATCH /api/v1/location-groups`; group deletion returns `409` while referenced.
- `GET/POST/PATCH /api/v1/credential-profiles`; responses include name, username, enabled,
  and `secret_ref` metadata only; no password field exists in an output schema.

- [ ] **Step 1: Write preview/apply and API contract tests**

  Build a disposable database fixture with the current 25-row shape. Assert preview reports
  distinct host/port sources, non-empty location groups, and one legacy credential profile
  without changing row counts or IDs. Assert apply is idempotent and preserves camera/event/
  zone references. Add API tests for admin-only mutations, masked credential output, source/group
  reference conflicts, and safe 409 deletion behavior.

- [ ] **Step 2: Run the new tests and confirm missing routes/script fail**

  ```bash
  cd backend
  pytest tests/test_camera_management_migrate.py tests/test_camera_reference_api.py
  ```

- [ ] **Step 3: Implement the backfill preview**

  Normalize legacy host values into host/port without rewriting stored camera paths. Report
  proposed source, group, and compatibility credential mappings, including ambiguous source
  kinds and duplicate `(host, path)` identities. Preview must perform no writes.

- [ ] **Step 4: Implement transactional apply and idempotence**

  Create/reuse source/group/profile rows by deterministic natural keys, update only nullable
  camera references, preserve all legacy columns, and return counts/mappings. A second apply
  must report zero new rows and no changed camera IDs. Do not auto-create unknown sources from
  future imports; this script is the explicit migration boundary.

- [ ] **Step 5: Add admin CRUD and register routers**

  Enforce admin mutation dependencies. Validate host/port, source kind, group names, and
  `env:` references. Prevent disabling a profile/source used by an enabled camera unless the
  request explicitly previews the impact and supplies a replacement. Never log resolved
  credentials.

- [ ] **Step 6: Run migration/API regression coverage**

  ```bash
  cd backend
  pytest tests/test_camera_management_migrate.py tests/test_camera_reference_api.py tests/test_cameras_api.py
  ```

- [ ] **Step 7: Commit the migration and management APIs**

  ```bash
  git add backend/scripts/camera_management_migrate.py backend/app/api backend/app/schemas backend/app/main.py backend/tests/test_camera_management_migrate.py backend/tests/test_camera_reference_api.py
  git commit -m "feat: add camera source and credential management"
  ```

---

### Task 4: Extend camera CRUD, probe, and import compatibility

**Files:**

- Modify: `backend/app/models/camera.py`
- Modify: `backend/app/schemas/camera.py`
- Modify: `backend/app/api/cameras.py`
- Modify: `backend/app/api/probe.py`
- Modify: `backend/tests/test_cameras_api.py`
- Modify: `frontend/src/api/cameras.ts` (types only after backend contract is fixed)

**Interfaces:**

- `CameraOut` exposes `source_id`, source summary, `location_group_id`, group summary,
  `credential_override_id`, and exact `main_path`/`sub_path` while retaining compatibility
  fields during rollout.
- `CameraIn`/`CameraPatch` accept either legacy host/path fields or the new source/path
  fields; new source references must exist and belong to an enabled source.
- Probe input accepts `camera_id` or explicit `source_id`, optional credential override, and
  exact paths. A probe without exact paths is clearly a suggestion request and never silently
  writes guessed paths.
- Import preview classifies `MATCHED`, `CREATE`, `UPDATE`, `NEW SOURCE`, `ORPHAN`, `DUPLICATE`,
  and `CREDENTIAL`; `apply=true` refuses any unresolved class.

- [ ] **Step 1: Add failing compatibility tests**

  Cover create/update with source references, exact path preservation, source/group validation,
  credential precedence, probe exactness, stable IDs, and import preview/apply decisions. Keep
  the current 24-camera inventory test and its no-delete behavior.

- [ ] **Step 2: Run the camera API tests before implementation**

  ```bash
  cd backend
  pytest tests/test_cameras_api.py
  ```

- [ ] **Step 3: Implement camera response/input translation**

  Keep old host/path payloads working by resolving or creating no new source implicitly. For
  new payloads, require an existing source and exact paths. On writes, update compatibility
  fields from the effective source/path values so old clients see a consistent representation.
  Reject duplicate `(source_id, main_path)` identities with a useful `409`.

- [ ] **Step 4: Implement exact probe flow**

  Add an exact probe path that receives the resolved endpoint and paths. Retain candidate
  discovery only as an explicit suggestion response. Persist probe metadata only when the
  camera save succeeds, preserving the current edit gate that prevents stale probe results.

- [ ] **Step 5: Upgrade import preview/apply**

  Preserve the deployed legacy text parser and its current 24/24 reconciliation behavior.
  Add the generalized entry shape from the specification with explicit source/group/profile
  references and explicit paths. Never derive `sub_path` by string replacement in the new
  format. Keep apply update-only unless a preview explicitly authorizes a create.

- [ ] **Step 6: Run all backend camera and integration tests**

  ```bash
  cd backend
  pytest tests/test_cameras_api.py tests/test_stream_endpoint.py tests/test_probe.py tests/test_go2rtc.py
  ```

- [ ] **Step 7: Commit the compatibility cutover**

  ```bash
  git add backend/app/models/camera.py backend/app/schemas/camera.py backend/app/api/cameras.py backend/app/api/probe.py backend/tests/test_cameras_api.py
  git commit -m "feat: make camera CRUD source-aware"
  ```

---

### Task 5: Build the source-aware camera administration UI

**Files:**

- Modify: `frontend/src/api/cameras.ts`
- Create: `frontend/src/api/streamSources.ts`
- Create: `frontend/src/api/locationGroups.ts`
- Create: `frontend/src/api/credentialProfiles.ts`
- Modify: `frontend/src/features/config/CamerasPage.tsx`
- Modify: `frontend/src/features/config/CameraWizard.tsx`
- Create: `frontend/src/features/config/CameraSourcesPanel.tsx`
- Create: `frontend/src/features/config/LocationGroupSelect.tsx`
- Modify: `frontend/src/app/i18n.tsx`
- Modify: `frontend/src/__tests__/cameras.test.tsx`
- Create: `frontend/src/__tests__/camera-sources.test.tsx`

**Interfaces:**

- Cameras list displays camera name, source, location group, main/sub probe metadata, node,
  and status without displaying passwords or resolved URLs.
- Wizard chooses an existing source, location group, and optional credential override; edits
  exact main/sub paths as opaque text; probe uses the selected source and paths.
- Source panel manages source metadata and credential profile references. Credential profiles
  expose only name, username, reference, and enabled state.
- Import preview displays all classifications and blocks Apply when unresolved decisions exist.

- [ ] **Step 1: Write failing user-visible tests**

  Add tests for:

  1. source/group/profile options load and render without secret fields;
  2. creating a camera sends source/group IDs and exact paths;
  3. changing a path does not rewrite the other path;
  4. same path under two sources remains selectable;
  5. edit preserves the selected source/group and requires a fresh exact probe after endpoint
     changes;
  6. import preview renders `NEW SOURCE`, `DUPLICATE`, and `CREDENTIAL` decisions and blocks
     apply until resolved;
  7. viewer cannot access source/profile mutations.

- [ ] **Step 2: Run focused frontend tests and confirm missing UI fails**

  ```bash
  cd frontend
  npx vitest run src/__tests__/cameras.test.tsx src/__tests__/camera-sources.test.tsx
  ```

- [ ] **Step 3: Add typed clients and selectors**

  Keep API response types separate from write-only credential input. Load source/group data
  once per camera workbench, show request errors through existing notification patterns, and
  preserve existing loading/empty/admin-gated behavior.

- [ ] **Step 4: Extend the wizard and source panel**

  Replace free host editing for new records with source selection while retaining a clearly
  labeled legacy compatibility path for rows not yet backfilled. Add exact path inputs with no
  vendor rewriting. Keep the current probe sequence guard so stale responses cannot overwrite a
  newer endpoint result.

- [ ] **Step 5: Update import preview and localization**

  Add bilingual ID/EN labels for source, group, credential reference, exact paths, and each
  preview classification. Do not add placeholder configuration tabs or unrelated navigation.

- [ ] **Step 6: Run focused frontend regression tests and build**

  ```bash
  cd frontend
  npx vitest run src/__tests__/cameras.test.tsx src/__tests__/camera-sources.test.tsx src/__tests__/configuration.test.tsx
  npm run build
  ```

- [ ] **Step 7: Commit the source-aware UI**

  ```bash
  git add frontend/src/api frontend/src/features/config frontend/src/app/i18n.tsx frontend/src/__tests__/cameras.test.tsx frontend/src/__tests__/camera-sources.test.tsx
  git commit -m "feat: add source-aware camera management UI"
  ```

---

### Task 6: Verify migration, derived integrations, and server cutover

**Files:**

- Modify: `.env.example` with the `CAMERA_CREDENTIAL_*` reference convention only; never add
  a real secret.
- Modify: `deploy/vision.env.example` only if the edge deployment needs a documented source
  resolver setting.
- Create: `docs/runbooks/camera-management-migration.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Run the complete local backend/frontend gates**

  ```bash
  cd backend && pytest
  cd ../frontend && npx vitest run && npm run build
  ```

  Fix only failures caused by this plan; do not widen scope.

- [ ] **Step 2: Exercise the migration against a disposable database**

  Load a fixture with the deployed 25-camera shape, run `--preview`, assert no writes, run
  `--apply`, assert all IDs/foreign keys/legacy paths survive, then run `--apply` again and
  assert idempotence. Test rollback by restoring the database snapshot and starting the
  pre-cutover application version.

- [ ] **Step 3: Prepare the server without mutation**

  Back up PostgreSQL, record current camera/source/node counts and go2rtc stream names,
  provision only the required `env:` credential variables outside Git, run Alembic expand, and
  capture the backfill preview. Stop if the preview is ambiguous or counts differ from the
  expected 25 rows.

- [ ] **Step 4: Apply and verify the compatibility cutover**

  Apply the backfill, restart API, and verify:

  - all 25 camera IDs still exist;
  - events and zones still resolve to those IDs;
  - API GET responses contain references but no passwords/credential-bearing URLs;
  - go2rtc retains `cam_<id>` and `cam_<id>_main` names;
  - server live view still plays;
  - the vision node receives valid substream config;
  - exact probe succeeds for one NVR path, one direct IP path, and one credential override;
  - legacy import preview remains 24/24 matched and apply remains update-only.

- [ ] **Step 5: Record evidence and rollback**

  Save counts, preview/apply response summaries, focused test output, live/go2rtc/vision smoke
  results, and the database backup location. Rollback is: stop at dual-read/dual-write,
  restore the database backup, restore the previous code/environment, restart API/vision, and
  leave new tables/data untouched until the rollback is confirmed.

- [ ] **Step 6: Commit the runbook and release record**

  ```bash
  git add .env.example deploy/vision.env.example docs/runbooks/camera-management-migration.md CHANGELOG.md
  git commit -m "docs: record camera management migration"
  ```

---

### Task 7: Contract legacy fields only after proof

This is a separate follow-up gate, not part of the first deploy.

- [ ] Prove all frontend/backend/import/vision/go2rtc callers use source/group/profile refs.
- [ ] Prove the deployed server has no legacy-only camera payloads in access logs or migration
  reports, without dumping credentials.
- [ ] Announce a backup and rollback window; take a fresh database backup.
- [ ] Add a later Alembic revision that removes compatibility writes first, then removes legacy
  columns only after one successful release cycle.
- [ ] Keep a reversible export of legacy host/path/location values and update the runbook.

## Definition of done

The first rollout is done when Tasks 1–6 pass and the server accepts both generalized and
legacy camera workflows without data loss. Task 7 remains intentionally gated; premature
column removal would make rollback harder and is not required to deliver the requested
camera-management behavior.
