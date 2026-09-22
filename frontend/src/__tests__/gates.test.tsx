import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import GatesPage from '../features/config/GatesPage'
import type { Zone } from '../api/zones'

const ME = { id: 1, username: 'admin', role: 'admin' }
const VIEWER = { id: 2, username: 'viewer', role: 'viewer' }

function gate(id: number, direction: 'entry' | 'exit'): Zone {
  return {
    id,
    camera_id: 1,
    name: direction === 'entry' ? 'Gate Entry' : 'Gate Exit',
    type: 'attendance',
    direction,
    polygon: [
      [0.1, 0.1],
      [0.9, 0.1],
      [0.9, 0.9],
    ],
    schedule: null,
    severity: 'warning',
    rate_limit_min: 5,
    snapshot: true, clip: true,
    telegram: false,
    active: true,
    trigger_seconds: 0,
    behaviors: [{ kind: 'attendance', trigger_seconds: 0 }],
    camera_name: 'CAM-01',
  }
}

const CAMS = [
  { id: 1, name: 'CAM-01', location: null, host: '1.2.3.4', rtsp_main: null, rtsp_sub: null, node_id: 1, enabled: true, status: 'online', probe_main: null, probe_sub: null },
]

const resp = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })

function stubFetch(zones: Zone[], me = ME) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    if (u.endsWith('/auth/me')) return resp(200, me)
    if (u.includes('/zones/') && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body))
      const z = zones.find((x) => u.endsWith(`/zones/${x.id}`))!
      return resp(200, { ...z, ...body })
    }
    if (u.endsWith('/zones')) return resp(200, zones)
    if (u.endsWith('/cameras')) return resp(200, CAMS)
    return resp(404, null)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderPage() {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/configuration?tab=gates']}>
        <GatesPage />
      </MemoryRouter>
    </I18nProvider>,
  )
}

test('warns when one camera has two active gates with different directions', async () => {
  stubFetch([gate(1, 'entry'), gate(2, 'exit')])
  renderPage()

  expect(await screen.findByTestId('gate-conflict-msg')).toHaveTextContent('Validasi: satu kamera hanya boleh satu arah.')
  expect(screen.getAllByText('KONFLIK').length).toBeGreaterThanOrEqual(1)
  expect(screen.getAllByText('CAM-01').length).toBeGreaterThanOrEqual(1)
})

test('no conflict when directions agree', async () => {
  stubFetch([gate(1, 'entry')])
  renderPage()

  await screen.findByTestId('gate-row-1')
  expect(screen.queryByTestId('gate-conflict-msg')).not.toBeInTheDocument()
})

test('viewer (non-admin) sees disabled mutation controls', async () => {
  stubFetch([gate(1, 'entry')], VIEWER)
  renderPage()

  await screen.findByTestId('gate-row-1')
  expect(screen.getByTestId('gate-add')).toBeDisabled()
  for (const combo of screen.getAllByRole('combobox')) expect(combo).toBeDisabled()
  for (const toggle of screen.getAllByRole('switch')) expect(toggle).toBeDisabled()
})

test('admin can add a gate zone', async () => {
  stubFetch([gate(1, 'entry')])
  renderPage()

  await screen.findByTestId('gate-row-1')
  expect(screen.getByTestId('gate-add')).toBeEnabled()
  expect(screen.getAllByRole('combobox')[1]).toBeEnabled()
})

test('admin ubah trigger threshold per gate (PATCH trigger_seconds + behaviors)', async () => {
  const fetchMock = stubFetch([gate(1, 'entry')])
  renderPage()

  await screen.findByTestId('gate-row-1')
  const trigger = screen.getByTestId('gate-trigger-1')
  expect(trigger).toHaveValue(0)
  fireEvent.change(trigger, { target: { value: '3' } })

  await waitFor(() => {
    const patch = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith('/zones/1') && i?.method === 'PATCH')
    expect(patch).toBeTruthy()
    expect(JSON.parse(String(patch![1]!.body))).toEqual({
      trigger_seconds: 3,
      behaviors: [{ kind: 'attendance', trigger_seconds: 3 }],
    })
  })
})

test('viewer tidak bisa ubah trigger threshold', async () => {
  stubFetch([gate(1, 'entry')], VIEWER)
  renderPage()

  await screen.findByTestId('gate-row-1')
  expect(screen.getByTestId('gate-trigger-1')).toBeDisabled()
})
