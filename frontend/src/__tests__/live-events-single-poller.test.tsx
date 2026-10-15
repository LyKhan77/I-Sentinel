import { act, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import { EventAlertsProvider } from '../features/notifications/EventAlertsProvider'
import LiveTvPage from '../features/live/LiveTvPage'

const CAMS = [1, 2].map((id) => ({
  id, name: `CAM-0${id}`, location: null, host: `10.0.0.${id}`, rtsp_main: null, rtsp_sub: null, node_id: 1,
  enabled: true, status: 'online', probe_main: null, probe_sub: null,
}))
const ok = (body: unknown) => ({ ok: true, status: 200, json: () => Promise.resolve(body) })

const sockets: object[] = []
class FakeWS {
  onmessage: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor() { sockets.push(this) }
  close() {}
  send() {}
  addEventListener() {}
  removeEventListener() {}
}

function stubFetch() {
  return vi.fn(async (url: string) => {
    const u = String(url)
    if (u.includes('/events?')) return ok([]) // riwayat provider dan poll useLiveEvents
    if (u.endsWith('/cameras')) return ok(CAMS)
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
}
// poll aliran (useLiveEvents): /events tanpa filter jenis; riwayat provider memakai type=
const streamPolls = (f: { mock: { calls: unknown[][] } }) =>
  f.mock.calls.filter((c) => String(c[0]).includes('/events?') && !String(c[0]).includes('type=')).length

beforeEach(() => { sockets.length = 0 })
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

test('/live/tv di bawah provider: satu poller /events dan satu WebSocket per jendela (bukan dua)', async () => {
  vi.useFakeTimers()
  const f = stubFetch()
  vi.stubGlobal('fetch', f)
  vi.stubGlobal('WebSocket', FakeWS)
  render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/live/tv?screen=A&cameras=1,2']}>
        <EventAlertsProvider>
          <LiveTvPage />
        </EventAlertsProvider>
      </MemoryRouter>
    </I18nProvider>,
  )
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
  expect(screen.getByTestId('live-tv')).toBeInTheDocument()
  expect(streamPolls(f)).toBe(1)
  expect(sockets).toHaveLength(1)
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(streamPolls(f)).toBe(2) // satu poll per tick 5 detik
})
