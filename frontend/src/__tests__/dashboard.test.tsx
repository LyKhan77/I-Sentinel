import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import DashboardPage from '../features/dashboard/DashboardPage'

const CAMS = [
  { id: 1, name: 'CAM-01', location: null, host: '192.168.1.101', rtsp_main: null, rtsp_sub: null, node_id: 1, enabled: true, status: 'online', probe_main: null, probe_sub: null },
  { id: 2, name: 'CAM-02', location: null, host: '192.168.1.102', rtsp_main: null, rtsp_sub: null, node_id: 1, enabled: true, status: 'offline', probe_main: null, probe_sub: null },
]
const NODES = [
  {
    id: 1,
    name: 'server',
    type: 'server',
    status: 'online',
    hw: {
      gpus: [
        { idx: 0, name: 'NVIDIA GeForce RTX 4090', vram_used_mb: 9000, vram_total_mb: 24564, util_pct: 12, processes: [{ pid: 123, name: 'ollama', user: null, mem_mb: 9000 }] },
        { idx: 1, name: 'NVIDIA GeForce RTX 5080', vram_used_mb: 0, vram_total_mb: 16303, util_pct: 0, processes: [] },
      ],
    },
    modules: { detector: { device: 'cuda:1', model: 'yolo26s.engine', ms_per_frame: 7.2 } },
  },
  { id: 2, name: 'edge-1', type: 'edge', status: 'offline' },
]
const STATS = { total: 47, by_type: { intrusi: 12, loitering: 8 } }
const EVENTS = [
  { id: 1, event_id: 'ev-1', type: 'intrusi', camera_id: 1, zone_id: null, severity: 'critical', ts_event: '2026-02-12T10:00:00Z', payload: null, clip_path: null, snapshot_path: null },
]

function stubFetch() {
  return vi.fn(async (url: string) => {
    const u = String(url)
    if (u.endsWith('/cameras')) return { ok: true, status: 200, json: () => Promise.resolve(CAMS) }
    if (u.endsWith('/nodes')) return { ok: true, status: 200, json: () => Promise.resolve(NODES) }
    if (u.endsWith('/events/stats/today')) return { ok: true, status: 200, json: () => Promise.resolve(STATS) }
    if (u.includes('/events?')) return { ok: true, status: 200, json: () => Promise.resolve(EVENTS) }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
}

function renderPage() {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/dashboard']}>
        <DashboardPage />
      </MemoryRouter>
    </I18nProvider>,
  )
}

test('renders tiles: cameras online/total, event stats, nodes, latest alerts', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()

  // kamera dan node sama-sama 1/2
  expect(await screen.findAllByText('1/2')).toHaveLength(2)
  expect(screen.getByText('47')).toBeInTheDocument() // event hari ini
  expect(screen.getByText(/intrusi 12 · loitering 8/)).toBeInTheDocument()
  expect(screen.getByText('intrusi')).toBeInTheDocument() // alert terbaru
  expect(screen.getByText('cam 1')).toBeInTheDocument()
})

test('renders node hardware cards with GPUs, processes, and detector badge', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()

  // kartu node 'server': GPU 4090 + VRAM + proses pemakai
  expect((await screen.findAllByText('server')).length).toBeGreaterThan(0)
  expect(screen.getByText('NVIDIA GeForce RTX 4090')).toBeInTheDocument()
  expect(screen.getByText('VRAM 9000/24564 MB · 12%')).toBeInTheDocument()
  expect(screen.getByText(/pid 123 ollama 9000 MB/)).toBeInTheDocument()
  expect(screen.getByText('NVIDIA GeForce RTX 5080')).toBeInTheDocument()
  // detector dipin cuda:1 -> badge PIN
  expect(screen.getByText('Detektor: PIN cuda:1')).toBeInTheDocument()
  // node tanpa hw: teks fallback
  expect(screen.getAllByText('Tidak ada info GPU (node belum kirim heartbeat atau tanpa NVIDIA)').length).toBeGreaterThan(0)
})

test('empty stats shows empty state', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const u = String(url)
      if (u.endsWith('/cameras')) return { ok: true, status: 200, json: () => Promise.resolve([]) }
      if (u.endsWith('/nodes')) return { ok: true, status: 200, json: () => Promise.resolve([]) }
      if (u.endsWith('/events/stats/today')) return { ok: true, status: 200, json: () => Promise.resolve({ total: 0, by_type: {} }) }
      if (u.includes('/events?')) return { ok: true, status: 200, json: () => Promise.resolve([]) }
      return { ok: false, status: 404, json: () => Promise.resolve(null) }
    }),
  )
  renderPage()
  expect(await screen.findAllByText('0/0')).toHaveLength(2)
  expect(screen.getAllByText('belum ada event').length).toBeGreaterThan(0)
})
