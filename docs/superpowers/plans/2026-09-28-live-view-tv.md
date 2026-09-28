# Live View Mode TV Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Live View siap untuk TV command center: mode kiosk `/live/tv?screen=A`, filter kamera checkbox, auto-scroll halus, pengaturan per layar, stream hanya untuk tile terlihat + coba ulang, dan sesi login bergulir 48 jam.

**Architecture:** Frontend dipecah: `LiveWall` (grid + tile + modal debugger, dipakai Live View biasa dan mode TV), `useLiveCameras` (data), `screenPrefs` (pengaturan per layar di `localStorage`), `CameraPicker`, `useInView`, `useAutoScroll`/`useIdle`, dan halaman `LiveTvPage` di luar `AppShell`. Backend hanya `get_current_user` yang memperbarui cookie saat token lewat separuh umur + default expire 2880 menit.

**Tech Stack:** React 19 + TypeScript + Carbon + React Router 7, Vitest + Testing Library; FastAPI + PyJWT, pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-live-view-tv-design.md`

## Global Constraints

- Branch `feat/live-view-tv` (dari `main` @ `de32abc`; spec di `2ecaf34`).
- **Tanpa AI attribution** di commit/kode/docs (`AGENTS.md` §9).
- Tanpa dependensi baru, tanpa migrasi DB, tanpa perubahan vision/go2rtc.
- REST hanya lewat `src/api/*`; semua string UI lewat `i18n.tsx` (`id` + `en`, kunci sama); Carbon + token tema; Live View
  biasa 390 px tanpa overflow horizontal.
- Akses `localStorage` selalu dibungkus try/catch (mode privat / storage penuh tidak mematahkan halaman).
- **Jangan** `uv sync` / `uv lock` / membuat ulang venv.
- Setiap task: commit Conventional Commits + satu bullet di `CHANGELOG.md` bagian
  `### Live View mode TV (2026-09-28 – …)` (dibuat di Task 1, di atas `### Behavior Idle Zone + Crowd (2026-09-28)`).
- Baseline `main` `de32abc`: backend **432**, vision **223** (3 deselected), frontend **142**, build 0, lint = set rule+file lama.
- **Eksekutor berhenti setelah `git push`.** Deploy (restart API) dan uji lapangan di sesi perencana.

## Deviasi / keputusan teknis dari spec

1. **Auto-scroll menggulir dokumen** (`document.scrollingElement`), bukan kontainer grid: halaman TV tanpa `AppShell`
   menggulir window, dan `IntersectionObserver` (root = viewport) hanya menerapkan `rootMargin` pada viewport — pada
   kontainer bergulir, tile di bawah area terlihat terpotong kontainer dan tidak pernah "dekat layar".
2. **Area pra-muat = 50 % tinggi viewport di bawah layar** (`rootMargin: '0px 0px 50% 0px'`), setara ± 1–1,5 baris
   tile; tinggi tile tidak diketahui di sisi observer.
3. **Tidak memakai `visibilityThreshold` bawaan `video-rtc.js`**: tanpa `rootMargin`, dan bentrok dengan timer fallback
   10 s (tile di luar layar tidak pernah `playing` → dianggap gagal). Unmount `<video-stream>` memicu
   `disconnectedCallback` bawaan (WS/PC ditutup setelah `DISCONNECT_TIMEOUT`).
4. **Auto-scroll hanya di mode TV** (toolbar TV); Live View biasa tetap tanpa gulir otomatis.
5. **Snapshot tampil selama stream menyambung** (sampai `playing`) → tes lama "snapshot hanya fallback" diperbarui:
   img boleh ada saat menyambung, hilang setelah `playing`.
6. **Bug tambahan**: efek stream `CameraTile` bergantung `[canStream, ws]`; saat `<video-stream>` di-mount ulang
   (coba ulang / masuk layar) efek tidak jalan lagi → `src` tidak diset. Diganti `[streaming, ws]`.
7. Role `viewer` **sudah ada** di backend (`POST /users` menerima `role: "viewer"`); catatan User management di spec
   tetap berlaku (`is_active`, `token_version`, pembatasan akses `viewer`).
8. Route `/live/tv` di `main.tsx` (router tidak diekspor) diverifikasi lewat build + cek visual; tes komponen
   merender `LiveTvPage` langsung.

## Review Focus

1. **Stream putus/gagal di TV 24/7** → tile kembali streaming sendiri ≤ 60 s setelah pulih, bukan snapshot selamanya.
   Tes: Task 4 `stream gagal → snapshot, dicoba ulang setelah 60 detik`.
2. **Tile keluar-masuk layar saat digulir** → `<video-stream>` di-unmount saat keluar (tidak menumpuk koneksi di Pi),
   di-mount + `src` diset saat masuk. Tes: Task 4 `tile di luar layar tidak streaming …`.
3. **Dua layar di satu Pi** (`?screen=A`, `?screen=B`) → pengaturan satu layar tidak menimpa yang lain; `?screen=`
   ngawur → `default`. Tes: Task 2 `pengaturan per layar terpisah …`, Task 7 `layar B hanya menampilkan pilihannya …`.
4. **Pilihan kamera "Semua" + kamera baru / kamera terhapus** → kamera baru ikut tampil; ID hilang diabaikan; pilihan
   kosong → pesan + tombol pemilih. Tes: Task 2 `selectCameras …`, Task 5 `pilihan kosong …`.
5. **Sesi TV** → cookie diperbarui hanya untuk token cookie yang lewat separuh umur; Bearer dan token baru tidak.
   Tes: Task 1 kedua tes sesi.

---

### Task 1: Sesi bergulir + expire 48 jam (backend)

**Files:**
- Modify: `backend/app/api/deps.py` (`set_auth_cookie`, `get_current_user`)
- Modify: `backend/app/api/auth.py` (`_login` memakai `set_auth_cookie`)
- Modify: `backend/app/core/config.py:8` (`access_token_expire_min` 480 → 2880)
- Modify: `.env.example` (tambah `ACCESS_TOKEN_EXPIRE_MIN=2880`)
- Test: `backend/tests/test_auth_api.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `app.api.deps.set_auth_cookie(response: Response, token: str) -> None`.

- [ ] **Step 1: Tulis tes (gagal)** — tambahkan di `backend/tests/test_auth_api.py`:

```python
def _token_with(uid: int, minutes_left: float) -> str:
    import jwt
    from datetime import datetime, timedelta, timezone
    from app.core.config import settings
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes_left)
    return jwt.encode({"sub": str(uid), "role": "admin", "exp": exp}, settings.jwt_secret, settings.jwt_algorithm)


def _admin_id(client) -> int:
    return client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["user"]["id"]


def test_session_cookie_renewed_past_half_life(client):
    """TV command center: token cookie yang lewat separuh umur diganti baru (sesi bergulir)."""
    from datetime import datetime, timezone
    from app.core.config import settings
    from app.core.security import decode_token
    old = _token_with(_admin_id(client), 60)
    r = client.get("/api/v1/auth/me", headers={"Cookie": f"isentinel_token={old}"})
    assert r.status_code == 200
    cookie = r.headers.get("set-cookie", "")
    assert cookie.startswith("isentinel_token=") and "httponly" in cookie.lower()
    new = cookie.split(";")[0].split("=", 1)[1]
    left = decode_token(new)["exp"] - datetime.now(timezone.utc).timestamp()
    assert left > settings.access_token_expire_min * 60 - 60


def test_session_cookie_not_renewed_when_fresh_or_bearer(client):
    uid = _admin_id(client)
    fresh = _token_with(uid, 2800)
    assert "set-cookie" not in client.get("/api/v1/auth/me", headers={"Cookie": f"isentinel_token={fresh}"}).headers
    old = _token_with(uid, 60)
    assert "set-cookie" not in client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old}"}).headers


def test_default_session_is_48_hours():
    from app.core.config import Settings
    assert Settings.model_fields["access_token_expire_min"].default == 2880
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest tests/test_auth_api.py -q`
Expected: FAIL — tidak ada `set-cookie`; default 480.

- [ ] **Step 3: Implementasi**

`backend/app/api/deps.py`:

```python
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, Response
from app.core.config import settings
from app.core.db import get_db
from app.core.security import create_access_token, decode_token
from app.models.user import User

COOKIE = "isentinel_token"


def set_auth_cookie(response: Response, token: str) -> None:
    """Cookie sesi httpOnly (dipakai login dan perpanjangan sesi)."""
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=settings.cookie_secure)
```

`_token_from` tetap. `get_current_user`:

```python
def get_current_user(request: Request, response: Response, db=Depends(get_db)) -> User:
    tok = _token_from(request)
    payload = decode_token(tok) if tok else None
    if not payload: raise HTTPException(401, "not authenticated")
    user = db.get(User, int(payload["sub"]))
    if not user: raise HTTPException(401, "user gone")
    # Sesi bergulir: token cookie yang lewat separuh umurnya diganti baru, jadi layar TV yang
    # terus me-refresh tidak pernah logout. Bearer (skrip/API) tidak diubah.
    remaining_s = payload["exp"] - datetime.now(timezone.utc).timestamp()
    if request.cookies.get(COOKIE) == tok and remaining_s < settings.access_token_expire_min * 30:
        set_auth_cookie(response, create_access_token(user.id, user.role))
    return user
```

`backend/app/api/auth.py` `_login`: ganti baris `response.set_cookie(...)` dengan `set_auth_cookie(response, token)`
(import dari `app.api.deps`; pertahankan komentar `secure=True` di atasnya bila relevan).

`backend/app/core/config.py:8`: `access_token_expire_min: int = 2880  # 48 jam; diperpanjang otomatis (sesi bergulir)`.

`.env.example`: tambahkan di dekat `JWT_SECRET`:

```
# Masa berlaku sesi login (menit). Diperpanjang otomatis selama halaman aktif dipakai.
ACCESS_TOKEN_EXPIRE_MIN=2880
```

- [ ] **Step 4: Jalankan, pastikan lulus** — backend suite penuh:
`cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1`

- [ ] **Step 5: CHANGELOG + commit** — di atas `### Behavior Idle Zone + Crowd (2026-09-28)`:

```markdown
### Live View mode TV (2026-09-28 – …)

- **Sesi bergulir 48 jam**: `get_current_user` menerbitkan cookie baru bila token cookie lewat separuh umur (Bearer
  tidak diubah); default `ACCESS_TOKEN_EXPIRE_MIN` 480 → 2880. Layar TV yang me-refresh Live View tidak logout.
  Backend **<angka> passed**. Rollback: revert commit + restart API.
```

```bash
git add backend/app/api/deps.py backend/app/api/auth.py backend/app/core/config.py .env.example backend/tests/test_auth_api.py CHANGELOG.md
git commit -m "feat(auth): sesi bergulir dan masa berlaku login 48 jam"
```

---

### Task 2: Pengaturan per layar (`screenPrefs`)

**Files:**
- Create: `frontend/src/features/live/screenPrefs.ts`
- Test: `frontend/src/__tests__/live-prefs.test.ts` (baru)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces (`features/live/screenPrefs.ts`):
  - `type Cols = 2 | 3 | 4`, `type ScrollSpeed = 'slow' | 'medium' | 'fast'`
  - `type CameraSel = { mode: 'all' } | { mode: 'some'; ids: number[] }`
  - `type ScreenPrefs = { cols: Cols; cameras: CameraSel; scroll: { on: boolean; speed: ScrollSpeed } }`
  - `COL_OPTIONS: Cols[]` (`[3, 2, 4]`), `SCROLL_SPEEDS: Record<ScrollSpeed, number>` (`20/40/80` px/s)
  - `screenName(raw: string | null | undefined): string`, `defaultCols(): Cols`
  - `loadPrefs(screen: string): ScreenPrefs`, `savePrefs(screen: string, prefs: ScreenPrefs): void`
  - `useScreenPrefs(screen: string): [ScreenPrefs, (patch: Partial<ScreenPrefs>) => void]`
  - `isSelected(sel: CameraSel, id: number): boolean`, `selectCameras<T extends { id: number }>(cams: T[], sel: CameraSel): T[]`
  - `setCameras(sel: CameraSel, cams: { id: number }[], ids: number[], on: boolean): CameraSel`

- [ ] **Step 1: Tulis tes (gagal)** — `frontend/src/__tests__/live-prefs.test.ts`:

```ts
import {
  defaultCols, loadPrefs, savePrefs, screenName, selectCameras, setCameras, type ScreenPrefs,
} from '../features/live/screenPrefs'

const CAMS = [{ id: 1 }, { id: 2 }, { id: 3 }]

beforeEach(() => localStorage.clear())

test('screenName: hanya huruf/angka/-/_ maks 32, selain itu default', () => {
  expect(screenName('A')).toBe('A')
  expect(screenName('tv-kiri_2')).toBe('tv-kiri_2')
  for (const bad of [null, undefined, '', 'a b', '<x>', 'x'.repeat(33)]) expect(screenName(bad)).toBe('default')
})

test('pengaturan per layar terpisah: layar A tidak menimpa layar B', () => {
  const a: ScreenPrefs = { cols: 4, cameras: { mode: 'some', ids: [2] }, scroll: { on: true, speed: 'fast' } }
  savePrefs('A', a)
  expect(loadPrefs('A')).toEqual(a)
  expect(loadPrefs('B')).toEqual({ cols: 3, cameras: { mode: 'all' }, scroll: { on: false, speed: 'medium' } })
})

test('nilai rusak jatuh ke default per field; legacy kolom hanya untuk layar default', () => {
  localStorage.setItem('isentinel_live_screen:A', '{"cols": 7, "cameras": {"mode":"some","ids":[1,"x",2.5]}, "scroll": {"on":"yes","speed":"toString"}}')
  expect(loadPrefs('A')).toEqual({ cols: 3, cameras: { mode: 'some', ids: [1] }, scroll: { on: false, speed: 'medium' } })
  localStorage.setItem('isentinel_live_screen:B', 'bukan json')
  expect(loadPrefs('B').cols).toBe(3)
  localStorage.setItem('isentinel_live_cols', '2')
  expect(loadPrefs('default').cols).toBe(2)
  expect(loadPrefs('C').cols).toBe(3)
})

test('localStorage melempar error → default, tanpa crash', () => {
  const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
  const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('full') })
  try {
    expect(loadPrefs('A').cameras).toEqual({ mode: 'all' })
    expect(() => savePrefs('A', loadPrefs('A'))).not.toThrow()
  } finally {
    get.mockRestore()
    set.mockRestore()
  }
})

test('defaultCols: portrait 2, landscape 3', () => {
  const orig = window.matchMedia
  window.matchMedia = ((q: string) => ({ matches: q.includes('portrait') })) as unknown as typeof window.matchMedia
  expect(defaultCols()).toBe(2)
  window.matchMedia = orig
  expect(defaultCols()).toBe(3)
})

test('selectCameras: all ikut kamera baru, ID yang hilang diabaikan', () => {
  expect(selectCameras([...CAMS, { id: 9 }], { mode: 'all' }).map((c) => c.id)).toEqual([1, 2, 3, 9])
  expect(selectCameras(CAMS, { mode: 'some', ids: [3, 42] }).map((c) => c.id)).toEqual([3])
})

test('setCameras: toggle, semua terpilih kembali jadi all, ID usang dibuang', () => {
  const s1 = setCameras({ mode: 'all' }, CAMS, [2], false)
  expect(s1).toEqual({ mode: 'some', ids: [1, 3] })
  expect(setCameras(s1, CAMS, [2], true)).toEqual({ mode: 'all' })
  expect(setCameras({ mode: 'some', ids: [1, 42] }, CAMS, [3], true)).toEqual({ mode: 'some', ids: [1, 3] })
  expect(setCameras({ mode: 'all' }, CAMS, [1, 2, 3], false)).toEqual({ mode: 'some', ids: [] })
})
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `cd frontend && npx vitest run src/__tests__/live-prefs.test.ts` → FAIL (modul tidak ada).

- [ ] **Step 3: Implementasi** — `frontend/src/features/live/screenPrefs.ts`:

```ts
// Pengaturan Live View per layar (?screen=): satu Pi bisa menjalankan dua jendela TV di origin yang sama,
// jadi setiap layar punya kunci localStorage sendiri.
import { useCallback, useState } from 'react'

export type Cols = 2 | 3 | 4
export type ScrollSpeed = 'slow' | 'medium' | 'fast'
export type CameraSel = { mode: 'all' } | { mode: 'some'; ids: number[] }
export type ScreenPrefs = { cols: Cols; cameras: CameraSel; scroll: { on: boolean; speed: ScrollSpeed } }

export const COL_OPTIONS: Cols[] = [3, 2, 4] // urutan mockup 02: default dulu
export const SCROLL_SPEEDS: Record<ScrollSpeed, number> = { slow: 20, medium: 40, fast: 80 } // px per detik
const KEY = 'isentinel_live_screen:'
const LEGACY_COLS_KEY = 'isentinel_live_cols'

export function screenName(raw: string | null | undefined): string {
  return raw && /^[A-Za-z0-9_-]{1,32}$/.test(raw) ? raw : 'default'
}

export function defaultCols(): Cols {
  return window.matchMedia?.('(orientation: portrait)').matches ? 2 : 3
}

const isCols = (v: unknown): v is Cols => v === 2 || v === 3 || v === 4

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export function loadPrefs(screen: string): ScreenPrefs {
  let raw: Record<string, unknown> = {}
  try {
    const v: unknown = JSON.parse(read(KEY + screen) ?? '{}')
    if (v && typeof v === 'object') raw = v as Record<string, unknown>
  } catch {
    // nilai rusak → default
  }
  const legacy = screen === 'default' ? Number(read(LEGACY_COLS_KEY)) : NaN
  const cols = isCols(raw.cols) ? raw.cols : isCols(legacy) ? legacy : defaultCols()
  const c = raw.cameras as { mode?: unknown; ids?: unknown } | undefined
  const cameras: CameraSel = c?.mode === 'some' && Array.isArray(c.ids)
    ? { mode: 'some', ids: c.ids.filter((x): x is number => Number.isInteger(x)) }
    : { mode: 'all' }
  const s = raw.scroll as { on?: unknown; speed?: unknown } | undefined
  const speed = typeof s?.speed === 'string' && Object.hasOwn(SCROLL_SPEEDS, s.speed) ? (s.speed as ScrollSpeed) : 'medium'
  return { cols, cameras, scroll: { on: s?.on === true, speed } }
}

export function savePrefs(screen: string, prefs: ScreenPrefs): void {
  try {
    localStorage.setItem(KEY + screen, JSON.stringify(prefs))
  } catch {
    // storage penuh / mode privat: pengaturan hanya berlaku di sesi ini
  }
}

export function useScreenPrefs(screen: string): [ScreenPrefs, (patch: Partial<ScreenPrefs>) => void] {
  const [prefs, setPrefs] = useState(() => loadPrefs(screen))
  const update = useCallback((patch: Partial<ScreenPrefs>) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch }
      savePrefs(screen, next)
      return next
    })
  }, [screen])
  return [prefs, update]
}

export function isSelected(sel: CameraSel, id: number): boolean {
  return sel.mode === 'all' || sel.ids.includes(id)
}

export function selectCameras<T extends { id: number }>(cams: T[], sel: CameraSel): T[] {
  return cams.filter((c) => isSelected(sel, c.id))
}

/** Pilih/buang `ids`; bila semua kamera terpilih → `all` (kamera baru ikut tampil). */
export function setCameras(sel: CameraSel, cams: { id: number }[], ids: number[], on: boolean): CameraSel {
  const chosen = new Set(cams.filter((c) => isSelected(sel, c.id)).map((c) => c.id))
  for (const id of ids) {
    if (on) chosen.add(id)
    else chosen.delete(id)
  }
  if (cams.length > 0 && cams.every((c) => chosen.has(c.id))) return { mode: 'all' }
  return { mode: 'some', ids: cams.filter((c) => chosen.has(c.id)).map((c) => c.id) }
}
```

(Bila `Object.hasOwn` ditolak `lib` TS, pakai `Object.prototype.hasOwnProperty.call(SCROLL_SPEEDS, s.speed)`.)

- [ ] **Step 4: Jalankan, pastikan lulus** — `npx vitest run src/__tests__/live-prefs.test.ts` → 7 passed.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Pengaturan Live View per layar**: `screenPrefs` (kolom, pilihan kamera `all`/`some`, auto-scroll) disimpan per
  `?screen=` di `localStorage` (`isentinel_live_screen:<nama>`), nilai rusak → default per field, kunci lama
  `isentinel_live_cols` jadi default layar `default`. Frontend **<angka> passed**.
```

```bash
git add frontend/src/features/live/screenPrefs.ts frontend/src/__tests__/live-prefs.test.ts CHANGELOG.md
git commit -m "feat(live): pengaturan Live View per layar"
```

---

### Task 3: Pecah Live View — `LiveWall` + `useLiveCameras` (tanpa perubahan perilaku)

**Files:**
- Create: `frontend/src/features/live/LiveWall.tsx`
- Create: `frontend/src/features/live/useLiveCameras.ts`
- Modify: `frontend/src/features/live/LiveViewPage.tsx`
- Test: `frontend/src/__tests__/liveview.test.tsx` (tidak berubah; harus tetap hijau)

**Interfaces:**
- Produces:
  - `export default function LiveWall(props: { cams: Camera[]; lives: Record<number, LiveInfo>; cols: number; tv?: boolean; onDebugChange?: (open: boolean) => void }): JSX.Element`
  - `export function CameraTile(props: { cam: Camera; live: LiveInfo | null; big?: boolean; tv?: boolean; onClick?: () => void })` (dari `LiveWall.tsx`)
  - `export function useLiveCameras(): { cams: Camera[]; lives: Record<number, LiveInfo>; loading: boolean; loadFailed: boolean; dismissError: () => void }`

- [ ] **Step 1: Pastikan baseline hijau** — `cd frontend && npx vitest run src/__tests__/liveview.test.tsx` → 12 passed.

- [ ] **Step 2: Pindahkan kode (verbatim)**

- `LiveWall.tsx`: pindahkan dari `LiveViewPage.tsx` baris 13–15 (`SNAPSHOT_REFRESH_MS`, `STREAM_TIMEOUT_MS`), baris
  26–258 (`CameraTile`, `ZONE_COLORS`, `BOX_COLORS`, tipe `DetectionKind`/`DetBox`, `BOX_TTL_MS`, `NAME_TTL_MS`,
  `FaceName`, `FACE_GATE_CODES`, `DebugOverlay`) beserta import yang dipakai (`Maximize`, `VideoOff`,
  `InlineLoading` tidak; `Modal`, `Toggle`, `useT`/`TKey`, `Camera`, `LiveInfo`, `listZones`/`Zone`,
  `useLiveEvents`, `playerMode`, `./go2rtc-player`, `StreamElement`). `CameraTile` diekspor dan mendapat prop
  `tv?: boolean` (dipakai di Task 7; untuk sekarang hanya diteruskan).
- Tambahkan komponen `LiveWall` di akhir `LiveWall.tsx` — state/efek dipindah verbatim dari `LiveViewPage`
  baris 264–268 (`debugCam`, `showZones`, `showDetection`, `boxes`, `faceNames`), 274–311 (`useLiveEvents` +
  interval kotak basi), JSX grid (406–412) dan modal (414–433):

```tsx
export default function LiveWall({ cams, lives, cols, tv, onDebugChange }: {
  cams: Camera[]
  lives: Record<number, LiveInfo>
  cols: number
  tv?: boolean
  onDebugChange?: (open: boolean) => void
}) {
  const { t } = useT()
  const [debugCam, setDebugCamState] = useState<Camera | null>(null)
  // … showZones, showDetection, boxes, faceNames, useLiveEvents, interval kotak basi (verbatim) …
  const setDebugCam = (cam: Camera | null) => {
    setDebugCamState(cam)
    onDebugChange?.(cam !== null)
  }
  return (
    <>
      <div className={tv ? 'lv-grid lv-grid--tv' : 'lv-grid'} style={{ '--lv-cols': cols } as React.CSSProperties}>
        {cams.map((cam) => (
          <div key={cam.id} onClick={() => { setBoxes([]); setDebugCam(cam) }} title={t('live.openDebug')}>
            <CameraTile cam={cam} live={lives[cam.id] ?? null} tv={tv} />
          </div>
        ))}
      </div>
      {debugCam && (
        /* <Modal …> verbatim dari LiveViewPage baris 415–432 */
      )}
    </>
  )
}
```

- `useLiveCameras.ts`: pindahkan state `cams`, `lives`, `loading`, `loadFailed`, `refresh` (313–334) dan efek
  interval 30 s (336–340) verbatim:

```ts
import { useCallback, useEffect, useState } from 'react'
import { listCameras, type Camera } from '../../api/cameras'
import { getLive, type LiveInfo } from '../../api/events'

/** Daftar kamera + URL live, di-refresh tiap 30 s (juga menjaga sesi bergulir tetap hidup). */
export function useLiveCameras() {
  const [cams, setCams] = useState<Camera[]>([])
  const [lives, setLives] = useState<Record<number, LiveInfo>>({})
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const refresh = useCallback(async () => { /* verbatim baris 314–333 */ }, [])
  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 30000) // refresh info /live (snapshot img sendiri auto 2s)
    return () => clearInterval(timer)
  }, [refresh])
  return { cams, lives, loading, loadFailed, dismissError: () => setLoadFailed(false) }
}
```

- `LiveViewPage.tsx` tinggal: kolom + filter lokasi (masih sama), `useLiveCameras()`, dan
  `<LiveWall cams={shown} lives={lives} cols={cols} />` menggantikan grid + modal; `InlineNotification` memakai
  `onCloseButtonClick={dismissError}`.

- [ ] **Step 3: Jalankan** — `npx vitest run src/__tests__/liveview.test.tsx && npm run build && npm run lint` →
  12 passed, build 0, lint set sama.

- [ ] **Step 4: Commit** (tanpa bullet CHANGELOG terpisah — refactor murni; sebut di bullet Task 4)

```bash
git add frontend/src/features/live/LiveWall.tsx frontend/src/features/live/useLiveCameras.ts frontend/src/features/live/LiveViewPage.tsx
git commit -m "refactor(live): pisahkan LiveWall dan useLiveCameras dari LiveViewPage"
```

---

### Task 4: Tile — stream hanya saat terlihat, snapshot saat menyambung, coba ulang 60 s

**Files:**
- Create: `frontend/src/features/live/useInView.ts`
- Modify: `frontend/src/features/live/LiveWall.tsx` (`CameraTile`)
- Test: `frontend/src/__tests__/liveview.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `useInView(ref: RefObject<Element | null>, always?: boolean): boolean` — tanpa `IntersectionObserver`
  (jsdom) → `true`; `always` (tile modal) → `true`.

- [ ] **Step 1: Tulis tes (gagal)** — di `liveview.test.tsx`:

Perbarui tes `tile streaming: …` (deviasi 5) — ganti blok setelah `expect(streamEl!.style.objectFit).toBe('fill')`:

```tsx
  // selama menyambung snapshot tampil di bawah video (tanpa kotak hitam); hilang setelah playing
  expect(screen.getByAltText('CAM-01')).toBeInTheDocument()
  act(() => { streamEl!.querySelector('video')!.dispatchEvent(new Event('playing')) })
  expect(screen.queryByAltText('CAM-01')).not.toBeInTheDocument()
```

Tambahkan:

```tsx
class FakeIO {
  static all: FakeIO[] = []
  cb: IntersectionObserverCallback
  el: Element | null = null
  constructor(cb: IntersectionObserverCallback) {
    this.cb = cb
    FakeIO.all.push(this)
  }
  observe(el: Element) { this.el = el }
  unobserve() {}
  disconnect() {}
  fire(isIntersecting: boolean) {
    this.cb([{ isIntersecting } as IntersectionObserverEntry], this as unknown as IntersectionObserver)
  }
}

test('tile di luar layar tidak streaming; masuk layar → streaming, keluar → berhenti', async () => {
  FakeIO.all = []
  vi.stubGlobal('IntersectionObserver', FakeIO)
  vi.stubGlobal('fetch', stubFetch())
  vi.stubGlobal('WebSocket', FakeWebSocket)
  try {
    renderPage()
    expect(await screen.findByText('CAM-01')).toBeInTheDocument()
    expect(document.querySelector('video-stream')).toBeNull()
    expect(screen.getByAltText('CAM-01')).toBeInTheDocument() // snapshot terakhir
    const io = FakeIO.all.find((o) => o.el === screen.getByTestId('cam-tile-1'))!
    act(() => io.fire(true))
    const el = document.querySelector('video-stream') as (HTMLElement & { mode?: string }) | null
    expect(el).not.toBeNull()
    expect(el!.mode).toBe('webrtc,mse')
    act(() => io.fire(false))
    expect(document.querySelector('video-stream')).toBeNull()
  } finally {
    vi.unstubAllGlobals()
  }
})

test('stream gagal → snapshot, dicoba ulang setelah 60 detik', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', stubFetch())
  vi.stubGlobal('WebSocket', FakeWebSocket)
  try {
    renderPage()
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
    expect(document.querySelector('video-stream')).toBeNull()
    await act(async () => { await vi.advanceTimersByTimeAsync(60000) })
    const el = document.querySelector('video-stream') as (HTMLElement & { mode?: string }) | null
    expect(el).not.toBeNull()
    expect(el!.mode).toBe('webrtc,mse') // efek stream jalan lagi di elemen baru
  } finally {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  }
})
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `npx vitest run src/__tests__/liveview.test.tsx` → 3 FAIL.

- [ ] **Step 3: Implementasi**

`frontend/src/features/live/useInView.ts`:

```ts
import { useEffect, useState, type RefObject } from 'react'

// Pra-muat ± 1 baris tile di bawah layar: tile sudah menyambung sebelum auto-scroll membawanya masuk.
const ROOT_MARGIN = '0px 0px 50% 0px'

/** Tile dekat viewport? Tanpa IntersectionObserver (jsdom/browser lama) selalu true. */
export function useInView(ref: RefObject<Element | null>, always = false): boolean {
  const supported = typeof IntersectionObserver !== 'undefined'
  const [inView, setInView] = useState(always || !supported)
  useEffect(() => {
    if (always || !supported || !ref.current) return
    const io = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { rootMargin: ROOT_MARGIN })
    io.observe(ref.current)
    return () => io.disconnect()
  }, [ref, always, supported])
  return inView
}
```

`CameraTile` di `LiveWall.tsx` — ganti bagian state/efek/render stream:

```tsx
const STREAM_RETRY_MS = 60000 // tile gagal stream mencoba lagi (TV 24/7 pulih sendiri)

export function CameraTile({ cam, live, big, tv, onClick }: {
  cam: Camera; live: LiveInfo | null; big?: boolean; tv?: boolean; onClick?: () => void
}) {
  const { t } = useT()
  const rootRef = useRef<HTMLDivElement | null>(null)
  const inView = useInView(rootRef, !!big) // tile modal selalu terlihat
  const [streamFailed, setStreamFailed] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [tick, setTick] = useState(0)
  const [imgFailed, setImgFailed] = useState(false)
  const [mode, setMode] = useState<'WebRTC' | 'MSE' | null>(null)
  const elRef = useRef<StreamElement | null>(null)

  const ws = live?.webrtc
  const online = cam.status === 'online'
  const canStream = !!ws && online && typeof WebSocket !== 'undefined'
  // hanya tile dekat layar yang men-decode video (Pi 5 tanpa decoder H.264 hardware)
  const streaming = canStream && !streamFailed && inView

  // deps [streaming, ws]: <video-stream> di-mount ulang saat masuk layar / coba ulang → src harus diset lagi
  useEffect(() => {
    if (!streaming || !elRef.current) return
    const el = elRef.current
    let ok = false
    el.mode = 'webrtc,mse'
    el.src = ws
    const video = el.querySelector('video')
    const onPlaying = () => {
      ok = true
      setPlaying(true)
      clearTimeout(timer)
    }
    const timer = setTimeout(() => {
      if (!ok) setStreamFailed(true)
    }, STREAM_TIMEOUT_MS)
    video?.addEventListener('playing', onPlaying)
    return () => {
      video?.removeEventListener('playing', onPlaying)
      clearTimeout(timer)
      setPlaying(false)
    }
  }, [streaming, ws])

  useEffect(() => {
    if (!streamFailed) return
    const timer = setTimeout(() => setStreamFailed(false), STREAM_RETRY_MS)
    return () => clearTimeout(timer)
  }, [streamFailed])

  // efek badge transport (big) tetap seperti sebelumnya

  const sep = live?.snapshot?.includes('?') ? '&' : '?'
  const snapSrc = live?.snapshot && !imgFailed ? `${live.snapshot}${sep}_t=${tick}` : null
  // snapshot berkala hanya untuk tile terlihat yang tidak streaming; tile di luar layar = gambar terakhir
  useEffect(() => {
    if (streaming || !inView || !live?.snapshot) return
    const timer = setInterval(() => setTick((v) => v + 1), SNAPSHOT_REFRESH_MS)
    return () => clearInterval(timer)
  }, [streaming, inView, live?.snapshot])
  const showSnap = !!snapSrc && (!streaming || !playing)
```

Render (ganti ternary `streaming ? … : snapSrc ? … : offline`), `ref={rootRef}` di div terluar:

```tsx
      {streaming && (
        // fill (bukan cover): frame penuh — overlay zona debugger memakai geometri frame yang sama dengan vision
        <video-stream
          ref={elRef}
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'fill',
            background: '#000', opacity: playing ? 1 : 0 }}
        />
      )}
      {showSnap ? (
        <img src={snapSrc!} alt={cam.name} onError={() => setImgFailed(true)}
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'fill' }} />
      ) : !streaming && (
        /* div offline (VideoOff + live.offline) verbatim */
      )}
```

Span timestamp snapshot: kondisi `showSnap && !streaming`. Sisanya (badge mode, bar nama/LIVE) tetap.

- [ ] **Step 4: Jalankan, pastikan lulus** — `npx vitest run src/__tests__/liveview.test.tsx` → semua passed; lalu
  `npx vitest run && npm run build && npm run lint`.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Tile Live View hemat & pulih sendiri**: grid dipisah ke `LiveWall`/`useLiveCameras`; `<video-stream>` hanya
  di-mount untuk tile dekat layar (`IntersectionObserver`, pra-muat 50 % viewport), tile lain snapshot terakhir;
  snapshot tampil sampai video `playing`; tile gagal stream dicoba ulang tiap 60 s (dulu snapshot selamanya; efek
  stream kini `[streaming, ws]`). Frontend **<angka> passed**.
```

```bash
git add frontend/src/features/live/useInView.ts frontend/src/features/live/LiveWall.tsx frontend/src/__tests__/liveview.test.tsx CHANGELOG.md
git commit -m "feat(live): stream hanya tile terlihat dan coba ulang stream gagal"
```

---

### Task 5: Pemilih kamera (checkbox) + Live View biasa memakai pengaturan layar `default`

**Files:**
- Create: `frontend/src/features/live/CameraPicker.tsx`
- Modify: `frontend/src/features/live/LiveViewPage.tsx`
- Modify: `frontend/src/app/theme.scss` (`.lv-picker*`)
- Modify: `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/liveview.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `useScreenPrefs`, `COL_OPTIONS`, `selectCameras`, `setCameras`, `isSelected`, `CameraSel` (Task 2);
  `LiveWall`, `useLiveCameras` (Task 3).
- Produces: `export default function CameraPicker(props: { cams: Camera[]; value: CameraSel; onChange: (v: CameraSel) => void; open: boolean; onOpenChange: (open: boolean) => void })`.

- [ ] **Step 1: Tulis tes (gagal)** — di `liveview.test.tsx`:
  - Fixture: beri `location: 'Gudang'` pada CAM-01 dan CAM-02 di `CAMS`, dan tambahkan
    `{ id: 3, name: 'CAM-03', location: null, …, status: 'online' }` (salin bentuk CAM-01); `stubFetch` untuk
    `/cameras/3/live` → 503. Sesuaikan tes lama yang menghitung tile (`click tile …` jadi 3 tile) — hanya angka.
  - Perbarui tes kolom: ganti `localStorage.getItem('isentinel_live_cols')).toBe('2')` dengan
    `JSON.parse(localStorage.getItem('isentinel_live_screen:default')!).cols).toBe(2)`; blok nilai `'99'` tetap.
  - Tambahkan:

```tsx
test('pemilih kamera: per lokasi, uncheck menyembunyikan tile dan tersimpan di layar default', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()
  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('live-picker-open'))
  expect(screen.getByTestId('live-picker-open')).toHaveTextContent('3/3')
  await userEvent.click(screen.getByLabelText('CAM-02'))
  expect(screen.queryByTestId('cam-tile-2')).not.toBeInTheDocument()
  expect(JSON.parse(localStorage.getItem('isentinel_live_screen:default')!).cameras).toEqual({ mode: 'some', ids: [1, 3] })
  // grup setengah terpilih (indeterminate) → klik memilih seluruh grup → kembali "all"
  await userEvent.click(screen.getByLabelText('Gudang'))
  expect(screen.getByTestId('cam-tile-2')).toBeInTheDocument()
  expect(JSON.parse(localStorage.getItem('isentinel_live_screen:default')!).cameras).toEqual({ mode: 'all' })
  // grup penuh → klik membuang seluruh grup; kamera tanpa lokasi ada di "Lainnya"
  await userEvent.click(screen.getByLabelText('Gudang'))
  expect(screen.queryByTestId('cam-tile-1')).not.toBeInTheDocument()
  expect(screen.queryByTestId('cam-tile-2')).not.toBeInTheDocument()
  expect(screen.getByTestId('cam-tile-3')).toBeInTheDocument()
  expect(screen.getByLabelText('Lainnya')).toBeChecked()
  vi.unstubAllGlobals()
})

test('pilihan kosong → pesan + tombol pemilih; Semua memulihkan', async () => {
  localStorage.setItem('isentinel_live_screen:default', JSON.stringify({ cameras: { mode: 'some', ids: [] } }))
  vi.stubGlobal('fetch', stubFetch())
  renderPage()
  expect(await screen.findByTestId('live-empty-selection')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('live-empty-open'))
  await userEvent.click(screen.getByTestId('live-picker-all'))
  expect(await screen.findByTestId('cam-tile-1')).toBeInTheDocument()
  expect(screen.getByTestId('cam-tile-3')).toBeInTheDocument()
  vi.unstubAllGlobals()
})
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `npx vitest run src/__tests__/liveview.test.tsx`.

- [ ] **Step 3: Implementasi**

`frontend/src/features/live/CameraPicker.tsx`:

```tsx
import { Button, Checkbox } from '@carbon/react'
import { useT } from '../../app/i18n'
import type { Camera } from '../../api/cameras'
import { isSelected, setCameras, type CameraSel } from './screenPrefs'

/** Pilih kamera yang tampil, dikelompokkan per lokasi (checkbox grup = semua kamera di lokasi itu). */
export default function CameraPicker({ cams, value, onChange, open, onOpenChange }: {
  cams: Camera[]
  value: CameraSel
  onChange: (v: CameraSel) => void
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { t } = useT()
  const groups = new Map<string, Camera[]>()
  for (const c of cams) groups.set(c.location || '', [...(groups.get(c.location || '') ?? []), c])
  const count = cams.filter((c) => isSelected(value, c.id)).length
  return (
    <div className="lv-picker">
      <Button kind="tertiary" size="sm" data-testid="live-picker-open" aria-expanded={open}
        onClick={() => onOpenChange(!open)}>
        {t('live.picker.button').replace('{n}', String(count)).replace('{m}', String(cams.length))}
      </Button>
      {open && (
        <div className="lv-picker__panel" data-testid="live-picker" role="dialog" aria-label={t('live.picker.title')}>
          <div className="lv-picker__actions">
            <Button kind="ghost" size="sm" data-testid="live-picker-all" onClick={() => onChange({ mode: 'all' })}>
              {t('live.picker.all')}
            </Button>
            <Button kind="ghost" size="sm" data-testid="live-picker-none" onClick={() => onChange({ mode: 'some', ids: [] })}>
              {t('live.picker.none')}
            </Button>
          </div>
          {[...groups].map(([loc, list], i) => {
            const on = list.filter((c) => isSelected(value, c.id)).length
            return (
              <fieldset key={loc} className="lv-picker__group">
                <Checkbox id={`lv-pick-loc-${i}`} labelText={loc || t('live.picker.noLocation')}
                  checked={on === list.length} indeterminate={on > 0 && on < list.length}
                  onChange={(_, { checked }) => onChange(setCameras(value, cams, list.map((c) => c.id), checked))} />
                {list.map((c) => (
                  <Checkbox key={c.id} id={`lv-pick-${c.id}`} labelText={c.name} className="lv-picker__cam"
                    checked={isSelected(value, c.id)}
                    onChange={(_, { checked }) => onChange(setCameras(value, cams, [c.id], checked))} />
                ))}
              </fieldset>
            )
          })}
        </div>
      )}
    </div>
  )
}
```

`LiveViewPage.tsx` (hapus `COLS_KEY`, `initialCols`, `Cols` lokal, `loc`/`locOptions`/Dropdown lokasi):

```tsx
export default function LiveViewPage() {
  const { t } = useT()
  const [prefs, update] = useScreenPrefs('default')
  const [pickerOpen, setPickerOpen] = useState(false)
  const { cams, lives, loading, loadFailed, dismissError } = useLiveCameras()

  if (loading) return <div className="app-page"><InlineLoading description={t('common.loading')} /></div>

  // Kamera nonaktif tidak punya stream di go2rtc (sync_camera(delete=True) saat disable)
  const active = cams.filter((c) => c.enabled)
  const shown = selectCameras(active, prefs.cameras)

  return (
    <div className="app-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('nav.live')}</h1>
          <p className="app-page__sub">{t('live.sub')}</p>
        </div>
        <div className="lv-chips">
          {COL_OPTIONS.map((n) => (
            <button key={n} type="button" data-testid={`live-cols-${n}`} aria-pressed={prefs.cols === n}
              className={prefs.cols === n ? 'lv-chip lv-chip--sel' : 'lv-chip'} onClick={() => update({ cols: n })}>
              {t('live.cols').replace('{n}', String(n))}
            </button>
          ))}
          <CameraPicker cams={active} value={prefs.cameras} onChange={(cameras) => update({ cameras })}
            open={pickerOpen} onOpenChange={setPickerOpen} />
        </div>
      </div>
      {loadFailed && (
        <InlineNotification kind="error" lowContrast title={t('common.error')} subtitle={t('common.loadFailed')}
          onCloseButtonClick={dismissError} />
      )}
      {active.length === 0 ? (
        <p style={{ color: '#8d8d8d' }}>{cams.length === 0 ? t('live.noCameras') : t('live.noActiveCameras')}</p>
      ) : shown.length === 0 ? (
        <p data-testid="live-empty-selection" style={{ color: '#8d8d8d' }}>
          {t('live.picker.empty')}{' '}
          <Button kind="ghost" size="sm" data-testid="live-empty-open" onClick={() => setPickerOpen(true)}>
            {t('live.picker.title')}
          </Button>
        </p>
      ) : (
        <LiveWall cams={shown} lives={lives} cols={prefs.cols} />
      )}
    </div>
  )
}
```

(Hook dipanggil sebelum `return` loading — urutan hook tetap.)

`theme.scss` (setelah `.lv-chip`):

```scss
.lv-picker {
  position: relative;
}

.lv-picker__panel {
  position: absolute;
  right: 0;
  top: calc(100% + 4px);
  z-index: 20;
  width: min(320px, calc(100vw - 32px));
  max-height: 60vh;
  overflow: auto;
  padding: 8px 12px;
  background: var(--cds-layer-01);
  border: 1px solid var(--cds-border-subtle);
}

.lv-picker__actions {
  display: flex;
  gap: 4px;
  margin-bottom: 4px;
}

.lv-picker__group {
  margin-bottom: 8px;
}

.lv-picker__cam {
  margin-left: 24px;
}

@media (max-width: 671px) {
  .lv-picker__panel {
    position: fixed;
    left: 16px;
    right: 16px;
    top: 120px;
    width: auto;
  }
}
```

`i18n.tsx` — `id`: `'live.picker.button': 'Kamera ({n}/{m})'`, `'live.picker.title': 'Pilih kamera'`,
`'live.picker.all': 'Semua'`, `'live.picker.none': 'Kosongkan'`, `'live.picker.noLocation': 'Lainnya'`,
`'live.picker.empty': 'Belum ada kamera dipilih.'`. `en`: `'Cameras ({n}/{m})'`, `'Select cameras'`, `'All'`,
`'Clear'`, `'Other'`, `'No cameras selected.'`. Hapus `'live.allLocations'` bila tidak dipakai lagi (grep).

- [ ] **Step 4: Jalankan, pastikan lulus** — `npx vitest run && npm run build && npm run lint`; cek 390 px Live View
  (pemilih terbuka) tanpa overflow horizontal.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Pemilih kamera Live View**: dropdown lokasi diganti checkbox per kamera dikelompokkan per lokasi (grup
  indeterminate, Semua/Kosongkan, "Kamera (n/m)"); disimpan di layar `default`; pilihan kosong → pesan + tombol
  pemilih. Frontend **<angka> passed**.
```

```bash
git add frontend/src/features/live/CameraPicker.tsx frontend/src/features/live/LiveViewPage.tsx frontend/src/app/theme.scss frontend/src/app/i18n.tsx frontend/src/__tests__/liveview.test.tsx CHANGELOG.md
git commit -m "feat(live): pemilih kamera checkbox per lokasi"
```

---

### Task 6: Auto-scroll + deteksi idle

**Files:**
- Create: `frontend/src/features/live/useAutoScroll.ts`
- Test: `frontend/src/__tests__/live-autoscroll.test.tsx` (baru)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces (`features/live/useAutoScroll.ts`):
  - `END_PAUSE_MS = 5000`
  - `type ScrollState = { phase: 'down' | 'bottom' | 'top'; pos: number; wait: number }`, `SCROLL_START: ScrollState`
  - `stepScroll(s: ScrollState, dtMs: number, max: number, pxPerSec: number): ScrollState`
  - `useAutoScroll(opts: { on: boolean; pxPerSec: number; paused: boolean }): void` — menggulir `document.scrollingElement`
  - `useIdle(ms: number): boolean` — `true` bila tidak ada `mousemove/mousedown/keydown/touchstart/wheel` selama `ms`

- [ ] **Step 1: Tulis tes (gagal)** — `frontend/src/__tests__/live-autoscroll.test.tsx`:

```tsx
import { act, render, screen } from '@testing-library/react'
import { END_PAUSE_MS, SCROLL_START, stepScroll, useIdle, type ScrollState } from '../features/live/useAutoScroll'

function run(s: ScrollState, steps: number, dt: number, max: number, px: number) {
  for (let i = 0; i < steps; i++) s = stepScroll(s, dt, max, px)
  return s
}

test('turun dengan kecepatan tetap, posisi pecahan diakumulasi', () => {
  // 20 px/s, frame 16 ms → 0,32 px per frame; 100 frame = 32 px (tidak hilang karena pembulatan)
  expect(run(SCROLL_START, 100, 16, 1000, 20).pos).toBeCloseTo(32, 5)
})

test('dasar: berhenti 5 detik, kembali ke atas, jeda 5 detik, lalu turun lagi', () => {
  let s = run(SCROLL_START, 30, 100, 100, 40) // 3 s × 40 px/s ≥ 100 → dasar
  expect(s).toEqual({ phase: 'bottom', pos: 100, wait: END_PAUSE_MS })
  s = run(s, 49, 100, 100, 40)
  expect(s.phase).toBe('bottom')
  s = run(s, 1, 100, 100, 40)
  expect(s).toEqual({ phase: 'top', pos: 0, wait: END_PAUSE_MS })
  s = run(s, 50, 100, 100, 40)
  expect(s).toEqual({ phase: 'down', pos: 0, wait: 0 })
  expect(stepScroll(s, 100, 100, 40).pos).toBeCloseTo(4, 5)
})

test('konten muat satu layar → tidak menggulir; jeda frame panjang dibatasi', () => {
  expect(stepScroll({ phase: 'down', pos: 50, wait: 0 }, 16, 0, 40)).toEqual(SCROLL_START)
  // tab sempat tidak aktif 5 s: satu frame tidak melompat 200 px
  expect(stepScroll(SCROLL_START, 5000, 1000, 40).pos).toBeCloseTo(4, 5)
})

function IdleProbe({ ms }: { ms: number }) {
  return <span data-testid="idle">{String(useIdle(ms))}</span>
}

test('useIdle: aktif saat mouse bergerak, idle setelah ms tanpa aktivitas', () => {
  vi.useFakeTimers()
  try {
    render(<IdleProbe ms={4000} />)
    expect(screen.getByTestId('idle')).toHaveTextContent('false')
    act(() => { vi.advanceTimersByTime(4000) })
    expect(screen.getByTestId('idle')).toHaveTextContent('true')
    act(() => { window.dispatchEvent(new MouseEvent('mousemove')) })
    expect(screen.getByTestId('idle')).toHaveTextContent('false')
    act(() => { vi.advanceTimersByTime(3999) })
    expect(screen.getByTestId('idle')).toHaveTextContent('false')
    act(() => { vi.advanceTimersByTime(1) })
    expect(screen.getByTestId('idle')).toHaveTextContent('true')
  } finally {
    vi.useRealTimers()
  }
})
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `npx vitest run src/__tests__/live-autoscroll.test.tsx`.

- [ ] **Step 3: Implementasi** — `frontend/src/features/live/useAutoScroll.ts`:

```ts
// Auto-scroll halus vertikal untuk layar TV: turun pelan, jeda di dasar, kembali ke atas, jeda, ulang.
import { useEffect, useRef, useState } from 'react'

export const END_PAUSE_MS = 5000
const MAX_DT_MS = 100 // frame tertunda (tab tidak aktif) tidak membuat lompatan besar

export type ScrollState = { phase: 'down' | 'bottom' | 'top'; pos: number; wait: number }
export const SCROLL_START: ScrollState = { phase: 'down', pos: 0, wait: 0 }

export function stepScroll(s: ScrollState, dtMs: number, max: number, pxPerSec: number): ScrollState {
  if (max <= 0) return SCROLL_START
  const dt = Math.min(dtMs, MAX_DT_MS)
  if (s.phase === 'down') {
    const pos = s.pos + (pxPerSec * dt) / 1000
    return pos >= max ? { phase: 'bottom', pos: max, wait: END_PAUSE_MS } : { ...s, pos }
  }
  const wait = s.wait - dt
  if (wait > 0) return { ...s, wait }
  return s.phase === 'bottom' ? { phase: 'top', pos: 0, wait: END_PAUSE_MS } : SCROLL_START
}

/** Gulir `document.scrollingElement`; saat `paused`, posisi disinkronkan ulang dari scroll manual operator. */
export function useAutoScroll({ on, pxPerSec, paused }: { on: boolean; pxPerSec: number; paused: boolean }) {
  const pausedRef = useRef(paused)
  pausedRef.current = paused
  useEffect(() => {
    if (!on || typeof requestAnimationFrame === 'undefined') return
    let state = SCROLL_START
    let last = performance.now()
    let resync = true
    let raf = 0
    const frame = (now: number) => {
      const dt = now - last
      last = now
      const el = document.scrollingElement as HTMLElement | null
      if (el && !pausedRef.current) {
        if (resync) {
          state = { ...SCROLL_START, pos: el.scrollTop }
          resync = false
        }
        const next = stepScroll(state, dt, el.scrollHeight - el.clientHeight, pxPerSec)
        if (next.phase === 'top') {
          if (state.phase !== 'top') el.scrollTo({ top: 0, behavior: 'smooth' })
        } else {
          el.scrollTop = Math.round(next.pos)
        }
        state = next
      } else {
        resync = true
      }
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [on, pxPerSec])
}

const ACTIVITY = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'wheel'] as const

/** true bila operator tidak beraktivitas selama `ms` (auto-hide toolbar, lanjut auto-scroll). */
export function useIdle(ms: number): boolean {
  const [idle, setIdle] = useState(false)
  useEffect(() => {
    let timer = setTimeout(() => setIdle(true), ms)
    const wake = () => {
      setIdle(false)
      clearTimeout(timer)
      timer = setTimeout(() => setIdle(true), ms)
    }
    ACTIVITY.forEach((e) => window.addEventListener(e, wake, { passive: true }))
    return () => {
      clearTimeout(timer)
      ACTIVITY.forEach((e) => window.removeEventListener(e, wake))
    }
  }, [ms])
  return idle
}
```

(Bila lint mengeluh `pausedRef.current = paused` saat render, pindahkan ke `useEffect(() => { pausedRef.current = paused })`.)

- [ ] **Step 4: Jalankan, pastikan lulus** — `npx vitest run src/__tests__/live-autoscroll.test.tsx` → 4 passed; lint.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Auto-scroll + idle**: `stepScroll` (turun px/s dengan posisi pecahan, jeda 5 s di dasar, kembali ke atas, jeda
  5 s; konten muat → diam; frame tertunda dibatasi 100 ms), `useAutoScroll` (rAF di dokumen, sinkron ulang setelah
  jeda), `useIdle`. Frontend **<angka> passed**.
```

```bash
git add frontend/src/features/live/useAutoScroll.ts frontend/src/__tests__/live-autoscroll.test.tsx CHANGELOG.md
git commit -m "feat(live): auto-scroll halus dan deteksi idle operator"
```

---

### Task 7: Halaman mode TV (kiosk) + tombol "Mode TV"

**Files:**
- Create: `frontend/src/features/live/LiveTvPage.tsx`
- Modify: `frontend/src/main.tsx` (route `/live/tv` di bawah `RequireAuth`, di luar `AppShell`)
- Modify: `frontend/src/features/live/LiveViewPage.tsx` (tombol Mode TV)
- Modify: `frontend/src/features/live/LiveWall.tsx` (`CameraTile` teks `tv`)
- Modify: `frontend/src/app/theme.scss` (`.lv-tv*`, `.lv-grid--tv`)
- Modify: `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/live-tv.test.tsx` (baru), `frontend/src/__tests__/liveview.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `screenName`, `useScreenPrefs`, `COL_OPTIONS`, `SCROLL_SPEEDS`, `selectCameras`, `ScrollSpeed` (Task 2);
  `LiveWall`, `useLiveCameras` (Task 3); `CameraPicker` (Task 5); `useAutoScroll`, `useIdle` (Task 6).
- Produces: `export default function LiveTvPage()`; konstanta `TOOLBAR_HIDE_MS = 4000`, `SCROLL_RESUME_MS = 10000`.

- [ ] **Step 1: Tulis tes (gagal)** — `frontend/src/__tests__/live-tv.test.tsx`:

```tsx
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import LiveTvPage from '../features/live/LiveTvPage'

const cam = (id: number) => ({ id, name: `CAM-0${id}`, location: null, host: `10.0.0.${id}`, rtsp_main: null,
  rtsp_sub: null, node_id: 1, enabled: true, status: 'offline', probe_main: null, probe_sub: null })

function stubFetch() {
  return vi.fn(async (url: string) => (String(url).endsWith('/cameras')
    ? { ok: true, status: 200, json: () => Promise.resolve([cam(1), cam(2)]) }
    : { ok: false, status: 503, json: () => Promise.resolve(null) }))
}

function renderTv(entry: string) {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/live/tv" element={<LiveTvPage />} />
          <Route path="/live" element={<div data-testid="normal-live" />} />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  )
}

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

test('layar B hanya menampilkan pilihannya; perubahan di layar A tidak menimpa B', async () => {
  localStorage.setItem('isentinel_live_screen:B', JSON.stringify({ cameras: { mode: 'some', ids: [2] } }))
  vi.stubGlobal('fetch', stubFetch())
  const { unmount } = renderTv('/live/tv?screen=B')
  expect(await screen.findByTestId('cam-tile-2')).toBeInTheDocument()
  expect(screen.queryByTestId('cam-tile-1')).not.toBeInTheDocument()
  expect(screen.getByTestId('live-tv-toolbar')).toHaveTextContent('Layar B')
  unmount()

  renderTv('/live/tv?screen=A')
  expect(await screen.findByTestId('cam-tile-1')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('live-tv-cols-4'))
  await userEvent.click(screen.getByTestId('live-tv-scroll'))
  expect(JSON.parse(localStorage.getItem('isentinel_live_screen:A')!)).toMatchObject({ cols: 4, scroll: { on: true } })
  expect(JSON.parse(localStorage.getItem('isentinel_live_screen:B')!)).toEqual({ cameras: { mode: 'some', ids: [2] } })
  expect(document.querySelector('.lv-grid--tv')).toHaveStyle({ '--lv-cols': '4' })
})

test('toolbar hilang setelah 4 detik tanpa aktivitas (kursor disembunyikan) dan muncul lagi saat mouse bergerak', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', stubFetch())
  try {
    renderTv('/live/tv?screen=A')
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(screen.getByTestId('live-tv-toolbar')).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(4000) })
    expect(screen.queryByTestId('live-tv-toolbar')).not.toBeInTheDocument()
    expect(screen.getByTestId('live-tv')).toHaveClass('lv-tv--idle')
    act(() => { window.dispatchEvent(new MouseEvent('mousemove')) })
    expect(screen.getByTestId('live-tv-toolbar')).toBeInTheDocument()
  } finally {
    vi.useRealTimers()
  }
})

test('screen ngawur → layar default; tombol Keluar kembali ke /live', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderTv('/live/tv?screen=%3Cx%3E')
  expect(await screen.findByTestId('live-tv-toolbar')).toHaveTextContent('Layar default')
  await userEvent.click(screen.getByTestId('live-tv-exit'))
  expect(screen.getByTestId('normal-live')).toBeInTheDocument()
})
```

Di `liveview.test.tsx` — `renderPage` dibungkus `Routes` agar navigasi bisa diamati, lalu:

```tsx
test('tombol Mode TV membuka /live/tv?screen=default dan meminta fullscreen', async () => {
  const requestFullscreen = vi.fn(() => Promise.resolve())
  Object.defineProperty(document.documentElement, 'requestFullscreen', { configurable: true, value: requestFullscreen })
  vi.stubGlobal('fetch', stubFetch())
  render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/live']}>
        <Routes>
          <Route path="/live" element={<LiveViewPage />} />
          <Route path="/live/tv" element={<div data-testid="tv-route" />} />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  )
  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('live-tv-open'))
  expect(screen.getByTestId('tv-route')).toBeInTheDocument()
  expect(requestFullscreen).toHaveBeenCalled()
  vi.unstubAllGlobals()
})
```

(import `Route, Routes` dari `react-router-dom` di file ini.)

- [ ] **Step 2: Jalankan, pastikan gagal** — `npx vitest run src/__tests__/live-tv.test.tsx src/__tests__/liveview.test.tsx`.

- [ ] **Step 3: Implementasi**

`frontend/src/features/live/LiveTvPage.tsx`:

```tsx
// Mode TV (kiosk) untuk command center: tanpa AppShell, grid memenuhi layar, toolbar auto-hide,
// pengaturan per layar (?screen=A / ?screen=B untuk dua monitor di satu Pi).
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Button, Toggle } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import CameraPicker from './CameraPicker'
import LiveWall from './LiveWall'
import { useLiveCameras } from './useLiveCameras'
import { useAutoScroll, useIdle } from './useAutoScroll'
import { COL_OPTIONS, SCROLL_SPEEDS, screenName, selectCameras, useScreenPrefs, type ScrollSpeed } from './screenPrefs'

export const TOOLBAR_HIDE_MS = 4000
export const SCROLL_RESUME_MS = 10000
const SPEEDS = Object.keys(SCROLL_SPEEDS) as ScrollSpeed[]

export default function LiveTvPage() {
  const { t } = useT()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const screen = screenName(params.get('screen'))
  const [prefs, update] = useScreenPrefs(screen)
  const { cams, lives, loading, loadFailed } = useLiveCameras()
  const [pickerOpen, setPickerOpen] = useState(false)
  const [debugOpen, setDebugOpen] = useState(false)
  const barHidden = useIdle(TOOLBAR_HIDE_MS)
  const resumed = useIdle(SCROLL_RESUME_MS)

  useAutoScroll({
    on: prefs.scroll.on,
    pxPerSec: SCROLL_SPEEDS[prefs.scroll.speed],
    paused: !resumed || pickerOpen || debugOpen,
  })

  const active = cams.filter((c) => c.enabled)
  const shown = selectCameras(active, prefs.cameras)
  const showBar = !barHidden || pickerOpen

  const exit = () => {
    if (document.fullscreenElement) void document.exitFullscreen?.().catch(() => {})
    navigate('/live')
  }

  return (
    <div data-testid="live-tv" className={showBar ? 'lv-tv' : 'lv-tv lv-tv--idle'}>
      {showBar && (
        <div className="lv-tv__bar" data-testid="live-tv-toolbar">
          <strong>{t('live.tv.screen').replace('{name}', screen)}</strong>
          {COL_OPTIONS.map((n) => (
            <button key={n} type="button" data-testid={`live-tv-cols-${n}`} aria-pressed={prefs.cols === n}
              className={prefs.cols === n ? 'lv-chip lv-chip--sel' : 'lv-chip'} onClick={() => update({ cols: n })}>
              {t('live.cols').replace('{n}', String(n))}
            </button>
          ))}
          <CameraPicker cams={active} value={prefs.cameras} onChange={(cameras) => update({ cameras })}
            open={pickerOpen} onOpenChange={setPickerOpen} />
          <Toggle id="live-tv-scroll" data-testid="live-tv-scroll" size="sm" labelText={t('live.tv.autoScroll')}
            hideLabel toggled={prefs.scroll.on} onToggle={(on) => update({ scroll: { ...prefs.scroll, on } })} />
          <span>{t('live.tv.autoScroll')}</span>
          {SPEEDS.map((s) => (
            <button key={s} type="button" data-testid={`live-tv-speed-${s}`} aria-pressed={prefs.scroll.speed === s}
              className={prefs.scroll.speed === s ? 'lv-chip lv-chip--sel' : 'lv-chip'}
              onClick={() => update({ scroll: { ...prefs.scroll, speed: s } })}>
              {t(`live.tv.speed.${s}` as TKey)}
            </button>
          ))}
          <Button kind="ghost" size="sm" data-testid="live-tv-exit" onClick={exit} style={{ marginLeft: 'auto' }}>
            {t('live.tv.exit')}
          </Button>
        </div>
      )}
      {loadFailed && <p className="lv-tv__msg">{t('common.loadFailed')}</p>}
      {loading ? null : active.length === 0 ? (
        <p className="lv-tv__msg">{cams.length === 0 ? t('live.noCameras') : t('live.noActiveCameras')}</p>
      ) : shown.length === 0 ? (
        <p className="lv-tv__msg" data-testid="live-empty-selection">{t('live.picker.empty')}</p>
      ) : (
        <LiveWall cams={shown} lives={lives} cols={prefs.cols} tv onDebugChange={setDebugOpen} />
      )}
    </div>
  )
}
```

(Bila `Toggle` Carbon tidak meneruskan `data-testid` ke tombolnya, klik lewat
`screen.getByRole('switch', { name: 'Gulir otomatis' })` di tes dan hapus `data-testid` — catat deviasinya.)

`frontend/src/main.tsx` — import `LiveTvPage` dan tambahkan sebagai anak `RequireAuth`, **sebelum** entri `path: '/'`:

```tsx
      { path: '/live/tv', element: <LiveTvPage /> }, // kiosk TV: tanpa header/side nav
```

`LiveViewPage.tsx` — tombol di akhir `.lv-chips` (+ `useNavigate`, ikon `Screen` dari `@carbon/icons-react`):

```tsx
          <Button kind="primary" size="sm" renderIcon={Screen} data-testid="live-tv-open"
            onClick={() => {
              // fullscreen harus dipicu gesture user; browser yang menolak tetap masuk mode TV
              void document.documentElement.requestFullscreen?.()?.catch(() => {})
              navigate('/live/tv?screen=default')
            }}>
            {t('live.tv.open')}
          </Button>
```

`LiveWall.tsx` `CameraTile` — teks bar bawah membesar di TV: `fontSize: tv ? 'clamp(12px, 0.9vw, 32px)' : 12` untuk
nama kamera dan `fontSize: tv ? 'clamp(10px, 0.7vw, 24px)' : 10` untuk badge LIVE/OFFLINE; titik status
`width/height: tv ? '0.6em' : 6`.

`theme.scss`:

```scss
.lv-tv {
  min-height: 100vh;
  background: #000;
}

.lv-tv--idle,
.lv-tv--idle * {
  cursor: none;
}

.lv-tv__bar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 10;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: rgba(22, 22, 22, 0.92);
  color: var(--cds-text-primary);
}

.lv-tv__msg {
  padding: 96px 16px;
  color: #8d8d8d;
  text-align: center;
}

.lv-grid--tv {
  gap: 2px;
  border: 0;
  background: #000;
}
```

`i18n.tsx` — `id`: `'live.tv.open': 'Mode TV'`, `'live.tv.screen': 'Layar {name}'`, `'live.tv.exit': 'Keluar'`,
`'live.tv.autoScroll': 'Gulir otomatis'`, `'live.tv.speed.slow': 'Lambat'`, `'live.tv.speed.medium': 'Sedang'`,
`'live.tv.speed.fast': 'Cepat'`. `en`: `'TV mode'`, `'Screen {name}'`, `'Exit'`, `'Auto-scroll'`, `'Slow'`,
`'Medium'`, `'Fast'`.

- [ ] **Step 4: Jalankan, pastikan lulus** — `npx vitest run && npm run build && npm run lint`. Cek visual (Vite dev +
  API lokal atau stub) `/live/tv?screen=A` pada 1920×1080, 2560×1440, 3840×2160, 1080×1920: 3/3/3/2 kolom default,
  tanpa overflow horizontal, teks tile terbaca; `/live` 390 px tanpa overflow.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Mode TV (kiosk)**: route `/live/tv?screen=<nama>` di luar AppShell; toolbar auto-hide 4 s (kursor ikut hilang):
  kolom, pemilih kamera, gulir otomatis + kecepatan, keluar; auto-scroll jeda saat operator aktif (lanjut 10 s),
  pemilih/debugger terbuka; teks tile membesar di 2K/4K; tombol **Mode TV** di Live View (fullscreen bila
  diizinkan). Frontend **<angka> passed**, build 0, lint set sama.
```

```bash
git add frontend/src/features/live/LiveTvPage.tsx frontend/src/main.tsx frontend/src/features/live/LiveViewPage.tsx frontend/src/features/live/LiveWall.tsx frontend/src/app/theme.scss frontend/src/app/i18n.tsx frontend/src/__tests__/live-tv.test.tsx frontend/src/__tests__/liveview.test.tsx CHANGELOG.md
git commit -m "feat(live): mode TV kiosk dengan toolbar auto-hide dan auto-scroll"
```

---

### Task 8: Runbook Pi, dokumen, suite penuh, push (eksekutor berhenti di sini)

- [ ] **Step 1: Runbook** — buat `docs/runbooks/live-view-tv-pi.md`:

````markdown
# Runbook — Live View mode TV di Raspberry Pi (2 monitor)

Tujuan: satu Raspberry Pi 5 menampilkan `/live/tv` di dua monitor command center, pulih sendiri setelah boot.

## Prasyarat
- Raspberry Pi OS (Bookworm, desktop), Chromium terpasang, kedua monitor terdeteksi (Screen Configuration).
- Resolusi monitor 1080p (disarankan untuk beban decode; Pi 5 tanpa decoder H.264 hardware).
- URL aplikasi: `http://<server>:5173` (LAN).

## Satu kali per layar
1. Jalankan Chromium dengan profil layar A (perintah di bawah tanpa `--kiosk`), login, lalu tutup.
2. Ulangi untuk layar B. Setiap profil menyimpan cookie login dan pengaturan layarnya sendiri.

## Perintah per layar
```bash
chromium-browser --kiosk --noerrdialogs --disable-infobars --autoplay-policy=no-user-gesture-required \
  --user-data-dir="$HOME/.config/isentinel-tv-A" --window-position=0,0 \
  "http://<server>:5173/live/tv?screen=A"

chromium-browser --kiosk --noerrdialogs --disable-infobars --autoplay-policy=no-user-gesture-required \
  --user-data-dir="$HOME/.config/isentinel-tv-B" --window-position=1920,0 \
  "http://<server>:5173/live/tv?screen=B"
```
`--window-position` = posisi kiri-atas monitor kedua di layout desktop (lebar monitor pertama).

## Autostart
Tambahkan kedua perintah (diakhiri `&`) ke `~/.config/labwc/autostart` (Wayland/labwc) atau
`~/.config/lxsession/LXDE-pi/autostart` (X11, awali tiap baris dengan `@`).

## Operasional
- Gerakkan mouse → toolbar muncul: kolom, **Kamera (n/m)**, gulir otomatis + kecepatan, Keluar.
- Sesi login diperpanjang otomatis selama halaman terbuka (48 jam tanpa aktivitas → login ulang).
- Tile yang putus kembali streaming sendiri ≤ 60 s. Beban: pantau `top` di Pi; turunkan kolom bila CPU > 85 %.

## Rollback
Hapus baris autostart; `rm -rf ~/.config/isentinel-tv-A ~/.config/isentinel-tv-B` untuk mengosongkan profil.
````

- [ ] **Step 2: Suite penuh**

```bash
cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1; cd ..
backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu" | tail -1
cd frontend && npx vitest run | tail -3 && npm run build > /dev/null; echo build=$?; npm run lint | tail -2; cd ..
```

- [ ] **Step 3: Dokumen**
  - `README.md` — di bagian Live View (dekat baris "Live View filter"): pemilih kamera, Mode TV
    `/live/tv?screen=<nama>`, auto-scroll, stream hanya tile terlihat + coba ulang 60 s, sesi 48 jam bergulir,
    tautan runbook.
  - `ROADMAP.md` — baris sebelum `| E | Edge Jetson …`:
    `| TV | Live View mode TV (kiosk, filter kamera, auto-scroll, sesi bergulir) | [~] lokal selesai, PENDING deploy + verifikasi | — | spec + plan 2026-09-28 | |`
  - `CHANGELOG.md` — bullet dokumen + suite akhir.

```bash
git add docs/runbooks/live-view-tv-pi.md README.md ROADMAP.md CHANGELOG.md
git commit -m "docs(live): runbook TV Raspberry Pi dan dokumentasi mode TV"
```

- [ ] **Step 4: Push** — `git push -u origin feat/live-view-tv` (diizinkan). **Jangan** deploy, ssh, atau merge.
  Catatan untuk sesi perencana: deploy = restart **isentinel-api** (frontend Vite dev HMR); cek dulu apakah
  `.env` server menyetel `ACCESS_TOKEN_EXPIRE_MIN` (grep nama kunci saja) — bila ya, nilai itu menimpa default 2880.
