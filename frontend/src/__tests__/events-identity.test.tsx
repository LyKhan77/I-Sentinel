import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import EventsPage from '../features/events/EventsPage'
import type { EventOut } from '../api/events'

const EVENTS: EventOut[] = [
  {
    id: 1, event_id: 'ev-1', type: 'intrusion', camera_id: 1, zone_id: null, severity: 'critical',
    ts_event: '2026-02-12T10:00:00Z',
    payload: {
      face: { status: 'recognized', name: 'Budi', score: 0.83, employee_id: 7 },
      crop_path: 'crops/2026/10/08/x.jpg',
    },
    clip_path: null, snapshot_path: null,
  },
  { id: 2, event_id: 'ev-2', type: 'intrusion', camera_id: 2, zone_id: null, severity: 'critical',
    ts_event: '2026-02-12T09:30:00Z', payload: { face: { status: 'unknown' } }, clip_path: null, snapshot_path: null },
  { id: 3, event_id: 'ev-3', type: 'intrusion', camera_id: 2, zone_id: null, severity: 'critical',
    ts_event: '2026-02-12T09:40:00Z', payload: null, clip_path: null, snapshot_path: null },
]

class FakeWS {
  onmessage: ((ev: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  constructor(_url: string) {}
  close() {}
  send() {}
  addEventListener() {}
  removeEventListener() {}
}

function stubFetch(events: EventOut[]) {
  return vi.fn(async (url: string) => {
    const u = String(url)
    if (u.includes('/events?')) return { ok: true, status: 200, json: () => Promise.resolve(events) }
    if (u.includes('/alerts/by-events')) return { ok: true, status: 200, json: () => Promise.resolve({}) }
    if (u.includes('/zones')) return { ok: true, status: 200, json: () => Promise.resolve([]) }
    if (u.endsWith('/cameras')) return { ok: true, status: 200, json: () => Promise.resolve([{ id: 1, name: 'CAM-01' }, { id: 2, name: 'CAM-02' }]) }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
}

function renderPage(entry = '/events') {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[entry]}>
        <EventsPage />
      </MemoryRouter>
    </I18nProvider>,
  )
}

test('detail shows identity row for each payload.face status', async () => {
  const texts = [
    { face: { status: 'recognized', name: 'Budi', score: 0.83 }, want: /Dikenali: Budi/ },
    { face: { status: 'unknown' }, want: /Wajah terlihat, tidak dikenali/ },
    { face: { status: 'not_visible' }, want: /Wajah tidak terlihat jelas/ },
    { face: { status: 'unverified' }, want: /Identitas tidak terverifikasi/ },
  ]
  for (const [i, t] of texts.entries()) {
    const ev: EventOut = {
      ...EVENTS[0], id: i + 100, event_id: `ev-x${i}`,
      payload: { face: t.face },
    }
    vi.stubGlobal('fetch', stubFetch([ev]))
    const { unmount } = renderPage(`/events?event=${ev.id}`)
    const row = await screen.findByTestId('event-identity')
    expect(row).toHaveTextContent(t.want)
    if (t.face.status === 'recognized') expect(row).toHaveTextContent('0.83')
    unmount()
  }
})

test('no identity row without payload.face', async () => {
  vi.stubGlobal('fetch', stubFetch([EVENTS[2]]))
  renderPage('/events?event=3')
  await screen.findByTestId('event-detail')
  expect(screen.queryByTestId('event-identity')).toBeNull()
})

test('ws face frame triggers a refresh', async () => {
  const handlers: FakeWS[] = []
  class Capturing extends FakeWS {
    constructor(url: string) { super(url); handlers.push(this) }
  }
  vi.stubGlobal('WebSocket', Capturing as unknown as typeof WebSocket)
  const fetchMock = stubFetch(EVENTS)
  vi.stubGlobal('fetch', fetchMock)
  renderPage()

  await screen.findByTestId('event-item-1')
  const before = fetchMock.mock.calls.filter(([u]) => String(u).includes('/events?')).length

  await act(async () => {
    handlers[0].onmessage?.({ data: JSON.stringify({ kind: 'face', event_id: 1, status: 'recognized' }) })
  })

  await waitFor(() =>
    expect(fetchMock.mock.calls.filter(([u]) => String(u).includes('/events?')).length)
      .toBeGreaterThan(before))
})

test('intrusion event with payload.crop_path shows the crop tab and image', async () => {
  vi.stubGlobal('fetch', stubFetch([EVENTS[0]]))
  renderPage('/events?event=1')
  await screen.findByTestId('event-detail')
  const tab = screen.getByTestId('event-tab-crop')
  expect(tab).not.toBeDisabled()
  fireEvent.click(tab)
  const crop = screen.getByTestId('event-crop')
  expect(crop.querySelector('img')).toHaveAttribute('src', '/api/v1/media/crops/2026/10/08/x.jpg')
})

test('intrusion event without crop_path has no crop tab', async () => {
  vi.stubGlobal('fetch', stubFetch([EVENTS[2]]))
  renderPage('/events?event=3')
  await screen.findByTestId('event-detail')
  const tab = screen.queryByTestId('event-tab-crop')
  expect(tab).toBeNull()
})
