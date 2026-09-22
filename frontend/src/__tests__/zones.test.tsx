import { useState } from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import ZoneEditor from '../components/ZoneEditor'
import ZonesPage from '../features/config/ZonesPage'
import type { Zone } from '../api/zones'

const CAMS = [{ id: 1, name: 'CAM-01', location: null, host: '1.2.3.4', rtsp_main: null, rtsp_sub: null, node_id: 1, enabled: true, status: 'online', probe_main: null, probe_sub: null }]

function stubFetch(opts: { zones?: Zone[]; created?: Zone } = {}) {
  const zones = opts.zones ?? []
  return vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    if (u.endsWith('/cameras')) return { ok: true, status: 200, json: () => Promise.resolve(CAMS) }
    if (u.endsWith('/cameras/1/live')) {
      return {
        ok: true,
        status: 200,
        json: () => Promise.resolve({ camera_id: 1, streams: { sub: 'cam_1' }, snapshot: 'http://192.168.2.10:1984/api/frame.jpeg?src=cam_1' }),
      }
    }
    if (u.endsWith('/zones') && (init?.method ?? 'GET') === 'GET') {
      return { ok: true, status: 200, json: () => Promise.resolve(zones) }
    }
    if (u.endsWith('/zones') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body))
      const created = opts.created ?? { id: 10, camera_name: 'CAM-01', direction: null, schedule: null, rate_limit_min: 5, telegram: false, camera_id: 1, ...body }
      return { ok: true, status: 200, json: () => Promise.resolve(created) }
    }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
}

// jsdom tanpa layout: rect manual utk konversi koordinat klik → normalisasi
function stubRect(el: Element) {
  el.getBoundingClientRect = () => ({ x: 0, y: 0, left: 0, top: 0, width: 1000, height: 500, right: 1000, bottom: 500, toJSON: () => ({}) }) as DOMRect
}

function renderEditor(onChange: (z: Zone[]) => void, zones: Zone[] = []) {
  return render(
    <I18nProvider>
      <ZoneEditor cameraId={1} initialZones={zones} onChange={onChange} selectedId={null} onSelect={() => {}} />
    </I18nProvider>,
  )
}

test('click 3 points shows green start ring, click ring closes polygon', async () => {
  vi.stubGlobal('fetch', stubFetch())
  let zones: Zone[] = []
  const onChange = (z: Zone[]) => (zones = z)
  renderEditor(onChange)

  const svg = await screen.findByTestId('zone-svg')
  stubRect(svg)

  fireEvent.click(screen.getByTestId('zone-draw-start'))
  ;[[200, 100], [800, 100], [500, 400]].forEach(([x, y]) => fireEvent.click(svg, { clientX: x, clientY: y }))

  // ≥3 titik → ring hijau pulsing muncul di titik pertama
  const ring = screen.getByTestId('zone-start-ring')
  expect(ring).toBeInTheDocument()
  expect(ring.getAttribute('cx')).toBe('20') // 200/1000*100
  expect(ring.getAttribute('cy')).toBe('20') // 100/500*100

  // klik ring = tutup polygon
  fireEvent.click(ring)
  await waitFor(() => expect(zones).toHaveLength(1))
  expect(zones[0].polygon).toEqual([[0.2, 0.2], [0.8, 0.2], [0.5, 0.8]])
  expect(screen.queryByTestId('zone-start-ring')).not.toBeInTheDocument()
})

test('save calls createZone with normalized polygon', async () => {
  const created: Zone = { id: 10, camera_id: 1, name: 'Zona 1', type: 'restricted', direction: null, polygon: [[0.2, 0.2], [0.8, 0.2], [0.5, 0.8]], schedule: null, severity: 'warning', rate_limit_min: 5, snapshot: true, clip: true, telegram: false, active: true }
  const fetchMock = stubFetch({ created })
  vi.stubGlobal('fetch', fetchMock)
  render(<I18nProvider><ZonesPage /></I18nProvider>)

  await waitFor(() => expect(screen.getByTestId('zone-draw-start')).toBeInTheDocument())
  // hook kelas semantik utk breakpoint: kanvas/daftar dulu, panel properti kedua
  expect(document.querySelector('.configuration-zones')).toBeInTheDocument()
  expect(document.querySelector('.configuration-zones__details')).toBeInTheDocument()
  const svg = screen.getByTestId('zone-svg')
  stubRect(svg)

  fireEvent.click(screen.getByTestId('zone-draw-start'))
  ;[[200, 100], [800, 100], [500, 400]].forEach(([x, y]) => fireEvent.click(svg, { clientX: x, clientY: y }))
  fireEvent.click(screen.getByTestId('zone-start-ring'))

  // panel properti zone baru muncul → simpan
  await waitFor(() => expect(screen.getByTestId('zone-save')).toBeInTheDocument())
  fireEvent.click(screen.getByTestId('zone-save'))

  await waitFor(() => {
    const post = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith('/zones') && i?.method === 'POST')
    expect(post).toBeTruthy()
    const body = JSON.parse(String(post![1]!.body))
    expect(body.camera_id).toBe(1)
    expect(body.polygon).toEqual([[0.2, 0.2], [0.8, 0.2], [0.5, 0.8]])
  })
})

test('draw mode cancel resets points', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderEditor(() => {})

  const svg = await screen.findByTestId('zone-svg')
  stubRect(svg)
  fireEvent.click(screen.getByTestId('zone-draw-start'))
  fireEvent.click(svg, { clientX: 100, clientY: 100 })
  fireEvent.click(screen.getByTestId('zone-draw-cancel'))
  fireEvent.click(svg, { clientX: 300, clientY: 300 })
  expect(screen.queryByTestId('zone-start-ring')).not.toBeInTheDocument()
})

test('right-click handle deletes point, min 3 enforced', async () => {
  const zone: Zone = { id: 1, camera_id: 1, name: 'z', type: 'free', direction: null, polygon: [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]], schedule: null, severity: 'warning', rate_limit_min: 5, snapshot: true, clip: true, telegram: false, active: true }
  vi.stubGlobal('fetch', stubFetch({ zones: [zone] }))
  let zones: Zone[] = [zone]
  // parent-nya ZonesPage yg pegang selectedId — bungkus dgn state, pola sama dgn page asli
  function Harness() {
    const [sel, setSel] = useState<number | null>(null)
    return <ZoneEditor cameraId={1} initialZones={zones} onChange={(z) => (zones = z)} selectedId={sel} onSelect={setSel} />
  }
  render(
    <I18nProvider>
      <Harness />
    </I18nProvider>,
  )

  await screen.findByTestId('zone-svg')
  fireEvent.click(screen.getByTestId('zone-list-item-1'))
  await waitFor(() => expect(screen.getByTestId('zone-handle-0-0')).toBeInTheDocument())
  fireEvent.contextMenu(screen.getByTestId('zone-handle-0-0'))
  // 3 titik = minimum → tidak berubah
  expect(zones[0].polygon).toHaveLength(3)
})
