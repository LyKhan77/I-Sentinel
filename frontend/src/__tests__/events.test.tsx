import { render, screen, waitFor } from '@testing-library/react'
import { act } from 'react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import EventsPage from '../features/events/EventsPage'
import type { EventOut } from '../api/events'

const EVENTS: EventOut[] = [
  { id: 1, event_id: 'ev-1', type: 'intrusi', camera_id: 1, zone_id: null, severity: 'critical', ts_event: '2026-02-12T10:00:00Z', payload: { line: 'A' }, clip_path: null, snapshot_path: null },
  { id: 2, event_id: 'ev-2', type: 'loitering', camera_id: 2, zone_id: null, severity: 'warning', ts_event: '2026-02-12T09:30:00Z', payload: null, clip_path: null, snapshot_path: null },
]

function stubFetch(events = EVENTS) {
  return vi.fn(async (url: string) => {
    const u = String(url)
    if (u.includes('/events?')) return { ok: true, status: 200, json: () => Promise.resolve(events) }
    if (u.endsWith('/cameras')) {
      return {
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve([
            { id: 1, name: 'CAM-01' },
            { id: 2, name: 'CAM-02' },
          ]),
      }
    }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
}

function renderPage() {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/events']}>
        <EventsPage />
      </MemoryRouter>
    </I18nProvider>,
  )
}

test('renders event list with camera names', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()

  // master-detail: type muncul di list + detail panel → pakai getAllByText
  expect((await screen.findAllByText('intrusi')).length).toBeGreaterThanOrEqual(1)
  expect(screen.getAllByText('loitering').length).toBeGreaterThanOrEqual(1)
  expect(screen.getAllByText('CAM-01').length).toBeGreaterThanOrEqual(1)
  expect(screen.getAllByText(/critical/).length).toBeGreaterThanOrEqual(1)
})

test('click list item selects event detail', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()

  const item = (await screen.findAllByTestId('event-item-1'))[0]
  await userEvent.click(item)
  await waitFor(() => expect(screen.getByTestId('event-detail')).toBeInTheDocument())
  expect(screen.getByText('ev-1')).toBeInTheDocument()
  // payload JSON dihilangkan dari detail (metadata grid menggantikan) — event_id cukup
})

test('poll (5s) appends new event row realtime', async () => {
  vi.useFakeTimers()
  let current = EVENTS
  const fetchMock = vi.fn(async (url: string) => {
    const u = String(url)
    if (u.includes('/events?')) return { ok: true, status: 200, json: () => Promise.resolve(current) }
    if (u.endsWith('/cameras')) {
      return {
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve([
            { id: 1, name: 'CAM-01' },
            { id: 2, name: 'CAM-02' },
          ]),
      }
    }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
  vi.stubGlobal('fetch', fetchMock)
  renderPage()
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000) // poll awal
  })
  expect(screen.getAllByText('intrusi').length).toBeGreaterThanOrEqual(1)

  const newRow = { id: 3, event_id: 'ev-3', type: 'maling', camera_id: 1, zone_id: null, severity: 'critical', ts_event: '2026-02-12T10:05:00Z', payload: null, clip_path: null, snapshot_path: null }
  current = [...EVENTS, newRow] // tick poll berikutnya mengambil termasuk ev-3

  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000)
  })
  expect(screen.getAllByText('maling').length).toBeGreaterThanOrEqual(1)
  vi.useRealTimers()
})

test('click list item shows metadata in detail panel', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()

  const item = (await screen.findAllByTestId('event-item-1'))[0]
  await userEvent.click(item)
  await waitFor(() => expect(screen.getByTestId('event-detail')).toBeInTheDocument())
  expect(screen.getByText('ev-1')).toBeInTheDocument()
  expect(screen.getByText('ev-1').closest('[data-testid=event-detail]')).not.toBeNull()
})

test('detail panel shows video element when clip_path present', async () => {
  const withClip: typeof EVENTS = [
    { ...EVENTS[0], clip_path: 'clips/ev-1.mp4', snapshot_path: 'snaps/ev-1.jpg' },
    EVENTS[1],
  ]
  vi.stubGlobal('fetch', stubFetch(withClip))
  renderPage()

  expect(await screen.findByTestId('event-detail')).toBeInTheDocument()
  const video = screen.getByTestId('event-clip') as HTMLVideoElement
  expect(video.tagName).toBe('VIDEO')
  expect(video.src).toContain('/api/v1/media/clips/ev-1.mp4')
  // snapshot thumb di list + snapshot besar di detail
  expect(screen.getAllByAltText('intrusi').length).toBeGreaterThanOrEqual(1)
  expect(screen.getByTestId('event-download')).toHaveAttribute('href', '/api/v1/media/clips/ev-1.mp4')
})

test('detail panel shows placeholder when clip_path null', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()

  expect(await screen.findByTestId('event-clip-placeholder')).toBeInTheDocument()
  expect(screen.queryByTestId('event-clip')).not.toBeInTheDocument()
})
