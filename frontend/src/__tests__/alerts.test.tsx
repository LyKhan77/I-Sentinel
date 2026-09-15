import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import EventsPage from '../features/events/EventsPage'
import type { EventOut } from '../api/events'
import type { AlertStatus } from '../api/alerts'

const EVENTS: EventOut[] = [
  { id: 1, event_id: 'ev-1', type: 'intrusi', camera_id: 1, zone_id: null, severity: 'critical', ts_event: '2026-02-12T10:00:00Z', payload: null, clip_path: null, snapshot_path: null },
  { id: 2, event_id: 'ev-2', type: 'loitering', camera_id: 2, zone_id: null, severity: 'warning', ts_event: '2026-02-12T09:30:00Z', payload: null, clip_path: null, snapshot_path: null },
]

function stubFetch(opts: { alertMap?: Record<string, AlertStatus>; configured?: boolean } = {}) {
  const { alertMap = {}, configured = false } = opts
  return vi.fn(async (url: string) => {
    const u = String(url)
    if (u.includes('/events?')) return { ok: true, status: 200, json: () => Promise.resolve(EVENTS) }
    if (u.includes('/alerts/by-events')) return { ok: true, status: 200, json: () => Promise.resolve(alertMap) }
    if (u.includes('/telegram/status')) return { ok: true, status: 200, json: () => Promise.resolve({ configured, active_chats: configured ? 2 : 0 }) }
    if (u.includes('/alerts?')) return { ok: true, status: 200, json: () => Promise.resolve([]) }
    if (u.endsWith('/cameras')) {
      return { ok: true, status: 200, json: () => Promise.resolve([{ id: 1, name: 'CAM-01' }, { id: 2, name: 'CAM-02' }]) }
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

test('detail badge shows TELEGRAM TERKIRIM when alert status is sent', async () => {
  vi.stubGlobal('fetch', stubFetch({ alertMap: { 'ev-1': 'sent' } }))
  renderPage()

  const badge = await screen.findByTestId('alert-badge')
  expect(badge).toHaveTextContent('TELEGRAM TERKIRIM')
})

test('detail badge shows RATE-LIMITED when alert status is rate_limited', async () => {
  vi.stubGlobal('fetch', stubFetch({ alertMap: { 'ev-1': 'rate_limited' } }))
  renderPage()

  const badge = await screen.findByTestId('alert-badge')
  expect(badge).toHaveTextContent('RATE-LIMITED')
  // dot kuning di list item event tersebut
  expect(screen.getByTestId('alert-dot-1')).toBeInTheDocument()
})

test('badge hidden when selected event has no alert row', async () => {
  vi.stubGlobal('fetch', stubFetch({ alertMap: {} }))
  renderPage()

  await screen.findByTestId('event-detail')
  await waitFor(() => expect(screen.queryByTestId('alert-badge')).not.toBeInTheDocument())
})

test('telegram chip shows not-configured state', async () => {
  vi.stubGlobal('fetch', stubFetch({ configured: false }))
  renderPage()

  const chip = await screen.findByTestId('telegram-chip')
  expect(chip).toHaveTextContent('Telegram: belum dikonfigurasi')
})

test('telegram chip shows ready state with active chat count', async () => {
  vi.stubGlobal('fetch', stubFetch({ configured: true }))
  renderPage()

  const chip = await screen.findByTestId('telegram-chip')
  expect(chip).toHaveTextContent('Telegram: siap · 2 chat')
})

test('severity filter offers critical option and filters the list', async () => {
  vi.stubGlobal('fetch', stubFetch({ alertMap: {} }))
  renderPage()
  await screen.findByTestId('event-item-1')

  const label = screen.getAllByText('Severity')[0]
  const wrapper = label.closest('.cds--dropdown__wrapper') as HTMLElement
  expect(wrapper).not.toBeNull()
  await userEvent.click(wrapper.querySelector('button') as HTMLElement)

  const option = await screen.findByRole('option', { name: 'critical' })
  await userEvent.click(option)

  // hanya event critical (ev-1) yang tersisa
  await waitFor(() => expect(screen.queryByTestId('event-item-2')).not.toBeInTheDocument())
  expect(screen.getByTestId('event-item-1')).toBeInTheDocument()
})
