import { render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import SystemEvidence from '../features/events/EvidencePanel'
import type { EventOut } from '../api/events'
import type { NodeHistory } from '../api/monitoring'

const MIN = 60_000
const NOW = Date.now()
const T = (ms: number) => new Date(ms).toISOString()

function ev(payload: Record<string, unknown>, ts = NOW - 5 * MIN, extra: Partial<EventOut> = {}): EventOut {
  return {
    id: 1, event_id: 'ev-1', type: 'system', camera_id: null, zone_id: null, severity: 'warning',
    ts_event: T(ts), payload, clip_path: null, snapshot_path: null, node_id: 1, ...extra,
  }
}

const node = (over: Partial<NodeHistory> = {}): NodeHistory => ({
  id: 1, name: 'server',
  series: { cpu_pct: [{ t: T(NOW - 10 * MIN), avg: 91, max: 99 }], ram_pct: [], ms_avg: [], ms_max: [],
    infer_fps: [{ t: T(NOW - 10 * MIN), avg: 34 }], mqtt_backlog: [], gpus: {} },
  cameras: [], offline: [], ...over,
})

function stubHistory(body: unknown, ok = true) {
  const calls: string[] = []
  const mock = vi.fn(async (url: string) => {
    calls.push(String(url))
    if (!String(url).includes('/monitoring/history')) return { ok: false, status: 404, json: () => Promise.resolve(null) }
    return { ok, status: ok ? 200 : 500, json: () => Promise.resolve(body) }
  })
  vi.stubGlobal('fetch', mock)
  return calls
}

const historyBody = (n: NodeHistory) => ({
  range: 'custom', bucket_s: 60, from: T(NOW - 35 * MIN), to: T(NOW), nodes: [n],
})

const renderPanel = (e: EventOut) => render(
  <I18nProvider><SystemEvidence event={e} /></I18nProvider>,
)

afterEach(() => { vi.unstubAllGlobals() })

test('stored evidence draws charts without any history request', async () => {
  const calls = stubHistory(historyBody(node()))
  const from = NOW - 35 * MIN
  renderPanel(ev({ kind: 'health', rule: 'node_cpu', target: 'node:1', label: 'Server', value: 91.5,
    threshold: 90, unit: '%', duration_min: 5, state: 'firing',
    evidence: { v: 1, from: T(from), step_s: 60, series: { value: [80, 90, 91.5] } } }))

  expect(await screen.findByTestId('lc-line-value')).toBeInTheDocument()
  expect(screen.getByTestId('lc-ref')).toBeInTheDocument()
  expect(screen.getAllByTestId('lc-marker')).toHaveLength(1)
  await new Promise((r) => setTimeout(r, 20))
  expect(calls).toHaveLength(0)
})

test('event older than 7 days with stored evidence still shows charts, not the expired note', async () => {
  const calls = stubHistory(historyBody(node()))
  const from = NOW - 10 * 24 * 3_600_000 - 3 * MIN
  renderPanel(ev({ kind: 'health', rule: 'node_cpu', label: 'Server', value: 91.5, threshold: 90, unit: '%',
    duration_min: 5, state: 'firing',
    evidence: { v: 1, from: T(from), step_s: 60, series: { value: [91, 91.5] } } }, NOW - 10 * 24 * 3_600_000))

  expect(await screen.findByTestId('lc-line-value')).toBeInTheDocument()
  expect(screen.queryByText('Data tren hanya disimpan 7 hari')).not.toBeInTheDocument()
  await new Promise((r) => setTimeout(r, 20))
  expect(calls).toHaveLength(0)
})

test('nulls in the stored series create gaps', async () => {
  const from = NOW - 35 * MIN
  renderPanel(ev({ kind: 'health', rule: 'node_cpu', label: 'Server', value: 91.5, threshold: 90, unit: '%',
    duration_min: 5, state: 'firing',
    evidence: { v: 1, from: T(from), step_s: 60, series: { value: [80, null, null, 91.5] } } }))

  const line = await screen.findByTestId('lc-line-value')
  expect(line.getAttribute('d')?.match(/M/gu)).toHaveLength(2)
})

test('node offline stored evidence shows cpu and fps charts and the last-seen fact', async () => {
  const calls = stubHistory(historyBody(node()))
  const from = NOW - 32 * MIN
  renderPanel(ev({ node: 'edge-1', reason: 'timeout', last_seen: T(NOW - 5 * MIN),
    evidence: { v: 1, from: T(from), step_s: 60, series: { cpu_pct: [40, null, 42], infer_fps: [30, null, 28] } } }))

  expect(await screen.findByTestId('lc-line-cpu_pct')).toBeInTheDocument()
  expect(screen.getByTestId('lc-line-infer_fps')).toBeInTheDocument()
  expect(screen.getByText('Heartbeat terakhir')).toBeInTheDocument()
  expect(screen.queryByTestId('lc-offline')).not.toBeInTheDocument()
  await new Promise((r) => setTimeout(r, 20))
  expect(calls).toHaveLength(0)
})

test('stored evidence with only nulls shows the no-data note', async () => {
  const from = NOW - 35 * MIN
  renderPanel(ev({ kind: 'health', rule: 'node_cpu', label: 'Server', value: 91.5, threshold: 90, unit: '%',
    duration_min: 5, state: 'firing',
    evidence: { v: 1, from: T(from), step_s: 60, series: { value: [null, null] } } }))

  expect(await screen.findByTestId('evidence-empty')).toBeInTheDocument()
  expect(screen.getByText('Tidak ada data tren pada jendela ini')).toBeInTheDocument()
})

test('malformed stored evidence falls back to the history fetch', async () => {
  const calls = stubHistory(historyBody(node()))
  renderPanel(ev({ kind: 'health', rule: 'node_cpu', label: 'Server', value: 91.5, threshold: 90, unit: '%',
    duration_min: 5, state: 'firing',
    evidence: { v: 2, from: T(NOW - 35 * MIN), step_s: 60, series: { value: [80, 91.5] } } }))

  expect(await screen.findByTestId('lc-line-cpu_pct')).toBeInTheDocument()
  await waitFor(() => expect(calls).toHaveLength(1))
})

test('event without evidence behaves as before', async () => {
  const calls = stubHistory(historyBody(node()))
  renderPanel(ev({ kind: 'health', rule: 'node_cpu', label: 'Server', value: 91.5, threshold: 90, unit: '%',
    duration_min: 5, state: 'firing' }))

  expect(await screen.findByTestId('lc-line-cpu_pct')).toBeInTheDocument()
  await waitFor(() => expect(calls).toHaveLength(1))
})

test('event node offline menampilkan dua grafik dengan arsir periode offline', async () => {
  stubHistory(historyBody(node({ offline: [{ from: T(NOW - 20 * MIN), to: null }] })))
  renderPanel(ev({ node: 'edge-1', reason: 'timeout' }))

  expect(await screen.findByTestId('lc-line-cpu_pct')).toBeInTheDocument()
  expect(screen.getByTestId('lc-line-infer_fps')).toBeInTheDocument()
  expect(screen.getAllByTestId('lc-offline')).toHaveLength(2)
  expect(screen.queryByTestId('lc-ref')).not.toBeInTheDocument()
})

test('camera_low_fps menggambar nilai sebagai persen target FPS', async () => {
  stubHistory(historyBody(node({
    cameras: [{ id: 3, name: 'Lorong', target_fps: 8, fps: [{ t: T(NOW - 10 * MIN), min: 2 }], frame_age_s: [] }],
  })))
  renderPanel(ev({ kind: 'health', rule: 'camera_low_fps', target: 'cam:3', label: 'Lorong', value: 25,
    threshold: 50, unit: '%', duration_min: 3, state: 'firing' }))

  const line = await screen.findByTestId('lc-line-camera_low_fps')
  expect(line.getAttribute('d')).toBeTruthy()
  // 2 fps dari target 8 = 25% → y setara nilai 25, bukan 2
  expect(screen.getByRole('img')).toHaveAttribute('aria-label', expect.stringContaining('25.0 %'))
})

test('event lebih tua dari 7 hari menampilkan fakta dan catatan kedaluwarsa tanpa permintaan history', async () => {
  const calls = stubHistory(historyBody(node()))
  renderPanel(ev({ kind: 'health', rule: 'node_cpu', label: 'Server', value: 1, threshold: 90, unit: '%',
    duration_min: 5, state: 'firing' }, NOW - 8 * 24 * 3_600_000))

  expect(await screen.findByText('Aturan')).toBeInTheDocument()
  expect(screen.getByText('Data tren hanya disimpan 7 hari')).toBeInTheDocument()
  expect(screen.queryByTestId('lc-marker')).not.toBeInTheDocument()
  await new Promise((r) => setTimeout(r, 20))
  expect(calls).toHaveLength(0)
})

test('gagal memuat history: fakta tetap tampil dan muncul pesan gagal', async () => {
  stubHistory(null, false)
  renderPanel(ev({ kind: 'health', rule: 'node_cpu', label: 'Server', value: 1, threshold: 90, unit: '%',
    duration_min: 5, state: 'firing' }))

  expect(await screen.findByText('Gagal memuat grafik')).toBeInTheDocument()
  expect(screen.getByText('Aturan')).toBeInTheDocument()
})

test('jendela kosong menampilkan catatan tanpa data tren', async () => {
  stubHistory(historyBody(node({ series: { ...node().series, cpu_pct: [] } })))
  renderPanel(ev({ kind: 'health', rule: 'node_cpu', label: 'Server', value: 1, threshold: 90, unit: '%',
    duration_min: 5, state: 'firing' }))

  expect(await screen.findByText('Tidak ada data tren pada jendela ini')).toBeInTheDocument()
})

test('rule tak dikenal menampilkan fakta saja tanpa permintaan history', async () => {
  const calls = stubHistory(historyBody(node()))
  renderPanel(ev({ kind: 'health', rule: 'weird_rule', label: 'Server', value: 1, threshold: 90, unit: '%',
    duration_min: 5, state: 'firing' }))

  expect(await screen.findByText('Aturan')).toBeInTheDocument()
  expect(screen.getByText('Tidak ada rincian tambahan untuk event ini')).toBeInTheDocument()
  await new Promise((r) => setTimeout(r, 20))
  expect(calls).toHaveLength(0)
})

test('payload tanpa rincian menampilkan catatan tanpa permintaan history', async () => {
  const calls = stubHistory(historyBody(node()))
  renderPanel(ev({}))
  expect(await screen.findByText('Tidak ada rincian tambahan untuk event ini')).toBeInTheDocument()
  await waitFor(() => expect(calls).toHaveLength(0))
})

test('menampilkan skeleton sebelum grafik selesai dimuat', async () => {
  let release: ((v: unknown) => void) | undefined
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true, status: 200,
    json: () => new Promise((res) => { release = res as (v: unknown) => void }),
  })))
  renderPanel(ev({ kind: 'health', rule: 'node_cpu', target: 'node:1', label: 'Server', value: 1,
    threshold: 90, unit: '%', duration_min: 5, state: 'firing' }))

  expect(await screen.findByTestId('evidence-loading')).toBeInTheDocument()
  release?.(historyBody(node()))
  expect(await screen.findByTestId('lc-line-cpu_pct')).toBeInTheDocument()
  expect(screen.queryByTestId('evidence-loading')).not.toBeInTheDocument()
})

test('event bertimestamp masa depan menampilkan catatan tanpa data dan tanpa request history', async () => {
  const calls = stubHistory(historyBody(node()))
  renderPanel(ev({ kind: 'health', rule: 'node_cpu', target: 'node:1', label: 'Server', value: 91.5,
    threshold: 90, unit: '%', duration_min: 5, state: 'firing' }, NOW + 2 * 3_600_000))

  expect(await screen.findByTestId('evidence-empty')).toBeInTheDocument()
  expect(screen.getByText('Aturan')).toBeInTheDocument()
  expect(calls).toEqual([])
})

test('stored evidence still draws charts when node_id is missing, without any history request', async () => {
  const calls = stubHistory(historyBody(node()))
  const from = NOW - 10 * 24 * 3_600_000 - 3 * MIN
  renderPanel(ev({ kind: 'health', rule: 'node_cpu', target: 'node:1', label: 'Server', value: 91.5,
    threshold: 90, unit: '%', duration_min: 5, state: 'firing',
    evidence: { v: 1, from: T(from), step_s: 60, series: { value: [80, 90, 91.5] } } },
  NOW - 10 * 24 * 3_600_000, { node_id: null }))

  expect(await screen.findByTestId('lc-line-value')).toBeInTheDocument()
  expect(screen.queryByText('Tidak ada rincian tambahan untuk event ini')).not.toBeInTheDocument()
  await new Promise((r) => setTimeout(r, 20))
  expect(calls).toHaveLength(0)
})
