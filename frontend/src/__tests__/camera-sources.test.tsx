import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import CamerasPage from '../features/config/CamerasPage'

type Call = { url: string; init?: RequestInit }
type Resp = { status: number; body?: unknown }

const ME = { id: 1, username: 'admin', role: 'admin' as const }
const SOURCE = {
  id: 11,
  name: 'NVR-A',
  kind: 'nvr' as const,
  host: '10.0.0.5',
  port: 554,
  vendor: null,
  default_credential_id: 31,
  enabled: true,
}
const GROUP = { id: 21, name: 'Lantai 1', sort_order: 0, enabled: true }
const PROFILE = { id: 31, name: 'nvr-main', username: 'viewer', secret_ref: 'env:CAMERA_TEST_SECRET', enabled: true }
const CAMERA = {
  id: 1,
  name: 'CAM-A',
  location: 'Lantai 1',
  host: '10.0.0.5',
  rtsp_main: '/vendor/main?profile=high',
  rtsp_sub: '/vendor/sub?profile=low',
  main_path: '/vendor/main?profile=high',
  sub_path: '/vendor/sub?profile=low',
  node_id: 1,
  source_id: SOURCE.id,
  location_group_id: GROUP.id,
  credential_override_id: null,
  source: SOURCE,
  location_group: GROUP,
  credential_override: null,
  enabled: true,
  status: 'online',
  probe_main: { res: '1920x1080', fps: 25, codec: 'h264' },
  probe_sub: { res: '640x360', fps: 15, codec: 'h264' },
}

function stubFetch(respond: (call: Call) => Resp | Promise<Resp>) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const call = { url, init }
    calls.push(call)
    const { status, body } = await respond(call)
    return { ok: status < 400, status, json: () => Promise.resolve(body) }
  }))
  return calls
}

function renderPage() {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/configuration?tab=cameras']}>
        <CamerasPage />
      </MemoryRouter>
    </I18nProvider>,
  )
}

function baseResponse(call: Call, cameras: unknown[] = [CAMERA]): Resp | null {
  if (call.url.endsWith('/auth/me')) return { status: 200, body: ME }
  if (call.url.endsWith('/stream-sources')) return { status: 200, body: [SOURCE] }
  if (call.url.endsWith('/location-groups')) return { status: 200, body: [GROUP] }
  if (call.url.endsWith('/credential-profiles')) return { status: 200, body: [PROFILE] }
  if (call.url.endsWith('/nodes')) return { status: 200, body: [{ id: 1, name: 'server', type: 'server', status: 'online' }] }
  if (call.url.endsWith('/cameras') && !call.init?.method) return { status: 200, body: cameras }
  return null
}

test('source, group, and credential options render without password fields', async () => {
  stubFetch((call) => baseResponse(call) ?? { status: 404 })
  renderPage()

  expect(await screen.findByText('NVR-A')).toBeInTheDocument()
  expect(screen.getAllByText('Lantai 1').length).toBeGreaterThan(0)
  expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
  expect((await screen.findAllByText(/NVR-A · 10\.0\.0\.5:554/)).length).toBeGreaterThan(0)

  await userEvent.click(screen.getByText('+ Tambah kamera'))
  const sourceSelect = await screen.findByLabelText('Sumber stream')
  expect(within(sourceSelect).getByText('NVR-A · 10.0.0.5:554')).toBeInTheDocument()
  await userEvent.selectOptions(sourceSelect, String(SOURCE.id))
  expect(within(screen.getByLabelText('Override kredensial')).getByText('nvr-main · viewer')).toBeInTheDocument()
})

test('creating a source camera sends exact paths and references', async () => {
  const calls = stubFetch((call) => {
    const fallback = baseResponse(call, [])
    if (fallback) return fallback
    if (call.url.endsWith('/cameras/probe')) {
      return {
        status: 200,
        body: {
          main: { res: '1920x1080', fps: 25, codec: 'h264' },
          sub: { res: '640x360', fps: 15, codec: 'h264' },
          main_path: '/vendor/high?profile=recording',
          sub_path: '/vendor/low?profile=ai',
        },
      }
    }
    if (call.url.endsWith('/cameras') && call.init?.method === 'POST') return { status: 200, body: CAMERA }
    return { status: 404 }
  })
  renderPage()
  await userEvent.click(await screen.findByText('+ Tambah kamera'))
  await userEvent.type(await screen.findByLabelText('Nama kamera'), 'CAM-B')
  const sourceSelect = await screen.findByLabelText('Sumber stream')
  await waitFor(() => expect(within(sourceSelect).getByText('NVR-A · 10.0.0.5:554')).toBeInTheDocument())
  await userEvent.selectOptions(sourceSelect, String(SOURCE.id))
  await userEvent.selectOptions(screen.getAllByLabelText('Grup lokasi').at(-1)!, String(GROUP.id))
  await userEvent.selectOptions(screen.getByLabelText('Override kredensial'), String(PROFILE.id))
  await userEvent.type(screen.getByLabelText('Path MAIN exact'), '/vendor/high?profile=recording')
  await userEvent.type(screen.getByLabelText('Path SUB exact'), '/vendor/low?profile=ai')
  await userEvent.click(screen.getByRole('button', { name: 'Probe stream' }))
  await waitFor(() => expect(screen.getByTestId('probe-box')).toHaveTextContent('1920x1080'))
  await userEvent.click(screen.getByRole('button', { name: 'Simpan' }))

  await waitFor(() => {
    const probe = calls.find((call) => call.url.endsWith('/cameras/probe'))
    const payload = JSON.parse(String(probe!.init!.body))
    expect(payload).toEqual({ source_id: SOURCE.id, credential_override_id: PROFILE.id, main_path: '/vendor/high?profile=recording', sub_path: '/vendor/low?profile=ai' })
    const create = calls.find((call) => call.url.endsWith('/cameras') && call.init?.method === 'POST')
    const saved = JSON.parse(String(create!.init!.body))
    expect(saved.source_id).toBe(SOURCE.id)
    expect(saved.location_group_id).toBe(GROUP.id)
    expect(saved.credential_override_id).toBe(PROFILE.id)
    expect(saved.main_path).toBe('/vendor/high?profile=recording')
    expect(saved.sub_path).toBe('/vendor/low?profile=ai')
    expect(saved.host).toBeUndefined()
  })
})

test('editing one exact path retains the other path', async () => {
  const calls = stubFetch((call) => {
    const fallback = baseResponse(call)
    if (fallback) return fallback
    if (call.url.endsWith('/cameras/probe')) {
      return {
        status: 200,
        body: {
          main: { res: '1280x720', fps: 20, codec: 'h265' },
          sub: { res: '640x360', fps: 15, codec: 'h265' },
          main_path: '/vendor/changed',
          sub_path: '/vendor/sub?profile=low',
        },
      }
    }
    if (call.url.endsWith('/cameras/1') && call.init?.method === 'PATCH') return { status: 200, body: CAMERA }
    return { status: 404 }
  })
  renderPage()
  await userEvent.click((await screen.findAllByRole('button', { name: 'Ubah' }))[0])
  const main = await screen.findByLabelText('Path MAIN exact')
  await waitFor(() => expect(screen.getByLabelText('Sumber stream')).toHaveValue(String(SOURCE.id)))
  expect(screen.getByLabelText('Grup lokasi')).toHaveValue(String(GROUP.id))
  await userEvent.clear(main)
  await userEvent.type(main, '/vendor/changed')
  await userEvent.click(screen.getByRole('button', { name: 'Probe stream' }))
  await waitFor(() => expect(screen.getByTestId('probe-box')).toHaveTextContent('1280x720'))
  await userEvent.click(screen.getByRole('button', { name: 'Simpan' }))

  await waitFor(() => {
    const patch = calls.find((call) => call.url.endsWith('/cameras/1') && call.init?.method === 'PATCH')
    const payload = JSON.parse(String(patch!.init!.body))
    expect(payload.main_path).toBe('/vendor/changed')
    expect(payload.sub_path).toBe('/vendor/sub?profile=low')
  })
})

test('import classifications are visible and unresolved changes block apply', async () => {
  const plan = {
    applied: false,
    total: 3,
    matched: 1,
    updated: 1,
    created: 0,
    unmatched: [
      { classification: 'NEW SOURCE', camera_id: null, matched: false, changed: false, before: null, after: { name: 'CAM-X', source: 'Missing', main_path: '/main' } },
      { classification: 'DUPLICATE', camera_id: null, matched: false, changed: false, before: null, after: { name: 'CAM-Y', source: 'NVR-A', main_path: '/vendor/main?profile=high' } },
    ],
    orphans: [],
    errors: ['CAM-X: NEW SOURCE', 'CAM-Y: duplicate input stream', 'CAM-Z: CREDENTIAL'],
    items: [
      { classification: 'NEW SOURCE', camera_id: null, matched: false, changed: false, before: null, after: { name: 'CAM-X', source: 'Missing', main_path: '/main' } },
      { classification: 'DUPLICATE', camera_id: null, matched: false, changed: false, before: null, after: { name: 'CAM-Y', source: 'NVR-A', main_path: '/vendor/main?profile=high' } },
      { classification: 'CREDENTIAL', camera_id: 9, matched: true, changed: true, before: { name: 'CAM-Z', host: '10.0.0.9', main_path: '/main' }, after: { name: 'CAM-Z', host: '10.0.0.9', main_path: '/main', credential_profile: 'missing-profile' } },
    ],
  }
  const calls = stubFetch((call) => {
    const fallback = baseResponse(call, [])
    if (fallback) return fallback
    if (call.url.endsWith('/cameras/import')) return { status: 200, body: plan }
    return { status: 404 }
  })
  renderPage()
  const file = new File(['rtsp://10.0.0.40/Streaming/Channels/101 (Unknown)\n'], 'inventory.txt', { type: 'text/plain' })
  const input = await screen.findByTestId('camera-import-input')
  fireEvent.change(input, { target: { files: [file] } })
  expect(await screen.findByTestId('camera-import-classifications')).toHaveTextContent('Sumber baru')
  expect(screen.getByTestId('camera-import-classifications')).toHaveTextContent('Duplikat')
  expect(screen.getByTestId('camera-import-classifications')).toHaveTextContent('Kredensial')
  expect(screen.getByRole('button', { name: 'Terapkan perubahan' })).toBeDisabled()
  expect(calls.some((call) => call.url.endsWith('/cameras/import?apply=true'))).toBe(false)
})

test('viewer cannot mutate sources, groups, or credential profiles', async () => {
  const calls = stubFetch((call) => {
    if (call.url.endsWith('/auth/me')) return { status: 200, body: { id: 2, username: 'viewer', role: 'viewer' } }
    if (call.url.endsWith('/cameras') && !call.init?.method) return { status: 200, body: [CAMERA] }
    return { status: 404 }
  })
  renderPage()

  expect(await screen.findByText('CAM-A')).toBeInTheDocument()
  expect(screen.queryByTestId('camera-sources-panel')).not.toBeInTheDocument()
  expect(screen.queryByTestId('source-create')).not.toBeInTheDocument()
  expect(screen.queryByTestId('group-create')).not.toBeInTheDocument()
  expect(screen.queryByTestId('profile-create')).not.toBeInTheDocument()
  expect(calls.some((call) => /(stream-sources|location-groups|credential-profiles)$/.test(call.url))).toBe(false)
})
