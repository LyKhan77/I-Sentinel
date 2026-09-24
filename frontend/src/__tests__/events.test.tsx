import { render, screen, waitFor } from '@testing-library/react'
import { act } from 'react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
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

function renderPage() {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/events']}>
        <EventsPage />
      </MemoryRouter>
    </I18nProvider>,
  )
}

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
