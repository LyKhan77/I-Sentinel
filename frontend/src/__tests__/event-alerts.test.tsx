import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import { EventAlertsProvider, asNotifyEvent, useEventAlerts, MUTE_KEY, SEEN_KEY } from '../features/notifications/EventAlertsProvider'
import { beep } from '../features/notifications/beep'
import NotificationBell from '../features/notifications/NotificationBell'
import EventToasts from '../features/notifications/EventToasts'
import LiveViewPage from '../features/live/LiveViewPage'
import LiveTvPage from '../features/live/LiveTvPage'

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
    // riwayat provider: ?since=<00:00 kemarin>&type=...&limit=200
    if (u.includes('/events?') && u.includes('type=')) {
      return history === 'fail' ? { ok: false, status: 500, json: () => Promise.resolve(null) } : ok(history)
    }
    if (u.includes('/events?') && u.includes('since=')) return ok([]) // polling useLiveEvents berikutnya
    if (u.includes('/events?limit=50')) return ok(history === 'fail' ? [] : history) // poll pertama useLiveEvents
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
  // tes chip memasang scrollIntoView; jsdom tidak punya → hapus lagi
  const proto: Partial<Element> = Element.prototype
  delete proto.scrollIntoView
})

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
    if (String(url).includes('type=')) await gate // riwayat tertahan
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

// ---- lonceng header + toast (Task 2) ----
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

test('lonceng: badge 99+, panel kosong, Escape menutup, toggle bunyi', async () => {
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

  for (let id = 100; id < 199; id++) send(ev(id))
  expect(screen.getByTestId('notif-badge')).toHaveTextContent('99') // tepat 99 → tanpa "+"
  expect(screen.getByTestId('notif-badge')).not.toHaveTextContent('+')
  send(ev(199))
  expect(screen.getByTestId('notif-badge')).toHaveTextContent('99+')
})

// 12:00 lokal, `daysAgo` hari lalu
const noon = (daysAgo: number) => {
  const d = new Date()
  d.setHours(12, 0, 0, 0)
  d.setDate(d.getDate() - daysAgo)
  return d.toISOString()
}

test('lonceng: tab Hari ini / Kemarin; event lebih lama tidak tampil; riwayat diminta per jenis sejak kemarin', async () => {
  const fetchMock = stubFetch()
  vi.stubGlobal('fetch', fetchMock)
  history = [ev(11), ev(10, { camera_id: 2, ts_event: noon(1) }), ev(9, { ts_event: noon(3) })]
  renderWith(shell)
  await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('11,10'))
  expect(screen.getByTestId('recent')).not.toHaveTextContent('9') // lusa dibuang walau backend mengirimnya

  const url = fetchMock.mock.calls.map(([u]) => String(u)).find((u) => u.includes('type='))!
  const qs = new URL(url, 'http://x').searchParams
  expect(qs.getAll('type').sort()).toEqual(['crowd', 'idle_zone', 'intrusion', 'loitering', 'running', 'system'])
  expect(qs.get('limit')).toBe('200')
  expect(new Date(qs.get('since')!).getTime()).toBe(new Date(noon(1)).setHours(0, 0, 0, 0))

  await userEvent.click(screen.getByTestId('notif-bell'))
  expect(screen.getByTestId('notif-tab-today')).toHaveTextContent('Hari ini (1)')
  expect(screen.getByTestId('notif-tab-yesterday')).toHaveTextContent('Kemarin (1)')
  expect(screen.getByTestId('notif-item-11')).toBeVisible()
  expect(screen.getByTestId('notif-item-10')).not.toBeVisible()
  expect(screen.queryByTestId('notif-item-9')).toBeNull()
  await userEvent.click(screen.getByTestId('notif-tab-yesterday'))
  expect(screen.getByTestId('notif-item-10')).toBeVisible()
  expect(screen.getByTestId('notif-item-11')).not.toBeVisible()
  expect(screen.getByTestId('notif-item-10')).toHaveTextContent('CAM-02 · Pagar')
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

test('event system reason online: label "pulih", menghapus chip offline node', async () => {
  renderWith(<><LiveViewPage />{shell}</>, '/live')
  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('11,10'))
  send(ev(30, { type: 'system', camera_id: null, zone_id: null, severity: 'warning', payload: { node: 'vision-1', reason: 'lwt' } }))
  expect(screen.getByTestId('alert-chip-node')).toHaveTextContent('Node vision-1 offline')
  send(ev(31, { type: 'system', camera_id: null, zone_id: null, severity: 'info', payload: { node: 'vision-1', reason: 'online' } }))
  expect(screen.queryByTestId('alert-chip-node')).toBeNull()
  expect(screen.getByTestId('toast-31')).toHaveTextContent('Node pulih')
  expect(screen.getByTestId('toast-31')).toHaveTextContent('Node vision-1 pulih')
})

// ---- Live View: outline tile, chip, bunyi TV (Task 3) ----
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

// ---- temuan review independen ----
test('kunjungan pertama: buka lonceng sebelum riwayat selesai tidak menyimpan penanda dibaca palsu', async () => {
  let release: () => void = () => {}
  const gate = new Promise<void>((r) => { release = r })
  const base = stubFetch()
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (String(url).includes('type=')) await gate // riwayat tertahan
    return base(url)
  }))
  renderWith(shell)
  await userEvent.click(await screen.findByTestId('notif-bell'))
  expect(screen.getByTestId('notif-panel')).toHaveTextContent('Belum ada event')
  expect(localStorage.getItem(SEEN_KEY)).toBeNull() // belum ada yang boleh ditandai dibaca
  await act(async () => { release() })
  await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('11,10'))
  expect(localStorage.getItem(SEEN_KEY)).toBe('11')
  expect(screen.queryByTestId('notif-badge')).toBeNull()
})

test('riwayat gagal: event basi dari aliran tidak dihitung belum dibaca di kunjungan pertama', async () => {
  history = 'fail'
  renderWith()
  send(ev(40, { ts_event: new Date(Date.now() - 120_000).toISOString() }))
  send(ev(41))
  await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('41,40'))
  expect(screen.getByTestId('unread')).toHaveTextContent('1') // hanya event 41 yang benar-benar baru
  expect(localStorage.getItem(SEEN_KEY)).toBe('40')
})

test('asNotifyEvent menolak tipe warisan Object.prototype', () => {
  for (const type of ['constructor', 'toString', 'valueOf', 'hasOwnProperty', '__proto__']) {
    expect(asNotifyEvent({ id: 1, event_id: 'e-1', type, ts_event: new Date().toISOString() })).toBeNull()
  }
  expect(asNotifyEvent({ id: 1, event_id: 'e-1', type: 'intrusion' })?.id).toBe(1)
})
