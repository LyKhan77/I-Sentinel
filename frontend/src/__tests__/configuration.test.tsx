import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import ConfigurationPage from '../features/config/ConfigurationPage'
import type { Zone } from '../api/zones'

const ME = { id: 1, username: 'admin', role: 'admin' }

const CAMS = [
  {
    id: 1,
    name: 'CAM-01',
    location: 'Gerbang Masuk',
    host: '192.168.1.101',
    rtsp_main: 'rtsp://192.168.1.101/Streaming/Channels/101',
    rtsp_sub: 'rtsp://192.168.1.101/Streaming/Channels/102',
    node_id: 1,
    enabled: true,
    status: 'online',
    probe_main: { res: '2560x1440', fps: 25, codec: 'h264' },
    probe_sub: null,
  },
]

function gate(id: number, direction: 'entry' | 'exit'): Zone {
  return {
    id,
    camera_id: 1,
    name: direction === 'entry' ? 'Gate Entry' : 'Gate Exit',
    type: 'absensi',
    direction,
    polygon: [
      [0.1, 0.1],
      [0.9, 0.1],
      [0.9, 0.9],
    ],
    schedule: null,
    severity: 'warning',
    rate_limit_min: 5,
    snapshot: true,
    telegram: false,
    active: true,
    camera_name: 'CAM-01',
  }
}

const STATS = {
  retention_days: 30,
  storage_root: '/data/isentinel',
  disk: { total: 1000, used: 850, free: 150, percent: 85.0 },
  kinds: {
    clips: { files: 10, bytes: 2048 },
    snapshots: { files: 5, bytes: 1024 },
    crops: { files: 0, bytes: 0 },
  },
  last_sweep: null,
}

type Call = { url: string; init?: RequestInit }

function stubFetch(zones: Zone[] = []) {
  const calls: Call[] = []
  const resp = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url)
      calls.push({ url: u, init })
      if (u.endsWith('/auth/me')) return resp(200, ME)
      if (u.endsWith('/cameras')) return resp(200, CAMS)
      if (u.includes('/cameras/1/live')) {
        return resp(200, { camera_id: 1, streams: { sub: 'cam_1' }, snapshot: 'http://192.168.2.10:1984/api/frame.jpeg?src=cam_1' })
      }
      if (u.includes('/zones')) return resp(200, zones)
      if (u.endsWith('/storage/stats')) return resp(200, STATS)
      return resp(404, null)
    }),
  )
  return calls
}

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.search}</output>
}

// probe history nyata: Back/Forward lewat useNavigate, bukan mock history
function NavigationProbe() {
  const navigate = useNavigate()
  return (
    <>
      <button type="button" onClick={() => navigate(-1)}>
        back
      </button>
      <button type="button" onClick={() => navigate(1)}>
        forward
      </button>
    </>
  )
}

function renderConfiguration(entry: string) {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/configuration" element={<ConfigurationPage />} />
        </Routes>
        <LocationProbe />
        <NavigationProbe />
      </MemoryRouter>
    </I18nProvider>,
  )
}

test('renders one shared workbench heading instead of per-panel titles', async () => {
  stubFetch()
  renderConfiguration('/configuration?tab=cameras')

  expect(await screen.findByRole('heading', { name: 'Konfigurasi' })).toBeInTheDocument()
  expect(screen.getByText('Kamera, zona, gate absensi, dan retensi dalam satu tempat')).toBeInTheDocument()
  expect(screen.queryByText('Kamera terdaftar, stream utama/sub, dan node vision')).not.toBeInTheDocument()
})

test('selects the tab named by the URL, mounts only that panel, and updates the query on selection', async () => {
  const user = userEvent.setup()
  const calls = stubFetch([gate(1, 'entry')])
  renderConfiguration('/configuration?tab=gates')

  expect(await screen.findByRole('tab', { name: 'Gate Absensi', selected: true })).toBeInTheDocument()
  expect(await screen.findByTestId('gate-add')).toBeInTheDocument()
  // panel non-aktif tidak di-mount → API-nya tidak dipanggil
  expect(calls.some((c) => c.url.includes('/storage/stats'))).toBe(false)
  expect(calls.some((c) => c.url.includes('/live'))).toBe(false)

  await user.click(screen.getByRole('tab', { name: 'Retensi & Storage' }))
  expect(screen.getByTestId('location')).toHaveTextContent('?tab=storage')
  expect(await screen.findByTestId('storage-retention')).toBeInTheDocument()
})

test('tab selection is a history entry that Back and Forward restore', async () => {
  const user = userEvent.setup()
  stubFetch([gate(1, 'entry')])
  renderConfiguration('/configuration?tab=gates')

  await user.click(await screen.findByRole('tab', { name: 'Retensi & Storage' }))
  expect(await screen.findByTestId('storage-retention')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'back' }))
  expect(await screen.findByRole('tab', { name: 'Gate Absensi', selected: true })).toBeInTheDocument()
  expect(screen.getByTestId('location')).toHaveTextContent('?tab=gates')

  await user.click(screen.getByRole('button', { name: 'forward' }))
  expect(await screen.findByRole('tab', { name: 'Retensi & Storage', selected: true })).toBeInTheDocument()
  expect(screen.getByTestId('location')).toHaveTextContent('?tab=storage')
})

test('clicking the already-selected tab does not push a duplicate history entry', async () => {
  const user = userEvent.setup()
  stubFetch([gate(1, 'entry')])
  renderConfiguration('/configuration?tab=gates')

  await user.click(await screen.findByRole('tab', { name: 'Retensi & Storage' }))
  const storageTab = await screen.findByRole('tab', { name: 'Retensi & Storage', selected: true })
  await user.click(storageTab)

  // satu Back harus kembali ke Gate; entri history duplikat membuat Back tetap di Storage
  await user.click(screen.getByRole('button', { name: 'back' }))
  expect(await screen.findByRole('tab', { name: 'Gate Absensi', selected: true })).toBeInTheDocument()
  expect(screen.getByTestId('location')).toHaveTextContent('?tab=gates')
})

test('falls back to Cameras for an invalid or missing tab', async () => {
  stubFetch()
  const { unmount } = renderConfiguration('/configuration?tab=bogus')

  expect(await screen.findByRole('tab', { name: 'Kamera', selected: true })).toBeInTheDocument()
  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  unmount()

  renderConfiguration('/configuration')
  expect(await screen.findByRole('tab', { name: 'Kamera', selected: true })).toBeInTheDocument()
  expect(screen.getByTestId('location').textContent).toBe('')
})

test('Gate draw action selects the Zones tab in the same workbench', async () => {
  const user = userEvent.setup()
  stubFetch([gate(1, 'entry')])
  renderConfiguration('/configuration?tab=gates')

  await user.click(await screen.findByTestId('gate-draw-1'))

  expect(await screen.findByRole('tab', { name: 'Zona Deteksi', selected: true })).toBeInTheDocument()
  expect(screen.getByTestId('location')).toHaveTextContent('?tab=zones')
  expect(await screen.findByTestId('zone-draw-start')).toBeInTheDocument()
})

const NODES = [
  {
    id: 1,
    name: 'server',
    type: 'server',
    status: 'online',
    detector_device: 'cuda:1',
    hw: {
      gpus: [
        { idx: 0, name: 'NVIDIA GeForce RTX 4090', vram_used_mb: 9000, vram_total_mb: 24564, util_pct: 12, processes: [] },
        { idx: 1, name: 'NVIDIA GeForce RTX 5080', vram_used_mb: 262, vram_total_mb: 16303, util_pct: 35, processes: [] },
      ],
    },
  },
]

test('Nodes tab lists nodes with GPU dropdown and saves detector device', async () => {
  const user = userEvent.setup()
  const calls: Call[] = []
  const resp = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })
  let nodeDevice = 'cuda:1'
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url)
      calls.push({ url: u, init })
      if (u.endsWith('/auth/me')) return resp(200, ME)
      if (u.endsWith('/nodes')) return resp(200, NODES.map((n) => ({ ...n, detector_device: nodeDevice })))
      if (u.endsWith('/nodes/1/detector-device')) {
        nodeDevice = JSON.parse(init?.body as string).device
        return resp(200, { ...NODES[0], detector_device: nodeDevice })
      }
      return resp(404, null)
    }),
  )
  renderConfiguration('/configuration?tab=nodes')

  // dropdown terisi dari DB + opsi GPU dari heartbeat hw
  expect(await screen.findByText('Device detektor (GPU)')).toBeInTheDocument()
  expect(screen.getByText(/cuda:1 — NVIDIA GeForce RTX 5080/)).toBeInTheDocument()

  // simpan pin baru
  await user.selectOptions(screen.getByLabelText('Device detektor (GPU)'), 'cuda:0')
  await user.click(screen.getByRole('button', { name: 'Simpan' }))
  await screen.findByText('Tersimpan, node hot-reload')
  const put = calls.find((c) => c.url.endsWith('/nodes/1/detector-device'))
  expect(put?.init?.method).toBe('PUT')
  expect(JSON.parse(put?.init?.body as string)).toEqual({ device: 'cuda:0' })
})

test('Nodes tab shows fallback when node has no hw heartbeat', async () => {
  const resp = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      const u = String(url)
      if (u.endsWith('/auth/me')) return resp(200, ME)
      if (u.endsWith('/nodes')) return resp(200, [{ id: 2, name: 'edge-1', type: 'edge', status: 'online' }])
      return resp(404, null)
    }),
  )
  renderConfiguration('/configuration?tab=nodes')
  expect(await screen.findByText('edge-1')).toBeInTheDocument()
  expect(screen.getByText('Belum ada data GPU dari heartbeat node — hanya Auto tersedia')).toBeInTheDocument()
})
