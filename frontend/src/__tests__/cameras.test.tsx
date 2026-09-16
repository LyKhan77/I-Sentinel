import { render, screen, waitFor } from '@testing-library/react'
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

function stubFetch(respond: (call: Call) => { status: number; body?: unknown }) {
  const calls: Call[] = []
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const call = { url, init }
    calls.push(call)
    const { status, body } = respond(call)
    return { ok: status < 400, status, json: () => Promise.resolve(body) }
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
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

test('wizard: probe success enables Simpan, payload carries rtsp paths', async () => {
  const calls = stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
    if (call.url.endsWith('/cameras') && call.init?.method === 'POST') {
      return { status: 200, body: CAMS[0] }
    }
    if (call.url.endsWith('/cameras/probe')) {
      return {
        status: 200,
        body: {
          main: { res: '2560x1440', fps: 25, codec: 'h264' },
          sub: { res: '640x360', fps: 15, codec: 'h264' },
          main_path: 'rtsp://u:p@192.168.1.108/Streaming/Channels/101',
          sub_path: 'rtsp://u:p@192.168.1.108/Streaming/Channels/102',
        },
      }
    }
    if (call.url.endsWith('/nodes')) return { status: 200, body: NODES }
    if (call.url.endsWith('/cameras')) return { status: 200, body: [] }
    return { status: 404 }
  })
  renderPage()

  // buka wizard
  await waitFor(() => expect(screen.getByText('+ Tambah kamera')).toBeEnabled())
  await userEvent.click(screen.getByText('+ Tambah kamera'))

  const nameInput = await screen.findByLabelText('Nama kamera')
  const hostInput = screen.getByLabelText('IP / Host')
  await userEvent.type(nameInput, 'CAM-06')
  await userEvent.type(hostInput, '192.168.1.108')

  const saveBtn = screen.getByRole('button', { name: 'Simpan' })
  expect(saveBtn).toBeDisabled()

  await userEvent.click(screen.getByRole('button', { name: 'Probe stream' }))
  await waitFor(() => expect(screen.getByTestId('probe-box')).toHaveTextContent('2560x1440'))

  expect(saveBtn).toBeEnabled()
  await userEvent.click(saveBtn)

  await waitFor(() => {
    const post = calls.find((c) => c.url.endsWith('/cameras') && c.init?.method === 'POST')
    expect(post).toBeDefined()
    const payload = JSON.parse(String(post!.init!.body))
    expect(payload.name).toBe('CAM-06')
    expect(payload.host).toBe('192.168.1.108')
    expect(payload.node_id).toBe(1)
    expect(payload.rtsp_main).toBe('rtsp://u:p@192.168.1.108/Streaming/Channels/101')
    expect(payload.rtsp_sub).toBe('rtsp://u:p@192.168.1.108/Streaming/Channels/102')
  })
})

test('wizard: probe failure keeps Simpan disabled', async () => {
  stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
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

  await userEvent.click(screen.getByRole('button', { name: 'Probe stream' }))
  await waitFor(() => expect(screen.getByTestId('probe-box')).toHaveTextContent('gagal · timeout'))

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
    main_path: 'rtsp://u:p@192.168.1.109/Streaming/Channels/101',
    sub_path: 'rtsp://u:p@192.168.1.109/Streaming/Channels/102',
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
  expect(screen.getByTestId('probe-box')).toHaveTextContent('192.168.1.101')
  await userEvent.clear(hostInput)
  await userEvent.type(hostInput, '192.168.1.109')

  // probe lama dibuang, simpan menunggu probe baru
  expect(screen.getByTestId('probe-box')).not.toHaveTextContent('192.168.1.101')
  const saveBtn = screen.getByRole('button', { name: 'Simpan' })
  expect(saveBtn).toBeDisabled()

  await userEvent.click(screen.getByRole('button', { name: 'Probe stream' }))
  await waitFor(() => expect(screen.getByTestId('probe-box')).toHaveTextContent('rtsp://u:p@192.168.1.109'))
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
    expect(payload.rtsp_main).toBe('rtsp://u:p@192.168.1.109/Streaming/Channels/101')
    expect(payload.rtsp_sub).toBe('rtsp://u:p@192.168.1.109/Streaming/Channels/102')
    // metadata probe ikut tersimpan lewat PATCH saat Simpan
    expect(payload.probe_main).toEqual(FRESH.main)
    expect(payload.probe_sub).toEqual(FRESH.sub)
    expect(payload.status).toBe('online')
    // probe edit tidak mengirim camera_id (tanpa persist di server)
    const probeCall = calls.find((c) => c.url.endsWith('/cameras/probe'))
    expect(JSON.parse(String(probeCall!.init!.body))).toEqual({ host: '192.168.1.109' })
  })
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
  await userEvent.click(editBtn)
  expect(screen.queryByText('Ubah kamera')).not.toBeInTheDocument()
})
