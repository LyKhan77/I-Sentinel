# Enrollment & Shift Refining Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Employee and Shift CRUD complete and unambiguous on the Enrollment page (editable NIK, delete/deactivate with confirmation, per-employee face purge, full shift CRUD in its own tab) and stop inactive employees from matching at the face gate.

**Architecture:** Backend keeps every endpoint; it only tightens Pydantic validation, adds `photo_count`/`face_ready` to `EmployeeOut`, and filters the in-memory face gallery to active employees. Frontend splits `EnrollmentPage.tsx` into a tab shell + `EmployeesTab.tsx` + `ShiftsTab.tsx`; modals are rendered conditionally; layout moves from inline styles to `theme.scss` classes with a one-column breakpoint.

**Tech Stack:** FastAPI + Pydantic v2 + SQLAlchemy 2 (pytest), React 19 + TypeScript + Carbon (`@carbon/react`) + Vitest/Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-23-enrollment-refining-design.md`

## Global Constraints

- Branch `feat/enrollment-refining` (from `main` @ `ea8cd3c`). No DB migration. No new endpoint.
- **No AI attribution** anywhere (commit messages, code, docs) — `AGENTS.md` §9 overrides any default trailer.
- Shell commands are prefixed with `rtk` (user's global rule), e.g. `rtk git status`.
- Face pipeline R5b is untouched except `FaceGallery.load` (active filter) and `refresh_gallery` after an `active` change.
- Shift times are `"HH:MM"`; `end_time` must be strictly greater than `start_time` (overnight shifts rejected — follow-up).
- Field limits: employee `name` 1–128, `employee_code` 1–32, shift `name` 1–64, all whitespace-trimmed.
- All user-facing strings through `frontend/src/app/i18n.tsx`, both `id` and `en` dicts.
- Mobile: zero horizontal page overflow at 390 px.
- Server `gspe-ai3`: read-only is free; push, deploy, and any data write need explicit user permission. Never touch employees Angly (id 1) / Ikhsal or the 2 existing shifts without permission.
- Commit per task (Conventional Commits) and add one bullet per commit to `CHANGELOG.md` under the section created in Task 1.
- Verification baseline (`main` `ea8cd3c`): backend 328 passed, vision 177 passed (3 deselected), frontend 104 passed, build exit 0, lint 22 old warnings — compare the **set** of warnings (rule + file), not the count. Moving code from `EnrollmentPage.tsx` to `EmployeesTab.tsx` may relocate an existing warning to the new file; that is acceptable only if the rule is the same.

## Review Focus

1. PATCH with an explicit `null` for a non-nullable field (`{"start_time": null}`, `{"name": null}`) must not 500 — it is ignored. Pinned in Task 1.
2. Clearing an employee's shift (`{"shift_id": null}`) must still work after the null-filter. Pinned in Task 1.
3. A NIK that differs from an existing one only by surrounding spaces is a duplicate (409), not a new code. Pinned in Task 1.
4. Delete blocked by attendance history on an **already inactive** employee must not offer "Nonaktifkan" again. Pinned in Task 5.
5. Deactivating the selected employee while the list filter is "Aktif" keeps the detail panel on that employee (with an "Aktifkan" button) even though the row leaves the list. Pinned in Task 5.

Also check before deploy (Task 6): an existing server shift with `end_time <= start_time` would become uneditable in the new modal — report it to the user instead of "fixing" data.

---

### Task 1: Backend validation (trim, required, end > start, null-safe PATCH)

**Files:**
- Modify: `backend/app/schemas/employee.py`
- Modify: `backend/app/api/shifts.py` (`update_shift`)
- Modify: `backend/app/api/employees.py` (`update_employee`)
- Test: `backend/tests/test_employees_api.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `app.schemas.employee.END_AFTER_START: str = "end_time must be after start_time"`; 422 on blank names/codes and on `end_time <= start_time` (POST and merged PATCH).

- [ ] **Step 1: Write the failing tests** — append to `backend/tests/test_employees_api.py`:

```python
# --- (i) validasi refining ---------------------------------------------------

def test_employee_blank_name_or_code_422(client):
    h = _admin_headers(client)
    assert client.post("/api/v1/employees", json={"name": "   ", "employee_code": "E1"}, headers=h).status_code == 422
    assert client.post("/api/v1/employees", json={"name": "Budi", "employee_code": ""}, headers=h).status_code == 422


def test_employee_fields_trimmed_and_trimmed_duplicate_409(client):
    h = _admin_headers(client)
    r = client.post("/api/v1/employees", json={"name": "  Budi ", "employee_code": " E001 "}, headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "Budi" and r.json()["employee_code"] == "E001"
    assert client.post("/api/v1/employees", json={"name": "Ani", "employee_code": "E001  "}, headers=h).status_code == 409


def test_employee_patch_code_and_blank_code_422(client):
    h = _admin_headers(client)
    eid = client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001"}, headers=h).json()["id"]
    r = client.patch(f"/api/v1/employees/{eid}", json={"employee_code": "E002"}, headers=h)
    assert r.status_code == 200 and r.json()["employee_code"] == "E002"
    assert client.patch(f"/api/v1/employees/{eid}", json={"employee_code": "  "}, headers=h).status_code == 422


def test_employee_patch_null_ignored_but_shift_can_be_cleared(client):
    h = _admin_headers(client)
    sid = _shift(client, h).json()["id"]
    eid = client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001", "shift_id": sid}, headers=h).json()["id"]
    r = client.patch(f"/api/v1/employees/{eid}", json={"name": None, "active": None}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "Budi" and r.json()["active"] is True
    r = client.patch(f"/api/v1/employees/{eid}", json={"shift_id": None}, headers=h)
    assert r.status_code == 200 and r.json()["shift_id"] is None and r.json()["shift_name"] is None


def test_shift_blank_name_422(client):
    h = _admin_headers(client)
    assert _shift(client, h, name="  ").status_code == 422


def test_shift_end_not_after_start_422(client):
    h = _admin_headers(client)
    assert _shift(client, h, end_time="07:00").status_code == 422
    assert _shift(client, h, end_time="08:00").status_code == 422


def test_shift_patch_validates_merged_times(client):
    h = _admin_headers(client)
    sid = _shift(client, h).json()["id"]  # 08:00–17:00
    assert client.patch(f"/api/v1/shifts/{sid}", json={"end_time": "07:00"}, headers=h).status_code == 422
    assert client.patch(f"/api/v1/shifts/{sid}", json={"start_time": "18:00"}, headers=h).status_code == 422
    r = client.patch(f"/api/v1/shifts/{sid}", json={"start_time": "06:00", "end_time": "07:00"}, headers=h)
    assert r.status_code == 200 and r.json()["end_time"] == "07:00"


def test_shift_patch_null_ignored(client):
    h = _admin_headers(client)
    sid = _shift(client, h).json()["id"]
    r = client.patch(f"/api/v1/shifts/{sid}", json={"start_time": None, "name": None}, headers=h)
    assert r.status_code == 200 and r.json()["start_time"] == "08:00" and r.json()["name"] == "Pagi"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_employees_api.py -q -k "blank or trimmed or patch_code or null or end_not_after or merged"`
Expected: FAIL (blank values return 200; end ≤ start returns 200; null PATCH returns 500/IntegrityError).

- [ ] **Step 3: Implement schemas** — in `backend/app/schemas/employee.py`:

Replace the import block top with:

```python
import re
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

TIME_RE = re.compile(r"^\d{2}:\d{2}$")
VALID_DAYS = set(range(1, 8))
END_AFTER_START = "end_time must be after start_time"

EmpName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
EmpCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
ShiftName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
```

In `ShiftIn`: change `name: str` → `name: ShiftName` and add after the `_v_days` line:

```python
    # ponytail: "HH:MM" sebanding leksikografis; shift lintas tengah malam ditolak (follow-up)
    @model_validator(mode="after")
    def end_after_start(self):
        if self.end_time <= self.start_time:
            raise ValueError(END_AFTER_START)
        return self
```

In `ShiftPatch`: `name: str | None = None` → `name: ShiftName | None = None`.

`EmployeeIn`: `name: EmpName`, `employee_code: EmpCode`.
`EmployeePatch`: `name: EmpName | None = None`, `employee_code: EmpCode | None = None`.

- [ ] **Step 4: Implement routers**

`backend/app/api/shifts.py` — import `END_AFTER_START` (`from app.schemas.employee import END_AFTER_START, ShiftIn, ShiftPatch, ShiftOut`) and in `update_shift` replace `changes = body.model_dump(exclude_unset=True)` with:

```python
    # semua kolom shift NOT NULL → null eksplisit diabaikan, bukan 500
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "name" in changes and _dup_name(db, changes["name"], exclude_id=shift_id):
        raise HTTPException(409, "shift name already exists")
    if changes.get("end_time", shift.end_time) <= changes.get("start_time", shift.start_time):
        raise HTTPException(422, END_AFTER_START)
```

(delete the old duplicate-name check lines that follow, keep the `setattr` loop).

`backend/app/api/employees.py` — in `update_employee` replace `changes = body.model_dump(exclude_unset=True)` with:

```python
    # shift_id boleh null (lepas shift); kolom lain NOT NULL → null eksplisit diabaikan
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k == "shift_id"}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_employees_api.py -q`
Expected: all PASS.

- [ ] **Step 6: Full backend suite**

Run: `cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1`
Expected: `336 passed` (328 + 8), 0 failed. If another test creates a shift with end ≤ start via the API, fix that test's fixture times (not the validator).

- [ ] **Step 7: CHANGELOG + commit** — add at the top of `CHANGELOG.md` (below the format lines):

```markdown
### Enrollment & Shift refining (lokal, 2026-09-23)

- **Validasi backend**: nama/NIK/nama shift di-trim dan wajib isi (422); shift wajib `end_time >
  start_time` di POST dan PATCH gabungan; PATCH null eksplisit diabaikan (dulu 500), `shift_id: null`
  tetap melepas shift. Backend **336 passed**.
```

```bash
rtk git add backend/app/schemas/employee.py backend/app/api/shifts.py backend/app/api/employees.py backend/tests/test_employees_api.py CHANGELOG.md
rtk git commit -m "feat(enrollment): validasi karyawan & shift (trim, wajib isi, selesai > mulai)"
```

---

### Task 2: `EmployeeOut` carries `photo_count` and `face_ready`

**Files:**
- Modify: `backend/app/models/employee.py`
- Modify: `backend/app/api/enrollment.py:20` (remove local `MIN_PHOTOS`, import it)
- Modify: `backend/app/schemas/employee.py` (`EmployeeOut`)
- Test: `backend/tests/test_employees_api.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `app.models.employee.MIN_PHOTOS = 3`; `Employee.photo_count: int`, `Employee.face_ready: bool` properties; JSON fields `photo_count`, `face_ready` on every `EmployeeOut` (list, get, create, patch).

- [ ] **Step 1: Write the failing test** — append:

```python
def test_employee_out_has_photo_count_and_face_ready(client, db):
    from app.models.face_embedding import FaceEmbedding
    h = _admin_headers(client)
    e1 = client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001"}, headers=h).json()
    e2 = client.post("/api/v1/employees", json={"name": "Ani", "employee_code": "E002"}, headers=h).json()
    assert e1["photo_count"] == 0 and e1["face_ready"] is False
    for _ in range(3):
        db.add(FaceEmbedding(employee_id=e1["id"], vector=[1.0, 0.0, 0.0, 0.0], quality=0.9))
    db.add(FaceEmbedding(employee_id=e2["id"], vector=[0.0, 1.0, 0.0, 0.0], quality=0.9))
    db.commit()
    by_id = {e["id"]: e for e in client.get("/api/v1/employees", headers=h).json()}
    assert by_id[e1["id"]]["photo_count"] == 3 and by_id[e1["id"]]["face_ready"] is True
    assert by_id[e2["id"]]["photo_count"] == 1 and by_id[e2["id"]]["face_ready"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_employees_api.py -q -k photo_count`
Expected: FAIL with `KeyError: 'photo_count'`.

- [ ] **Step 3: Implement**

`backend/app/models/employee.py` — after the imports add:

```python
MIN_PHOTOS = 3  # foto minimal agar wajah dianggap siap (enrollment-status + EmployeeOut)
```

and inside `Employee` after `shift_name`:

```python
    @property
    def photo_count(self) -> int:
        return self.embeddings.count()

    @property
    def face_ready(self) -> bool:
        return self.photo_count >= MIN_PHOTOS
```

`backend/app/api/enrollment.py` — delete `MIN_PHOTOS = 3` and change the import to `from app.models.employee import Employee, MIN_PHOTOS`.

`backend/app/schemas/employee.py` — `EmployeeOut` add:

```python
    photo_count: int = 0
    face_ready: bool = False
```

- [ ] **Step 4: Run tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_employees_api.py tests/test_enrollment_api.py -q`
Expected: all PASS.

- [ ] **Step 5: Full backend suite** (command as Task 1 Step 6). Expected `337 passed`.

- [ ] **Step 6: CHANGELOG + commit** — bullet:

```markdown
- **`EmployeeOut` memuat `photo_count` + `face_ready`** (≥ `MIN_PHOTOS` = 3, kini satu sumber di
  `models/employee.py`) → daftar Enrollment tak perlu lagi `enrollment-status` per karyawan (N+1).
```

```bash
rtk git add backend/app/models/employee.py backend/app/api/enrollment.py backend/app/schemas/employee.py backend/tests/test_employees_api.py CHANGELOG.md
rtk git commit -m "feat(enrollment): photo_count dan face_ready di EmployeeOut"
```

---

### Task 3: Face gallery holds only active employees

**Files:**
- Modify: `backend/app/services/face.py` (`FaceGallery.load`, imports)
- Modify: `backend/app/api/employees.py` (`update_employee`)
- Test: `backend/tests/test_face_service.py`, `backend/tests/test_employees_api.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `face.refresh_gallery(db)` (existing), `face.gallery.size()` (existing).
- Produces: gallery excludes `Employee.active == False`; `PATCH /employees/{id}` with `active` refreshes the gallery.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_face_service.py`:

```python
# --- (j) karyawan nonaktif tidak di gallery ---

def test_refresh_gallery_skips_inactive_employees(db):
    a = _employee(db, "E1")
    b = _employee(db, "E2")
    b.active = False
    db.add(FaceEmbedding(employee_id=a.id, vector=[1.0, 0.0, 0.0, 0.0], quality=0.9))
    db.add(FaceEmbedding(employee_id=b.id, vector=[0.0, 1.0, 0.0, 0.0], quality=0.9))
    db.commit()

    refresh_gallery(db)

    assert face.gallery.size() == 1
    assert face.gallery.match([0.0, 1.0, 0.0, 0.0]) is None
    m = face.gallery.match([1.0, 0.0, 0.0, 0.0])
    assert m is not None and m[0] == a.id
```

Append to `backend/tests/test_employees_api.py`:

```python
def test_toggle_active_refreshes_face_gallery(client, db, monkeypatch):
    from app.models.face_embedding import FaceEmbedding
    from app.services import face
    monkeypatch.setattr(face, "gallery", face.FaceGallery())
    h = _admin_headers(client)
    eid = client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001"}, headers=h).json()["id"]
    db.add(FaceEmbedding(employee_id=eid, vector=[1.0, 0.0, 0.0, 0.0], quality=0.9))
    db.commit()
    face.refresh_gallery(db)
    assert face.gallery.size() == 1

    assert client.patch(f"/api/v1/employees/{eid}", json={"active": False}, headers=h).status_code == 200
    assert face.gallery.size() == 0
    assert client.patch(f"/api/v1/employees/{eid}", json={"active": True}, headers=h).status_code == 200
    assert face.gallery.size() == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_face_service.py tests/test_employees_api.py -q -k "inactive or toggle_active"`
Expected: FAIL (`size() == 2` / `size() == 1` after deactivation).

- [ ] **Step 3: Implement**

`backend/app/services/face.py` — add import `from app.models.employee import Employee` next to the `FaceEmbedding` import, and in `FaceGallery.load` replace `for row in db.query(FaceEmbedding).all():` with:

```python
        rows = (
            db.query(FaceEmbedding)
            .join(Employee, Employee.id == FaceEmbedding.employee_id)
            .filter(Employee.active.is_(True))
        )
        for row in rows:
```

Update the `FaceGallery` docstring: `"""In-memory employee_id → list[vector] untuk karyawan AKTIF saja. ..."""` (keep the rest).

`backend/app/api/employees.py` — in `update_employee`, after `db.commit(); db.refresh(emp)`:

```python
    if "active" in changes:
        face.refresh_gallery(db)  # nonaktif = tidak dikenali di gate
```

- [ ] **Step 4: Run tests** — same command as Step 2. Expected: PASS.

- [ ] **Step 5: Full backend + vision suites**

Run: backend command from Task 1 Step 6 → expected `339 passed`; `backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"` → expected `177 passed, 3 deselected`.

- [ ] **Step 6: CHANGELOG + commit** — bullet:

```markdown
- **Karyawan nonaktif tidak dikenali di gate**: `FaceGallery.load` hanya memuat embedding karyawan
  aktif; PATCH `active` me-refresh gallery. Aktif kembali → dikenali lagi tanpa enroll ulang.
  Konsekuensi: wajah karyawan nonaktif tidak memicu peringatan duplikat saat enroll.
```

```bash
rtk git add backend/app/services/face.py backend/app/api/employees.py backend/tests/test_face_service.py backend/tests/test_employees_api.py CHANGELOG.md
rtk git commit -m "feat(attendance): gallery wajah hanya karyawan aktif"
```

---

### Task 4: Frontend — tab shell + Shift tab (full CRUD) + API client

**Files:**
- Modify: `frontend/src/api/employees.ts`
- Modify: `frontend/src/features/enrollment/EnrollmentPage.tsx` (becomes tab shell)
- Create: `frontend/src/features/enrollment/EmployeesTab.tsx` (mechanical move of the old page body)
- Create: `frontend/src/features/enrollment/ShiftsTab.tsx`
- Modify: `frontend/src/app/i18n.tsx`
- Modify: `frontend/src/app/theme.scss`
- Test: `frontend/src/__tests__/shifts.test.tsx` (new)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces (api): `Employee` gains `photo_count: number; face_ready: boolean`; `expectOk(res, what, codes?)` throws `Error(codes[status])` when mapped; `createEmployee`/`updateEmployee` 409 → `'duplicate'`; `deleteEmployee` 409 → `'has_attendance'`; `createShift`/`updateShift` 409 → `'duplicate'`, 422 → `'invalid'`; `updateShift(id: number, patch: Partial<ShiftPayload>): Promise<Shift>`; `deleteShift(id: number): Promise<void>` 409 → `'in_use'`.
- Produces (UI): `EmployeesTab({ isAdmin }: { isAdmin: boolean })`, `ShiftsTab({ isAdmin }: { isAdmin: boolean })`; URL `?tab=employees|shifts` (default employees). CSS classes `en-toolbar`, `en-form`, `en-form__row`, `en-form__hint`, `en-days`, `en-table-scroll`, `en-muted`.

- [ ] **Step 1: Write the failing test** — create `frontend/src/__tests__/shifts.test.tsx`:

```tsx
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import EnrollmentPage from '../features/enrollment/EnrollmentPage'

const ME = { id: 1, username: 'admin', role: 'admin' }
const SHIFTS = [{ id: 1, name: 'Shift 1', start_time: '07:00', end_time: '16:00', tolerance_min: 15, workdays: [1, 2, 3, 4, 5] }]

type Call = { url: string; init?: RequestInit }
const resp = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })
type Route = (u: string, init?: RequestInit) => ReturnType<typeof resp> | undefined

function stubFetch(route?: Route) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    calls.push({ url: u, init })
    const hit = route?.(u, init)
    if (hit) return hit
    if (u.endsWith('/auth/me')) return resp(200, ME)
    if (u.endsWith('/shifts') && init?.method === 'POST') return resp(200, { id: 2, ...JSON.parse(String(init.body)) })
    if (/\/shifts\/\d+$/.test(u) && init?.method === 'PATCH') return resp(200, { ...SHIFTS[0], ...JSON.parse(String(init.body)) })
    if (/\/shifts\/\d+$/.test(u) && init?.method === 'DELETE') return resp(200, { ok: true })
    if (u.endsWith('/shifts')) return resp(200, SHIFTS)
    if (u.endsWith('/employees')) return resp(200, [])
    return resp(404, null)
  }))
  return calls
}

function renderShifts() {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/enrollment?tab=shifts']}>
        <EnrollmentPage />
      </MemoryRouter>
    </I18nProvider>,
  )
}

test('tab Shift menampilkan jam, toleransi, dan hari kerja', async () => {
  stubFetch()
  renderShifts()
  const row = await screen.findByTestId('sh-row-1')
  expect(row).toHaveTextContent('07:00–16:00')
  expect(row).toHaveTextContent('15 mnt')
  expect(row).toHaveTextContent('Sen, Sel, Rab, Kam, Jum')
})

test('tambah shift: selesai <= mulai ditolak di form, valid → POST lengkap', async () => {
  const calls = stubFetch()
  renderShifts()
  fireEvent.click(await screen.findByTestId('sh-add'))
  const dialog = await screen.findByRole('dialog')
  fireEvent.change(within(dialog).getByLabelText('Nama shift'), { target: { value: 'Pagi' } })
  fireEvent.change(within(dialog).getByLabelText('Selesai'), { target: { value: '06:00' } })
  expect(within(dialog).getByTestId('sh-form-problem')).toHaveTextContent('Jam selesai harus setelah jam mulai')
  expect(within(dialog).getByRole('button', { name: 'Simpan' })).toBeDisabled()

  fireEvent.change(within(dialog).getByLabelText('Selesai'), { target: { value: '15:00' } })
  fireEvent.click(within(dialog).getByLabelText('Sab'))
  fireEvent.click(within(dialog).getByRole('button', { name: 'Simpan' }))
  await waitFor(() => {
    const post = calls.find((c) => c.url.endsWith('/shifts') && c.init?.method === 'POST')
    expect(post).toBeDefined()
    expect(JSON.parse(String(post!.init!.body))).toEqual({
      name: 'Pagi', start_time: '07:00', end_time: '15:00', tolerance_min: 15, workdays: [1, 2, 3, 4, 5, 6],
    })
  })
})

test('edit shift mengirim PATCH ke shift yang dipilih', async () => {
  const calls = stubFetch()
  renderShifts()
  fireEvent.click(await screen.findByTestId('sh-edit-1'))
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByLabelText('Nama shift')).toHaveValue('Shift 1')
  fireEvent.click(within(dialog).getByLabelText('Jum'))
  fireEvent.click(within(dialog).getByRole('button', { name: 'Simpan' }))
  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/shifts/1') && c.init?.method === 'PATCH')
    expect(JSON.parse(String(patch!.init!.body)).workdays).toEqual([1, 2, 3, 4])
  })
})

test('nama shift duplikat → pesan spesifik di modal', async () => {
  stubFetch((u, init) => (u.endsWith('/shifts') && init?.method === 'POST' ? resp(409, { detail: 'dup' }) : undefined))
  renderShifts()
  fireEvent.click(await screen.findByTestId('sh-add'))
  const dialog = await screen.findByRole('dialog')
  fireEvent.change(within(dialog).getByLabelText('Nama shift'), { target: { value: 'Shift 1' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Simpan' }))
  expect(await within(dialog).findByText('Nama shift sudah dipakai')).toBeInTheDocument()
})

test('hapus shift yang masih dipakai → 409 dijelaskan', async () => {
  stubFetch((u, init) => (/\/shifts\/1$/.test(u) && init?.method === 'DELETE' ? resp(409, { detail: 'in use' }) : undefined))
  renderShifts()
  fireEvent.click(await screen.findByTestId('sh-delete-1'))
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveTextContent('Shift 1')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Hapus' }))
  expect(await within(dialog).findByText(/Shift masih dipakai karyawan/)).toBeInTheDocument()
})
```

If `findByRole('dialog')` does not resolve with Carbon's Modal in jsdom, use `await waitFor(() => document.querySelector('.cds--modal.is-visible') as HTMLElement)` as the container instead — do not change the assertions.

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/shifts.test.tsx`
Expected: FAIL (`sh-row-1` not found — no Shift tab yet).

- [ ] **Step 3: API client** — in `frontend/src/api/employees.ts`:

Add to the `Employee` type:

```ts
  photo_count: number
  face_ready: boolean
```

Replace `expectOk` with:

```ts
// ponytail: status → kode error tetap yang dibaca UI (mis. 409 → 'duplicate'); selain itu pesan generik
async function expectOk(res: Response, what: string, codes: Record<number, string> = {}) {
  if (!res.ok) throw new Error(codes[res.status] ?? `${what} failed: ${res.status}`)
  return res.json()
}
```

Replace `createEmployee`, `updateEmployee`, `deleteEmployee`, `createShift` and add `updateShift`, `deleteShift`:

```ts
export async function createEmployee(payload: EmployeePayload): Promise<Employee> {
  return expectOk(await apiFetch('/employees', { method: 'POST', body: JSON.stringify(payload) }), 'create employee', { 409: 'duplicate' })
}

export async function updateEmployee(id: number, patch: Partial<EmployeePayload> & { active?: boolean }): Promise<Employee> {
  return expectOk(await apiFetch(`/employees/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }), 'update employee', { 409: 'duplicate' })
}

export async function deleteEmployee(id: number): Promise<void> {
  await expectOk(await apiFetch(`/employees/${id}`, { method: 'DELETE' }), 'delete employee', { 409: 'has_attendance' })
}

const SHIFT_ERRORS = { 409: 'duplicate', 422: 'invalid' }

export async function createShift(payload: ShiftPayload): Promise<Shift> {
  return expectOk(await apiFetch('/shifts', { method: 'POST', body: JSON.stringify(payload) }), 'create shift', SHIFT_ERRORS)
}

export async function updateShift(id: number, patch: Partial<ShiftPayload>): Promise<Shift> {
  return expectOk(await apiFetch(`/shifts/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }), 'update shift', SHIFT_ERRORS)
}

export async function deleteShift(id: number): Promise<void> {
  await expectOk(await apiFetch(`/shifts/${id}`, { method: 'DELETE' }), 'delete shift', { 409: 'in_use' })
}
```

- [ ] **Step 4: Move the old page body to `EmployeesTab.tsx`**

Run `cp frontend/src/features/enrollment/EnrollmentPage.tsx frontend/src/features/enrollment/EmployeesTab.tsx`, then in `EmployeesTab.tsx`:
1. `export default function EnrollmentPage()` → `export default function EmployeesTab({ isAdmin }: { isAdmin: boolean })`.
2. Remove `import { getMe, type Me } from '../../api/client'`, `createShift` from the api import, the `me` state, and `const isAdmin = me?.role === 'admin'`.
3. The mount effect becomes `useEffect(() => { refresh() }, [refresh])`.
4. Remove `newShift`/`showAddShift` state, the `addShift` handler, and the whole SHIFT card `<div …>` (the block starting with `<h4 …>{t('en.shift')}</h4>` through its `showAddShift` ternary).
5. Replace the outer `<div className="app-page">` and its `app-page__head` block with `<div>` and replace the search wrapper `<div style={{ width: 260, marginBottom: 14 }}>` with:

```tsx
      <div className="en-toolbar">
        <TextInput id="en-search" labelText={t('en.search')} value={query} onChange={(e) => setQuery(e.target.value)} />
        {isAdmin && (
          <Button data-testid="en-add" onClick={() => setAdding(true)}>
            {t('en.add')}
          </Button>
        )}
      </div>
```

(Task 5 rewrites this file fully; this step only has to keep the existing `enrollment.test.tsx` green.)

- [ ] **Step 5: Tab shell** — replace `frontend/src/features/enrollment/EnrollmentPage.tsx` entirely:

```tsx
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Tab, TabList, TabPanel, TabPanels, Tabs } from '@carbon/react'
import { useT } from '../../app/i18n'
import { getMe, type Me } from '../../api/client'
import EmployeesTab from './EmployeesTab'
import ShiftsTab from './ShiftsTab'

const TABS = ['employees', 'shifts'] as const
type EnrollmentTab = (typeof TABS)[number]

export default function EnrollmentPage() {
  const { t } = useT()
  const [params, setParams] = useSearchParams()
  const [me, setMe] = useState<Me | null>(null)
  // ponytail: nilai `tab` di luar daftar → employees; hanya panel terpilih yang di-mount
  const raw = params.get('tab')
  const tab: EnrollmentTab = TABS.includes(raw as EnrollmentTab) ? (raw as EnrollmentTab) : 'employees'
  const isAdmin = me?.role === 'admin'

  useEffect(() => {
    getMe().then(setMe).catch(() => setMe(null))
  }, [])

  return (
    <div className="app-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('en.title')}</h1>
          <p className="app-page__sub">{t('en.sub')}</p>
        </div>
      </div>
      <Tabs
        selectedIndex={TABS.indexOf(tab)}
        onChange={({ selectedIndex }) => {
          const next = TABS[selectedIndex]
          if (next !== tab) setParams({ tab: next })
        }}
      >
        <TabList aria-label={t('en.title')}>
          <Tab>{t('en.tab.employees')}</Tab>
          <Tab>{t('en.tab.shifts')}</Tab>
        </TabList>
        <TabPanels>
          <TabPanel>{tab === 'employees' && <EmployeesTab isAdmin={isAdmin} />}</TabPanel>
          <TabPanel>{tab === 'shifts' && <ShiftsTab isAdmin={isAdmin} />}</TabPanel>
        </TabPanels>
      </Tabs>
    </div>
  )
}
```

- [ ] **Step 6: Shift tab** — create `frontend/src/features/enrollment/ShiftsTab.tsx`:

```tsx
import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  Checkbox,
  InlineLoading,
  InlineNotification,
  Modal,
  NumberInput,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TextInput,
} from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { createShift, deleteShift, listShifts, updateShift, type Shift, type ShiftPayload } from '../../api/employees'

type ShiftForm = Required<ShiftPayload>

const DAYS = [1, 2, 3, 4, 5, 6, 7] as const
const EMPTY: ShiftForm = { name: '', start_time: '07:00', end_time: '16:00', tolerance_min: 15, workdays: [1, 2, 3, 4, 5] }
const HEADERS = ['sh.col.name', 'sh.col.time', 'sh.col.tolerance', 'sh.col.workdays'] as const

// ponytail: "HH:MM" sebanding leksikografis; shift lintas tengah malam sengaja ditolak (spec §2)
function formProblem(f: ShiftForm): TKey | null {
  if (!f.name.trim()) return 'sh.err.name'
  if (!f.start_time || !f.end_time || f.end_time <= f.start_time) return 'sh.err.endAfterStart'
  if (f.workdays.length === 0) return 'sh.err.workdays'
  return null
}

export default function ShiftsTab({ isAdmin }: { isAdmin: boolean }) {
  const { t } = useT()
  const [shifts, setShifts] = useState<Shift[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<Shift | 'new' | null>(null)
  const [form, setForm] = useState<ShiftForm>(EMPTY)
  const [serverError, setServerError] = useState<TKey | null>(null)
  const [deleting, setDeleting] = useState<Shift | null>(null)
  const [deleteError, setDeleteError] = useState<TKey | null>(null)

  const refresh = useCallback(async () => {
    try {
      setShifts(await listShifts())
    } catch {
      setError(t('sh.loadError'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    refresh()
  }, [refresh])

  const openForm = (s: Shift | 'new') => {
    setEditing(s)
    setForm(s === 'new' ? EMPTY : { name: s.name, start_time: s.start_time, end_time: s.end_time, tolerance_min: s.tolerance_min, workdays: s.workdays })
    setServerError(null)
  }

  const save = async () => {
    const payload = { ...form, name: form.name.trim() }
    try {
      if (editing === 'new') await createShift(payload)
      else if (editing) await updateShift(editing.id, payload)
      setEditing(null)
      await refresh()
    } catch (e) {
      const code = (e as Error).message
      setServerError(code === 'duplicate' ? 'sh.err.duplicate' : code === 'invalid' ? 'sh.err.invalid' : 'en.saveError')
    }
  }

  const remove = async () => {
    if (!deleting) return
    try {
      await deleteShift(deleting.id)
      setDeleting(null)
      await refresh()
    } catch (e) {
      setDeleteError((e as Error).message === 'in_use' ? 'sh.err.inUse' : 'en.saveError')
    }
  }

  const toggleDay = (d: number, on: boolean) =>
    setForm((f) => ({ ...f, workdays: on ? [...f.workdays, d].sort((a, b) => a - b) : f.workdays.filter((x) => x !== d) }))

  const dayNames = (ws: number[]) => ws.map((d) => t(`sh.day.${d}` as TKey)).join(', ')
  const problem = formProblem(form)

  return (
    <div>
      {error && <InlineNotification kind="error" lowContrast title={t('common.error')} subtitle={error} onCloseButtonClick={() => setError(null)} />}
      {isAdmin && (
        <div className="en-toolbar">
          <Button size="sm" data-testid="sh-add" onClick={() => openForm('new')}>
            {t('sh.add')}
          </Button>
        </div>
      )}

      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : shifts.length === 0 ? (
        <p className="en-muted">{t('sh.empty')}</p>
      ) : (
        <div className="en-table-scroll">
          <TableContainer>
            <Table size="sm">
              <TableHead>
                <TableRow>
                  {HEADERS.map((h) => (
                    <TableHeader key={h}>{t(h)}</TableHeader>
                  ))}
                  {isAdmin && <TableHeader>{t('sh.col.actions')}</TableHeader>}
                </TableRow>
              </TableHead>
              <TableBody>
                {shifts.map((s) => (
                  <TableRow key={s.id} data-testid={`sh-row-${s.id}`}>
                    <TableCell>{s.name}</TableCell>
                    <TableCell>
                      {s.start_time}–{s.end_time}
                    </TableCell>
                    <TableCell>{t('sh.minutes').replace('{n}', String(s.tolerance_min))}</TableCell>
                    <TableCell>{dayNames(s.workdays)}</TableCell>
                    {isAdmin && (
                      <TableCell>
                        <Button kind="ghost" size="sm" data-testid={`sh-edit-${s.id}`} onClick={() => openForm(s)}>
                          {t('sh.edit')}
                        </Button>
                        <Button
                          kind="danger--ghost"
                          size="sm"
                          data-testid={`sh-delete-${s.id}`}
                          onClick={() => {
                            setDeleting(s)
                            setDeleteError(null)
                          }}
                        >
                          {t('sh.delete')}
                        </Button>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </div>
      )}

      {editing !== null && (
        <Modal
          open
          modalHeading={t(editing === 'new' ? 'sh.addTitle' : 'sh.editTitle')}
          primaryButtonText={t('common.save')}
          secondaryButtonText={t('common.cancel')}
          primaryButtonDisabled={problem !== null}
          onRequestClose={() => setEditing(null)}
          onRequestSubmit={save}
          size="sm"
        >
          <div className="en-form">
            <TextInput id="sh-name" labelText={t('sh.name')} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <div className="en-form__row">
              <TextInput id="sh-start" type="time" labelText={t('sh.start')} value={form.start_time} onChange={(e) => setForm({ ...form, start_time: e.target.value })} />
              <TextInput id="sh-end" type="time" labelText={t('sh.end')} value={form.end_time} onChange={(e) => setForm({ ...form, end_time: e.target.value })} />
            </div>
            <NumberInput
              id="sh-tolerance"
              label={t('sh.tolerance')}
              min={0}
              max={120}
              step={1}
              value={form.tolerance_min}
              onChange={(_, state) => {
                const n = Number(state.value)
                if (Number.isInteger(n) && n >= 0 && n <= 120) setForm((f) => ({ ...f, tolerance_min: n }))
              }}
            />
            <fieldset className="en-days">
              <legend className="cds--label">{t('sh.workdays')}</legend>
              {DAYS.map((d) => (
                <Checkbox
                  key={d}
                  id={`sh-day-${d}`}
                  labelText={t(`sh.day.${d}` as TKey)}
                  checked={form.workdays.includes(d)}
                  onChange={(_, { checked }) => toggleDay(d, checked)}
                />
              ))}
            </fieldset>
            {problem && (
              <p className="en-form__hint" data-testid="sh-form-problem">
                {t(problem)}
              </p>
            )}
            {serverError && <InlineNotification kind="error" lowContrast hideCloseButton title={t(serverError)} />}
          </div>
        </Modal>
      )}

      {deleting && (
        <Modal
          open
          danger
          modalHeading={t('sh.deleteTitle')}
          primaryButtonText={t('sh.delete')}
          secondaryButtonText={t('common.cancel')}
          onRequestClose={() => setDeleting(null)}
          onRequestSubmit={remove}
          size="sm"
        >
          <p>{t('sh.deleteBody').replace('{name}', deleting.name)}</p>
          {deleteError && <InlineNotification kind="error" lowContrast hideCloseButton title={t(deleteError)} />}
        </Modal>
      )}
    </div>
  )
}
```

- [ ] **Step 7: i18n** — in `frontend/src/app/i18n.tsx`, remove `en.shift`, `en.shift.add`, `en.shift.name`, `en.shift.start`, `en.shift.end` from **both** dicts (first `rtk grep -rn "en\.shift\.\(add\|name\|start\|end\)'\|'en\.shift'" frontend/src` must show only i18n.tsx). Keep `en.shift.select`. Add after the `en.*` block of each dict:

`id`:
```ts
    'en.tab.employees': 'Karyawan',
    'en.tab.shifts': 'Shift',
    'sh.add': '+ Shift',
    'sh.empty': 'Belum ada shift',
    'sh.loadError': 'Gagal memuat shift',
    'sh.col.name': 'NAMA',
    'sh.col.time': 'JAM',
    'sh.col.tolerance': 'TOLERANSI',
    'sh.col.workdays': 'HARI KERJA',
    'sh.col.actions': 'AKSI',
    'sh.minutes': '{n} mnt',
    'sh.day.1': 'Sen',
    'sh.day.2': 'Sel',
    'sh.day.3': 'Rab',
    'sh.day.4': 'Kam',
    'sh.day.5': 'Jum',
    'sh.day.6': 'Sab',
    'sh.day.7': 'Min',
    'sh.addTitle': 'Tambah shift',
    'sh.editTitle': 'Edit shift',
    'sh.name': 'Nama shift',
    'sh.start': 'Mulai',
    'sh.end': 'Selesai',
    'sh.tolerance': 'Toleransi terlambat (menit)',
    'sh.workdays': 'Hari kerja',
    'sh.edit': 'Edit',
    'sh.delete': 'Hapus',
    'sh.deleteTitle': 'Hapus shift',
    'sh.deleteBody': 'Hapus shift "{name}"?',
    'sh.err.name': 'Nama shift wajib diisi',
    'sh.err.endAfterStart': 'Jam selesai harus setelah jam mulai (shift lintas tengah malam belum didukung)',
    'sh.err.workdays': 'Pilih minimal satu hari kerja',
    'sh.err.duplicate': 'Nama shift sudah dipakai',
    'sh.err.invalid': 'Data shift tidak valid',
    'sh.err.inUse': 'Shift masih dipakai karyawan. Pindahkan karyawan ke shift lain dulu.',
```

`en`:
```ts
    'en.tab.employees': 'Employees',
    'en.tab.shifts': 'Shifts',
    'sh.add': '+ Shift',
    'sh.empty': 'No shifts yet',
    'sh.loadError': 'Failed to load shifts',
    'sh.col.name': 'NAME',
    'sh.col.time': 'HOURS',
    'sh.col.tolerance': 'TOLERANCE',
    'sh.col.workdays': 'WORKDAYS',
    'sh.col.actions': 'ACTIONS',
    'sh.minutes': '{n} min',
    'sh.day.1': 'Mon',
    'sh.day.2': 'Tue',
    'sh.day.3': 'Wed',
    'sh.day.4': 'Thu',
    'sh.day.5': 'Fri',
    'sh.day.6': 'Sat',
    'sh.day.7': 'Sun',
    'sh.addTitle': 'Add shift',
    'sh.editTitle': 'Edit shift',
    'sh.name': 'Shift name',
    'sh.start': 'Start',
    'sh.end': 'End',
    'sh.tolerance': 'Late tolerance (minutes)',
    'sh.workdays': 'Workdays',
    'sh.edit': 'Edit',
    'sh.delete': 'Delete',
    'sh.deleteTitle': 'Delete shift',
    'sh.deleteBody': 'Delete shift "{name}"?',
    'sh.err.name': 'Shift name is required',
    'sh.err.endAfterStart': 'End time must be after start time (overnight shifts are not supported yet)',
    'sh.err.workdays': 'Pick at least one workday',
    'sh.err.duplicate': 'Shift name already in use',
    'sh.err.invalid': 'Invalid shift data',
    'sh.err.inUse': 'Shift is still assigned to employees. Move them to another shift first.',
```

- [ ] **Step 8: CSS** — append to `frontend/src/app/theme.scss`:

```scss
/* Enrollment (tab Karyawan | Shift) */
.en-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
  margin-block: 14px;
}

.en-toolbar .cds--form-item {
  flex: 0 1 260px;
  min-inline-size: 0;
}

.en-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.en-form__row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.en-form__row > * {
  flex: 1 1 140px;
}

.en-form__hint,
.en-muted {
  color: var(--cds-text-helper);
  font-size: 12px;
}

.en-days {
  display: flex;
  flex-wrap: wrap;
  column-gap: 12px;
}

.en-days legend {
  inline-size: 100%;
}

.en-table-scroll {
  overflow-x: auto;
  max-inline-size: 100%;
}
```

- [ ] **Step 9: Run tests**

Run: `cd frontend && npx vitest run src/__tests__/shifts.test.tsx src/__tests__/enrollment.test.tsx`
Expected: all PASS (existing enrollment tests unchanged and green).

- [ ] **Step 10: Full frontend verification**

Run: `cd frontend && npx vitest run && npm run build && npm run lint`
Expected: 109 passed (104 + 5), build exit 0, lint warning set unchanged (see Global Constraints).

- [ ] **Step 11: CHANGELOG + commit** — bullet:

```markdown
- **Tab Shift** di Enrollment (`?tab=shifts`): tabel + modal tambah/edit (nama, jam `type=time`,
  toleransi, hari kerja) + hapus dengan konfirmasi; error duplikat / selesai ≤ mulai / "masih dipakai"
  tampil spesifik. Kartu shift dikeluarkan dari panel karyawan. Frontend **109 passed**.
```

```bash
rtk git add frontend/src/api/employees.ts frontend/src/features/enrollment/ frontend/src/app/i18n.tsx frontend/src/app/theme.scss frontend/src/__tests__/shifts.test.tsx CHANGELOG.md
rtk git commit -m "feat(enrollment): tab Shift dengan CRUD lengkap"
```

---

### Task 5: Frontend — Employees tab rework

**Files:**
- Modify (full rewrite): `frontend/src/features/enrollment/EmployeesTab.tsx`
- Modify: `frontend/src/app/i18n.tsx`
- Modify: `frontend/src/app/theme.scss`
- Modify (rewrite fixtures + add tests): `frontend/src/__tests__/enrollment.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes (Task 4): `Employee.photo_count`, `Employee.face_ready`; error codes `'duplicate'`, `'has_attendance'`; classes `en-toolbar`, `en-form`, `en-muted`.
- Produces: test ids `en-row-{id}`, `en-face-{id}`, `en-dot-{id}`, `en-inactive-{id}`, `en-card-identity`, `en-card-face`, `en-card-status`, `en-save`, `en-purge`, `en-toggle-active`, `en-delete`, `en-add`, `en-upload-input`, `en-batch-results`, `en-photo-{id}`, `en-photo-del-{id}`.

- [ ] **Step 1: Rewrite the test file** — replace `frontend/src/__tests__/enrollment.test.tsx` entirely:

```tsx
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import EnrollmentPage from '../features/enrollment/EnrollmentPage'

const ME = { id: 1, username: 'admin', role: 'admin' }

const EMPLOYEES = [
  { id: 1, name: 'Budi Santoso', employee_code: 'EMP-0012', active: true, shift_id: 1, shift_name: 'Shift 1', photo_count: 3, face_ready: true },
  { id: 2, name: 'Sari Dewi', employee_code: 'EMP-0044', active: true, shift_id: 2, shift_name: 'Shift 2', photo_count: 0, face_ready: false },
  { id: 3, name: 'Joko Lama', employee_code: 'EMP-0003', active: false, shift_id: null, shift_name: null, photo_count: 1, face_ready: false },
]

const SHIFTS = [{ id: 1, name: 'Shift 1', start_time: '07:00', end_time: '16:00', tolerance_min: 15, workdays: [1, 2, 3, 4, 5] }]

const PHOTOS = [{ id: 5, quality: 0.97, created_at: '2025-01-10T08:00:00Z', path: 'faces/1/a.jpg' }]

type Call = { url: string; init?: RequestInit }
const resp = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })
type Route = (u: string, init?: RequestInit) => ReturnType<typeof resp> | undefined

function stubFetch(route?: Route) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    calls.push({ url: u, init })
    const hit = route?.(u, init)
    if (hit) return hit
    if (u.endsWith('/auth/me')) return resp(200, ME)
    if (u.endsWith('/shifts')) return resp(200, SHIFTS)
    if (u.endsWith('/photos/batch') && init?.method === 'POST') return resp(200, { results: [{ ok: true, quality: 0.9 }] })
    if (u.endsWith('/photos')) return resp(200, PHOTOS)
    if (u.endsWith('/biometrics') && init?.method === 'DELETE') return resp(200, { deleted: 3 })
    const one = u.match(/\/employees\/(\d+)$/)
    if (one && init?.method === 'PATCH') {
      const emp = EMPLOYEES.find((e) => e.id === Number(one[1]))
      return resp(200, { ...emp, ...JSON.parse(String(init.body)) })
    }
    if (one && init?.method === 'DELETE') return resp(200, { ok: true })
    if (u.endsWith('/employees')) return resp(200, EMPLOYEES)
    return resp(404, null)
  }))
  return calls
}

function renderPage() {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/enrollment']}>
        <EnrollmentPage />
      </MemoryRouter>
    </I18nProvider>,
  )
}

const bodyOf = (c: Call | undefined) => JSON.parse(String(c!.init!.body))

test('daftar: badge wajah dari photo_count tanpa panggilan enrollment-status', async () => {
  const calls = stubFetch()
  renderPage()
  expect((await screen.findAllByText('Budi Santoso')).length).toBeGreaterThanOrEqual(1)
  expect(screen.getByTestId('en-face-1')).toHaveTextContent('3 Foto')
  expect(screen.getByTestId('en-face-2')).toHaveTextContent('BELUM')
  const dot1 = screen.getByTestId('en-dot-1')
  const dot2 = screen.getByTestId('en-dot-2')
  expect(dot1.style.background).not.toBe(dot2.style.background)
  expect(calls.some((c) => c.url.endsWith('/enrollment-status'))).toBe(false)
})

test('filter status: default Aktif, Nonaktif menampilkan karyawan nonaktif dengan tag', async () => {
  stubFetch()
  renderPage()
  await screen.findAllByText('Budi Santoso')
  expect(screen.queryByTestId('en-row-3')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'inactive' } })
  expect(await screen.findByTestId('en-row-3')).toBeInTheDocument()
  expect(screen.getByTestId('en-inactive-3')).toHaveTextContent('Nonaktif')
  expect(screen.queryByTestId('en-row-1')).not.toBeInTheDocument()
})

test('NIK bisa diedit dan dikirim di PATCH', async () => {
  const calls = stubFetch()
  renderPage()
  await screen.findAllByText('Budi Santoso')
  const code = within(screen.getByTestId('en-card-identity')).getByLabelText('NIK')
  expect(code).not.toBeDisabled()
  fireEvent.change(code, { target: { value: ' EMP-0099 ' } })
  fireEvent.click(screen.getByTestId('en-save'))
  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/employees/1') && c.init?.method === 'PATCH')
    expect(bodyOf(patch)).toEqual({ name: 'Budi Santoso', employee_code: 'EMP-0099', shift_id: 1 })
  })
})

test('NIK duplikat saat simpan → pesan inline di field NIK', async () => {
  stubFetch((u, init) => (u.endsWith('/employees/1') && init?.method === 'PATCH' ? resp(409, { detail: 'dup' }) : undefined))
  renderPage()
  await screen.findAllByText('Budi Santoso')
  fireEvent.change(within(screen.getByTestId('en-card-identity')).getByLabelText('NIK'), { target: { value: 'EMP-0044' } })
  fireEvent.click(screen.getByTestId('en-save'))
  expect(await screen.findByText('NIK sudah dipakai')).toBeInTheDocument()
})

test('hapus foto wajah ada di kartu Wajah, menyebut nama, dan memanggil biometrics karyawan itu', async () => {
  const calls = stubFetch()
  renderPage()
  await screen.findAllByText('Budi Santoso')
  const purge = within(screen.getByTestId('en-card-face')).getByTestId('en-purge')
  expect(purge).toHaveTextContent('Budi Santoso')
  fireEvent.click(purge)
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveTextContent('3 foto')
  expect(dialog).toHaveTextContent('Budi Santoso')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Hapus foto' }))
  await waitFor(() => expect(calls.some((c) => c.url.endsWith('/employees/1/biometrics') && c.init?.method === 'DELETE')).toBe(true))
})

test('hapus foto wajah nonaktif bila belum ada foto', async () => {
  stubFetch()
  renderPage()
  fireEvent.click(await screen.findByTestId('en-row-2'))
  await waitFor(() => expect(within(screen.getByTestId('en-card-face')).getByTestId('en-purge')).toBeDisabled())
})

test('nonaktifkan butuh konfirmasi; detail tetap pada karyawan itu', async () => {
  const calls = stubFetch((u, init) => {
    if (u.endsWith('/employees') && !init?.method && calls.some((c) => c.init?.method === 'PATCH')) {
      return resp(200, EMPLOYEES.map((e) => (e.id === 1 ? { ...e, active: false } : e)))
    }
    return undefined
  })
  renderPage()
  await screen.findAllByText('Budi Santoso')
  fireEvent.click(screen.getByTestId('en-toggle-active'))
  expect(calls.some((c) => c.init?.method === 'PATCH')).toBe(false)
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveTextContent('tidak akan dikenali di gate')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Nonaktifkan' }))
  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/employees/1') && c.init?.method === 'PATCH')
    expect(bodyOf(patch)).toEqual({ active: false })
  })
  // baris keluar dari filter Aktif, tapi panel detail tetap pada Budi dengan tombol Aktifkan
  await waitFor(() => expect(screen.queryByTestId('en-row-1')).not.toBeInTheDocument())
  expect(screen.getByTestId('en-toggle-active')).toHaveTextContent('Aktifkan')
})

test('hapus karyawan ber-riwayat absensi → ditawarkan Nonaktifkan', async () => {
  const calls = stubFetch((u, init) => (u.endsWith('/employees/1') && init?.method === 'DELETE' ? resp(409, { detail: 'history' }) : undefined))
  renderPage()
  await screen.findAllByText('Budi Santoso')
  fireEvent.click(screen.getByTestId('en-delete'))
  let dialog = await screen.findByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Hapus karyawan' }))
  await waitFor(() => expect(screen.getByRole('dialog')).toHaveTextContent('sudah punya riwayat absensi'))
  dialog = screen.getByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Nonaktifkan' }))
  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/employees/1') && c.init?.method === 'PATCH')
    expect(bodyOf(patch)).toEqual({ active: false })
  })
})

test('hapus karyawan nonaktif ber-riwayat → tidak menawarkan Nonaktifkan lagi', async () => {
  stubFetch((u, init) => (u.endsWith('/employees/3') && init?.method === 'DELETE' ? resp(409, { detail: 'history' }) : undefined))
  renderPage()
  await screen.findAllByText('Budi Santoso')
  fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'inactive' } })
  fireEvent.click(await screen.findByTestId('en-row-3'))
  fireEvent.click(screen.getByTestId('en-delete'))
  fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Hapus karyawan' }))
  await waitFor(() => expect(screen.getByRole('dialog')).toHaveTextContent('sudah nonaktif'))
  expect(within(screen.getByRole('dialog')).queryByRole('button', { name: 'Nonaktifkan' })).not.toBeInTheDocument()
})

test('tambah karyawan: Simpan nonaktif selama nama/NIK kosong; 409 → pesan di NIK', async () => {
  stubFetch((u, init) => (u.endsWith('/employees') && init?.method === 'POST' ? resp(409, { detail: 'dup' }) : undefined))
  renderPage()
  await screen.findAllByText('Budi Santoso')
  fireEvent.click(screen.getByTestId('en-add'))
  const dialog = await screen.findByRole('dialog')
  const save = within(dialog).getByRole('button', { name: 'Simpan' })
  expect(save).toBeDisabled()
  fireEvent.change(within(dialog).getByLabelText('Nama'), { target: { value: 'Ani' } })
  fireEvent.change(within(dialog).getByLabelText('NIK'), { target: { value: 'EMP-0012' } })
  expect(save).not.toBeDisabled()
  fireEvent.click(save)
  expect(await within(dialog).findByText('NIK sudah dipakai')).toBeInTheDocument()
})

test('upload multi-file: batch sekali + hasil per foto', async () => {
  const calls = stubFetch((u, init) =>
    u.endsWith('/photos/batch') && init?.method === 'POST'
      ? resp(200, { results: [{ ok: true, quality: 0.91 }, { ok: false, reason: 'no_face' }] })
      : undefined,
  )
  renderPage()
  await screen.findAllByText('Budi Santoso')
  const ok = new File(['a'], 'a.jpg', { type: 'image/jpeg' })
  const bad = new File(['b'], 'b.jpg', { type: 'image/jpeg' })
  fireEvent.change(screen.getByTestId('en-upload-input'), { target: { files: [ok, bad] } })
  await waitFor(() => {
    const post = calls.find((c) => c.url.endsWith('/employees/1/photos/batch'))
    expect((post!.init!.body as FormData).getAll('files')).toEqual([ok, bad])
  })
  const list = await screen.findByTestId('en-batch-results')
  expect(list).toHaveTextContent('Tersimpan (hasil crop)')
  expect(list).toHaveTextContent('Skor: 0.91')
  expect(list).toHaveTextContent('Wajah tidak terdeteksi')
})
```

(Old test count 3 in this file → new 11: net +8.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/__tests__/enrollment.test.tsx`
Expected: FAIL — filter, NIK edit, purge-in-card, status and delete tests fail; badge test fails on `enrollment-status` being called.

- [ ] **Step 3: i18n** — in `frontend/src/app/i18n.tsx` change / add (both dicts):

`id` — change `'en.purge'` → `'Hapus semua foto wajah {name}'`, `'en.purgeConfirmTitle'` → `'Hapus semua foto wajah'`, `'en.createError'` → `'Gagal menambah karyawan'`; add:
```ts
    'en.purgeConfirm': 'Hapus foto',
    'en.filter.status': 'Status',
    'en.filter.active': 'Aktif',
    'en.filter.inactive': 'Nonaktif',
    'en.filter.all': 'Semua',
    'en.card.identity': 'IDENTITAS',
    'en.card.status': 'STATUS',
    'en.err.required': 'Wajib diisi',
    'en.err.codeDup': 'NIK sudah dipakai',
    'en.deactivateTitle': 'Nonaktifkan karyawan',
    'en.deactivateBody': '{name} tidak akan dikenali di gate absensi sampai diaktifkan lagi. Foto wajah dan riwayat absensi tetap tersimpan.',
    'en.delete': 'Hapus karyawan',
    'en.deleteTitle': 'Hapus karyawan',
    'en.deleteBody': 'Hapus "{name}" beserta {n} foto wajahnya? Tindakan ini tidak bisa dibatalkan.',
    'en.deleteBlocked': '{name} sudah punya riwayat absensi dan tidak bisa dihapus. Nonaktifkan saja?',
    'en.deleteBlockedInactive': '{name} sudah punya riwayat absensi dan tidak bisa dihapus. Karyawan ini sudah nonaktif.',
```

`en` — `'en.purge'` → `'Delete all face photos of {name}'`, `'en.purgeConfirmTitle'` → `'Delete all face photos'`, `'en.createError'` → `'Failed to add employee'`; add:
```ts
    'en.purgeConfirm': 'Delete photos',
    'en.filter.status': 'Status',
    'en.filter.active': 'Active',
    'en.filter.inactive': 'Inactive',
    'en.filter.all': 'All',
    'en.card.identity': 'IDENTITY',
    'en.card.status': 'STATUS',
    'en.err.required': 'Required',
    'en.err.codeDup': 'Employee ID already in use',
    'en.deactivateTitle': 'Deactivate employee',
    'en.deactivateBody': '{name} will not be recognized at the attendance gate until reactivated. Face photos and attendance history are kept.',
    'en.delete': 'Delete employee',
    'en.deleteTitle': 'Delete employee',
    'en.deleteBody': 'Delete "{name}" and their {n} face photos? This cannot be undone.',
    'en.deleteBlocked': '{name} has attendance history and cannot be deleted. Deactivate instead?',
    'en.deleteBlockedInactive': '{name} has attendance history and cannot be deleted. This employee is already inactive.',
```

Keep `en.purgeConfirmBody` (already "Hapus semua {n} foto + embedding wajah "{name}"? Riwayat absensi tetap tersimpan." — contains "{n} foto").

- [ ] **Step 4: CSS** — append to `frontend/src/app/theme.scss`:

```scss
/* Enrollment: daftar | detail; satu kolom di layar sempit (390px tanpa overflow) */
.en-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 1fr);
  border: 1px solid #393939;
}

.en-list {
  border-inline-end: 1px solid #393939;
  min-inline-size: 0;
}

.en-detail {
  padding: 16px;
  min-inline-size: 0;
}

.en-card {
  border: 1px solid #393939;
  background: #262626;
  padding: 14px;
  margin-block-end: 12px;
}

.en-card__title {
  font-size: 12px;
  color: var(--cds-text-helper);
  letter-spacing: 0.32px;
  font-weight: 400;
  margin: 0 0 10px;
}

.en-card__danger {
  margin-block-start: 12px;
  padding-block-start: 10px;
  border-block-start: 1px solid #393939;
}

.en-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

@media (max-width: 671px) {
  .en-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .en-list {
    border-inline-end: 0;
    border-block-end: 1px solid #393939;
  }
}
```

(Hex values are the ones the page already uses inline; keep them for visual parity.)

- [ ] **Step 5: Rewrite `EmployeesTab.tsx`** entirely:

```tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, InlineLoading, InlineNotification, Modal, Select, SelectItem, Tag, TextInput } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import {
  createEmployee,
  deleteEmployee,
  deletePhoto,
  listEmployees,
  listPhotos,
  listShifts,
  purgeBiometrics,
  updateEmployee,
  uploadPhotosBatch,
  type BatchPhotoResult,
  type Employee,
  type Photo,
  type Shift,
} from '../../api/employees'

type StatusFilter = 'active' | 'inactive' | 'all'
type EmpForm = { name: string; code: string; shiftId: string }

const EMPTY_FORM: EmpForm = { name: '', code: '', shiftId: '' }

function initials(name: string) {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')
}

const shiftLabel = (s: Shift) => `${s.name} · ${s.start_time}–${s.end_time}`
const shiftIdOf = (f: EmpForm) => (f.shiftId ? Number(f.shiftId) : null)
const isBlank = (f: EmpForm) => !f.name.trim() || !f.code.trim()

export default function EmployeesTab({ isAdmin }: { isAdmin: boolean }) {
  const { t } = useT()
  const [employees, setEmployees] = useState<Employee[]>([])
  const [shifts, setShifts] = useState<Shift[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [photos, setPhotos] = useState<Photo[]>([])
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('active')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState<EmpForm>(EMPTY_FORM)
  const [codeTaken, setCodeTaken] = useState(false)
  const [adding, setAdding] = useState(false)
  const [newEmp, setNewEmp] = useState<EmpForm>(EMPTY_FORM)
  const [newCodeTaken, setNewCodeTaken] = useState(false)
  const [purging, setPurging] = useState(false)
  const [deactivating, setDeactivating] = useState(false)
  const [deleting, setDeleting] = useState<'confirm' | 'blocked' | null>(null)
  const [batchResults, setBatchResults] = useState<BatchPhotoResult[] | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const selected = employees.find((e) => e.id === selectedId) ?? null

  const refresh = useCallback(async () => {
    try {
      const [emps, shs] = await Promise.all([listEmployees(), listShifts()])
      setEmployees(emps)
      setShifts(shs)
      // pertahankan pilihan; pilih karyawan aktif pertama hanya bila belum ada
      setSelectedId((cur) => cur ?? emps.find((e) => e.active)?.id ?? emps[0]?.id ?? null)
    } catch {
      setError(t('en.loadError'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    if (selectedId == null) {
      setPhotos([])
      return
    }
    listPhotos(selectedId)
      .then(setPhotos)
      .catch(() => setPhotos([]))
  }, [selectedId])

  useEffect(() => {
    if (!selected) return
    setForm({ name: selected.name, code: selected.employee_code, shiftId: selected.shift_id != null ? String(selected.shift_id) : '' })
    setCodeTaken(false)
  }, [selected])

  const reloadPhotos = async () => {
    if (selectedId == null) return
    setPhotos(await listPhotos(selectedId).catch(() => []))
    await refresh()
  }

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    e.target.value = ''
    if (files.length === 0 || selectedId == null) return
    setError(null)
    try {
      const { results } = await uploadPhotosBatch(selectedId, files)
      setBatchResults(results)
      await reloadPhotos()
    } catch {
      setError(t('en.uploadError'))
    }
  }

  const onDeletePhoto = async (p: Photo) => {
    if (selectedId == null) return
    try {
      await deletePhoto(selectedId, p.id)
      await reloadPhotos()
    } catch {
      setError(t('en.saveError'))
    }
  }

  const doPurge = async () => {
    if (!selected) return
    try {
      await purgeBiometrics(selected.id)
    } catch {
      setError(t('en.saveError'))
    }
    setPurging(false)
    await reloadPhotos()
  }

  const saveEmployee = async () => {
    if (!selected) return
    setCodeTaken(false)
    try {
      await updateEmployee(selected.id, { name: form.name.trim(), employee_code: form.code.trim(), shift_id: shiftIdOf(form) })
      await refresh()
    } catch (e) {
      if ((e as Error).message === 'duplicate') setCodeTaken(true)
      else setError(t('en.saveError'))
    }
  }

  const setActive = async (active: boolean) => {
    if (!selected) return
    setDeactivating(false)
    setDeleting(null)
    try {
      await updateEmployee(selected.id, { active })
      await refresh()
    } catch {
      setError(t('en.saveError'))
    }
  }

  const doDelete = async () => {
    if (!selected) return
    try {
      await deleteEmployee(selected.id)
      setDeleting(null)
      setSelectedId(null)
      await refresh()
    } catch (e) {
      if ((e as Error).message === 'has_attendance') {
        setDeleting('blocked')
      } else {
        setDeleting(null)
        setError(t('en.saveError'))
      }
    }
  }

  const addEmployee = async () => {
    setNewCodeTaken(false)
    try {
      const created = await createEmployee({ name: newEmp.name.trim(), employee_code: newEmp.code.trim(), shift_id: shiftIdOf(newEmp) })
      setAdding(false)
      setNewEmp(EMPTY_FORM)
      setStatusFilter((f) => (f === 'inactive' ? 'active' : f))
      setSelectedId(created.id)
      await refresh()
    } catch (e) {
      if ((e as Error).message === 'duplicate') setNewCodeTaken(true)
      else setError(t('en.createError'))
    }
  }

  const q = query.trim().toLowerCase()
  const filtered = employees.filter(
    (e) =>
      (statusFilter === 'all' || e.active === (statusFilter === 'active')) &&
      (!q || e.name.toLowerCase().includes(q) || e.employee_code.toLowerCase().includes(q)),
  )

  const shiftOptions = (
    <>
      <SelectItem value="" text="—" />
      {shifts.map((s) => (
        <SelectItem key={s.id} value={String(s.id)} text={shiftLabel(s)} />
      ))}
    </>
  )

  return (
    <div>
      {error && <InlineNotification kind="error" lowContrast title={t('common.error')} subtitle={error} onCloseButtonClick={() => setError(null)} />}

      <div className="en-toolbar">
        <TextInput id="en-search" labelText={t('en.search')} value={query} onChange={(e) => setQuery(e.target.value)} />
        <Select id="en-status-filter" labelText={t('en.filter.status')} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}>
          <SelectItem value="active" text={t('en.filter.active')} />
          <SelectItem value="inactive" text={t('en.filter.inactive')} />
          <SelectItem value="all" text={t('en.filter.all')} />
        </Select>
        {isAdmin && (
          <Button
            data-testid="en-add"
            onClick={() => {
              setNewEmp(EMPTY_FORM)
              setNewCodeTaken(false)
              setAdding(true)
            }}
          >
            {t('en.add')}
          </Button>
        )}
      </div>

      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : (
        <div className="en-layout">
          <div className="en-list">
            {filtered.map((e) => (
              <div
                key={e.id}
                data-testid={`en-row-${e.id}`}
                onClick={() => setSelectedId(e.id)}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '2fr 1fr 1fr 1fr',
                  alignItems: 'center',
                  fontSize: 13,
                  borderBottom: '1px solid #2d2d2d',
                  background: e.id === selectedId ? '#262626' : 'transparent',
                  borderLeft: e.id === selectedId ? '3px solid #4589ff' : '3px solid transparent',
                  cursor: 'pointer',
                }}
              >
                <div style={{ padding: '10px 14px', minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <div style={{ position: 'relative', width: 28, height: 28, background: '#333', color: '#c6c6c6', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 600, flexShrink: 0 }}>
                      {initials(e.name)}
                      <span
                        data-testid={`en-dot-${e.id}`}
                        style={{
                          position: 'absolute',
                          right: -2,
                          bottom: -2,
                          width: 9,
                          height: 9,
                          borderRadius: 9999,
                          background: e.face_ready ? '#42be65' : '#6f6f6f',
                          border: '2px solid #161616',
                        }}
                      />
                    </div>
                    {e.name}
                    {!e.active && (
                      <Tag type="gray" size="sm" data-testid={`en-inactive-${e.id}`}>
                        {t('en.inactive')}
                      </Tag>
                    )}
                  </div>
                </div>
                <div style={{ padding: '10px 14px', fontFamily: 'monospace', fontSize: 11, color: '#8d8d8d', overflowWrap: 'anywhere' }}>{e.employee_code}</div>
                <div style={{ padding: '10px 14px' }}>{e.shift_name ?? '—'}</div>
                <div style={{ padding: '10px 14px' }}>
                  <span
                    data-testid={`en-face-${e.id}`}
                    style={{
                      fontSize: 11,
                      padding: '2px 8px',
                      border: `1px solid ${e.face_ready ? '#42be65' : '#f1c21b'}`,
                      color: e.face_ready ? '#42be65' : '#f1c21b',
                      display: 'inline-block',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {e.face_ready ? t('en.face.count').replace('{n}', String(e.photo_count)) : t('en.face.none')}
                  </span>
                </div>
              </div>
            ))}
            {filtered.length === 0 && <div style={{ padding: 16 }} className="en-muted">{t('en.empty')}</div>}
          </div>

          <div className="en-detail">
            {!selected ? (
              <p className="en-muted">{t('en.selectHint')}</p>
            ) : (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
                  <div style={{ width: 40, height: 40, background: '#333', color: '#c6c6c6', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 600, flexShrink: 0 }}>
                    {initials(selected.name)}
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 16, fontWeight: 600 }}>{selected.name}</div>
                    <div style={{ fontSize: 12, color: '#8d8d8d', fontFamily: 'monospace' }}>
                      {selected.employee_code} · {selected.active ? t('en.active') : t('en.inactive')} · {selected.shift_name ?? '—'}
                    </div>
                  </div>
                </div>

                <section className="en-card" data-testid="en-card-identity">
                  <h4 className="en-card__title">{t('en.card.identity')}</h4>
                  <div className="en-form">
                    <TextInput
                      id="en-name"
                      labelText={t('en.name')}
                      value={form.name}
                      disabled={!isAdmin}
                      invalid={!form.name.trim()}
                      invalidText={t('en.err.required')}
                      onChange={(e) => setForm({ ...form, name: e.target.value })}
                    />
                    <TextInput
                      id="en-code"
                      labelText={t('en.code')}
                      value={form.code}
                      disabled={!isAdmin}
                      invalid={!form.code.trim() || codeTaken}
                      invalidText={codeTaken ? t('en.err.codeDup') : t('en.err.required')}
                      onChange={(e) => {
                        setForm({ ...form, code: e.target.value })
                        setCodeTaken(false)
                      }}
                    />
                    <Select id="en-shift" labelText={t('en.shift.select')} value={form.shiftId} disabled={!isAdmin} onChange={(e) => setForm({ ...form, shiftId: e.target.value })}>
                      {shiftOptions}
                    </Select>
                    <div>
                      <Button kind="primary" size="sm" data-testid="en-save" disabled={!isAdmin || isBlank(form)} onClick={saveEmployee}>
                        {t('en.save')}
                      </Button>
                    </div>
                  </div>
                </section>

                <section className="en-card" data-testid="en-card-face">
                  <h4 className="en-card__title">{t('en.faceTitle').replace('{n}', String(photos.length))}</h4>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6 }}>
                    {photos.map((p) => (
                      <div key={p.id} data-testid={`en-photo-${p.id}`} style={{ position: 'relative', aspectRatio: '3/4', background: '#0d1117', border: '1px solid #393939' }}>
                        {p.path && <img src={`/api/v1/media/${p.path}`} alt={selected.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />}
                        <span style={{ position: 'absolute', bottom: 0, left: 0, right: 0, fontSize: 9, color: '#8d8d8d', textAlign: 'center', padding: 2, background: 'rgba(0,0,0,.6)' }}>
                          {p.quality != null ? `${Math.round(p.quality * 100)}%` : '—'}
                        </span>
                        {isAdmin && (
                          <button
                            type="button"
                            title={t('en.photoDelete')}
                            data-testid={`en-photo-del-${p.id}`}
                            onClick={() => onDeletePhoto(p)}
                            style={{ position: 'absolute', top: 2, right: 2, background: 'rgba(0,0,0,.6)', color: '#fa4d56', border: '1px solid #fa4d56', cursor: 'pointer', fontSize: 10, lineHeight: '14px', padding: '0 4px' }}
                          >
                            ×
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                  <input ref={fileRef} type="file" accept="image/*" multiple data-testid="en-upload-input" style={{ display: 'none' }} onChange={onUpload} />
                  <Button
                    kind="tertiary"
                    size="sm"
                    style={{ marginTop: 10 }}
                    disabled={!isAdmin}
                    onClick={() => {
                      setBatchResults(null)
                      fileRef.current?.click()
                    }}
                  >
                    {t('en.upload')}
                  </Button>
                  {batchResults && (
                    <ul data-testid="en-batch-results" style={{ margin: '8px 0 0', padding: 0, listStyle: 'none', fontSize: 12 }}>
                      {batchResults.map((r, i) => (
                        <li key={i} style={{ color: r.ok ? '#42be65' : '#fa4d56' }}>
                          {r.ok
                            ? `${t('en.batch.ok')} — ${t('en.face.quality')}: ${(r.quality ?? 0).toFixed(2)}${r.duplicate_of ? ` — ⚠ ${t('en.dup.warn')} #${r.duplicate_of.employee_id} (${r.duplicate_of.score})` : ''}`
                            : `${t(`en.batch.${r.reason === 'max_photos' ? 'max' : r.reason === 'too_large' ? 'tooLarge' : r.reason}` as TKey)}`}
                        </li>
                      ))}
                    </ul>
                  )}
                  {isAdmin && (
                    <div className="en-card__danger">
                      <Button kind="danger--ghost" size="sm" data-testid="en-purge" disabled={selected.photo_count === 0} onClick={() => setPurging(true)}>
                        {t('en.purge').replace('{name}', selected.name)}
                      </Button>
                    </div>
                  )}
                </section>

                {isAdmin && (
                  <section className="en-card" data-testid="en-card-status">
                    <h4 className="en-card__title">{t('en.card.status')}</h4>
                    <div className="en-actions">
                      <Button kind="tertiary" size="sm" data-testid="en-toggle-active" onClick={() => (selected.active ? setDeactivating(true) : setActive(true))}>
                        {selected.active ? t('en.deactivate') : t('en.activate')}
                      </Button>
                      <Button kind="danger--tertiary" size="sm" data-testid="en-delete" onClick={() => setDeleting('confirm')}>
                        {t('en.delete')}
                      </Button>
                    </div>
                  </section>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {adding && (
        <Modal
          open
          modalHeading={t('en.addTitle')}
          primaryButtonText={t('common.save')}
          secondaryButtonText={t('common.cancel')}
          primaryButtonDisabled={isBlank(newEmp)}
          onRequestClose={() => setAdding(false)}
          onRequestSubmit={addEmployee}
          size="sm"
        >
          <div className="en-form">
            <TextInput id="new-name" labelText={t('en.name')} value={newEmp.name} onChange={(e) => setNewEmp({ ...newEmp, name: e.target.value })} />
            <TextInput
              id="new-code"
              labelText={t('en.code')}
              value={newEmp.code}
              invalid={newCodeTaken}
              invalidText={t('en.err.codeDup')}
              onChange={(e) => {
                setNewEmp({ ...newEmp, code: e.target.value })
                setNewCodeTaken(false)
              }}
            />
            <Select id="new-shift" labelText={t('en.shift.select')} value={newEmp.shiftId} onChange={(e) => setNewEmp({ ...newEmp, shiftId: e.target.value })}>
              {shiftOptions}
            </Select>
          </div>
        </Modal>
      )}

      {purging && selected && (
        <Modal
          open
          danger
          modalHeading={t('en.purgeConfirmTitle')}
          primaryButtonText={t('en.purgeConfirm')}
          secondaryButtonText={t('common.cancel')}
          onRequestClose={() => setPurging(false)}
          onRequestSubmit={doPurge}
          size="sm"
        >
          <p>{t('en.purgeConfirmBody').replace('{n}', String(selected.photo_count)).replace('{name}', selected.name)}</p>
        </Modal>
      )}

      {deactivating && selected && (
        <Modal
          open
          modalHeading={t('en.deactivateTitle')}
          primaryButtonText={t('en.deactivate')}
          secondaryButtonText={t('common.cancel')}
          onRequestClose={() => setDeactivating(false)}
          onRequestSubmit={() => setActive(false)}
          size="sm"
        >
          <p>{t('en.deactivateBody').replace('{name}', selected.name)}</p>
        </Modal>
      )}

      {deleting && selected && (
        <Modal
          open
          danger={deleting === 'confirm'}
          passiveModal={deleting === 'blocked' && !selected.active}
          modalHeading={t('en.deleteTitle')}
          primaryButtonText={deleting === 'confirm' ? t('en.delete') : t('en.deactivate')}
          secondaryButtonText={t('common.cancel')}
          onRequestClose={() => setDeleting(null)}
          onRequestSubmit={deleting === 'confirm' ? doDelete : () => setActive(false)}
          size="sm"
        >
          <p>
            {deleting === 'confirm'
              ? t('en.deleteBody').replace('{name}', selected.name).replace('{n}', String(selected.photo_count))
              : t(selected.active ? 'en.deleteBlocked' : 'en.deleteBlockedInactive').replace('{name}', selected.name)}
          </p>
        </Modal>
      )}
    </div>
  )
}
```

- [ ] **Step 6: Run tests**

Run: `cd frontend && npx vitest run src/__tests__/enrollment.test.tsx src/__tests__/shifts.test.tsx`
Expected: all PASS. If the Carbon `Tag` in the list makes `findAllByText('Budi Santoso')` ambiguous, it will not — the tag text is "Nonaktif"; do not weaken assertions.

- [ ] **Step 7: Full frontend verification**

Run: `cd frontend && npx vitest run && npm run build && npm run lint`
Expected: 117 passed (109 + 8), build exit 0, lint warning set unchanged. Also confirm unused i18n keys were not left behind: `rtk grep -n "en.shift'" frontend/src` → no hits.

- [ ] **Step 8: CHANGELOG + commit** — bullet:

```markdown
- **Tab Karyawan dirapikan**: filter status (default Aktif) + tag Nonaktif; kartu Identitas dengan
  **NIK bisa diedit** (409 → "NIK sudah dipakai" inline); kartu Wajah memuat tombol **"Hapus semua
  foto wajah {nama}"** (nonaktif bila 0 foto, konfirmasi menyebut nama + jumlah foto); kartu Status:
  Nonaktifkan dengan konfirmasi, Hapus karyawan (riwayat absensi → tawaran Nonaktifkan). Badge wajah
  dari `photo_count` (tanpa N+1). Grid satu kolom di ≤ 671 px. Frontend **117 passed**.
```

```bash
rtk git add frontend/src/features/enrollment/EmployeesTab.tsx frontend/src/app/i18n.tsx frontend/src/app/theme.scss frontend/src/__tests__/enrollment.test.tsx CHANGELOG.md
rtk git commit -m "feat(enrollment): CRUD karyawan lengkap, NIK bisa diedit, hapus foto wajah per karyawan"
```

---

### Task 6: Deploy check on gspe-ai3, evidence, docs

**Files:**
- Create: `docs/evidence/enrollment-employees-desktop.png`, `docs/evidence/enrollment-employees-390.png`, `docs/evidence/enrollment-shifts-desktop.png`, `docs/evidence/enrollment-shifts-390.png`
- Modify: `README.md` (enrollment section), `ROADMAP.md`, `CHANGELOG.md`, `.cooper/context/enrollment-refining.md`

- [ ] **Step 1: Ask the user** for explicit permission to (a) `git push -u origin feat/enrollment-refining`, (b) check it out on gspe-ai3 and restart `isentinel-api`, (c) optionally create/edit/delete a throwaway shift named `UJI` on the server. Stop until answered; do only what was approved.

- [ ] **Step 2: Deploy (only if approved; no migration)**

```bash
rtk git push -u origin feat/enrollment-refining
ssh gspe-ai3 'cd /home/gspe-ai3/project_cv/I-Sentinel && git fetch origin && git checkout feat/enrollment-refining && git pull --ff-only && git log --oneline -1'
ssh gspe-ai3 'kill $(cat /sys/fs/cgroup/system.slice/isentinel-api.service/cgroup.procs); sleep 5; curl -s localhost:8000/api/v1/health'
```
Expected: last line `{"status":"ok"}`. Frontend (Vite `isentinel-web`) picks up the change without restart.

- [ ] **Step 3: Existing-data check (read-only, in the UI)** — log in (`AGENTS`/prompt login command with `temp/tools/cdp-login.mjs`), open `http://192.168.2.133:5173/enrollment?tab=shifts`. For each existing shift confirm `end_time > start_time`. If any shift violates it, **stop and report** to the user (it can no longer be saved from the modal); do not edit it.

- [ ] **Step 4: UI verification + screenshots** — desktop and 390 px (`node temp/tools/cdp-viewport.mjs`), for both `?tab=employees` and `?tab=shifts`. On each 390 px page evaluate `document.documentElement.scrollWidth <= 390` → must be `true`. Check: Angly / Ikhsal badges show photo counts; NIK field is editable (do not save); "Hapus semua foto wajah Angly" button sits inside the face card; status card present. Save the four screenshots to `docs/evidence/` with the names above. If step 1(c) was approved: create shift `UJI` 08:00–17:00, edit it to Sen–Sab, delete it; confirm it is gone.

- [ ] **Step 5: Docs**
- `README.md`: in the Enrollment/Attendance feature description, add that the Enrollment page has tabs Karyawan | Shift, NIK is editable, "Hapus semua foto wajah" is per employee, and a deactivated employee is not recognized at the gate.
- `ROADMAP.md`: add an "Enrollment & Shift refining" line with status and evidence paths.
- `CHANGELOG.md`: add bullet `- **Deploy + verifikasi UI** …` with the commit hash deployed, health result, overflow check result, and follow-ups (overnight shift; recompute attendance days after shift edit).
- `.cooper/context/enrollment-refining.md`: replace the "BELUM DIMULAI" header with current state (branch, commits, suites, server state: which branch is checked out on gspe-ai3).

- [ ] **Step 6: Commit**

```bash
rtk git add docs/evidence/enrollment-*.png README.md ROADMAP.md CHANGELOG.md .cooper/context/enrollment-refining.md
rtk git commit -m "docs(enrollment): evidence UI, README/ROADMAP, checkpoint"
```

- [ ] **Step 7: Summary to the user** — suites (backend/vision/frontend counts vs baseline, lint set), what is deployed where, screenshots, follow-ups, and ask whether to merge `feat/enrollment-refining` into `main` (merge `--no-ff` like R5b) and return the server to `main`.
