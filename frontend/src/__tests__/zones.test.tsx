import type { Mock } from 'vitest'
import { useState } from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import ZoneEditor from '../components/ZoneEditor'
import ZonesPage from '../features/config/ZonesPage'
import type { Zone } from '../api/zones'

const CAM_BASE = { location: null, host: '1.2.3.4', rtsp_main: null, rtsp_sub: null, node_id: 1, enabled: true, status: 'online', probe_main: null, probe_sub: null }
const CAMS = [{ id: 1, name: 'CAM-01', ...CAM_BASE }, { id: 2, name: 'CAM-02', ...CAM_BASE }]
const ZONE_CAM1: Zone = { id: 5, camera_id: 1, camera_name: 'CAM-01', name: 'Zona A', type: 'behavior', direction: null, polygon: [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]], schedule: null, severity: 'warning', rate_limit_min: 5, trigger_seconds: 0, behaviors: [], snapshot: true, clip: true, telegram: false, active: true }

function stubFetch(opts: { zones?: Zone[]; created?: Zone; patchStatus?: number; patchDetail?: string } = {}) {
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
    if (u.includes('/zones') && (init?.method ?? 'GET') === 'GET') {
      return { ok: true, status: 200, json: () => Promise.resolve(zones) }
    }
    if (u.includes('/zones/') && init?.method === 'PATCH') {
      if (opts.patchStatus != null) {
        return { ok: false, status: opts.patchStatus, json: () => Promise.resolve({ detail: opts.patchDetail ?? 'x' }) }
      }
      const body = JSON.parse(String(init.body))
      return { ok: true, status: 200, json: () => Promise.resolve({ ...zones[0], ...body }) }
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

/** Gambar segitiga lalu tunggu panel properti zona baru muncul. */
async function drawTriangle() {
  await waitFor(() => expect(screen.getByTestId('zone-draw-start')).toBeInTheDocument())
  const svg = screen.getByTestId('zone-svg')
  stubRect(svg)
  fireEvent.click(screen.getByTestId('zone-draw-start'))
  ;[[200, 100], [800, 100], [500, 400]].forEach(([x, y]) => fireEvent.click(svg, { clientX: x, clientY: y }))
  fireEvent.click(screen.getByTestId('zone-start-ring'))
  await waitFor(() => expect(screen.getByTestId('zone-save')).toBeInTheDocument())
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
  const created: Zone = { id: 10, camera_id: 1, name: 'Zona 1', type: 'behavior', direction: null, polygon: [[0.2, 0.2], [0.8, 0.2], [0.5, 0.8]], schedule: null, severity: 'warning', rate_limit_min: 5, trigger_seconds: 0, behaviors: [], snapshot: true, clip: true, telegram: false, active: true }
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
  const zone: Zone = { id: 1, camera_id: 1, name: 'z', type: 'behavior', direction: null, polygon: [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]], schedule: null, severity: 'warning', rate_limit_min: 5, trigger_seconds: 0, behaviors: [], snapshot: true, clip: true, telegram: false, active: true }
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

const zoneFix = (over: Partial<Zone> = {}): Zone => ({
  id: 10, camera_id: 1, name: 'Zona 1', type: 'behavior', direction: null,
  polygon: [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]], schedule: null, severity: 'warning',
  rate_limit_min: 5, trigger_seconds: 0, behaviors: [], snapshot: true, clip: true,
  telegram: false, active: true, ...over,
})

async function selectZone(zones: Zone[], opts: { patchStatus?: number; patchDetail?: string } = {}) {
  const fetchMock = stubFetch({ zones, ...opts })
  vi.stubGlobal('fetch', fetchMock)
  render(<I18nProvider><ZonesPage /></I18nProvider>)
  fireEvent.click(await screen.findByTestId('zone-item-10'))
  return fetchMock
}

function patchBody(fetchMock: Mock) {
  const patch = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith('/zones/10') && i?.method === 'PATCH')
  expect(patch).toBeTruthy()
  return JSON.parse(String(patch![1]!.body))
}

test('tipe Behavior: tiap behavior terpilih punya trigger sendiri, dikirim sebagai behaviors', async () => {
  const fetchMock = await selectZone([zoneFix()])

  // field lama level-zona tidak boleh muncul lagi
  expect(screen.queryByTestId('zone-dwell')).not.toBeInTheDocument()

  fireEvent.click(screen.getByTestId('zone-behavior-intrusion'))
  fireEvent.click(screen.getByTestId('zone-behavior-loitering'))
  expect(await screen.findByTestId('zone-trigger-intrusion')).toHaveValue(0)
  fireEvent.change(screen.getByTestId('zone-trigger-loitering'), { target: { value: '30' } })
  fireEvent.click(screen.getByTestId('zone-save'))

  await waitFor(() =>
    expect(patchBody(fetchMock).behaviors).toEqual([
      { kind: 'intrusion', trigger_seconds: 0 },
      { kind: 'loitering', trigger_seconds: 30 },
    ]),
  )
})

test('behavior running membawa speed_limit_mps sendiri', async () => {
  const fetchMock = await selectZone([zoneFix()])

  fireEvent.click(screen.getByTestId('zone-behavior-running'))
  fireEvent.change(await screen.findByTestId('zone-speed-running'), { target: { value: '2.5' } })
  fireEvent.click(screen.getByTestId('zone-save'))

  await waitFor(() =>
    expect(patchBody(fetchMock).behaviors).toEqual([{ kind: 'running', trigger_seconds: 0, speed_limit_mps: 2.5 }]),
  )
})

test('Snapshot dan Clip diatur per behavior dan dikirim di item behaviors', async () => {
  const fetchMock = await selectZone([zoneFix({ behaviors: [
    { kind: 'intrusion', trigger_seconds: 0 }, { kind: 'loitering', trigger_seconds: 30 },
  ] })])
  expect(document.getElementById('zone-snapshot')).toBeNull() // toggle level zona dihapus
  expect(document.getElementById('zone-clip')).toBeNull()
  fireEvent.click(document.getElementById('zone-clip-intrusion')!)
  fireEvent.click(document.getElementById('zone-snapshot-loitering')!)
  fireEvent.click(screen.getByTestId('zone-save'))
  await waitFor(() => expect(patchBody(fetchMock).behaviors).toEqual([
    { kind: 'intrusion', trigger_seconds: 0, clip: false },
    { kind: 'loitering', trigger_seconds: 30, snapshot: false },
  ]))
})

test('toggle behavior mengikuti flag zona lama bila belum diatur', async () => {
  await selectZone([zoneFix({ clip: false, behaviors: [{ kind: 'intrusion', trigger_seconds: 0 }] })])
  expect(document.getElementById('zone-clip-intrusion')).toHaveAttribute('aria-checked', 'false')
  expect(document.getElementById('zone-snapshot-intrusion')).toHaveAttribute('aria-checked', 'true')
  expect(document.getElementById('zone-clip-loitering')).toBeNull() // behavior tidak dicentang → tanpa toggle
})

test('zona absensi tanpa toggle Snapshot/Clip; konflik arah menampilkan pesan', async () => {
  await selectZone(
    [zoneFix({ type: 'attendance', direction: 'exit', behaviors: [{ kind: 'attendance', trigger_seconds: 0 }] })],
    { patchStatus: 422, patchDetail: 'camera already has an active attendance zone with another direction' },
  )
  expect(document.querySelector('[id^="zone-clip"]')).toBeNull()
  expect(document.querySelector('[id^="zone-snapshot"]')).toBeNull()
  fireEvent.click(screen.getByTestId('zone-save'))
  expect(await screen.findByText('Kamera ini sudah punya zona absensi aktif dengan arah lain.')).toBeInTheDocument()
})

test('422 bukan konflik arah (validasi lain) memakai pesan simpan generik', async () => {
  await selectZone(
    [zoneFix({ type: 'attendance', direction: 'exit', behaviors: [{ kind: 'attendance', trigger_seconds: 0 }] })],
    { patchStatus: 422, patchDetail: 'direction is required' },
  )
  fireEvent.click(screen.getByTestId('zone-save'))
  expect(await screen.findByText('Gagal menyimpan zona')).toBeInTheDocument()
  expect(screen.queryByText('Kamera ini sudah punya zona absensi aktif dengan arah lain.')).toBeNull()
})

test('tipe Attendance: arah + petunjuk area wajah, tanpa input trigger', async () => {
  const fetchMock = await selectZone([
    zoneFix({ type: 'attendance', direction: 'entry', behaviors: [{ kind: 'attendance', trigger_seconds: 0 }] }),
  ])

  expect(screen.getByLabelText('Masuk')).toBeInTheDocument()
  expect(screen.queryByTestId('zone-behavior-intrusion')).not.toBeInTheDocument()
  expect(screen.queryByTestId('zone-trigger')).not.toBeInTheDocument()
  expect(screen.getByTestId('zone-attendance-hint')).toHaveTextContent(/wajah/i)
  fireEvent.click(screen.getByTestId('zone-save'))

  await waitFor(() => expect(patchBody(fetchMock).direction).toBe('entry'))
})

test('zona Behavior tanpa behavior terpilih tetap tersimpan (zona visual)', async () => {
  const fetchMock = await selectZone([zoneFix()])

  expect(screen.getByTestId('zone-behavior-intrusion')).not.toBeChecked()
  fireEvent.click(screen.getByTestId('zone-save'))

  await waitFor(() => expect(patchBody(fetchMock).behaviors).toEqual([]))
})

test('simpan berhasil memunculkan notifikasi sukses', async () => {
  const created: Zone = { id: 10, camera_id: 1, name: 'Zona 1', type: 'behavior', direction: null, polygon: [[0.2, 0.2], [0.8, 0.2], [0.5, 0.8]], schedule: null, severity: 'warning', rate_limit_min: 5, trigger_seconds: 0, behaviors: [], snapshot: true, clip: true, telegram: false, active: true }
  vi.stubGlobal('fetch', stubFetch({ created }))
  render(<I18nProvider><ZonesPage /></I18nProvider>)
  await drawTriangle()

  fireEvent.click(screen.getByTestId('zone-save'))

  expect(await screen.findByTestId('zone-toast')).toHaveTextContent(/tersimpan/i)
})

test('hapus meminta konfirmasi dulu, batal tidak memanggil DELETE', async () => {
  const fetchMock = stubFetch({})
  vi.stubGlobal('fetch', fetchMock)
  render(<I18nProvider><ZonesPage /></I18nProvider>)
  await drawTriangle()

  fireEvent.click(screen.getByTestId('zone-delete'))

  expect(await screen.findByTestId('zone-delete-confirm')).toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([, i]) => i?.method === 'DELETE')).toBe(false)
})

test('rail kamera menampilkan jumlah zona per kamera dan menandai yang belum punya', async () => {
  vi.stubGlobal('fetch', stubFetch({ zones: [ZONE_CAM1] }))
  render(<I18nProvider><ZonesPage /></I18nProvider>)

  const rail = await screen.findByTestId('zone-rail')
  expect(rail).toBeInTheDocument()
  // cam 1 punya 1 zona dari stub; kamera lain kosong dan diberi kelas redup
  expect(screen.getByTestId('zone-rail-cam-1')).toHaveTextContent('1')
  expect(screen.getByTestId('zone-rail-cam-2').className).toContain('zone-rail__item--empty')
})

test('kamera terpilih awal adalah yang sudah punya zona, bukan kamera pertama', async () => {
  // CAM-01 tanpa zona, CAM-02 punya satu → rail harus membuka CAM-02
  const onCam2: Zone = { ...ZONE_CAM1, id: 6, camera_id: 2, camera_name: 'CAM-02' }
  vi.stubGlobal('fetch', stubFetch({ zones: [onCam2] }))
  render(<I18nProvider><ZonesPage /></I18nProvider>)

  await screen.findByTestId('zone-rail')
  await waitFor(() =>
    expect(screen.getByTestId('zone-rail-cam-2').getAttribute('aria-selected')).toBe('true'))
  expect(screen.getByTestId('zone-rail-cam-1').getAttribute('aria-selected')).toBe('false')
})

test('Telegram per behavior default off, dikirim di item behaviors; toggle zona lama hilang', async () => {
  const fetchMock = await selectZone([zoneFix({ behaviors: [{ kind: 'intrusion', trigger_seconds: 0 }] })])
  expect(document.getElementById('zone-telegram')).toBeNull()
  const tg = document.getElementById('zone-telegram-intrusion')!
  expect(tg).toHaveAttribute('aria-checked', 'false')
  fireEvent.click(tg)
  fireEvent.click(screen.getByTestId('zone-save'))
  await waitFor(() => expect(patchBody(fetchMock).behaviors).toEqual([
    { kind: 'intrusion', trigger_seconds: 0, telegram: true },
  ]))
})

test('zona absensi punya satu toggle Telegram pada behavior attendance', async () => {
  const fetchMock = await selectZone([zoneFix({ type: 'attendance', direction: 'entry',
    behaviors: [{ kind: 'attendance', trigger_seconds: 0 }] })])
  fireEvent.click(document.getElementById('zone-telegram-attendance')!)
  fireEvent.click(screen.getByTestId('zone-save'))
  await waitFor(() => expect(patchBody(fetchMock).behaviors).toEqual([
    { kind: 'attendance', trigger_seconds: 0, telegram: true },
  ]))
})
