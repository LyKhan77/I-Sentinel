# Notifikasi Event Web UI + Outline Tile Live View — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Event behavior/system baru memunculkan lonceng + toast + bunyi di web UI, dan outline berwarna severity pada tile kamera di Live View (normal + TV), dengan chip untuk tile yang tidak terlihat.

**Architecture:** Frontend saja. Satu `EventAlertsProvider` (React context) dipasang di `RequireAuth`, berlangganan `useLiveEvents` sekali, memisahkan riwayat (dimuat saat mount) dari event baru, lalu membagikan `recent/unread/active/nodes/toasts/muted` ke `NotificationBell`, `EventToasts` (AppShell), `CameraTile`/`LiveWall` (Live View) dan toolbar TV. Tanpa provider, `useEventAlerts()` mengembalikan state kosong (tes lama tetap jalan).

**Tech Stack:** React 19, TypeScript, React Router 7, IBM Carbon (`@carbon/react` 1.115, `@carbon/icons-react` 11.87), SCSS (`app/theme.scss`), Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-29-event-notifications-design.md`

## Global Constraints

- Backend **tidak** diubah (tidak ada file di `backend/` atau `vision/` yang disentuh).
- Pemicu hanya `type ∈ {intrusion, loitering, running, idle_zone, crowd, system}`; `attendance`, `person_detect`, pesan `{"type":"detections"}` dan `{"kind":"alert"}` diabaikan.
- Outline/alert aktif **30 s** sejak event terakhir di kamera itu (`ACTIVE_MS = 30_000`).
- Daftar lonceng **20** event terakhir; badge tampil `20+` bila ≥ 20.
- Toast maks **3**, hilang sendiri **8 s**; hanya di halaman `AppShell` (bukan `/live/tv`).
- Bunyi maks 1 kali / **5 s**; mute per browser (localStorage `isentinel_notif_mute`, nilai `'1'` / `'0'`).
- Status dibaca per browser: localStorage `isentinel_notif_seen` = id event terakhir yang dibaca. Key belum ada → setelah riwayat dimuat diisi id terbesar riwayat (tanpa badge palsu).
- Warna severity sama dengan `ev-dot` halaman Events: critical `#fa4d56`, warning `#f1c21b`, info `#4589ff`; severity lain → warning.
- Chip alert: fixed **kanan bawah** di Live View normal dan TV.
- Semua string user-facing lewat `src/app/i18n.tsx` (id + en). REST hanya lewat `src/api/*`.
- 390 px tanpa overflow horizontal.
- Semua akses localStorage dibungkus try/catch.
- Commit Conventional Commits, **tanpa** trailer/atribusi AI apa pun (AGENTS.md §9). Prefix perintah shell dengan `rtk`.
- Baseline `main` `8476792`: backend 490, vision 223 (3 deselected), frontend 182, build 0.

## Review Focus

1. **Banjir notifikasi saat halaman dibuka / reload** — 50 event lama dari poll pertama `useLiveEvents` tidak boleh memicu toast/bunyi/outline (tes Task 1: riwayat awal + race poll vs riwayat).
2. **Event datang dua kali (WS + polling)** — hanya satu toast/bunyi/badge (tes Task 1: duplikat).
3. **Riwayat gagal dimuat** — event lama dari aliran polling tidak boleh jadi "baru" (tes Task 1: riwayat gagal).
4. **Tile di bawah layar dalam zona pra-muat (`rootMargin 50%`) dianggap terlihat** — chip harus memakai observer tanpa margin (tes Task 3: chip + FakeIO dengan `rootMargin '0px'`).
5. **Klik tombol tutup toast ikut menavigasi** — klik tombol × hanya menutup (tes Task 2).

---

## File Structure

| File | Tanggung jawab |
|---|---|
| Create `frontend/src/features/notifications/EventAlertsProvider.tsx` | Context + provider: penyaring, riwayat vs baru, anti duplikat, alert aktif, toast, unread, mute, bunyi |
| Create `frontend/src/features/notifications/beep.ts` | Beep Web Audio tanpa file audio |
| Create `frontend/src/features/notifications/labels.ts` | `sevClass`, `typeKey`, `eventWhere` (label bersama lonceng/toast/tile/chip) |
| Create `frontend/src/features/notifications/NotificationBell.tsx` | Lonceng header + panel |
| Create `frontend/src/features/notifications/EventToasts.tsx` | Tumpukan toast |
| Modify `frontend/src/main.tsx` | Pasang provider di `RequireAuth` |
| Modify `frontend/src/app/AppShell.tsx` | Render lonceng + toast |
| Modify `frontend/src/features/live/useInView.ts` | Parameter `rootMargin` |
| Modify `frontend/src/features/live/LiveWall.tsx` | Outline tile, laporan visibilitas, chip |
| Modify `frontend/src/features/live/LiveTvPage.tsx` | Toggle bunyi di toolbar |
| Modify `frontend/src/app/i18n.tsx` | Kunci `notif.*` (id + en) |
| Modify `frontend/src/app/theme.scss` | Gaya `.nb*`, `.nt-toasts`, `.lv-alert*` |
| Create `frontend/src/__tests__/event-alerts.test.tsx` | Semua tes fitur ini (`notifications.test.tsx` sudah dipakai tes Telegram) |
| Modify `README.md`, `ROADMAP.md`, `CHANGELOG.md` | Dokumentasi |

---

### Task 1: Provider, label, beep, i18n

**Files:**
- Create: `frontend/src/features/notifications/EventAlertsProvider.tsx`
- Create: `frontend/src/features/notifications/beep.ts`
- Create: `frontend/src/features/notifications/labels.ts`
- Modify: `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/event-alerts.test.tsx`

**Interfaces:**
- Consumes: `listEvents(params)` & `EventOut` (`src/api/events.ts`), `listCameras()` (`src/api/cameras.ts`), `useLiveEvents(onEvent)` (`src/api/useWs.ts`), `TKey` (`src/app/i18n.tsx`).
- Produces:
  - `EventAlertsProvider({ children })`, `useEventAlerts(): EventAlerts`
  - `type CamAlert = { eventId: number; type: string; severity: string; zoneName: string | null; until: number }`
  - `type NodeAlert = { eventId: number; node: string; until: number }`
  - `type EventAlerts = { recent: EventOut[]; unread: number; markAllRead(): void; active: Record<number, CamAlert>; nodes: NodeAlert[]; toasts: EventOut[]; dismissToast(id: number): void; muted: boolean; setMuted(v: boolean): void; cameraName(id: number | null): string }`
  - konstanta `ACTIVE_MS`, `RECENT_MAX`, `TOAST_MAX`, `BEEP_GAP_MS`, `STALE_MS`, `SEEN_KEY`, `MUTE_KEY`
  - `beep(): void`
  - `sevClass(s: string): 'critical' | 'warning' | 'info'`, `typeKey(type: string): TKey`, `eventWhere(e: EventOut, t: (k: TKey) => string, cameraName: (id: number | null) => string): string`

- [ ] **Step 1: Tambah kunci i18n**

Di `frontend/src/app/i18n.tsx`, dict `id`, tepat setelah baris `'events.emptyFiltered': 'Tidak ada event yang cocok',` tambahkan:

```ts
    'notif.bell': 'Notifikasi',
    'notif.bellUnread': '{n} notifikasi belum dibaca',
    'notif.title': 'Event terbaru',
    'notif.empty': 'Belum ada event',
    'notif.viewAll': 'Lihat semua event',
    'notif.sound': 'Bunyi',
    'notif.type.system': 'Node offline',
    'notif.nodeOffline': 'Node {node} offline',
    'notif.chips': 'Kamera dengan event',
```

Dict `en`, setelah `'events.emptyFiltered': 'No matching events',`:

```ts
    'notif.bell': 'Notifications',
    'notif.bellUnread': '{n} unread notifications',
    'notif.title': 'Recent events',
    'notif.empty': 'No events yet',
    'notif.viewAll': 'View all events',
    'notif.sound': 'Sound',
    'notif.type.system': 'Node offline',
    'notif.nodeOffline': 'Node {node} offline',
    'notif.chips': 'Cameras with events',
```

- [ ] **Step 2: Tulis tes provider (gagal)**

Buat `frontend/src/__tests__/event-alerts.test.tsx`. Bagian atas file (helper) dipakai juga oleh Task 2 dan 3 — tulis sekarang lengkap:

```tsx
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import { EventAlertsProvider, useEventAlerts, MUTE_KEY, SEEN_KEY } from '../features/notifications/EventAlertsProvider'
import { beep } from '../features/notifications/beep'

vi.mock('../features/notifications/beep', () => ({ beep: vi.fn() }))

const CAMS = [
  { id: 1, name: 'CAM-01', location: 'Gudang', host: '192.168.1.101', rtsp_main: null, rtsp_sub: null, node_id: 1, enabled: true, status: 'online', probe_main: null, probe_sub: null },
  { id: 2, name: 'CAM-02', location: 'Gudang', host: '192.168.1.102', rtsp_main: null, rtsp_sub: null, node_id: 1, enabled: true, status: 'online', probe_main: null, probe_sub: null },
]

type Ev = Record<string, unknown>
const ev = (id: number, over: Ev = {}): Ev => ({
  id, event_id: `e-${id}`, type: 'intrusion', camera_id: 1, zone_id: 1, severity: 'critical',
  ts_event: new Date().toISOString(), payload: { zone_name: 'Pagar' },
  clip_path: null, snapshot_path: 'snapshots/x.jpg', ...over,
})

let history: Ev[] | 'fail' = []
const ok = (body: unknown) => ({ ok: true, status: 200, json: () => Promise.resolve(body) })

function stubFetch() {
  return vi.fn(async (url: string) => {
    const u = String(url)
    if (u.includes('/events?') && u.includes('since=')) return ok([])
    if (u.includes('/events?limit=50')) {
      return history === 'fail' ? { ok: false, status: 500, json: () => Promise.resolve(null) } : ok(history)
    }
    if (u.endsWith('/cameras')) return ok(CAMS)
    if (u.includes('/zones')) return ok([])
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
}

// semua WebSocket yang dibuka (provider + LiveWall) menerima pesan yang sama, seperti hub backend
const sockets: { onmessage: ((ev: { data: string }) => void) | null }[] = []
class FakeWS {
  onmessage: ((ev: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  constructor() { sockets.push(this) }
  close() {}
  send() {}
  addEventListener() {}
  removeEventListener() {}
}
function send(msg: unknown) {
  act(() => { for (const s of sockets) s.onmessage?.({ data: JSON.stringify(msg) }) })
}

function Probe() {
  const a = useEventAlerts()
  const loc = useLocation()
  return (
    <>
      <span data-testid="recent">{a.recent.map((e) => e.id).join(',')}</span>
      <span data-testid="active">{Object.keys(a.active).join(',')}</span>
      <span data-testid="nodes">{a.nodes.map((n) => n.node).join(',')}</span>
      <span data-testid="toast-ids">{a.toasts.map((e) => e.id).join(',')}</span>
      <span data-testid="unread">{a.unread}</span>
      <span data-testid="loc">{loc.pathname + loc.search}</span>
    </>
  )
}

function renderWith(ui: ReactNode = null, entry = '/dashboard') {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[entry]}>
        <EventAlertsProvider>
          {ui}
          <Probe />
        </EventAlertsProvider>
      </MemoryRouter>
    </I18nProvider>,
  )
}

// fake timers: waitFor tidak dipakai; flush promise lewat advanceTimersByTimeAsync
const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms) })

beforeEach(() => {
  localStorage.clear()
  sockets.length = 0
  history = [ev(11), ev(10, { camera_id: 2 })]
  vi.mocked(beep).mockClear()
  vi.stubGlobal('fetch', stubFetch())
  vi.stubGlobal('WebSocket', FakeWS)
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView // dipasang tes chip (jsdom tidak punya)
})
```

Lalu tes provider:

```tsx
test('riwayat awal: masuk daftar tanpa toast/bunyi/outline; kunjungan pertama tanpa unread', async () => {
  renderWith()
  await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('11,10'))
  expect(screen.getByTestId('toast-ids')).toHaveTextContent('')
  expect(screen.getByTestId('active')).toHaveTextContent('')
  expect(beep).not.toHaveBeenCalled()
  expect(screen.getByTestId('unread')).toHaveTextContent('0')
  expect(localStorage.getItem(SEEN_KEY)).toBe('11')
})

test('event baru via WS: toast + bunyi + unread + alert aktif; duplikat dan event riwayat diabaikan', async () => {
  renderWith()
  await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('11,10'))
  send(ev(12))
  send(ev(12)) // WS + polling membawa event yang sama
  send(ev(11)) // event riwayat datang lagi lewat aliran
  expect(screen.getByTestId('toast-ids')).toHaveTextContent('12')
  expect(beep).toHaveBeenCalledTimes(1)
  expect(screen.getByTestId('unread')).toHaveTextContent('1')
  expect(screen.getByTestId('active')).toHaveTextContent('1')
  expect(screen.getByTestId('recent')).toHaveTextContent('12,11,10')
})

test('attendance, person_detect, detections, dan kind:alert tidak memicu apa pun', async () => {
  renderWith()
  await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('11,10'))
  send(ev(20, { type: 'attendance' }))
  send(ev(21, { type: 'person_detect' }))
  send({ type: 'detections', camera_id: 1, kind: 'person', boxes: [] })
  send({ kind: 'alert', event_id: 12, status: 'sent' })
  expect(screen.getByTestId('recent')).toHaveTextContent('11,10')
  expect(screen.getByTestId('toast-ids')).toHaveTextContent('')
  expect(beep).not.toHaveBeenCalled()
})

test('pesan aliran yang tiba sebelum riwayat selesai: id riwayat dibuang, sisanya baru', async () => {
  let release: () => void = () => {}
  const gate = new Promise<void>((r) => { release = r })
  const base = stubFetch()
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (String(url).includes('/events?limit=50')) await gate // riwayat tertahan
    return base(url)
  }))
  renderWith()
  send(ev(11)) // sama dengan riwayat
  send(ev(12)) // benar-benar baru
  expect(screen.getByTestId('toast-ids')).toHaveTextContent('')
  await act(async () => { release() })
  await waitFor(() => expect(screen.getByTestId('toast-ids')).toHaveTextContent('12'))
  expect(beep).toHaveBeenCalledTimes(1)
})

test('alert aktif 30 s, diperpanjang event baru di kamera yang sama', async () => {
  vi.useFakeTimers()
  renderWith()
  await advance(0)
  send(ev(12))
  expect(screen.getByTestId('active')).toHaveTextContent('1')
  await advance(20_000)
  send(ev(13))
  await advance(20_000)
  expect(screen.getByTestId('active')).toHaveTextContent('1')
  await advance(11_000)
  expect(screen.getByTestId('active')).toHaveTextContent('')
})

test('system: masuk nodes 30 s tanpa alert kamera', async () => {
  vi.useFakeTimers()
  renderWith()
  await advance(0)
  send(ev(30, { type: 'system', camera_id: null, zone_id: null, severity: 'warning', payload: { node: 'vision-1', reason: 'lwt' } }))
  expect(screen.getByTestId('nodes')).toHaveTextContent('vision-1')
  expect(screen.getByTestId('active')).toHaveTextContent('')
  expect(screen.getByTestId('toast-ids')).toHaveTextContent('30')
  await advance(31_000)
  expect(screen.getByTestId('nodes')).toHaveTextContent('')
})

test('bunyi: throttle 5 s, dan diam saat mute', async () => {
  vi.useFakeTimers()
  const { unmount } = renderWith()
  await advance(0)
  send(ev(12))
  send(ev(13, { camera_id: 2 }))
  expect(beep).toHaveBeenCalledTimes(1)
  await advance(5_000)
  send(ev(14))
  expect(beep).toHaveBeenCalledTimes(2)
  unmount()

  vi.mocked(beep).mockClear()
  sockets.length = 0
  localStorage.setItem(MUTE_KEY, '1')
  renderWith()
  await advance(0)
  send(ev(15))
  expect(beep).not.toHaveBeenCalled()
  expect(screen.getByTestId('toast-ids')).toHaveTextContent('15') // visual tetap jalan
})

test('toast maksimal 3: yang terlama dibuang', async () => {
  renderWith()
  await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('11,10'))
  for (const id of [12, 13, 14, 15]) send(ev(id))
  expect(screen.getByTestId('toast-ids')).toHaveTextContent('13,14,15')
})

test('riwayat gagal dimuat: event basi dari aliran = riwayat, event segar = baru', async () => {
  history = 'fail'
  renderWith()
  // urutan terhadap kegagalan riwayat tidak penting: pesan ditampung lalu diproses setelah gagal
  send(ev(40, { ts_event: new Date(Date.now() - 120_000).toISOString() }))
  send(ev(41))
  await waitFor(() => expect(screen.getByTestId('toast-ids')).toHaveTextContent('41'))
  expect(screen.getByTestId('toast-ids')).not.toHaveTextContent('40')
  expect(screen.getByTestId('recent')).toHaveTextContent('41,40')
  expect(beep).toHaveBeenCalledTimes(1)
})

test('localStorage diblokir: provider tetap jalan', async () => {
  const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
  const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
  try {
    renderWith()
    await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('11,10'))
    send(ev(12))
    expect(screen.getByTestId('toast-ids')).toHaveTextContent('12')
  } finally {
    get.mockRestore()
    set.mockRestore()
  }
})
```

- [ ] **Step 3: Jalankan tes, pastikan gagal**

Run (dari `frontend/`): `rtk npx vitest run src/__tests__/event-alerts.test.tsx`
Expected: FAIL — `Failed to resolve import "../features/notifications/EventAlertsProvider"`.

- [ ] **Step 4: Tulis `beep.ts`**

```ts
// Beep pendek tanpa file audio (Web Audio). AudioContext tidak ada / autoplay diblokir → diam.
let ctx: AudioContext | null = null

export function beep(): void {
  try {
    const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!AC) return
    ctx ??= new AC()
    if (ctx.state === 'suspended') void ctx.resume().catch(() => {})
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.frequency.value = 880
    gain.gain.value = 0.15
    osc.connect(gain).connect(ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + 0.15)
  } catch {
    // browser menolak audio → notifikasi visual tetap jalan
  }
}
```

- [ ] **Step 5: Tulis `labels.ts`**

```ts
import type { EventOut } from '../../api/events'
import type { TKey } from '../../app/i18n'

export type Sev = 'critical' | 'warning' | 'info'
const SEVS: readonly string[] = ['critical', 'warning', 'info']

/** Severity tak dikenal → warning (warna tetap terlihat). */
export const sevClass = (s: string): Sev => (SEVS.includes(s) ? (s as Sev) : 'warning')

/** Label jenis event: behavior memakai label zona; system = "Node offline". */
export const typeKey = (type: string): TKey =>
  type === 'system' ? 'notif.type.system' : (`zones.behavior.${type}` as TKey)

/** Lokasi event: "Node X offline" untuk system, selain itu "kamera · zona". */
export function eventWhere(e: EventOut, t: (k: TKey) => string, cameraName: (id: number | null) => string): string {
  if (e.type === 'system') return t('notif.nodeOffline').replace('{node}', String(e.payload?.node ?? '?'))
  const zone = typeof e.payload?.zone_name === 'string' && e.payload.zone_name ? e.payload.zone_name : null
  return zone ? `${cameraName(e.camera_id)} · ${zone}` : cameraName(e.camera_id)
}
```

- [ ] **Step 6: Tulis `EventAlertsProvider.tsx`**

```tsx
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { listCameras } from '../../api/cameras'
import { listEvents, type EventOut } from '../../api/events'
import { useLiveEvents } from '../../api/useWs'
import { beep } from './beep'

export const NOTIFY_TYPES = new Set(['intrusion', 'loitering', 'running', 'idle_zone', 'crowd', 'system'])
export const ACTIVE_MS = 30_000
export const RECENT_MAX = 20
export const TOAST_MAX = 3
export const BEEP_GAP_MS = 5_000
export const STALE_MS = 60_000
const HISTORY_LIMIT = 50
export const SEEN_KEY = 'isentinel_notif_seen'
export const MUTE_KEY = 'isentinel_notif_mute'

export type CamAlert = { eventId: number; type: string; severity: string; zoneName: string | null; until: number }
export type NodeAlert = { eventId: number; node: string; until: number }
export type EventAlerts = {
  recent: EventOut[]
  unread: number
  markAllRead: () => void
  active: Record<number, CamAlert>
  nodes: NodeAlert[]
  toasts: EventOut[]
  dismissToast: (id: number) => void
  muted: boolean
  setMuted: (v: boolean) => void
  cameraName: (id: number | null) => string
}

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // storage diblokir → berlaku untuk sesi ini saja
  }
}

/** Pesan WS/polling → event pemicu notifikasi, atau null (detections, kind:alert, attendance, ...). */
export function asNotifyEvent(m: unknown): EventOut | null {
  const e = m as Partial<EventOut> | null
  if (!e || typeof e.id !== 'number' || typeof e.event_id !== 'string' || typeof e.type !== 'string') return null
  return NOTIFY_TYPES.has(e.type) ? (e as EventOut) : null
}

// tanpa provider (tes lama, komponen dipakai terpisah) → state kosong, aksi no-op
const INERT: EventAlerts = {
  recent: [], unread: 0, markAllRead: () => {}, active: {}, nodes: [], toasts: [],
  dismissToast: () => {}, muted: false, setMuted: () => {}, cameraName: (id) => `#${id ?? '?'}`,
}
const Ctx = createContext<EventAlerts>(INERT)
export const useEventAlerts = () => useContext(Ctx)

/**
 * Satu langganan event untuk seluruh app: riwayat (dimuat saat mount) hanya mengisi daftar lonceng;
 * event yang tiba sesudahnya memicu toast, bunyi, dan alert aktif per kamera / node.
 */
export function EventAlertsProvider({ children }: { children: ReactNode }) {
  const [recent, setRecent] = useState<EventOut[]>([])
  const [seenId, setSeenId] = useState<number | null>(() => {
    const raw = read(SEEN_KEY)
    const n = raw === null ? NaN : Number(raw)
    return Number.isFinite(n) ? n : null
  })
  const [active, setActive] = useState<Record<number, CamAlert>>({})
  const [nodes, setNodes] = useState<NodeAlert[]>([])
  const [toasts, setToasts] = useState<EventOut[]>([])
  const [muted, setMutedState] = useState(() => read(MUTE_KEY) === '1')
  const [camNames, setCamNames] = useState<Record<number, string>>({})
  const seen = useRef(new Set<number>())
  const buffer = useRef<EventOut[] | null>([]) // null = riwayat sudah diproses
  const historyFailed = useRef(false)
  const lastBeep = useRef(-Infinity)
  const mutedRef = useRef(muted)
  mutedRef.current = muted

  const addRecent = (list: EventOut[]) =>
    setRecent((prev) => [...list, ...prev].sort((a, b) => b.id - a.id).slice(0, RECENT_MAX))

  const fire = (e: EventOut) => {
    const now = Date.now()
    addRecent([e])
    if (e.type === 'system') {
      const node = String(e.payload?.node ?? '?')
      setNodes((prev) => [...prev.filter((n) => n.node !== node), { eventId: e.id, node, until: now + ACTIVE_MS }])
    } else if (e.camera_id != null) {
      const zoneName = typeof e.payload?.zone_name === 'string' && e.payload.zone_name ? e.payload.zone_name : null
      setActive((prev) => ({
        ...prev,
        [e.camera_id]: { eventId: e.id, type: e.type, severity: e.severity, zoneName, until: now + ACTIVE_MS },
      }))
    }
    setToasts((prev) => [...prev, e].slice(-TOAST_MAX))
    if (!mutedRef.current && now - lastBeep.current >= BEEP_GAP_MS) {
      lastBeep.current = now
      beep()
    }
  }

  // riwayat gagal dimuat → event aliran yang sudah basi = riwayat, bukan kejadian baru
  const route = (e: EventOut) => {
    if (historyFailed.current && Date.now() - Date.parse(e.ts_event) >= STALE_MS) addRecent([e])
    else fire(e)
  }

  useLiveEvents((m) => {
    const e = asNotifyEvent(m)
    if (!e || seen.current.has(e.id)) return
    seen.current.add(e.id)
    if (seen.current.size > 2000) seen.current = new Set([...seen.current].slice(-1000)) // TV 24/7
    if (buffer.current) buffer.current.push(e)
    else route(e)
  })

  useEffect(() => {
    let alive = true
    const flush = (historyIds: Set<number>) => {
      const pending = buffer.current ?? []
      buffer.current = null
      for (const e of pending) if (!historyIds.has(e.id)) route(e)
    }
    listEvents({ limit: HISTORY_LIMIT })
      .then((list) => {
        if (!alive) return
        const hist = list.map(asNotifyEvent).filter((e): e is EventOut => e !== null)
        for (const e of hist) seen.current.add(e.id)
        addRecent(hist)
        flush(new Set(hist.map((e) => e.id)))
        // kunjungan pertama: riwayat dianggap sudah dibaca (tanpa badge "20+" palsu)
        const max = hist.reduce((m, e) => Math.max(m, e.id), 0)
        setSeenId((s) => s ?? max)
        if (read(SEEN_KEY) === null) write(SEEN_KEY, String(max))
      })
      .catch(() => {
        if (!alive) return
        historyFailed.current = true
        flush(new Set())
        setSeenId((s) => s ?? 0)
      })
    listCameras()
      .then((cs) => { if (alive) setCamNames(Object.fromEntries(cs.map((c) => [c.id, c.name]))) })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, []) // sekali saat mount

  // alert kedaluwarsa dibersihkan tiap detik; state baru hanya bila ada yang berubah
  useEffect(() => {
    const timer = setInterval(() => {
      const now = Date.now()
      setActive((prev) => {
        const keep = Object.entries(prev).filter(([, a]) => a.until > now)
        return keep.length === Object.keys(prev).length ? prev : (Object.fromEntries(keep) as Record<number, CamAlert>)
      })
      setNodes((prev) => {
        const keep = prev.filter((n) => n.until > now)
        return keep.length === prev.length ? prev : keep
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  const value: EventAlerts = {
    recent,
    unread: seenId === null ? 0 : recent.filter((e) => e.id > seenId).length,
    markAllRead: () => {
      const max = Math.max(recent[0]?.id ?? 0, seenId ?? 0)
      setSeenId(max)
      write(SEEN_KEY, String(max))
    },
    active,
    nodes,
    toasts,
    dismissToast: (id) => setToasts((prev) => prev.filter((e) => e.id !== id)),
    muted,
    setMuted: (v) => {
      setMutedState(v)
      write(MUTE_KEY, v ? '1' : '0')
    },
    cameraName: (id) => (id != null && camNames[id]) || `#${id ?? '?'}`,
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
```

Catatan: oxlint (`.oxlintrc.json`) memberi **warning** `react/only-export-components` untuk export hook/fungsi di file ini — pola sama dengan `i18n.tsx`; yang dilarang hanya error baru.

- [ ] **Step 7: Jalankan tes, pastikan lulus**

Run: `rtk npx vitest run src/__tests__/event-alerts.test.tsx`
Expected: PASS (10 tes).

- [ ] **Step 8: Commit**

```bash
rtk git add frontend/src/features/notifications frontend/src/app/i18n.tsx frontend/src/__tests__/event-alerts.test.tsx
rtk git commit -m "feat(notifications): provider alert event (riwayat vs baru, anti duplikat, bunyi)"
```

---

### Task 2: Lonceng header + toast di AppShell

**Files:**
- Create: `frontend/src/features/notifications/NotificationBell.tsx`
- Create: `frontend/src/features/notifications/EventToasts.tsx`
- Modify: `frontend/src/app/AppShell.tsx` (import; `HeaderGlobalBar` baris ~119; setelah `</Header>` baris ~134)
- Modify: `frontend/src/main.tsx` (`RequireAuth`, baris ~51)
- Modify: `frontend/src/app/theme.scss` (tambah di akhir file)
- Test: `frontend/src/__tests__/event-alerts.test.tsx`

**Interfaces:**
- Consumes: `useEventAlerts()`, `RECENT_MAX`, `SEEN_KEY` (Task 1); `sevClass`, `typeKey`, `eventWhere` (Task 1).
- Produces: `NotificationBell` (default export), `EventToasts` (default export), `TOAST_MS = 8000`; test id `notif-bell`, `notif-badge`, `notif-panel`, `notif-item-<id>`, `event-toasts`, `toast-<id>`.

- [ ] **Step 1: Tulis tes (gagal)**

Tambahkan import di atas file tes:

```tsx
import NotificationBell from '../features/notifications/NotificationBell'
import EventToasts from '../features/notifications/EventToasts'
```

Tambahkan tes:

```tsx
const shell = (
  <>
    <NotificationBell />
    <EventToasts />
  </>
)

test('lonceng: badge unread, buka panel = dibaca (persist), item membuka detail event', async () => {
  localStorage.setItem(SEEN_KEY, '10') // event 11 belum dibaca
  const { unmount } = renderWith(shell)
  expect(await screen.findByTestId('notif-badge')).toHaveTextContent('1')
  await userEvent.click(screen.getByTestId('notif-bell'))
  expect(screen.getByTestId('notif-panel')).toBeInTheDocument()
  expect(screen.queryByTestId('notif-badge')).toBeNull()
  expect(localStorage.getItem(SEEN_KEY)).toBe('11')
  expect(screen.getByTestId('notif-item-11')).toHaveTextContent('Intrusi')
  expect(screen.getByTestId('notif-item-11')).toHaveTextContent('CAM-01 · Pagar')
  await userEvent.click(screen.getByTestId('notif-item-11'))
  expect(screen.getByTestId('loc')).toHaveTextContent('/events?event=11')
  expect(screen.queryByTestId('notif-panel')).toBeNull()
  unmount()

  sockets.length = 0
  renderWith(shell)
  await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('11,10'))
  expect(screen.queryByTestId('notif-badge')).toBeNull()
})

test('lonceng: badge 20+, panel kosong, Escape menutup, toggle bunyi', async () => {
  history = []
  localStorage.setItem(SEEN_KEY, '0')
  renderWith(shell)
  await waitFor(() => expect(screen.getByTestId('unread')).toHaveTextContent('0'))
  await userEvent.click(screen.getByTestId('notif-bell'))
  expect(screen.getByTestId('notif-panel')).toHaveTextContent('Belum ada event')
  await userEvent.click(screen.getByTestId('notif-sound'))
  expect(localStorage.getItem(MUTE_KEY)).toBe('1')
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByTestId('notif-panel')).toBeNull()

  for (let id = 100; id < 125; id++) send(ev(id))
  expect(screen.getByTestId('notif-badge')).toHaveTextContent('20+')
})

test('toast: tampil untuk event baru, klik isi → detail, klik tutup hanya menutup', async () => {
  renderWith(shell)
  await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('11,10'))
  expect(screen.queryByTestId('event-toasts')).toBeNull()
  send(ev(12))
  send(ev(13, { type: 'system', camera_id: null, zone_id: null, severity: 'warning', payload: { node: 'vision-1' } }))
  expect(screen.getByTestId('toast-12')).toHaveTextContent('Intrusi')
  expect(screen.getByTestId('toast-12')).toHaveTextContent('CAM-01 · Pagar')
  expect(screen.getByTestId('toast-13')).toHaveTextContent('Node vision-1 offline')

  await userEvent.click(screen.getByTestId('toast-13').querySelector('button')!)
  expect(screen.queryByTestId('toast-13')).toBeNull()
  expect(screen.getByTestId('loc')).toHaveTextContent('/dashboard')

  await userEvent.click(screen.getByText('CAM-01 · Pagar'))
  expect(screen.getByTestId('loc')).toHaveTextContent('/events?event=12')
  expect(screen.queryByTestId('toast-12')).toBeNull()
})
```

- [ ] **Step 2: Jalankan tes, pastikan gagal**

Run: `rtk npx vitest run src/__tests__/event-alerts.test.tsx`
Expected: FAIL — `Failed to resolve import "../features/notifications/NotificationBell"`.

- [ ] **Step 3: Tulis `NotificationBell.tsx`**

```tsx
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, HeaderGlobalAction, Toggle } from '@carbon/react'
import { Notification as NotificationIcon } from '@carbon/icons-react'
import { useT } from '../../app/i18n'
import { RECENT_MAX, useEventAlerts } from './EventAlertsProvider'
import { eventWhere, sevClass, typeKey } from './labels'

/** Lonceng header: badge belum dibaca + panel event terbaru. Membuka panel = semua dibaca. */
export default function NotificationBell() {
  const { t, locale } = useT()
  const navigate = useNavigate()
  const { recent, unread, markAllRead, muted, setMuted, cameraName } = useEventAlerts()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])

  const toggle = () => {
    if (!open) markAllRead()
    setOpen((o) => !o)
  }
  const go = (to: string) => {
    setOpen(false)
    navigate(to)
  }
  const label = unread > 0 ? t('notif.bellUnread').replace('{n}', String(unread)) : t('notif.bell')

  return (
    <div className="nb" ref={rootRef}>
      <HeaderGlobalAction aria-label={label} isActive={open} onClick={toggle} data-testid="notif-bell">
        <NotificationIcon size={20} />
        {unread > 0 && (
          <span className="nb__badge" data-testid="notif-badge" aria-hidden="true">
            {unread >= RECENT_MAX ? `${RECENT_MAX}+` : unread}
          </span>
        )}
      </HeaderGlobalAction>
      {open && (
        <div className="nb__panel" role="dialog" aria-label={t('notif.title')} data-testid="notif-panel">
          <div className="nb__head">
            <strong>{t('notif.title')}</strong>
            <Toggle id="notif-sound" data-testid="notif-sound" size="sm" labelText={t('notif.sound')}
              toggled={!muted} onToggle={(on) => setMuted(!on)} />
          </div>
          {recent.length === 0 ? (
            <p className="nb__empty">{t('notif.empty')}</p>
          ) : (
            <ul className="nb__list">
              {recent.map((e) => (
                <li key={e.id}>
                  <button type="button" className="nb__item" data-testid={`notif-item-${e.id}`}
                    onClick={() => go(`/events?event=${e.id}`)}>
                    <span className={`ev-dot ev-dot--${sevClass(e.severity)}`} aria-hidden="true" />
                    <span className="nb__text">
                      <span>{t(typeKey(e.type))}</span>
                      <span className="nb__sub">{eventWhere(e, t, cameraName)}</span>
                      <span className="nb__sub">
                        {new Date(e.ts_event).toLocaleString(locale, { dateStyle: 'short', timeStyle: 'short' })}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="nb__foot">
            <Button kind="ghost" size="sm" onClick={() => go('/events')}>{t('notif.viewAll')}</Button>
          </div>
        </div>
      )}
    </div>
  )
}
```

Catatan: bila Carbon `HeaderGlobalAction` tidak meneruskan `data-testid` ke `<button>`, bungkus ikon di `<span data-testid="notif-bell">` bukan solusi (klik harus pada tombol) — gunakan `screen.getByRole('button', { name: /notifikasi/i })` di tes sebagai gantinya, dan catat di laporan.

- [ ] **Step 4: Tulis `EventToasts.tsx`**

```tsx
import { useNavigate } from 'react-router-dom'
import { ToastNotification } from '@carbon/react'
import { useT } from '../../app/i18n'
import { useEventAlerts } from './EventAlertsProvider'
import { eventWhere, sevClass, typeKey } from './labels'

export const TOAST_MS = 8000
const TOAST_KIND = { critical: 'error', warning: 'warning', info: 'info' } as const

/** Toast event baru (kanan atas). Klik isi → detail event; tombol × hanya menutup. */
export default function EventToasts() {
  const { t, locale } = useT()
  const navigate = useNavigate()
  const { toasts, dismissToast, cameraName } = useEventAlerts()
  if (toasts.length === 0) return null
  return (
    <div className="nt-toasts" data-testid="event-toasts">
      {toasts.map((e) => (
        <div key={e.id} data-testid={`toast-${e.id}`} className="nt-toasts__item"
          onClick={(ev) => {
            if ((ev.target as HTMLElement).closest('button')) return // tombol tutup
            dismissToast(e.id)
            navigate(`/events?event=${e.id}`)
          }}>
          <ToastNotification kind={TOAST_KIND[sevClass(e.severity)]} lowContrast timeout={TOAST_MS}
            title={t(typeKey(e.type))} subtitle={eventWhere(e, t, cameraName)}
            caption={new Date(e.ts_event).toLocaleTimeString(locale)}
            onClose={() => { dismissToast(e.id) }} />
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 5: Pasang di AppShell dan main.tsx**

`frontend/src/app/AppShell.tsx` — tambah import setelah `import ChangePasswordModal ...`:

```tsx
import NotificationBell from '../features/notifications/NotificationBell'
import EventToasts from '../features/notifications/EventToasts'
```

Di dalam `<HeaderGlobalBar>`, sisipkan `<NotificationBell />` sebagai anak pertama (sebelum `<div className="app-lang" ...>`). Tepat setelah `</Header>` sisipkan `<EventToasts />`.

`frontend/src/main.tsx` — tambah import:

```tsx
import { EventAlertsProvider } from './features/notifications/EventAlertsProvider'
```

Di `RequireAuth`, ganti `return <Outlet />` dengan:

```tsx
  // satu langganan notifikasi event untuk semua halaman login (AppShell + /live/tv)
  return (
    <EventAlertsProvider>
      <Outlet />
    </EventAlertsProvider>
  )
```

- [ ] **Step 6: Gaya (tambah di akhir `frontend/src/app/theme.scss`)**

```scss
/* Notifikasi event: lonceng header + panel, toast. */
.nb {
  position: relative;
  display: flex;
}

.nb__badge {
  position: absolute;
  top: 8px;
  right: 6px;
  min-inline-size: 16px;
  block-size: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: #da1e28;
  color: #fff;
  font-size: 10px;
  line-height: 16px;
  text-align: center;
  pointer-events: none;
}

.nb__panel {
  position: fixed;
  top: 48px;
  right: 0;
  z-index: 8000;
  inline-size: min(360px, 100vw);
  max-block-size: calc(100vh - 48px);
  overflow-y: auto;
  background: var(--cds-layer-01);
  border: 1px solid var(--cds-border-subtle);
  color: var(--cds-text-primary);
}

.nb__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--cds-border-subtle);
}

.nb__list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.nb__item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  inline-size: 100%;
  padding: 10px 16px;
  background: none;
  border: 0;
  border-bottom: 1px solid var(--cds-border-subtle);
  color: inherit;
  font: inherit;
  text-align: start;
  cursor: pointer;

  &:hover {
    background: var(--cds-layer-hover-01);
  }

  .ev-dot {
    margin-block-start: 6px;
  }
}

.nb__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-inline-size: 0;
  font-size: 13px;
}

.nb__sub {
  color: var(--cds-text-secondary);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.nb__empty {
  padding: 16px;
  color: var(--cds-text-secondary);
}

.nb__foot {
  padding: 8px 16px;
}

.nt-toasts {
  position: fixed;
  top: 56px;
  right: 16px;
  z-index: 8000;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-inline-size: calc(100vw - 32px);

  .cds--toast-notification {
    cursor: pointer;
    max-inline-size: 100%;
  }
}
```

- [ ] **Step 7: Jalankan tes fitur + tes shell**

Run: `rtk npx vitest run src/__tests__/event-alerts.test.tsx src/__tests__/shell.test.tsx`
Expected: PASS semua (shell lama tetap lulus karena `useEventAlerts()` tanpa provider = state kosong).

- [ ] **Step 8: Commit**

```bash
rtk git add frontend/src/features/notifications frontend/src/app/AppShell.tsx frontend/src/main.tsx frontend/src/app/theme.scss frontend/src/__tests__/event-alerts.test.tsx
rtk git commit -m "feat(notifications): lonceng header dan toast event baru"
```

---

### Task 3: Live View — outline tile, chip tile tak terlihat, bunyi di TV

**Files:**
- Modify: `frontend/src/features/live/useInView.ts`
- Modify: `frontend/src/features/live/LiveWall.tsx` (`CameraTile` baris 22-203; `LiveWall` render baris ~335-350)
- Modify: `frontend/src/features/live/LiveTvPage.tsx` (toolbar, setelah tombol kecepatan)
- Modify: `frontend/src/app/theme.scss` (akhir file)
- Test: `frontend/src/__tests__/event-alerts.test.tsx`

**Interfaces:**
- Consumes: `useEventAlerts()` (`active`, `nodes`, `muted`, `setMuted`), `sevClass`, `typeKey` (Task 1).
- Produces:
  - `useInView(ref, always = false, rootMargin = PRELOAD_MARGIN): boolean`
  - `CameraTile` prop baru `onVisibleChange?: (visible: boolean) => void`
  - test id `cam-alert-<camId>`, `alert-chips`, `alert-chip-<camId>`, `alert-chip-node`, `live-tv-sound`
  - kelas `lv-alert lv-alert--<sev>`, `lv-alert-chips[--tv]`, `lv-alert-chip lv-alert-chip--<sev>`

- [ ] **Step 1: Tulis tes (gagal)**

Tambahkan import:

```tsx
import LiveViewPage from '../features/live/LiveViewPage'
import LiveTvPage from '../features/live/LiveTvPage'
```

Tambahkan FakeIO (mencatat `rootMargin` agar tes memilih observer yang benar) dan tes:

```tsx
class FakeIO {
  static all: FakeIO[] = []
  cb: IntersectionObserverCallback
  margin: string
  el: Element | null = null
  constructor(cb: IntersectionObserverCallback, opts?: IntersectionObserverInit) {
    this.cb = cb
    this.margin = opts?.rootMargin ?? ''
    FakeIO.all.push(this)
  }
  observe(el: Element) { this.el = el }
  unobserve() {}
  disconnect() {}
  fire(isIntersecting: boolean) {
    this.cb([{ isIntersecting } as IntersectionObserverEntry], this as unknown as IntersectionObserver)
  }
}
// observer "benar-benar terlihat" (tanpa pra-muat) milik tile kamera
const visibleIO = (camId: number) =>
  FakeIO.all.find((o) => o.margin === '0px' && o.el === screen.getByTestId(`cam-tile-${camId}`))!

test('Live View: tile kena event diberi outline severity + label; tile lain tidak', async () => {
  renderWith(<LiveViewPage />, '/live')
  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('11,10'))
  expect(screen.queryByTestId('cam-alert-1')).toBeNull() // riwayat tidak memberi outline
  send(ev(12))
  const ring = screen.getByTestId('cam-alert-1')
  expect(ring).toHaveClass('lv-alert', 'lv-alert--critical')
  expect(ring).toHaveTextContent('Intrusi · Pagar')
  expect(screen.queryByTestId('cam-alert-2')).toBeNull()
  send(ev(13, { camera_id: 2, severity: 'bogus', type: 'crowd', payload: {} }))
  expect(screen.getByTestId('cam-alert-2')).toHaveClass('lv-alert--warning')
  expect(screen.getByTestId('cam-alert-2')).toHaveTextContent('Kerumunan (Crowd)')
})

test('Live View: chip untuk tile kena event yang tidak terlihat; klik menggulir; terlihat lagi → chip hilang', async () => {
  FakeIO.all = []
  vi.stubGlobal('IntersectionObserver', FakeIO)
  const scroll = vi.fn()
  Element.prototype.scrollIntoView = scroll
  renderWith(<LiveViewPage />, '/live')
  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('11,10'))
  act(() => { visibleIO(1).fire(true); visibleIO(2).fire(true) })
  send(ev(12))
  expect(screen.queryByTestId('alert-chips')).toBeNull() // tile terlihat → cukup outline

  act(() => visibleIO(1).fire(false))
  expect(screen.getByTestId('alert-chip-1')).toHaveTextContent('CAM-01')
  expect(screen.getByTestId('alert-chip-1')).toHaveTextContent('Intrusi')
  await userEvent.click(screen.getByTestId('alert-chip-1'))
  expect(scroll).toHaveBeenCalled()

  act(() => visibleIO(1).fire(true))
  expect(screen.queryByTestId('alert-chips')).toBeNull()
})

test('Live View: event system → chip "Node offline", tanpa outline tile', async () => {
  renderWith(<LiveViewPage />, '/live')
  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('11,10'))
  send(ev(30, { type: 'system', camera_id: null, zone_id: null, severity: 'warning', payload: { node: 'vision-1' } }))
  expect(screen.getByTestId('alert-chip-node')).toHaveTextContent('Node vision-1 offline')
  expect(document.querySelector('.lv-alert')).toBeNull()
})

test('mode TV: outline tampil dan toggle bunyi menyimpan mute', async () => {
  renderWith(<LiveTvPage />, '/live/tv')
  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('11,10'))
  send(ev(12))
  expect(screen.getByTestId('cam-alert-1')).toHaveClass('lv-alert--critical')
  await userEvent.click(screen.getByTestId('live-tv-sound'))
  expect(localStorage.getItem(MUTE_KEY)).toBe('1')
})
```

- [ ] **Step 2: Jalankan tes, pastikan gagal**

Run: `rtk npx vitest run src/__tests__/event-alerts.test.tsx`
Expected: FAIL — `Unable to find an element by: [data-testid="cam-alert-1"]`.

- [ ] **Step 3: `useInView` menerima `rootMargin`**

Ganti isi `frontend/src/features/live/useInView.ts`:

```ts
import { useEffect, useState, type RefObject } from 'react'

// Pra-muat ± 1 baris tile di bawah layar: tile sudah menyambung sebelum auto-scroll membawanya masuk.
const PRELOAD_MARGIN = '0px 0px 50% 0px'

/**
 * Elemen dekat viewport? Default dengan margin pra-muat; '0px' = benar-benar terlihat.
 * Tanpa IntersectionObserver (jsdom/browser lama) selalu true.
 */
export function useInView(ref: RefObject<Element | null>, always = false, rootMargin = PRELOAD_MARGIN): boolean {
  const supported = typeof IntersectionObserver !== 'undefined'
  const [inView, setInView] = useState(always || !supported)
  useEffect(() => {
    if (always || !supported || !ref.current) return
    const io = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { rootMargin })
    io.observe(ref.current)
    return () => io.disconnect()
  }, [ref, always, supported, rootMargin])
  return inView
}
```

- [ ] **Step 4: `CameraTile` — outline + laporan visibilitas**

Di `frontend/src/features/live/LiveWall.tsx` tambah import:

```tsx
import { useEventAlerts } from '../notifications/EventAlertsProvider'
import { sevClass, typeKey } from '../notifications/labels'
```

Signature `CameraTile` menjadi:

```tsx
export function CameraTile({ cam, live, big, tv, onClick, onVisibleChange }: {
  cam: Camera; live: LiveInfo | null; big?: boolean; tv?: boolean; onClick?: () => void
  onVisibleChange?: (visible: boolean) => void
}) {
```

Tepat **setelah** baris `const inView = useInView(rootRef, !!big)` (urutan penting: observer pra-muat dibuat lebih dulu — tes lama `liveview.test.tsx` memilih observer pertama milik tile):

```tsx
  // benar-benar terlihat (tanpa pra-muat) → LiveWall menampilkan chip untuk tile kena event yang tersembunyi
  const visible = useInView(rootRef, !!big, '0px')
  const onVisibleRef = useRef(onVisibleChange)
  onVisibleRef.current = onVisibleChange
  useEffect(() => { onVisibleRef.current?.(visible) }, [visible])
  const alert = useEventAlerts().active[cam.id]
```

Sebagai anak **terakhir** `<div ref={rootRef} ...>` (setelah bar nama kamera), tambahkan:

```tsx
      {alert && (
        // key = eventId: event baru me-mount ulang ring → animasi kedip mulai lagi
        <span key={alert.eventId} className={`lv-alert lv-alert--${sevClass(alert.severity)}`}
          data-testid={`cam-alert-${cam.id}`}>
          <span className="lv-alert__label" style={{ fontSize: tv ? 'clamp(11px, 0.8vw, 28px)' : 11 }}>
            {t(typeKey(alert.type))}{alert.zoneName ? ` · ${alert.zoneName}` : ''}
          </span>
        </span>
      )}
```

- [ ] **Step 5: `LiveWall` — state visibilitas + chip**

Di fungsi `LiveWall`, setelah `const [faceNames, setFaceNames] = ...`:

```tsx
  const { active, nodes } = useEventAlerts()
  const [hidden, setHidden] = useState<Record<number, boolean>>({})
  const hiddenAlerts = cams.filter((c) => active[c.id] && hidden[c.id])
  const scrollTo = (id: number) =>
    document.querySelector(`[data-testid="cam-tile-${id}"]`)?.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
```

Pada tile grid, ganti `<CameraTile cam={cam} live={lives[cam.id] ?? null} tv={tv} />` dengan:

```tsx
            <CameraTile cam={cam} live={lives[cam.id] ?? null} tv={tv}
              onVisibleChange={(v) => setHidden((h) => (h[cam.id] === !v ? h : { ...h, [cam.id]: !v }))} />
```

Setelah `</div>` penutup `lv-grid` (sebelum `{debugCam && (`), tambahkan:

```tsx
      {(hiddenAlerts.length > 0 || nodes.length > 0) && (
        <div className={tv ? 'lv-alert-chips lv-alert-chips--tv' : 'lv-alert-chips'} role="status"
          aria-label={t('notif.chips')} data-testid="alert-chips">
          {hiddenAlerts.map((c) => {
            const a = active[c.id]
            const cls = `lv-alert-chip lv-alert-chip--${sevClass(a.severity)}`
            const text = `⚠ ${c.name} — ${t(typeKey(a.type))}`
            // TV kiosk tanpa mouse: chip hanya indikator, auto-scroll tidak diganggu
            return tv ? (
              <span key={c.id} className={cls} data-testid={`alert-chip-${c.id}`}>{text}</span>
            ) : (
              <button key={c.id} type="button" className={cls} data-testid={`alert-chip-${c.id}`}
                onClick={() => scrollTo(c.id)}>{text}</button>
            )
          })}
          {nodes.map((n) => (
            <span key={n.node} className="lv-alert-chip lv-alert-chip--warning" data-testid="alert-chip-node">
              ⚠ {t('notif.nodeOffline').replace('{node}', n.node)}
            </span>
          ))}
        </div>
      )}
```

Tile di modal debugger (`<CameraTile cam={debugCam} ... big />`) **tidak** diberi `onVisibleChange` (tetap tampil outline karena membaca `active`).

- [ ] **Step 6: Toggle bunyi di toolbar TV**

`frontend/src/features/live/LiveTvPage.tsx` — tambah import:

```tsx
import { useEventAlerts } from '../notifications/EventAlertsProvider'
```

Di dalam komponen, setelah `const resumed = useIdle(SCROLL_RESUME_MS)`:

```tsx
  const { muted, setMuted } = useEventAlerts()
```

Di toolbar, setelah blok `{SPEEDS.map(...)}` dan sebelum tombol keluar:

```tsx
          <Toggle id="live-tv-sound" data-testid="live-tv-sound" size="sm" labelText={t('notif.sound')}
            hideLabel toggled={!muted} onToggle={(on) => setMuted(!on)} />
          <span>{t('notif.sound')}</span>
```

- [ ] **Step 7: Gaya (akhir `frontend/src/app/theme.scss`)**

```scss
/* Live View: outline tile kamera kena event (warna = titik severity Events) + chip tile tersembunyi. */
.lv-alert,
.lv-alert-chip {
  --lv-alert-color: #f1c21b;

  &--critical {
    --lv-alert-color: #fa4d56;
  }

  &--info {
    --lv-alert-color: #4589ff;
  }
}

.lv-alert {
  position: absolute;
  inset: 0;
  z-index: 2;
  border: 4px solid var(--lv-alert-color);
  pointer-events: none;
  animation: lv-alert-blink 0.5s step-end 6; // ~3 s kedip lalu menyala tetap
}

.lv-alert__label {
  position: absolute;
  top: 0;
  right: 0;
  max-inline-size: 100%;
  padding: 2px 8px;
  background: var(--lv-alert-color);
  color: #161616;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@keyframes lv-alert-blink {
  50% {
    border-color: transparent;
  }
}

@media (prefers-reduced-motion: reduce) {
  .lv-alert {
    animation: none;
  }
}

.lv-alert-chips {
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 8000;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  max-inline-size: calc(100vw - 32px);
}

.lv-alert-chip {
  padding: 6px 12px;
  border: 0;
  border-inline-start: 4px solid var(--lv-alert-color);
  background: rgba(22, 22, 22, 0.92);
  color: #f4f4f4;
  font: inherit;
  font-size: 13px;
  text-align: start;
  overflow-wrap: anywhere;
}

button.lv-alert-chip {
  cursor: pointer;
}

.lv-alert-chips--tv .lv-alert-chip {
  font-size: clamp(13px, 1vw, 32px);
}
```

- [ ] **Step 8: Jalankan tes Live View (baru + lama)**

Run: `rtk npx vitest run src/__tests__/event-alerts.test.tsx src/__tests__/liveview.test.tsx src/__tests__/live-tv.test.tsx src/__tests__/live-autoscroll.test.tsx`
Expected: PASS semua. Bila tes lama "tile di luar layar ..." gagal karena memilih observer yang salah, perbaiki **tesnya** untuk memilih observer pra-muat secara eksplisit (observer pertama milik tile), jangan mengubah urutan hook.

- [ ] **Step 9: Commit**

```bash
rtk git add frontend/src/features/live frontend/src/app/theme.scss frontend/src/__tests__/event-alerts.test.tsx
rtk git commit -m "feat(live): outline tile kamera kena event, chip tile tersembunyi, bunyi di mode TV"
```

---

### Task 4: Verifikasi penuh, dokumentasi, push

**Files:**
- Modify: `README.md` (bagian `## Live View & Mode TV`, baris ~161, + satu paragraf notifikasi)
- Modify: `ROADMAP.md` (tabel baris AM/EM, baris ~31-32)
- Modify: `CHANGELOG.md` (entri teratas)

- [ ] **Step 1: Suite penuh + lint + build**

Run (dari `frontend/`):

```bash
rtk npx vitest run
rtk npm run lint
rtk npm run build
```

Expected: frontend **≥ 199** tes lulus (182 + 17 baru), lint tanpa error baru dibanding `main`, build exit 0. Backend/vision tidak disentuh — cukup `rtk git diff --stat main -- backend vision` kosong.

Bila `liveview.test.tsx` "tile di luar layar ..." gagal acak (flaky yang sudah tercatat), jalankan ulang file itu sekali dan laporkan hasil keduanya; jangan menyembunyikan.

- [ ] **Step 2: Cek 390 px**

Jalankan `rtk npm run dev`, buka `/dashboard` dan `/live` di viewport 390×844 (Playwright/DevTools), buka panel lonceng; pastikan `document.documentElement.scrollWidth <= 390`. Simpan screenshot ke `docs/evidence/2026-09-29-notif-390.png` bila memungkinkan (backend lokal tidak wajib; panel kosong cukup).

- [ ] **Step 3: Dokumentasi**

`README.md` — di bawah `## Live View & Mode TV` tambahkan paragraf:

```markdown
**Notifikasi event.** Event behavior (intrusion, loitering, running, idle zone, crowd) dan node offline memunculkan
badge di lonceng header (20 event terakhir, klik → detail event), toast 8 detik, dan bunyi pendek (bisa di-mute di
lonceng atau toolbar mode TV; status dibaca & mute disimpan per browser). Di Live View, tile kamera yang kena event
diberi outline warna severity selama 30 detik; bila tile sedang di luar layar muncul chip di kanan bawah. Absensi
tidak memicu notifikasi. Notifikasi OS tidak tersedia karena app diakses lewat `http://` LAN.
```

`ROADMAP.md` — tambah baris setelah `| EM | ...`:

```markdown
| NT | Notifikasi event web UI (lonceng, toast, bunyi) + outline tile Live View | [ ] menunggu deploy + verifikasi user | — | spec `docs/superpowers/specs/2026-09-29-event-notifications-design.md`; frontend saja | — |
```

`CHANGELOG.md` — entri teratas (di atas `### Event wajib bermedia (2026-09-29)`):

```markdown
### Notifikasi event web UI + outline tile Live View (2026-09-29)

- **Konteks:** operator command center perlu tahu event baru tanpa membuka halaman Events; tile kamera yang kena
  event harus menonjol di Live View / mode TV.
- **Perubahan:** `EventAlertsProvider` (satu langganan WS/polling, riwayat vs event baru, anti duplikat),
  lonceng header + panel, toast, bunyi Web Audio (mute per browser), outline severity 30 s di tile, chip untuk tile
  tersembunyi dan node offline, toggle bunyi di toolbar TV. Backend tidak berubah.
- **File:** `frontend/src/features/notifications/*`, `features/live/{LiveWall,LiveTvPage,useInView}.tsx`,
  `app/{AppShell,i18n}.tsx`, `app/theme.scss`, `main.tsx`, `__tests__/event-alerts.test.tsx`.
- **Bukti:** frontend <N> tes lulus, lint, build 0 (isi angka dari Step 1).
- **Dampak:** polling `/events` bertambah satu per tab (5 s); tanpa migrasi.
- **Rollback:** `git revert` merge + build frontend; key localStorage `isentinel_notif_seen` / `isentinel_notif_mute`
  diabaikan kode lama.
```

- [ ] **Step 4: Commit + push (berhenti di sini)**

```bash
rtk git add README.md ROADMAP.md CHANGELOG.md docs/evidence
rtk git commit -m "docs(notifications): README, ROADMAP, CHANGELOG notifikasi event"
rtk git push -u origin feat/event-notifications
```

Deploy, uji lapangan, dan merge dilakukan di sesi perencanaan — **jangan** deploy atau merge.
