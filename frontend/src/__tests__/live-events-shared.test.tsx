import { act, render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { I18nProvider } from '../app/i18n'
import { EventAlertsProvider, useSharedLiveEvents } from '../features/notifications/EventAlertsProvider'

const ok = (body: unknown) => ({ ok: true, status: 200, json: () => Promise.resolve(body) })
const polled = { id: 5, event_id: 'e-5', type: 'intrusion', camera_id: 1, zone_id: 1, severity: 'critical', ts_event: new Date().toISOString(), payload: null }

const sockets: { onmessage: ((ev: { data: string }) => void) | null }[] = []
class FakeWS {
  onmessage: ((ev: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  constructor() { sockets.push(this) }
  close() {}
  send() {}
  addEventListener() {}
  removeEventListener() {}
}
const sendWs = (msg: unknown) => act(() => { for (const s of sockets) s.onmessage?.({ data: JSON.stringify(msg) }) })

function Sub({ onEvent }: { onEvent: (e: unknown) => void }) {
  useSharedLiveEvents(onEvent)
  return null
}

function stubFetch() {
  return vi.fn(async (url: string) => {
    const u = String(url)
    if (u.includes('/events?') && !u.includes('type=')) return ok([polled])
    if (u.includes('/events?')) return ok([])
    if (u.endsWith('/cameras')) return ok([])
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
}

beforeEach(() => { sockets.length = 0 })
afterEach(() => vi.unstubAllGlobals())

const wrap = (ui: React.ReactNode, provider: boolean) => render(
  <I18nProvider>
    <MemoryRouter>{provider ? <EventAlertsProvider>{ui}</EventAlertsProvider> : ui}</MemoryRouter>
  </I18nProvider>,
)

test('dua pelanggan di bawah provider: satu WebSocket; pesan WS dan hasil polling sampai ke keduanya', async () => {
  vi.stubGlobal('fetch', stubFetch())
  vi.stubGlobal('WebSocket', FakeWS)
  const a = vi.fn()
  const b = vi.fn()
  wrap(<><Sub onEvent={a} /><Sub onEvent={b} /></>, true)
  await act(async () => { await Promise.resolve() })
  expect(sockets).toHaveLength(1)
  sendWs({ type: 'detections', camera_id: 1, kind: 'person', boxes: [] })
  for (const cb of [a, b]) {
    expect(cb).toHaveBeenCalledWith(expect.objectContaining({ type: 'detections', camera_id: 1 }))
    expect(cb).toHaveBeenCalledWith(expect.objectContaining({ id: 5, type: 'intrusion' })) // dari poll pertama
  }
})

test('pelanggan yang unmount berhenti menerima; yang lain tetap menerima', async () => {
  vi.stubGlobal('fetch', stubFetch())
  vi.stubGlobal('WebSocket', FakeWS)
  const a = vi.fn()
  const b = vi.fn()
  const view = wrap(<><Sub onEvent={a} /><Sub onEvent={b} /></>, true)
  await act(async () => { await Promise.resolve() })
  view.rerender(
    <I18nProvider><MemoryRouter><EventAlertsProvider><Sub onEvent={b} /></EventAlertsProvider></MemoryRouter></I18nProvider>,
  )
  a.mockClear(); b.mockClear()
  sendWs({ type: 'detections', camera_id: 2, boxes: [] })
  expect(a).not.toHaveBeenCalled()
  expect(b).toHaveBeenCalledWith(expect.objectContaining({ camera_id: 2 }))
})

test('tanpa provider: memakai langganan sendiri (WebSocket sendiri) dan tetap menerima', async () => {
  vi.stubGlobal('fetch', stubFetch())
  vi.stubGlobal('WebSocket', FakeWS)
  const a = vi.fn()
  wrap(<Sub onEvent={a} />, false)
  await act(async () => { await Promise.resolve() })
  expect(sockets).toHaveLength(1)
  sendWs({ type: 'detections', camera_id: 3, boxes: [] })
  expect(a).toHaveBeenCalledWith(expect.objectContaining({ camera_id: 3 }))
})
