import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { act } from 'react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation, useNavigate, useNavigationType } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import EventsPage from '../features/events/EventsPage'
import type { EventOut } from '../api/events'

const EVENTS: EventOut[] = [
  { id: 1, event_id: 'ev-1', type: 'intrusi', camera_id: 1, zone_id: null, severity: 'critical', ts_event: '2026-02-12T10:00:00Z', payload: { line: 'A' }, clip_path: null, snapshot_path: null },
  { id: 2, event_id: 'ev-2', type: 'loitering', camera_id: 2, zone_id: null, severity: 'warning', ts_event: '2026-02-12T09:30:00Z', payload: null, clip_path: null, snapshot_path: null },
]

function stubFetch(events = EVENTS) {
  return vi.fn(async (url: string) => {
    const u = String(url)
    if (u.includes('/events?')) return { ok: true, status: 200, json: () => Promise.resolve(events) }
    if (u.includes('/zones')) return { ok: true, status: 200, json: () => Promise.resolve([{ id: 7, name: 'Lorong-15', camera_id: 1 }]) }
    if (u.endsWith('/cameras')) {
      return {
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve([
            { id: 1, name: 'CAM-01' },
            { id: 2, name: 'CAM-02' },
          ]),
      }
    }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
}

function renderPage(entry = '/events') {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[entry]}>
        <EventsPage />
      </MemoryRouter>
    </I18nProvider>,
  )
}

// uji ber-fake-timer yang gagal sebelum `useRealTimers` akan meracuni uji berikutnya
beforeEach(() => { vi.useRealTimers() })

test('renders event list with camera names', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()

  // master-detail: type muncul di list + detail panel → pakai getAllByText
  expect((await screen.findAllByText('intrusi')).length).toBeGreaterThanOrEqual(1)
  expect(screen.getAllByText('loitering').length).toBeGreaterThanOrEqual(1)
  expect(screen.getAllByText('CAM-01').length).toBeGreaterThanOrEqual(1)
  expect(screen.getAllByText(/critical/).length).toBeGreaterThanOrEqual(1)
})

test('click list item selects event detail', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()

  const item = (await screen.findAllByTestId('event-item-1'))[0]
  await userEvent.click(item)
  await waitFor(() => expect(screen.getByTestId('event-detail')).toBeInTheDocument())
  expect(screen.getByText('ev-1')).toBeInTheDocument()
  expect(screen.getByTestId('event-item-1')).toHaveAttribute('aria-current', 'true')
  expect(screen.getByTestId('event-item-2')).not.toHaveAttribute('aria-current')
  // payload JSON dihilangkan dari detail (metadata grid menggantikan) — event_id cukup
})

test('poll (5s) appends new event row realtime', async () => {
  vi.useFakeTimers()
  let current = EVENTS
  const fetchMock = vi.fn(async (url: string) => {
    const u = String(url)
    if (u.includes('/events?')) return { ok: true, status: 200, json: () => Promise.resolve(current) }
    if (u.endsWith('/cameras')) {
      return {
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve([
            { id: 1, name: 'CAM-01' },
            { id: 2, name: 'CAM-02' },
          ]),
      }
    }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
  vi.stubGlobal('fetch', fetchMock)
  renderPage()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000) // poll awal
  })
  expect(screen.getAllByText('intrusi').length).toBeGreaterThanOrEqual(1)

  const newRow = { id: 3, event_id: 'ev-3', type: 'maling', camera_id: 1, zone_id: null, severity: 'critical', ts_event: '2026-02-12T10:05:00Z', payload: null, clip_path: null, snapshot_path: null }
  current = [...EVENTS, newRow] // tick poll berikutnya mengambil termasuk ev-3

  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000)
  })
  expect(screen.getAllByText('maling').length).toBeGreaterThanOrEqual(1)
  vi.useRealTimers()
})

test('click list item shows metadata in detail panel', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()

  const item = (await screen.findAllByTestId('event-item-1'))[0]
  await userEvent.click(item)
  await waitFor(() => expect(screen.getByTestId('event-detail')).toBeInTheDocument())
  expect(screen.getByText('ev-1')).toBeInTheDocument()
  expect(screen.getByText('ev-1').closest('[data-testid=event-detail]')).not.toBeNull()
})

test('detail panel shows video element when clip_path present', async () => {
  const withClip: typeof EVENTS = [
    { ...EVENTS[0], clip_path: 'clips/ev-1.mp4', snapshot_path: 'snaps/ev-1.jpg' },
    EVENTS[1],
  ]
  vi.stubGlobal('fetch', stubFetch(withClip))
  renderPage()

  expect(await screen.findByTestId('event-detail')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('event-tab-clip'))
  const video = screen.getByTestId('event-clip') as HTMLVideoElement
  expect(video.tagName).toBe('VIDEO')
  expect(video.src).toContain('/api/v1/media/clips/ev-1.mp4')
  expect(screen.getByTestId('event-download')).toHaveAttribute('href', '/api/v1/media/clips/ev-1.mp4')
})

test('shared incident clip starts at this event offset', async () => {
  const withOffset: typeof EVENTS = [
    { ...EVENTS[0], clip_path: 'clips/inc.mp4', payload: { track_id: 6, clip_offset_s: 12.4 } },
  ]
  vi.stubGlobal('fetch', stubFetch(withOffset))
  renderPage()

  await screen.findByTestId('event-detail')
  await userEvent.click(screen.getByTestId('event-tab-clip'))
  expect((screen.getByTestId('event-clip') as HTMLVideoElement).src).toMatch(/clips\/inc\.mp4#t=12\.4$/)
  expect(screen.getByTestId('event-download')).toHaveAttribute('href', '/api/v1/media/clips/inc.mp4')
})

test('detail panel shows placeholder when clip_path null', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()

  await screen.findByTestId('event-detail')
  await userEvent.click(screen.getByTestId('event-tab-clip'))
  expect(screen.getByTestId('event-clip-placeholder')).toBeInTheDocument()
  expect(screen.queryByTestId('event-clip')).not.toBeInTheDocument()
})

test('fresh event without clip shows recording placeholder and refetches', async () => {
  const fresh: EventOut[] = [{ ...EVENTS[0], ts_event: new Date().toISOString() }]
  const fetchMock = stubFetch(fresh)
  vi.stubGlobal('fetch', fetchMock)
  renderPage()

  await screen.findByTestId('event-detail')
  await userEvent.click(screen.getByTestId('event-tab-clip'))
  expect(screen.getByTestId('event-clip-placeholder')).toHaveTextContent('Clip sedang direkam')
  const before = fetchMock.mock.calls.filter(([u]) => String(u).includes('limit=200')).length
  await waitFor(
    () => expect(fetchMock.mock.calls.filter(([u]) => String(u).includes('limit=200')).length)
      .toBeGreaterThan(before),
    { timeout: 7000 },
  )
}, 10000)

test('old event without clip shows unavailable placeholder', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()

  await screen.findByTestId('event-detail')
  await userEvent.click(screen.getByTestId('event-tab-clip'))
  expect(screen.getByTestId('event-clip-placeholder')).toHaveTextContent('Clip belum tersedia')
})

test('search narrows list by camera name and payload, count follows', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()
  await screen.findByTestId('event-item-1')
  expect(screen.getByTestId('event-count')).toHaveTextContent('2 event')

  const search = screen.getByLabelText('Cari')

  await userEvent.type(search, 'CAM-02') // nama kamera, bukan tipe
  await waitFor(() => expect(screen.queryByTestId('event-item-1')).not.toBeInTheDocument())
  expect(screen.getByTestId('event-item-2')).toBeInTheDocument()
  expect(screen.getByTestId('event-count')).toHaveTextContent('1 event')
  // pilihan ikut list ter-filter: ev-2 jadi event terpilih
  expect(screen.getByTestId('event-item-2')).toHaveAttribute('aria-current', 'true')

  await userEvent.clear(search)
  await userEvent.type(search, 'line') // payload ev-1 = { line: 'A' }
  await waitFor(() => expect(screen.queryByTestId('event-item-2')).not.toBeInTheDocument())
  expect(screen.getByTestId('event-item-1')).toBeInTheDocument()

  await userEvent.clear(search)
  await userEvent.type(search, 'zzz')
  await waitFor(() => expect(screen.getByText('Tidak ada event yang cocok')).toBeInTheDocument())
  expect(screen.getByTestId('event-count')).toHaveTextContent('0 event')
})

test('range selector sends since for a finite range, plain limit for all', async () => {
  const fetchMock = stubFetch()
  vi.stubGlobal('fetch', fetchMock)
  renderPage()
  await screen.findByTestId('event-item-1')

  const listQuery = () =>
    fetchMock.mock.calls
      .map(([url]) => String(url))
      .filter((url) => url.includes('/events?') && url.includes('limit=200'))
  expect(listQuery()[0]).not.toContain('since=')

  await userEvent.selectOptions(screen.getByLabelText('Rentang'), '24h')
  await waitFor(() => expect(listQuery().some((url) => /since=\d{4}-\d{2}-\d{2}/.test(url))).toBe(true))

  const before = listQuery().length
  await userEvent.selectOptions(screen.getByLabelText('Rentang'), 'all')
  await waitFor(() => expect(listQuery().length).toBeGreaterThan(before))
  expect(listQuery()[listQuery().length - 1]).not.toContain('since=')
})

test('detail event attendance menampilkan crop beranotasi dari payload', async () => {
  const events: EventOut[] = [
    { id: 1, event_id: 'ev-1', type: 'attendance', camera_id: 1, zone_id: 2, severity: 'info',
      ts_event: '2026-09-21T07:00:00+07:00', clip_path: 'clips/x.mp4',
      snapshot_path: 'snapshots/x.jpg',
      payload: { crop_path: 'crops/x.jpg', face_quality: 0.9 } },
  ]
  vi.stubGlobal('fetch', stubFetch(events))
  renderPage()

  const item = (await screen.findAllByTestId('event-item-1'))[0]
  await userEvent.click(item)
  expect(await screen.findByTestId('event-detail')).toBeInTheDocument()
  // metadata grid tampil default (di bawah media), tanpa perlu pilih tab
  expect(screen.getByText('ev-1')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('event-tab-crop'))
  expect(await screen.findByTestId('event-crop')).toBeInTheDocument()
  const img = screen.getByTestId('event-crop').querySelector('img')
  expect(img?.getAttribute('src')).toBe('/api/v1/media/crops/x.jpg')
})

// --- R4: tabstrip detail (mockup 03) ---------------------------------------

const CLIP_EVENT: EventOut[] = [
  { id: 1, event_id: 'ev-1', type: 'intrusion', camera_id: 1, zone_id: 2, severity: 'warning',
    ts_event: '2026-09-21T07:00:00+07:00', clip_path: 'clips/x.mp4', snapshot_path: 'snapshots/x.jpg',
    payload: null },
]

const ATT_EVENT: EventOut[] = [
  { id: 1, event_id: 'ev-1', type: 'attendance', camera_id: 1, zone_id: 2, severity: 'info',
    ts_event: '2026-09-21T07:00:00+07:00', clip_path: 'clips/x.mp4', snapshot_path: 'snapshots/x.jpg',
    payload: { crop_path: 'crops/x.jpg' } },
]

test('tabstrip: default Snapshot, metadata (Details) tampil di bawah media', async () => {
  vi.stubGlobal('fetch', stubFetch(ATT_EVENT))
  renderPage()

  expect(await screen.findByTestId('event-detail')).toBeInTheDocument()
  expect(screen.getByTestId('event-tab-snapshot')).toHaveClass('on')
  expect(screen.queryByTestId('event-tab-detail')).not.toBeInTheDocument()
  // media default = snapshot; clip & crop belum dirender
  expect(screen.getByTestId('event-snapshot')).toBeInTheDocument()
  expect(screen.queryByTestId('event-clip')).not.toBeInTheDocument()
  expect(screen.queryByTestId('event-crop')).not.toBeInTheDocument()
  // metadata grid ikut tampil walau tab media aktif
  expect(screen.getByText('ev-1')).toBeInTheDocument()
})

test('metadata tetap tampil saat pindah tab media', async () => {
  vi.stubGlobal('fetch', stubFetch(ATT_EVENT))
  renderPage()
  await screen.findByTestId('event-detail')

  await userEvent.click(screen.getByTestId('event-tab-snapshot'))
  expect(screen.getByText('ev-1')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('event-tab-crop'))
  expect(screen.getByText('ev-1')).toBeInTheDocument()
})

test('tabstrip klik Clip → video, klik Snapshot → img snapshot', async () => {
  vi.stubGlobal('fetch', stubFetch(CLIP_EVENT))
  renderPage()
  await screen.findByTestId('event-detail')

  await userEvent.click(screen.getByTestId('event-tab-clip'))
  expect(screen.getByTestId('event-clip')).toBeInTheDocument()
  expect(screen.queryByTestId('event-snapshot')).not.toBeInTheDocument()
  expect(screen.getByTestId('event-tab-clip')).toHaveClass('on')
  expect(screen.getByTestId('event-tab-snapshot')).not.toHaveClass('on')

  await userEvent.click(screen.getByTestId('event-tab-snapshot'))
  const snap = screen.getByTestId('event-snapshot') as HTMLImageElement
  expect(snap.getAttribute('src')).toBe('/api/v1/media/snapshots/x.jpg')
  expect(screen.queryByTestId('event-clip')).not.toBeInTheDocument()
})

test('tab Face crop disabled bila event tanpa crop_path', async () => {
  const noCrop: EventOut[] = [{ ...ATT_EVENT[0], payload: { face_quality: 0.4 } }]
  vi.stubGlobal('fetch', stubFetch(noCrop))
  renderPage()
  await screen.findByTestId('event-detail')

  expect(screen.getByTestId('event-tab-crop')).toBeDisabled()
})

test('tab Face crop tidak ada untuk event non-attendance', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()
  await screen.findByTestId('event-detail')

  expect(screen.getByTestId('event-tab-snapshot')).toBeInTheDocument()
  expect(screen.getByTestId('event-tab-clip')).toBeInTheDocument()
  expect(screen.queryByTestId('event-tab-crop')).not.toBeInTheDocument()
})

test('ganti event → tab kembali ke Snapshot', async () => {
  const two: EventOut[] = [
    CLIP_EVENT[0],
    { id: 2, event_id: 'ev-2', type: 'intrusion', camera_id: 1, zone_id: null, severity: 'warning',
      ts_event: '2026-09-21T06:00:00+07:00', payload: null, clip_path: 'clips/y.mp4', snapshot_path: null },
  ]
  vi.stubGlobal('fetch', stubFetch(two))
  renderPage()
  await screen.findByTestId('event-detail')

  await userEvent.click(screen.getByTestId('event-tab-clip'))
  expect(screen.getByTestId('event-tab-clip')).toHaveClass('on')

  await userEvent.click(screen.getAllByTestId('event-item-2')[0])
  await waitFor(() => expect(screen.getByTestId('event-tab-snapshot')).toHaveClass('on'))
  expect(screen.queryByTestId('event-clip')).not.toBeInTheDocument()
})

test('detail event attendance menampilkan hasil pencocokan wajah', async () => {
  const att: EventOut[] = [{ id: 3, event_id: 'ev-3', type: 'attendance', camera_id: 1, zone_id: 9, severity: 'info',
    ts_event: '2026-09-23T02:00:00Z', payload: { match_reason: 'no_match', employee_id: null, crop_path: 'crops/x.jpg' },
    clip_path: null, snapshot_path: null }]
  vi.stubGlobal('fetch', stubFetch(att))
  renderPage()
  expect(await screen.findByTestId('event-face-match')).toHaveTextContent('Tidak dikenal')
})

test('detail event attendance cooldown menampilkan nama + keterangan', async () => {
  const att: EventOut[] = [{ id: 4, event_id: 'ev-4', type: 'attendance', camera_id: 1, zone_id: 9, severity: 'info',
    ts_event: '2026-09-23T02:00:00Z', payload: { match_reason: 'cooldown', employee_id: 1, employee_name: 'Budi' },
    clip_path: null, snapshot_path: null }]
  vi.stubGlobal('fetch', stubFetch(att))
  renderPage()
  expect(await screen.findByTestId('event-face-match')).toHaveTextContent('Budi · sudah tercatat (cooldown)')
})

test('detail event attendance entry kedua hari yang sama menampilkan keterangan', async () => {
  const att: EventOut[] = [{ id: 5, event_id: 'ev-5', type: 'attendance', camera_id: 1, zone_id: 9, severity: 'info',
    ts_event: '2026-09-23T02:00:00Z', payload: { match_reason: 'already_in', employee_id: 1, employee_name: 'Budi' },
    clip_path: null, snapshot_path: null }]
  vi.stubGlobal('fetch', stubFetch(att))
  renderPage()
  expect(await screen.findByTestId('event-face-match')).toHaveTextContent('Budi · sudah absen masuk hari ini')
})

test('event attendance tanpa tab Clip (attendance tidak merekam klip)', async () => {
  const att: EventOut[] = [{ id: 6, event_id: 'ev-6', type: 'attendance', camera_id: 1, zone_id: 9, severity: 'info',
    ts_event: '2026-09-23T02:00:00Z', payload: { match_reason: 'matched', employee_name: 'Budi', crop_path: 'crops/x.jpg' },
    clip_path: null, snapshot_path: 'snapshots/x.jpg' }]
  vi.stubGlobal('fetch', stubFetch(att))
  renderPage()
  await screen.findByTestId('event-detail')

  expect(screen.getByTestId('event-tab-snapshot')).toBeInTheDocument()
  expect(screen.getByTestId('event-tab-crop')).toBeInTheDocument()
  expect(screen.queryByTestId('event-tab-clip')).not.toBeInTheDocument()
})

test('?event=<id> opens that event in the detail panel', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage('/events?event=2')
  await screen.findByTestId('event-detail')
  expect(screen.getByTestId('event-detail')).toHaveTextContent('loitering')
})

// --- Item A: status alert Telegram realtime -------------------------------

class FakeWS {
  onmessage: ((ev: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  constructor(_url: string) {}
  close() {}
  send() {}
  addEventListener() {}
  removeEventListener() {}
}

function stubFetchWithAlerts(events: EventOut[], alerts: Record<string, string>) {
  return vi.fn(async (url: string) => {
    const u = String(url)
    if (u.includes('/alerts/by-events')) return { ok: true, status: 200, json: () => Promise.resolve(alerts) }
    if (u.includes('/events?')) return { ok: true, status: 200, json: () => Promise.resolve(events) }
    if (u.includes('/zones')) return { ok: true, status: 200, json: () => Promise.resolve([]) }
    if (u.endsWith('/cameras')) {
      return { ok: true, status: 200, json: () => Promise.resolve([{ id: 1, name: 'CAM-01' }, { id: 2, name: 'CAM-02' }]) }
    }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
}

test('alert WS frame updates status chip live tanpa reload', async () => {
  const handlers: FakeWS[] = []
  class Capturing extends FakeWS {
    constructor(url: string) { super(url); handlers.push(this) }
  }
  vi.stubGlobal('WebSocket', Capturing as unknown as typeof WebSocket)
  vi.stubGlobal('fetch', stubFetchWithAlerts(EVENTS, { 'ev-1': 'queued' }))
  renderPage()

  await screen.findByTestId('event-item-1')
  expect((await screen.findAllByText('MENGIRIM…')).length).toBeGreaterThan(0)

  await act(async () => {
    handlers[0].onmessage?.({ data: JSON.stringify({ kind: 'alert', event_id: 1, status: 'sent' }) })
  })

  expect((await screen.findAllByText('TELEGRAM TERKIRIM')).length).toBeGreaterThan(0)
  expect(screen.queryByText('MENGIRIM…')).not.toBeInTheDocument()
})

test('alert WS frame dengan event_id atau status tak dikenal diabaikan', async () => {
  const handlers: FakeWS[] = []
  class Capturing extends FakeWS {
    constructor(url: string) { super(url); handlers.push(this) }
  }
  vi.stubGlobal('WebSocket', Capturing as unknown as typeof WebSocket)
  vi.stubGlobal('fetch', stubFetchWithAlerts(EVENTS, { 'ev-1': 'queued' }))
  renderPage()

  await screen.findByTestId('event-item-1')
  expect((await screen.findAllByText('MENGIRIM…')).length).toBeGreaterThan(0)

  await act(async () => {
    handlers[0].onmessage?.({ data: JSON.stringify({ kind: 'alert', event_id: 999, status: 'sent' }) })
  })
  await act(async () => {
    handlers[0].onmessage?.({ data: JSON.stringify({ kind: 'alert', event_id: 1, status: 'bogus' }) })
  })

  // tak berubah: status ev-1 masih queued
  expect((await screen.findAllByText('MENGIRIM…')).length).toBeGreaterThan(0)
  expect(screen.queryByText('TELEGRAM TERKIRIM')).not.toBeInTheDocument()
})

test('fallback polling: status queued dicek ulang tiap 10s, berhenti setelah resolve', async () => {
  vi.useFakeTimers()
  let alerts: Record<string, string> = { 'ev-1': 'queued' }
  const fetchMock = vi.fn(async (url: string) => {
    const u = String(url)
    if (u.includes('/alerts/by-events')) return { ok: true, status: 200, json: () => Promise.resolve(alerts) }
    if (u.includes('/events?')) return { ok: true, status: 200, json: () => Promise.resolve(EVENTS) }
    if (u.includes('/zones')) return { ok: true, status: 200, json: () => Promise.resolve([]) }
    if (u.endsWith('/cameras')) {
      return { ok: true, status: 200, json: () => Promise.resolve([{ id: 1, name: 'CAM-01' }, { id: 2, name: 'CAM-02' }]) }
    }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
  vi.stubGlobal('fetch', fetchMock)
  renderPage()

  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
  expect(screen.getAllByText('MENGIRIM…').length).toBeGreaterThan(0)

  const byEventsCalls = () => fetchMock.mock.calls.filter(([u]) => String(u).includes('/alerts/by-events')).length
  const before = byEventsCalls()

  alerts = { 'ev-1': 'sent' } // server sudah menyelesaikan kirim, WS dianggap mati (tidak ada frame)
  await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
  expect(byEventsCalls()).toBeGreaterThan(before)
  expect(screen.queryAllByText('MENGIRIM…')).toHaveLength(0)
  expect(screen.getAllByText('TELEGRAM TERKIRIM').length).toBeGreaterThan(0)

  const afterResolved = byEventsCalls()
  await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
  expect(byEventsCalls()).toBe(afterResolved) // tidak ada lagi yang queued → interval berhenti

  vi.useRealTimers()
})

test('inbox shows zone names; deleted zone falls back to #id', async () => {
  const withZones: EventOut[] = [
    { ...EVENTS[0], zone_id: 7 },
    { ...EVENTS[1], zone_id: 99 },
  ]
  vi.stubGlobal('fetch', stubFetch(withZones))
  renderPage()
  expect((await screen.findAllByText(/Lorong-15/)).length).toBeGreaterThanOrEqual(1)
  expect(screen.getByText(/#99/)).toBeInTheDocument()
  expect(screen.getByTestId('event-detail')).toHaveTextContent('Lorong-15')
})

// --- Filter server-side: Semua, reset, penanda 200+ -----------------------

function listCalls(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls
    .map(([u]) => String(u))
    .filter((u) => u.includes('/events?') && u.includes('limit=200'))
}

/** Tunggu sampai request daftar ke-(before+1) datang, lalu cek URL terakhir. */
async function waitNewListUrl(fetchMock: ReturnType<typeof vi.fn>, before: number, pred: (u: string) => boolean) {
  await waitFor(() => {
    const calls = listCalls(fetchMock)
    expect(calls.length).toBeGreaterThan(before)
    expect(pred(calls[calls.length - 1])).toBe(true)
  })
}

// Carbon Dropdown menggulir item tersorot; jsdom tidak punya scrollIntoView
function stubScrollIntoView() {
  Element.prototype.scrollIntoView = vi.fn()
}

test('type dropdown sends type to the API and Semua restores the full list', async () => {
  stubScrollIntoView()
  const fetchMock = stubFetch()
  vi.stubGlobal('fetch', fetchMock)
  renderPage()
  await screen.findByTestId('event-item-1')

  const beforePick = listCalls(fetchMock).length
  await userEvent.click(screen.getByRole('combobox', { name: 'Tipe' }))
  await userEvent.click(await screen.findByRole('option', { name: 'Sistem' }))
  await waitNewListUrl(fetchMock, beforePick, (u) => u.includes('type=system'))

  const beforeAll = listCalls(fetchMock).length
  await userEvent.click(screen.getByRole('combobox', { name: 'Tipe' }))
  await userEvent.click(await screen.findByRole('option', { name: 'Semua' }))
  await waitNewListUrl(fetchMock, beforeAll, (u) => !u.includes('type='))
})

test('camera and severity dropdowns also restore with Semua', async () => {
  stubScrollIntoView()
  const fetchMock = stubFetch()
  vi.stubGlobal('fetch', fetchMock)
  renderPage()
  await screen.findByTestId('event-item-1')

  let before = listCalls(fetchMock).length
  await userEvent.click(screen.getByRole('combobox', { name: 'Kamera' }))
  await userEvent.click(await screen.findByRole('option', { name: 'CAM-01' }))
  await waitNewListUrl(fetchMock, before, (u) => u.includes('camera_id=1'))

  before = listCalls(fetchMock).length
  await userEvent.click(screen.getByRole('combobox', { name: 'Kamera' }))
  await userEvent.click(await screen.findByRole('option', { name: 'Semua' }))
  await waitNewListUrl(fetchMock, before, (u) => !u.includes('camera_id='))

  before = listCalls(fetchMock).length
  await userEvent.click(screen.getByRole('combobox', { name: 'Severity' }))
  await userEvent.click(await screen.findByRole('option', { name: 'critical' }))
  await waitNewListUrl(fetchMock, before, (u) => u.includes('severity=critical'))

  before = listCalls(fetchMock).length
  await userEvent.click(screen.getByRole('combobox', { name: 'Severity' }))
  await userEvent.click(await screen.findByRole('option', { name: 'Semua' }))
  await waitNewListUrl(fetchMock, before, (u) => !u.includes('severity='))
})

test('severity and camera filters are sent to the API', async () => {
  stubScrollIntoView()
  const fetchMock = stubFetch()
  vi.stubGlobal('fetch', fetchMock)
  renderPage()
  await screen.findByTestId('event-item-1')

  let before = listCalls(fetchMock).length
  await userEvent.click(screen.getByRole('combobox', { name: 'Kamera' }))
  await userEvent.click(await screen.findByRole('option', { name: 'CAM-01' }))
  await waitNewListUrl(fetchMock, before, (u) => u.includes('camera_id=1'))

  before = listCalls(fetchMock).length
  await userEvent.click(screen.getByRole('combobox', { name: 'Severity' }))
  await userEvent.click(await screen.findByRole('option', { name: 'critical' }))
  await waitNewListUrl(fetchMock, before, (u) => u.includes('severity=critical') && u.includes('camera_id=1'))
})

test('type options are static, localized and independent of loaded events', async () => {
  stubScrollIntoView()
  vi.stubGlobal('fetch', stubFetch()) // fixture bertipe mentah 'intrusi' (bukan tipe ingest)
  renderPage()
  await screen.findByTestId('event-item-1')

  await userEvent.click(screen.getByRole('combobox', { name: 'Tipe' }))
  expect(await screen.findByRole('option', { name: 'Sistem' })).toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'Absensi' })).toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'Deteksi orang (debug)' })).toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'Intrusi' })).toBeInTheDocument()
})

test('reset button is hidden by default and clears every filter, range and search', async () => {
  stubScrollIntoView()
  const fetchMock = stubFetch()
  vi.stubGlobal('fetch', fetchMock)
  renderPage()
  await screen.findByTestId('event-item-1')
  expect(screen.queryByTestId('filter-reset')).not.toBeInTheDocument()

  await userEvent.click(screen.getByRole('combobox', { name: 'Tipe' }))
  await userEvent.click(await screen.findByRole('option', { name: 'Sistem' }))
  await userEvent.selectOptions(screen.getByLabelText('Rentang'), '24h')
  await userEvent.type(screen.getByLabelText('Cari'), 'abc')
  expect(await screen.findByTestId('filter-reset')).toBeInTheDocument()

  const before = listCalls(fetchMock).length
  await userEvent.click(screen.getByTestId('filter-reset'))
  await waitNewListUrl(fetchMock, before, (u) => !u.includes('type=') && !u.includes('since='))

  expect(screen.queryByTestId('filter-reset')).not.toBeInTheDocument()
  expect(screen.getByLabelText('Cari')).toHaveValue('')
  expect(screen.getByLabelText('Rentang')).toHaveValue('all')
  expect(screen.getByRole('combobox', { name: 'Tipe' })).toHaveTextContent('Semua')
})

test('full page shows N+ and the limit hint', async () => {
  const many: EventOut[] = Array.from({ length: 200 }, (_, i) => ({
    ...EVENTS[0], id: i + 1, event_id: `ev-${i + 1}`,
  }))
  vi.stubGlobal('fetch', stubFetch(many))
  renderPage()
  await screen.findByTestId('event-limit-hint')
  expect(screen.getByTestId('event-count')).toHaveTextContent('200+')
})

test('short page shows no limit hint and no plus', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()
  await screen.findByTestId('event-item-1')
  expect(screen.queryByTestId('event-limit-hint')).not.toBeInTheDocument()
  expect(screen.getByTestId('event-count')).toHaveTextContent('2 event')
  expect(screen.getByTestId('event-count')).not.toHaveTextContent('+')
})

test('live event that does not match the active filter is not prepended', async () => {
  stubScrollIntoView()
  vi.useFakeTimers()
  let current = EVENTS
  const fetchMock = vi.fn(async (url: string) => {
    const u = String(url)
    if (u.includes('/events?')) return { ok: true, status: 200, json: () => Promise.resolve(current) }
    if (u.endsWith('/cameras')) {
      return { ok: true, status: 200, json: () => Promise.resolve([{ id: 1, name: 'CAM-01' }, { id: 2, name: 'CAM-02' }]) }
    }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
  vi.stubGlobal('fetch', fetchMock)
  const { container } = renderPage()
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })

  // downshift/Carbon menjadwalkan timer saat membuka menu → pakai fireEvent, bukan userEvent
  const before = listCalls(fetchMock).length
  fireEvent.click(container.querySelector('#filter-severity .cds--list-box__field')!)
  fireEvent.click(screen.getByRole('option', { name: 'critical' }))
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
  expect(listCalls(fetchMock).length).toBeGreaterThan(before)
  expect(listCalls(fetchMock).at(-1)).toContain('severity=critical')

  // tick poll 5s berikutnya mengirim event warning yang tak cocok filter
  const warn = { ...EVENTS[0], id: 9, event_id: 'ev-9', type: 'maling', severity: 'warning' }
  current = [...EVENTS, warn]
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(screen.queryByTestId('event-item-9')).not.toBeInTheDocument()

  const crit = { ...EVENTS[0], id: 10, event_id: 'ev-10', type: 'penyusup', severity: 'critical' }
  current = [...current, crit]
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(screen.getAllByTestId('event-item-10')).toHaveLength(1)

  vi.useRealTimers()
})

test('a stale response does not overwrite a newer one', async () => {
  stubScrollIntoView()
  let releaseFirst: ((rows: EventOut[]) => void) | null = null
  let call = 0
  const fetchMock = vi.fn(async (url: string) => {
    const u = String(url)
    if (u.includes('/events?')) {
      if (!u.includes('limit=200')) return { ok: true, status: 200, json: () => Promise.resolve([]) }
      call += 1
      if (call === 1) {
        const rows = await new Promise<EventOut[]>((res) => { releaseFirst = res })
        return { ok: true, status: 200, json: () => Promise.resolve(rows) }
      }
      return { ok: true, status: 200, json: () => Promise.resolve([EVENTS[1]]) }
    }
    if (u.includes('/zones')) return { ok: true, status: 200, json: () => Promise.resolve([]) }
    if (u.endsWith('/cameras')) {
      return { ok: true, status: 200, json: () => Promise.resolve([{ id: 1, name: 'CAM-01' }, { id: 2, name: 'CAM-02' }]) }
    }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
  vi.stubGlobal('fetch', fetchMock)
  renderPage()

  await userEvent.click(screen.getByRole('combobox', { name: 'Tipe' }))
  await userEvent.click(await screen.findByRole('option', { name: 'Sistem' }))
  expect(await screen.findByTestId('event-item-2')).toBeInTheDocument()

  await act(async () => { releaseFirst?.([EVENTS[0]]) })
  await waitFor(() => expect(call).toBeGreaterThanOrEqual(2))
  expect(screen.queryByTestId('event-item-1')).not.toBeInTheDocument()
  expect(screen.getByTestId('event-item-2')).toBeInTheDocument()
})

// --- Integrasi event system: panel Bukti menggantikan media -----------------

const SYS_HEALTH: EventOut = {
  id: 7, event_id: 'ev-sys-1', type: 'system', camera_id: 1, zone_id: null, severity: 'warning',
  ts_event: new Date(Date.now() - 5 * 60_000).toISOString(), payload: { kind: 'health', rule: 'node_cpu', target: 'node:1', label: 'Server',
    value: 91.5, threshold: 90, unit: '%', duration_min: 5, state: 'firing' },
  clip_path: null, snapshot_path: null, node_id: 1,
}
const SYS_NODE: EventOut = {
  id: 8, event_id: 'ev-sys-2', type: 'system', camera_id: null, zone_id: null, severity: 'warning',
  ts_event: new Date(Date.now() - 10 * 60_000).toISOString(), payload: { node: 'edge-1', reason: 'timeout' },
  clip_path: null, snapshot_path: null, node_id: 1,
}

function stubSystemFetch(rows: EventOut[]) {
  return vi.fn(async (url: string) => {
    const u = String(url)
    if (u.includes('/monitoring/history')) {
      // server nyata mengembalikan jendela yang diminta → stub menggemakan from/to
      const q = new URLSearchParams(u.slice(u.indexOf('?') + 1))
      const from = q.get('from') ?? ''
      const to = q.get('to') ?? ''
      const mid = new Date((Date.parse(from) + Date.parse(to)) / 2).toISOString()
      return { ok: true, status: 200, json: () => Promise.resolve({ range: 'custom', bucket_s: 60, from, to,
        nodes: [{ id: 1, name: 'server', cameras: [], offline: [],
          series: { cpu_pct: [{ t: mid, avg: 91 }], ram_pct: [], ms_avg: [], ms_max: [],
            infer_fps: [], mqtt_backlog: [], gpus: {} } }] }) }
    }
    if (u.includes('/events?')) return { ok: true, status: 200, json: () => Promise.resolve(rows) }
    if (u.includes('/zones')) return { ok: true, status: 200, json: () => Promise.resolve([]) }
    if (u.endsWith('/cameras')) return { ok: true, status: 200, json: () => Promise.resolve([{ id: 1, name: 'CAM-01' }]) }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
}

test('event system menyembunyikan tab media dan menampilkan panel Bukti', async () => {
  vi.stubGlobal('fetch', stubSystemFetch([SYS_HEALTH, EVENTS[0]]))
  renderPage()

  const item = await screen.findByTestId('event-item-7')
  await userEvent.click(item)
  await waitFor(() => expect(screen.getByTestId('event-evidence')).toBeInTheDocument())
  expect(screen.queryByTestId('event-tab-snapshot')).not.toBeInTheDocument()
  expect(screen.queryByTestId('event-tab-clip')).not.toBeInTheDocument()
  expect(screen.queryByTestId('event-tab-crop')).not.toBeInTheDocument()
  // bukti health: fakta + grafik + marker waktu
  expect(await screen.findByTestId('lc-line-cpu_pct')).toBeInTheDocument()
  expect(screen.getAllByTestId('lc-marker')).toHaveLength(1)
})

test('event system tidak polling klip dan tidak menampilkan teks rekaman', async () => {
  vi.useFakeTimers()
  const rows = [{ ...SYS_HEALTH, ts_event: new Date().toISOString() }]
  const fetchMock = stubSystemFetch(rows)
  vi.stubGlobal('fetch', fetchMock)
  renderPage()
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })

  const before = listCalls(fetchMock).length
  await act(async () => { await vi.advanceTimersByTimeAsync(6000) })
  expect(screen.queryByText('Clip sedang direkam')).not.toBeInTheDocument()
  expect(listCalls(fetchMock).length).toBe(before)
  vi.useRealTimers()
})

test('baris event system memakai judul dan lokasi manusiawi, bukan teks mentah', async () => {
  vi.stubGlobal('fetch', stubSystemFetch([SYS_NODE, EVENTS[0]]))
  renderPage()

  const row = await screen.findByTestId('event-item-8')
  expect(row).toHaveTextContent('Node offline')
  expect(row).toHaveTextContent('Node edge-1 offline')
  expect(row).not.toHaveTextContent('cam null')
})

test('detail event system menyembunyikan meta Kamera dan Zona', async () => {
  vi.stubGlobal('fetch', stubSystemFetch([SYS_HEALTH, EVENTS[0]]))
  renderPage()

  await userEvent.click(await screen.findByTestId('event-item-7'))
  const detail = await screen.findByTestId('event-detail')
  await waitFor(() => expect(detail).toHaveTextContent('CPU node tinggi'))
  expect(detail).not.toHaveTextContent('Kamera')
  expect(detail).not.toHaveTextContent('Zona')
})

test('pencarian menemukan event system lewat nama node', async () => {
  vi.stubGlobal('fetch', stubSystemFetch([SYS_NODE, EVENTS[0]]))
  renderPage()
  await screen.findByTestId('event-item-8')

  await userEvent.type(screen.getByLabelText('Cari'), 'edge-1')
  await waitFor(() => expect(screen.queryByTestId('event-item-1')).not.toBeInTheDocument())
  expect(screen.getByTestId('event-item-8')).toBeInTheDocument()
})

test('event non-system tetap memakai tab media (regresi)', async () => {
  const clip: EventOut[] = [{ ...EVENTS[0], clip_path: 'clips/x.mp4', snapshot_path: 'snapshots/x.jpg' }]
  vi.stubGlobal('fetch', stubSystemFetch(clip))
  renderPage()

  await screen.findByTestId('event-detail')
  expect(screen.getByTestId('event-tab-snapshot')).toBeInTheDocument()
  expect(screen.getByTestId('event-tab-clip')).toBeInTheDocument()
  expect(screen.queryByTestId('event-evidence')).not.toBeInTheDocument()
})

test('changing a filter refetches the event list only, not cameras or zones', async () => {
  stubScrollIntoView()
  const fetchMock = stubFetch()
  vi.stubGlobal('fetch', fetchMock)
  renderPage()
  await screen.findByTestId('event-item-1')

  const count = (needle: string) => fetchMock.mock.calls.filter(([u]) => String(u).includes(needle)).length
  const cams0 = count('/cameras')
  const zones0 = count('/zones')
  expect(cams0).toBeGreaterThan(0)

  const before = listCalls(fetchMock).length
  await userEvent.click(screen.getByRole('combobox', { name: 'Tipe' }))
  await userEvent.click(await screen.findByRole('option', { name: 'Sistem' }))
  await waitNewListUrl(fetchMock, before, (u) => u.includes('type=system'))

  expect(count('/cameras')).toBe(cams0)
  expect(count('/zones')).toBe(zones0)
})

// --- Deep link ?event=<id>: URL sumber kebenaran pemilihan -------------------

const BY_ID_RE = /\/events\/(\d+)$/

function stubDeeplinkFetch(
  events: EventOut[],
  byId: (id: number) => { status: number; body?: EventOut | null } = () => ({ status: 404 }),
) {
  return vi.fn(async (url: string) => {
    const u = String(url)
    const m = BY_ID_RE.exec(u) // cabang by-id SEBELUM cabang umum (jebakan prompt §7)
    if (m) {
      const res = byId(Number(m[1]))
      return { ok: res.status === 200, status: res.status, json: () => Promise.resolve(res.body ?? null) }
    }
    if (u.includes('/alerts/by-events')) return { ok: true, status: 200, json: () => Promise.resolve({}) }
    if (u.includes('/events?')) return { ok: true, status: 200, json: () => Promise.resolve(events) }
    if (u.includes('/zones')) return { ok: true, status: 200, json: () => Promise.resolve([]) }
    if (u.endsWith('/cameras')) {
      return { ok: true, status: 200, json: () => Promise.resolve([{ id: 1, name: 'CAM-01' }, { id: 2, name: 'CAM-02' }]) }
    }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
}

const byIdCalls = (fetchMock: ReturnType<typeof vi.fn>) =>
  fetchMock.mock.calls.filter(([u]) => BY_ID_RE.test(String(u))).length

// probe kecil: lokasi + navigasi dari luar halaman (peran lonceng/toast, plan Task 2)
function DeeplinkProbe() {
  const loc = useLocation()
  const nav = useNavigate()
  const navType = useNavigationType()
  return (
    <>
      <span data-testid="loc">{loc.pathname + loc.search}</span>
      <span data-testid="nav-type">{navType}</span>
      <button data-testid="nav-btn" onClick={() => nav('/events?event=2')}>go</button>
    </>
  )
}

function renderWithProbe(entry = '/events') {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[entry]}>
        <EventsPage />
        <DeeplinkProbe />
      </MemoryRouter>
    </I18nProvider>,
  )
}

const PINNED: EventOut = {
  id: 777, event_id: 'ev-777', type: 'penyusup', camera_id: 1, zone_id: null, severity: 'critical',
  ts_event: '2026-02-01T08:00:00Z', payload: null, clip_path: null, snapshot_path: null,
}

function byIdStub(body: EventOut | null, status = 200) {
  return (id: number) => (id === (body?.id ?? -1) ? { status, body } : { status: 404 })
}

test('?event beyond the loaded list is fetched by id and pinned', async () => {
  const fetchMock = stubDeeplinkFetch(EVENTS, byIdStub(PINNED))
  vi.stubGlobal('fetch', fetchMock)
  renderPage('/events?event=777')

  const detail = await screen.findByTestId('event-detail')
  expect(detail).toHaveTextContent('ev-777')
  expect(screen.getByTestId('event-pinned-note')).toBeInTheDocument()
  expect(byIdCalls(fetchMock)).toBe(1)
})

test('?event already in the list does not trigger a by-id fetch', async () => {
  const fetchMock = stubDeeplinkFetch(EVENTS, byIdStub(PINNED))
  vi.stubGlobal('fetch', fetchMock)
  renderPage('/events?event=2')

  await screen.findByTestId('event-detail')
  expect(screen.getByTestId('event-detail')).toHaveTextContent('ev-2')
  expect(screen.queryByTestId('event-pinned-note')).not.toBeInTheDocument()
  expect(byIdCalls(fetchMock)).toBe(0)
})

test('?event with an invalid value is ignored without a fetch', async () => {
  for (const raw of ['abc', '0', '-1', '1.5']) {
    const fetchMock = stubDeeplinkFetch(EVENTS, byIdStub(PINNED))
    vi.stubGlobal('fetch', fetchMock)
    const { unmount } = renderPage(`/events?event=${raw}`)
    const detail = await screen.findByTestId('event-detail')
    expect(detail).toHaveTextContent('ev-1')
    expect(byIdCalls(fetchMock)).toBe(0)
    expect(screen.queryByText(/tidak ditemukan|Gagal memuat/)).not.toBeInTheDocument()
    unmount()
  }
})

test('missing event shows a warning and falls back to the first event', async () => {
  const fetchMock = stubDeeplinkFetch(EVENTS)
  vi.stubGlobal('fetch', fetchMock)
  renderPage('/events?event=777')

  expect(await screen.findByTestId('event-detail')).toHaveTextContent('ev-1')
  expect(await screen.findByText(/Event #777 tidak ditemukan/)).toBeInTheDocument()
  expect(screen.queryByTestId('event-pinned-note')).not.toBeInTheDocument()
})

test('by-id failure shows the failed message', async () => {
  const fetchMock = stubDeeplinkFetch(EVENTS, () => ({ status: 500 }))
  vi.stubGlobal('fetch', fetchMock)
  renderPage('/events?event=777')

  expect(await screen.findByTestId('event-detail')).toHaveTextContent('ev-1')
  expect(await screen.findByText(/Gagal memuat event #777/)).toBeInTheDocument()
  expect(byIdCalls(fetchMock)).toBe(1)
})

test('changing ?event while mounted selects that event', async () => {
  const fetchMock = stubDeeplinkFetch(EVENTS, byIdStub(PINNED))
  vi.stubGlobal('fetch', fetchMock)
  renderWithProbe('/events')

  expect(await screen.findByTestId('event-detail')).toHaveTextContent('ev-1')
  await userEvent.click(screen.getByTestId('nav-btn')) // navigasi dari luar, seperti lonceng
  expect(await screen.findByTestId('event-detail')).toHaveTextContent('ev-2')
  expect(screen.getByTestId('event-item-2')).toHaveAttribute('aria-current', 'true')
  expect(screen.getByTestId('loc')).toHaveTextContent('/events?event=2')
  expect(byIdCalls(fetchMock)).toBe(0) // id 2 ada di daftar
})

test('clicking a row writes ?event= to the URL without adding history', async () => {
  vi.stubGlobal('fetch', stubDeeplinkFetch(EVENTS, byIdStub(PINNED)))
  renderWithProbe('/events')

  expect(await screen.findByTestId('event-detail')).toHaveTextContent('ev-1')
  await userEvent.click(screen.getByTestId('event-item-2'))
  expect(screen.getByTestId('loc')).toHaveTextContent('/events?event=2')
  expect(screen.getByTestId('nav-type')).toHaveTextContent('REPLACE') // riwayat tidak menumpuk
  expect(screen.getByTestId('event-detail')).toHaveTextContent('ev-2')
})

test('no ?event keeps the first event selected and the URL untouched', async () => {
  const fetchMock = stubDeeplinkFetch(EVENTS, byIdStub(PINNED))
  vi.stubGlobal('fetch', fetchMock)
  renderWithProbe('/events')

  expect(await screen.findByTestId('event-detail')).toHaveTextContent('ev-1')
  expect(screen.getByTestId('loc').textContent).toBe('/events') // tanpa '?event'
  expect(byIdCalls(fetchMock)).toBe(0)
})

test('a stale by-id response does not override a newer selection', async () => {
  let release: ((body: EventOut) => void) = () => {}
  const held = new Promise<EventOut>((res) => { release = res })
  const fetchMock = vi.fn(async (url: string) => {
    const u = String(url)
    if (BY_ID_RE.test(u)) {
      const body = await held
      return { ok: true, status: 200, json: () => Promise.resolve(body) }
    }
    if (u.includes('/alerts/by-events')) return { ok: true, status: 200, json: () => Promise.resolve({}) }
    if (u.includes('/events?')) return { ok: true, status: 200, json: () => Promise.resolve(EVENTS) }
    if (u.includes('/zones')) return { ok: true, status: 200, json: () => Promise.resolve([]) }
    if (u.endsWith('/cameras')) {
      return { ok: true, status: 200, json: () => Promise.resolve([{ id: 1, name: 'CAM-01' }, { id: 2, name: 'CAM-02' }]) }
    }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
  vi.stubGlobal('fetch', fetchMock)
  renderWithProbe('/events?event=777')

  await screen.findByTestId('event-item-1')
  await waitFor(() => expect(byIdCalls(fetchMock)).toBe(1))
  // lonceng navigasi ke event 2 selama fetch by-id 777 masih di jalan
  await userEvent.click(screen.getByTestId('nav-btn'))
  expect(await screen.findByTestId('event-detail')).toHaveTextContent('ev-2')
  await act(async () => { release(PINNED) })
  // respons basi 777 tidak boleh menimpa pilihan baru
  expect(screen.getByTestId('event-detail')).toHaveTextContent('ev-2')
  expect(screen.queryByTestId('event-pinned-note')).not.toBeInTheDocument()
})

test('pinned event survives a list refetch', async () => {
  const fetchMock = stubDeeplinkFetch(EVENTS, byIdStub(PINNED))
  vi.stubGlobal('fetch', fetchMock)
  renderPage('/events?event=777')
  await screen.findByTestId('event-pinned-note')
  expect(screen.getByTestId('event-detail')).toHaveTextContent('ev-777')

  await userEvent.selectOptions(screen.getByLabelText('Rentang'), '24h') // refetch daftar
  await waitFor(() => expect(listCalls(fetchMock).length).toBeGreaterThan(0))
  expect(await screen.findByTestId('event-detail')).toHaveTextContent('ev-777')
  expect(screen.getByTestId('event-pinned-note')).toBeInTheDocument()
  expect(byIdCalls(fetchMock)).toBe(1) // tidak diambil ulang
})

test('empty list with a pinned event still shows the detail', async () => {
  const fetchMock = stubDeeplinkFetch([], byIdStub(PINNED))
  vi.stubGlobal('fetch', fetchMock)
  renderPage('/events?event=777')

  const detail = await screen.findByTestId('event-detail')
  expect(detail).toHaveTextContent('ev-777')
  expect(screen.queryByText('Belum ada event')).not.toBeInTheDocument()
})

test('while the by-id fetch is pending a loading placeholder is shown, not the first event', async () => {
  let release: ((body: EventOut) => void) = () => {}
  const held = new Promise<EventOut>((res) => { release = res })
  const fetchMock = vi.fn(async (url: string) => {
    const u = String(url)
    if (BY_ID_RE.test(u)) {
      const body = await held
      return { ok: true, status: 200, json: () => Promise.resolve(body) }
    }
    if (u.includes('/alerts/by-events')) return { ok: true, status: 200, json: () => Promise.resolve({}) }
    if (u.includes('/events?')) return { ok: true, status: 200, json: () => Promise.resolve(EVENTS) }
    if (u.includes('/zones')) return { ok: true, status: 200, json: () => Promise.resolve([]) }
    if (u.endsWith('/cameras')) {
      return { ok: true, status: 200, json: () => Promise.resolve([{ id: 1, name: 'CAM-01' }, { id: 2, name: 'CAM-02' }]) }
    }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
  vi.stubGlobal('fetch', fetchMock)
  renderPage('/events?event=777')

  await screen.findByTestId('event-item-1')
  await waitFor(() => expect(byIdCalls(fetchMock)).toBe(1))
  // event yang dituju belum ada: jangan tampilkan event pertama sebagai penggantinya
  expect(screen.queryByTestId('event-detail')).not.toBeInTheDocument()
  expect(screen.getByTestId('event-detail-loading')).toBeInTheDocument()

  await act(async () => { release(PINNED) })
  expect(await screen.findByTestId('event-detail')).toHaveTextContent('ev-777')
  expect(screen.queryByTestId('event-detail-loading')).not.toBeInTheDocument()
})
