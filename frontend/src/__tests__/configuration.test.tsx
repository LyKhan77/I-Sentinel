import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
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

function renderConfiguration(entry: string) {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/configuration" element={<ConfigurationPage />} />
        </Routes>
        <LocationProbe />
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
