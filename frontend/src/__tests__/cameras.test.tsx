import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

const PROFILES = [
  { id: 31, name: 'zkteco', username: 'admin', secret_ref: 'store:cred_31', enabled: true },
  { id: 32, name: 'lama', username: 'x', secret_ref: 'store:cred_32', enabled: false },
]

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
    if (call.url.endsWith('/stream-sources')) return { status: 200, body: [] }
    if (call.url.endsWith('/credential-profiles')) return { status: 200, body: PROFILES }
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
  await userEvent.type(screen.getByLabelText('IP kamera'), '192.168.1.108')

  const saveBtn = screen.getByRole('button', { name: 'Simpan' })
  expect(saveBtn).toBeDisabled()

  await userEvent.click(within(screen.getByTestId('wiz-advanced')).getByText('Lanjutan'))
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
    expect(payload.credential_override_id).toBeNull()
  })
})

test('wizard: untested camera needs a second Simpan click', async () => {
  const calls = stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/stream-sources')) return { status: 200, body: [] }
    if (call.url.endsWith('/credential-profiles')) return { status: 200, body: PROFILES }
    if (call.url.endsWith('/cameras') && call.init?.method === 'POST') return { status: 200, body: CAMS[0] }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: [] }
    return { status: 404 }
  })
  renderPage()
  await userEvent.click(await screen.findByText('+ Tambah kamera'))
  await userEvent.type(await screen.findByLabelText('Nama kamera'), 'CAM-07')
  await userEvent.type(screen.getByLabelText('IP kamera'), '10.0.0.99')
  const save = screen.getByRole('button', { name: 'Simpan' })
  expect(save).toBeDisabled() // path mainstream wajib
  await userEvent.type(screen.getByLabelText('Path mainstream'), '/Streaming/Channels/101')
  expect(save).toBeEnabled()

  await userEvent.click(save)
  expect(await screen.findByText('Koneksi belum dites. Klik Simpan sekali lagi untuk tetap menyimpan.')).toBeInTheDocument()
  expect(calls.some((c) => c.init?.method === 'POST' && c.url.endsWith('/cameras'))).toBe(false)

  await userEvent.click(save)
  await waitFor(() => expect(calls.some((c) => c.init?.method === 'POST' && c.url.endsWith('/cameras'))).toBe(true))
})

test('edit: form prefilled, metadata-only save PATCHes name and location', async () => {
  const calls = stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/stream-sources')) return { status: 200, body: [] }
    if (call.url.endsWith('/credential-profiles')) return { status: 200, body: PROFILES }
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
  expect(screen.getByLabelText('IP kamera')).toHaveValue('192.168.1.101')
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
    if (call.url.endsWith('/stream-sources')) return { status: 200, body: [] }
    if (call.url.endsWith('/credential-profiles')) return { status: 200, body: PROFILES }
    if (call.url.endsWith('/cameras/probe')) return { status: 200, body: FRESH }
    if (call.url.endsWith('/cameras/1') && call.init?.method === 'PATCH') return { status: 200, body: CAMS[0] }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: CAMS }
    return { status: 404 }
  })
  renderPage()

  const [editBtn] = await screen.findAllByRole('button', { name: 'Ubah' })
  await userEvent.click(editBtn)

  const hostInput = await screen.findByLabelText('IP kamera')
  expect(screen.getByTestId('probe-box')).toHaveTextContent('/Streaming/Channels/101')
  await userEvent.clear(hostInput)
  await userEvent.type(hostInput, '192.168.1.109')

  // probe lama dibuang, simpan menunggu probe baru
  expect(screen.getByTestId('probe-box')).not.toHaveTextContent('192.168.1.101')
  const saveBtn = screen.getByRole('button', { name: 'Simpan' })
  await userEvent.click(saveBtn)
  expect(screen.getByText('Koneksi belum dites. Klik Simpan sekali lagi untuk tetap menyimpan.')).toBeInTheDocument()
  expect(calls.some((c) => c.init?.method === 'PATCH')).toBe(false)

  await userEvent.click(screen.getByRole('button', { name: 'Tes koneksi' }))
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
    expect(payload.credential_override_id).toBeNull()
    // probe edit tidak mengirim camera_id (tanpa persist di server)
    const probeCall = calls.find((c) => c.url.endsWith('/cameras/probe'))
    expect(JSON.parse(String(probeCall!.init!.body))).toEqual({
      host: '192.168.1.109',
      main_path: '/Streaming/Channels/101',
      sub_path: '/Streaming/Channels/102',
      snapshot: true,
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
    if (call.url.endsWith('/stream-sources')) return { status: 200, body: [] }
    if (call.url.endsWith('/credential-profiles')) return { status: 200, body: PROFILES }
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
  const hostInput = await screen.findByLabelText('IP kamera')
  await userEvent.click(screen.getByRole('button', { name: 'Tes koneksi' }))
  await userEvent.clear(hostInput)
  await userEvent.type(hostInput, '192.168.1.109')
  await userEvent.click(screen.getByRole('button', { name: 'Tes koneksi' }))
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

test('wizard: main form is short; Node and NVR scan live under Lanjutan', async () => {
  stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/stream-sources')) return { status: 200, body: [] }
    if (call.url.endsWith('/credential-profiles')) return { status: 200, body: PROFILES }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: CAMS }
    return { status: 404 }
  })
  renderPage()
  await userEvent.click(await screen.findByText('+ Tambah kamera'))
  await screen.findByLabelText('Nama kamera')
  for (const label of ['Lokasi', 'IP kamera', 'Path mainstream', 'Path substream', 'Kredensial']) {
    expect(screen.getByLabelText(label)).toBeInTheDocument()
  }
  expect(screen.getByTestId('wiz-advanced')).not.toHaveAttribute('open')
  expect(screen.queryByLabelText('Node')).not.toBeInTheDocument() // hanya 1 node
  const options = [...(screen.getByLabelText('Kredensial') as HTMLSelectElement).options].map((o) => o.text)
  expect(options).toEqual(['Default (NVR)', 'zkteco', '+ Kredensial baru…']) // profil nonaktif disembunyikan
})

test('wizard: new credential from the inline form is selected and sent', async () => {
  const created = { id: 33, name: 'Gudang', username: 'admin', secret_ref: 'store:cred_33', enabled: true }
  const calls = stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/stream-sources')) return { status: 200, body: [] }
    if (call.url.endsWith('/credential-profiles') && call.init?.method === 'POST') return { status: 200, body: created }
    if (call.url.endsWith('/credential-profiles')) return { status: 200, body: PROFILES }
    if (call.url.endsWith('/cameras/probe')) {
      return { status: 200, body: { main: { res: '1920x1080', fps: 25, codec: 'h264' }, sub: null,
        main_path: '/stream', sub_path: null, snapshot_jpeg_b64: 'QUJD' } }
    }
    if (call.url.endsWith('/cameras') && call.init?.method === 'POST') return { status: 200, body: CAMS[0] }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: [] }
    return { status: 404 }
  })
  renderPage()
  await userEvent.click(await screen.findByText('+ Tambah kamera'))
  await userEvent.type(await screen.findByLabelText('Nama kamera'), 'Gudang')
  await userEvent.type(screen.getByLabelText('IP kamera'), '192.168.2.179:8554')
  await userEvent.type(screen.getByLabelText('Path mainstream'), '/stream')
  await userEvent.selectOptions(screen.getByLabelText('Kredensial'), 'new')
  await userEvent.type(await screen.findByLabelText('Nama kredensial'), 'Gudang')
  await userEvent.type(screen.getByLabelText('Password', { selector: 'input' }), 'Rahasia#1')
  await userEvent.click(screen.getByRole('button', { name: 'Simpan kredensial' }))
  await waitFor(() => expect((screen.getByLabelText('Kredensial') as HTMLSelectElement).value).toBe('33'))

  await userEvent.click(screen.getByRole('button', { name: 'Tes koneksi' }))
  expect(await screen.findByTestId('probe-thumb')).toHaveAttribute('src', 'data:image/jpeg;base64,QUJD')
  await userEvent.click(screen.getByRole('button', { name: 'Simpan' }))
  await waitFor(() => {
    const probe = calls.find((c) => c.url.endsWith('/cameras/probe'))
    expect(JSON.parse(String(probe!.init!.body))).toMatchObject({ credential_override_id: 33, snapshot: true })
    const create = calls.find((c) => c.url.endsWith('/cameras') && c.init?.method === 'POST')
    const saved = JSON.parse(String(create!.init!.body))
    expect(saved.host).toBe('192.168.2.179:8554')
    expect(saved.credential_override_id).toBe(33)
  })
})

test('wizard: pasted RTSP URL keeps only the path and warns when sub equals main', async () => {
  const calls = stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/stream-sources')) return { status: 200, body: [] }
    if (call.url.endsWith('/credential-profiles')) return { status: 200, body: PROFILES }
    if (call.url.endsWith('/cameras/probe')) return { status: 200, body: { main: null, sub: null, main_path: null, sub_path: null } }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: [] }
    return { status: 404 }
  })
  renderPage()
  await userEvent.click(await screen.findByText('+ Tambah kamera'))
  await userEvent.type(await screen.findByLabelText('IP kamera'), '10.0.0.5')
  await userEvent.type(screen.getByLabelText('Path mainstream'), 'rtsp://admin:rahasia@10.0.0.5/Streaming/Channels/101')
  await userEvent.type(screen.getByLabelText('Path substream'), '/Streaming/Channels/101')
  expect(screen.getByText('Substream sama dengan mainstream — AI akan memproses resolusi penuh.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Tes koneksi' }))
  await waitFor(() => {
    const probe = calls.find((c) => c.url.endsWith('/cameras/probe'))
    const body = String(probe!.init!.body)
    expect(JSON.parse(body).main_path).toBe('/Streaming/Channels/101')
    expect(body).not.toContain('rahasia')
  })
})

test('edit: switching credential sends credential_override_id; disabled profile stays selected', async () => {
  const withDisabled = [{ ...CAMS[0], credential_override_id: 32, credential_override: { id: 32, name: 'lama', username: 'x', enabled: false } }]
  const calls = stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/stream-sources')) return { status: 200, body: [] }
    if (call.url.endsWith('/credential-profiles')) return { status: 200, body: PROFILES }
    if (call.url.endsWith('/cameras/1') && call.init?.method === 'PATCH') return { status: 200, body: CAMS[0] }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: withDisabled }
    return { status: 404 }
  })
  renderPage()
  await userEvent.click((await screen.findAllByRole('button', { name: 'Ubah' }))[0])
  const select = (await screen.findByLabelText('Kredensial')) as HTMLSelectElement
  expect(select.value).toBe('32')

  await userEvent.selectOptions(select, '31')
  const save = screen.getByRole('button', { name: 'Simpan' })
  await userEvent.click(save) // belum dites → peringatan
  await userEvent.click(save)
  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/cameras/1') && c.init?.method === 'PATCH')
    expect(JSON.parse(String(patch!.init!.body)).credential_override_id).toBe(31)
  })
})
