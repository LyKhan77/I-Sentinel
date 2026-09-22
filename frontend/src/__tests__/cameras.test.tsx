import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import CamerasPage from '../features/config/CamerasPage'

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
    probe_sub: { res: '640x360', fps: 15, codec: 'h264' },
  },
  {
    id: 2,
    name: 'CAM-02',
    location: null,
    host: '192.168.1.102',
    rtsp_main: null,
    rtsp_sub: null,
    node_id: null,
    enabled: false,
    status: 'unknown',
    probe_main: null,
    probe_sub: null,
  },
]

const NODES = [{ id: 1, name: 'server', type: 'server', status: 'online' }]

type Call = { url: string; init?: RequestInit }

type Resp = { status: number; body?: unknown }

function stubFetch(respond: (call: Call) => Resp | Promise<Resp>) {
  const calls: Call[] = []
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const call = { url, init }
    calls.push(call)
    const { status, body } = await respond(call)
    return { ok: status < 400, status, json: () => Promise.resolve(body) }
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

// lib ES2023 belum punya tipe Promise.withResolvers (ES2024); runtime vitest Node ≥22 mendukung
const promiseWithResolvers = Promise as unknown as {
  withResolvers<T>(): { promise: Promise<T>; resolve: (v: T) => void }
}

function renderPage(initial = '/configuration?tab=cameras') {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[initial]}>
        <CamerasPage />
      </MemoryRouter>
    </I18nProvider>,
  )
}

test('renders camera rows from mocked list', async () => {
  stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/cameras')) return { status: 200, body: CAMS }
    return { status: 404 }
  })
  renderPage()
  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  expect(screen.getByText('CAM-02')).toBeInTheDocument()
  // stream chips: MAIN + SUB per kamera
  expect(screen.getByText(/2560x1440 · 25fps · h264/)).toBeInTheDocument()
  expect(screen.getByText(/640x360 · 15fps · h264/)).toBeInTheDocument()
})

test('wizard: auto-detect scan enables Simpan with selected channel paths', async () => {
  const SCAN = [
    { channel: 1, main: { res: '1920x1080', fps: 25, codec: 'h264' }, sub: { res: '640x480', fps: 25, codec: 'h264' }, main_path: '/Streaming/Channels/101', sub_path: '/Streaming/Channels/102' },
    { channel: 2, main: { res: '1920x1080', fps: 25, codec: 'h264' }, sub: { res: '640x480', fps: 25, codec: 'h264' }, main_path: '/Streaming/Channels/201', sub_path: '/Streaming/Channels/202' },
  ]
  const calls = stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/cameras/scan')) {
      return { status: 200, body: { streams: SCAN } }
    }
    if (call.url.endsWith('/cameras') && call.init?.method === 'POST') {
      return { status: 200, body: CAMS[0] }
    }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: [] }
    return { status: 404 }
  })
  renderPage()

  // buka wizard
  await waitFor(() => expect(screen.getByText('+ Tambah kamera')).toBeEnabled())
  await userEvent.click(screen.getByText('+ Tambah kamera'))

  await userEvent.type(await screen.findByLabelText('Nama kamera'), 'CAM-06')
  await userEvent.type(screen.getByLabelText('IP / Host'), '192.168.1.108')

  const saveBtn = screen.getByRole('button', { name: 'Simpan' })
  expect(saveBtn).toBeDisabled()

  await userEvent.click(screen.getByRole('button', { name: 'Deteksi otomatis' }))
  await waitFor(() => expect(screen.getByTestId('probe-box')).toHaveTextContent('1920x1080'))

  // hasil scan pertama otomatis terpilih
  expect((screen.getByLabelText('Stream terdeteksi') as HTMLSelectElement).value).toBe('1')
  await waitFor(() => expect(screen.getByTestId('probe-box').closest('[role=dialog]')!.textContent).toContain('channel terdeteksi'))

  expect(saveBtn).toBeEnabled()
  await userEvent.click(saveBtn)

  await waitFor(() => {
    const post = calls.find((c) => c.url.endsWith('/cameras') && c.init?.method === 'POST')
    expect(post).toBeDefined()
    const payload = JSON.parse(String(post!.init!.body))
    expect(payload.name).toBe('CAM-06')
    expect(payload.host).toBe('192.168.1.108')
    expect(payload.node_id).toBe(1)
    expect(payload.rtsp_main).toBe('/Streaming/Channels/101')
    expect(payload.rtsp_sub).toBe('/Streaming/Channels/102')
  })
})

test('wizard: scan without result offers manual paths, Simpan stays disabled', async () => {
  stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/cameras/scan')) return { status: 200, body: { streams: [] } }
    if (call.url.endsWith('/cameras/probe')) return { status: 500, body: null }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: [] }
    return { status: 404 }
  })
  renderPage()

  await waitFor(() => expect(screen.getByText('+ Tambah kamera')).toBeEnabled())
  await userEvent.click(screen.getByText('+ Tambah kamera'))

  await screen.findByLabelText('Nama kamera')
  await userEvent.type(screen.getByLabelText('Nama kamera'), 'CAM-06')
  await userEvent.type(screen.getByLabelText('IP / Host'), '10.0.0.99')

  await userEvent.click(screen.getByRole('button', { name: 'Deteksi otomatis' }))
  await waitFor(() => expect(screen.getByText('Tidak ada channel NVR terdeteksi. Gunakan isi path manual.')).toBeInTheDocument())

  expect(screen.getByRole('button', { name: 'Simpan' })).toBeDisabled()

  // fallback manual: isi path lalu probe exact
  await userEvent.click(screen.getByRole('button', { name: 'Isi path manual' }))
  await userEvent.type(screen.getByLabelText('Path MAIN (utama)'), '/Streaming/Channels/101')
  expect(screen.getByRole('button', { name: 'Simpan' })).toBeDisabled()
})

test('edit: form prefilled, metadata-only save PATCHes name and location', async () => {
  const calls = stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/cameras/1') && call.init?.method === 'PATCH') return { status: 200, body: CAMS[0] }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: CAMS }
    return { status: 404 }
  })
  renderPage()

  const [editBtn] = await screen.findAllByRole('button', { name: 'Ubah' })
  await userEvent.click(editBtn)

  expect(await screen.findByText('Ubah kamera')).toBeInTheDocument()
  expect(screen.getByLabelText('Nama kamera')).toHaveValue('CAM-01')
  expect(screen.getByLabelText('Lokasi')).toHaveValue('Gerbang Masuk')
  expect(screen.getByLabelText('IP / Host')).toHaveValue('192.168.1.101')
  // probe tersimpan tampil di form edit
  expect(screen.getByTestId('probe-box')).toHaveTextContent('2560x1440')

  await userEvent.clear(screen.getByLabelText('Lokasi'))
  await userEvent.type(screen.getByLabelText('Lokasi'), 'Lobi Utara')
  await userEvent.click(screen.getByRole('button', { name: 'Simpan' }))

  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/cameras/1') && c.init?.method === 'PATCH')
    expect(patch).toBeDefined()
    expect(JSON.parse(String(patch!.init!.body))).toEqual({ name: 'CAM-01', location: 'Lobi Utara' })
  })
})

test('edit: connection change needs a fresh probe before save', async () => {
  const FRESH = {
    main: { res: '1280x720', fps: 20, codec: 'h265' },
    sub: { res: '640x360', fps: 15, codec: 'h265' },
    main_path: 'rtsp://192.168.1.109/Streaming/Channels/101',
    sub_path: 'rtsp://192.168.1.109/Streaming/Channels/102',
  }
  const calls = stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/cameras/probe')) return { status: 200, body: FRESH }
    if (call.url.endsWith('/cameras/1') && call.init?.method === 'PATCH') return { status: 200, body: CAMS[0] }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: CAMS }
    return { status: 404 }
  })
  renderPage()

  const [editBtn] = await screen.findAllByRole('button', { name: 'Ubah' })
  await userEvent.click(editBtn)

  const hostInput = await screen.findByLabelText('IP / Host')
  expect(screen.getByTestId('probe-box')).toHaveTextContent('/Streaming/Channels/101')
  await userEvent.clear(hostInput)
  await userEvent.type(hostInput, '192.168.1.109')

  // probe lama dibuang, simpan menunggu probe baru
  expect(screen.getByTestId('probe-box')).not.toHaveTextContent('192.168.1.101')
  const saveBtn = screen.getByRole('button', { name: 'Simpan' })
  expect(saveBtn).toBeDisabled()

  await userEvent.click(screen.getByRole('button', { name: 'Probe stream' }))
  await waitFor(() => expect(screen.getByTestId('probe-box')).toHaveTextContent('rtsp://192.168.1.109'))
  expect(saveBtn).toBeEnabled()
  // probe murni: belum ada PATCH sebelum Simpan
  expect(calls.some((c) => c.init?.method === 'PATCH')).toBe(false)

  await userEvent.click(saveBtn)

  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/cameras/1') && c.init?.method === 'PATCH')
    expect(patch).toBeDefined()
    const payload = JSON.parse(String(patch!.init!.body))
    expect(payload.name).toBe('CAM-01')
    expect(payload.host).toBe('192.168.1.109')
    expect(payload.node_id).toBe(1)
    expect(payload.rtsp_main).toBe('rtsp://192.168.1.109/Streaming/Channels/101')
    expect(payload.rtsp_sub).toBe('rtsp://192.168.1.109/Streaming/Channels/102')
    // metadata probe ikut tersimpan lewat PATCH saat Simpan
    expect(payload.probe_main).toEqual(FRESH.main)
    expect(payload.probe_sub).toEqual(FRESH.sub)
    expect(payload.status).toBe('online')
    // probe edit tidak mengirim camera_id (tanpa persist di server)
    const probeCall = calls.find((c) => c.url.endsWith('/cameras/probe'))
    expect(JSON.parse(String(probeCall!.init!.body))).toEqual({
      host: '192.168.1.109',
      main_path: '/Streaming/Channels/101',
      sub_path: '/Streaming/Channels/102',
    })
  })
})

test('edit: response of the old host probe cannot overwrite the new host result', async () => {
  const stale = promiseWithResolvers.withResolvers<void>()
  const STALE = {
    main: { res: '2560x1440', fps: 25, codec: 'h264' },
    sub: { res: '640x360', fps: 15, codec: 'h264' },
    main_path: 'rtsp://192.168.1.101/Streaming/Channels/101',
    sub_path: 'rtsp://192.168.1.101/Streaming/Channels/102',
  }
  const FRESH = {
    main: { res: '1280x720', fps: 20, codec: 'h265' },
    sub: { res: '640x360', fps: 15, codec: 'h265' },
    main_path: 'rtsp://192.168.1.109/Streaming/Channels/101',
    sub_path: 'rtsp://192.168.1.109/Streaming/Channels/102',
  }
  stubFetch(async (call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/cameras/probe')) {
      const body = JSON.parse(String(call.init?.body)) as { host: string } // body probe selalu { host }
      if (body.host === '192.168.1.101') {
        await stale.promise // respons host lama sengaja ditahan
        return { status: 200, body: STALE }
      }
      return { status: 200, body: FRESH }
    }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: CAMS }
    return { status: 404 }
  })
  renderPage()

  const [editBtn] = await screen.findAllByRole('button', { name: 'Ubah' })
  await userEvent.click(editBtn)

  // probe host lama dibiarkan in-flight, host diganti lalu di-probe ulang
  const hostInput = await screen.findByLabelText('IP / Host')
  await userEvent.click(screen.getByRole('button', { name: 'Probe stream' }))
  await userEvent.clear(hostInput)
  await userEvent.type(hostInput, '192.168.1.109')
  await userEvent.click(screen.getByRole('button', { name: 'Probe stream' }))
  await waitFor(() => expect(screen.getByTestId('probe-box')).toHaveTextContent('1280x720'))

  // respons host lama baru tiba: tidak boleh menimpa hasil host baru
  stale.resolve(undefined)
  const tick = promiseWithResolvers.withResolvers<void>()
  setTimeout(tick.resolve, 0)
  await act(async () => {
    await tick.promise
  })

  expect(screen.getByTestId('probe-box')).toHaveTextContent('1280x720')
  expect(screen.getByTestId('probe-box')).not.toHaveTextContent('2560x1440')
  expect(screen.getByRole('button', { name: 'Simpan' })).toBeEnabled()
})

test('admin previews and applies CCTV inventory keyed by stream path', async () => {
  const plan = {
    applied: false,
    total: 2,
    matched: 2,
    updated: 2,
    unmatched: [],
    errors: [],
    items: [],
  }
  const calls = stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/cameras/import') || call.url.endsWith('/cameras/import?apply=true')) {
      return { status: 200, body: call.url.endsWith('?apply=true') ? { ...plan, applied: true } : plan }
    }
    if (call.url.endsWith('/cameras')) return { status: 200, body: CAMS }
    return { status: 404 }
  })
  renderPage()

  const file = new File([
    'rtsp://192.168.2.184:554/Streaming/Channels/101 (Lantai 3 - IOT samping)\n',
    'rtsp://192.168.2.184:554/Streaming/Channels/201 (Lantai 3 - IOT Belakang Pojok)\n',
  ], 'cctv-list.txt', { type: 'text/plain' })
  fireEvent.change(await screen.findByTestId('camera-import-input'), { target: { files: [file] } })

  expect(await screen.findByText('2 kamera · 2 cocok · 2 berubah')).toBeInTheDocument()
  const preview = calls.find((call) => call.url.endsWith('/cameras/import'))
  expect(JSON.parse(String(preview!.init!.body)).entries).toEqual([
    {
      name: 'NVR-CAM-01',
      location: 'Lantai 3 - IOT samping',
      host: '192.168.2.184:554',
      rtsp_main: '/Streaming/Channels/101',
      rtsp_sub: '/Streaming/Channels/102',
    },
    {
      name: 'NVR-CAM-02',
      location: 'Lantai 3 - IOT Belakang Pojok',
      host: '192.168.2.184:554',
      rtsp_main: '/Streaming/Channels/201',
      rtsp_sub: '/Streaming/Channels/202',
    },
  ])

  await userEvent.click(screen.getByRole('button', { name: 'Terapkan perubahan' }))
  await waitFor(() => expect(calls.some((call) => call.url.endsWith('/cameras/import?apply=true'))).toBe(true))
})

test('viewer cannot edit cameras', async () => {
  stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: { id: 2, username: 'viewer', role: 'viewer' } }
    if (call.url.endsWith('/cameras')) return { status: 200, body: CAMS }
    return { status: 404 }
  })
  renderPage()

  const [editBtn] = await screen.findAllByRole('button', { name: 'Ubah' })
  expect(editBtn).toBeDisabled()
  expect(screen.queryByTestId('camera-import-btn')).not.toBeInTheDocument()
  await userEvent.click(editBtn)
  expect(screen.queryByText('Ubah kamera')).not.toBeInTheDocument()
})

test('tombol Sync go2rtc memanggil endpoint dan menampilkan hasil', async () => {
  const calls = stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/cameras/sync-go2rtc') && call.init?.method === 'POST') {
      return { status: 200, body: { added: ['cam_364', 'cam_364_main'], removed: ['cam_9'], kept: 4 } }
    }
    if (call.url.endsWith('/cameras')) return { status: 200, body: CAMS }
    return { status: 404 }
  })
  renderPage()

  await waitFor(() => expect(screen.getByText('CAM-01')).toBeInTheDocument())
  await userEvent.click(screen.getByTestId('go2rtc-sync'))

  await waitFor(() => expect(screen.getByTestId('go2rtc-sync-result')).toBeInTheDocument())
  expect(calls.some((c) => c.url.endsWith('/cameras/sync-go2rtc') && c.init?.method === 'POST')).toBe(true)
  // pesan hasil: jumlah added/removed, bukan daftar mentah
  expect(screen.getByTestId('go2rtc-sync-result')).toHaveTextContent('+2')
  expect(screen.getByTestId('go2rtc-sync-result').textContent).toContain('1')
})
