import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import { EventAlertsProvider } from '../features/notifications/EventAlertsProvider'
import DashboardPage from '../features/dashboard/DashboardPage'
import { mon, alert, att, stats, storage, ev, ok, fail } from './dashboardFixtures'

vi.mock('../features/notifications/beep', () => ({ beep: vi.fn() }))

const CAMS = [
  { id: 1, name: 'CAM-01', location: 'Gudang', host: '192.168.1.101', rtsp_main: null, rtsp_sub: null, node_id: 1, enabled: true, status: 'online', probe_main: null, probe_sub: null },
]

// semua WebSocket (provider + useLiveEvents) menerima pesan yang sama, seperti hub backend
const sockets: { onmessage: ((msg: { data: string }) => void) | null; onerror: (() => void) | null }[] = []
class FakeWS {
  onmessage: ((msg: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  constructor() { sockets.push(this) }
  close() {}
  send() {}
}

function stubFetch(opts: { history?: unknown[]; failAll?: boolean; storageBody?: unknown } = {}) {
  const { history = [], failAll = false, storageBody } = opts
  const calls = { stats: 0 }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (failAll) return fail()
    const u = String(url)
    if (u.endsWith('/monitoring/alerts')) return ok({ active: [alert({ label: 'NVR-1' })], recent: [] })
    if (u.endsWith('/monitoring')) return ok(mon())
    if (u.endsWith('/events/stats/today')) { calls.stats++; return ok(stats()) }
    if (u.endsWith('/attendance')) return ok([att('ontime'), att('late')])
    if (u.endsWith('/storage/stats')) return ok(storageBody ?? storage())
    if (u.endsWith('/cameras')) return ok(CAMS)
    if (u.includes('/events?')) return ok(history)
    return fail()
  }))
  vi.stubGlobal('WebSocket', FakeWS)
  return calls
}

function renderPage() {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/dashboard']}>
        <EventAlertsProvider>
          <DashboardPage />
        </EventAlertsProvider>
      </MemoryRouter>
    </I18nProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  sockets.length = 0
})

test('renders every block from API data', async () => {
  stubFetch({ history: [ev(11)] })
  renderPage()

  // strip status: 1 alert aktif (active issues juga 1 alert yang sama)
  expect(await screen.findByText('1 peringatan aktif')).toBeInTheDocument()
  // tile event + kamera
  expect(screen.getByText('47')).toBeInTheDocument()
  expect(screen.getByText('1/3')).toBeInTheDocument()
  // event terbaru: nama kamera (bukan id) + tautan detail
  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /CAM-01/ })).toHaveAttribute('href', '/events?event=11')
  // masalah aktif + node ringkas
  expect(screen.getByText('Kamera tanpa frame')).toBeInTheDocument()
  expect(screen.getByText('server')).toBeInTheDocument()
  // chart per jam ada
  expect(screen.getByTestId('lc-line-total')).toBeInTheDocument()
})

test('shows the disk alert banner when usage is over the threshold', async () => {
  const alerting = storage({ disk: { total: 100, used: 91, free: 9, percent: 91 }, disk_alert: { threshold: 85, over: true } })
  stubFetch({ storageBody: alerting })
  renderPage()
  expect(await screen.findByTestId('disk-alert')).toHaveTextContent('Disk hampir penuh (91%)')
})

test('never shows fake zeros when every request fails', async () => {
  stubFetch({ failAll: true })
  renderPage()
  expect(await screen.findByText('Status sistem tidak tersedia')).toBeInTheDocument()
  await waitFor(() => expect(screen.getAllByText('Gagal memuat').length).toBeGreaterThan(0))
  expect(screen.queryByText('0/0')).toBeNull()
})

test('a new live event refetches today stats', async () => {
  const calls = stubFetch()
  renderPage()
  await waitFor(() => expect(calls.stats).toBe(1))
  expect(await screen.findByTestId('dash-hourly')).toBeInTheDocument()
  act(() => {
    for (const s of sockets) s.onmessage?.({ data: JSON.stringify(ev(999)) })
  })
  await waitFor(() => expect(calls.stats).toBe(2))
  // event live tampil di daftar terbaru
  expect(await screen.findByRole('link', { name: /CAM-01/ })).toHaveAttribute('href', '/events?event=999')
})
