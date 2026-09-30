import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import MonitoringPage from '../features/monitoring/MonitoringPage'

const RULES = [
  { rule: 'camera_no_frames', enabled: true, threshold: 30, duration_min: 2, severity: 'critical', telegram: true,
    unit: 's', min: 10, max: 600, target: 'camera' },
  { rule: 'gpu_temp', enabled: true, threshold: 85, duration_min: 5, severity: 'critical', telegram: true,
    unit: '°C', min: 50, max: 110, target: 'gpu' },
]
const ALERTS = {
  active: [{ id: 1, rule: 'gpu_temp', target: 'gpu:1:0', label: 'GPU 0 · server', node_id: 1, camera_id: null,
    severity: 'critical', value: 90, threshold: 85, unit: '°C', started_at: '2026-09-30T07:50:00Z', resolved_at: null }],
  recent: [{ id: 2, rule: 'camera_no_frames', target: 'cam:3', label: 'Lorong', node_id: 1, camera_id: 3,
    severity: 'critical', value: null, threshold: 30, unit: 's', started_at: '2026-09-30T06:00:00Z',
    resolved_at: '2026-09-30T06:12:00Z' }],
}

let puts: unknown[]
let putStatus = 200
function stub(role: 'admin' | 'viewer') {
  puts = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    if (u.endsWith('/auth/me')) return { ok: true, status: 200, json: () => Promise.resolve({ id: 1, username: 'u', role }) }
    if (u.endsWith('/monitoring/rules') && init?.method === 'PUT') {
      puts.push(JSON.parse(String(init.body)))
      return putStatus === 200
        ? { ok: true, status: 200, json: () => Promise.resolve(RULES) }
        : { ok: false, status: 422, json: () => Promise.resolve({ detail: 'x' }) }
    }
    if (u.endsWith('/monitoring/rules')) return { ok: true, status: 200, json: () => Promise.resolve(RULES) }
    if (u.endsWith('/monitoring/alerts')) return { ok: true, status: 200, json: () => Promise.resolve(ALERTS) }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  }))
}
afterEach(() => { vi.unstubAllGlobals(); putStatus = 200 })

const renderTab = (role: 'admin' | 'viewer') => {
  stub(role)
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/monitoring?tab=alerts']}>
        <Routes><Route element={<Outlet context={{ id: 1, username: 'u', role }} />}><Route path="/monitoring" element={<MonitoringPage />} /></Route></Routes>
      </MemoryRouter>
    </I18nProvider>)
}

test('alert aktif & riwayat tampil', async () => {
  renderTab('viewer')
  const row = await screen.findByTestId('alert-row-1')
  expect(row).toHaveTextContent('GPU panas')
  expect(row).toHaveTextContent('GPU 0 · server')
  expect(row).toHaveTextContent('90')
  expect(within(screen.getByTestId('alerts-recent')).getByText('Lorong')).toBeInTheDocument()
})

test('admin mengubah ambang lalu simpan → PUT parsial + pesan sukses', async () => {
  renderTab('admin')
  const row = await screen.findByTestId('rule-row-gpu_temp')
  const input = within(row).getByLabelText(/ambang/i)
  await userEvent.clear(input)
  await userEvent.type(input, '80')
  await userEvent.click(screen.getByTestId('rules-save'))
  await waitFor(() => expect(puts).toEqual([{ gpu_temp: { threshold: 80 } }]))
  expect(await screen.findByTestId('rules-saved')).toBeInTheDocument()
})

test('422 → pesan error', async () => {
  renderTab('admin')
  putStatus = 422
  const row = await screen.findByTestId('rule-row-gpu_temp')
  await userEvent.click(within(row).getByRole('switch', { name: /telegram/i }))
  await userEvent.click(screen.getByTestId('rules-save'))
  expect(await screen.findByTestId('rules-error')).toBeInTheDocument()
})

test('viewer read-only: kontrol nonaktif, tanpa tombol simpan', async () => {
  renderTab('viewer')
  const row = await screen.findByTestId('rule-row-gpu_temp')
  expect(within(row).getByLabelText(/ambang/i)).toBeDisabled()
  expect(screen.queryByTestId('rules-save')).toBeNull()
})
