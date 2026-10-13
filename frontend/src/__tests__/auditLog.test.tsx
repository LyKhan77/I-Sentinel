import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Mock } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { MemoryRouter } from 'react-router-dom'
import { I18nProvider } from '../app/i18n'
import AuditLogPage from '../features/audit/AuditLogPage'
import type { AuditLogEntry } from '../api/auditLogs'

const NOW = '2026-10-13T03:00:00Z'
const entries: AuditLogEntry[] = [
  {
    id: 2, ts: NOW, category: 'config', action: 'camera.update',
    actor_id: 1, actor_label: 'admin', target_type: 'camera', target_id: '3',
    target_label: 'Gerbang', changes: { location: 'Lobby' }, ip: '10.0.0.5',
    user_agent: 'vitest', status: 'ok',
  },
  {
    id: 1, ts: NOW, category: 'auth', action: 'auth.login',
    actor_id: 1, actor_label: 'admin', target_type: null, target_id: null,
    target_label: null, changes: null, ip: '10.0.0.5', user_agent: 'vitest', status: 'ok',
  },
]

function json(status: number, body: unknown) {
  return { ok: status < 400, status, json: () => Promise.resolve(body) }
}

function stubFetch() {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    const method = init?.method ?? 'GET'
    if (u.includes('/audit-logs/actors') && method === 'GET') return json(200, ['admin'])
    if (u.includes('/audit-logs/verify') && method === 'POST')
      return json(200, { ok: true, checked: 2, first_break_id: null })
    if (u.includes('/audit-logs') && method === 'GET')
      return json(200, { total: 60, items: entries })
    return json(404, null)
  })
}

function renderPage() {
  const f = stubFetch()
  vi.stubGlobal('fetch', f)
  render(
    <I18nProvider>
      <MemoryRouter>
        <AuditLogPage />
      </MemoryRouter>
    </I18nProvider>,
  )
  return f
}

function lastAuditUrl(f: Mock) {
  const calls = f.mock.calls.filter(([u]) => String(u).includes('/audit-logs?'))
  return calls.length ? String(calls[calls.length - 1][0]) : ''
}

afterEach(() => vi.unstubAllGlobals())

test('render entri + info paginasi', async () => {
  renderPage()
  expect(await screen.findByTestId('audit-row-2')).toHaveTextContent('camera.update')
  expect(screen.getByTestId('audit-row-1')).toHaveTextContent('auth.login')
  expect(screen.getByTestId('audit-page-info')).toHaveTextContent('1–2 dari 60')
})

test('filter status memanggil API dengan param benar', async () => {
  const f = renderPage()
  await screen.findByTestId('audit-row-2')
  await userEvent.selectOptions(screen.getByLabelText('Status'), 'failed')
  await waitFor(() => expect(lastAuditUrl(f)).toContain('status=failed'))
})

test('verifikasi integritas menampilkan notifikasi sukses', async () => {
  renderPage()
  await screen.findByTestId('audit-row-2')
  await userEvent.click(screen.getByTestId('audit-verify'))
  expect(await screen.findByTestId('audit-verify-ok')).toHaveTextContent('2 entri')
})

test('paginasi next menambah offset', async () => {
  const f = renderPage()
  await screen.findByTestId('audit-row-2')
  await userEvent.click(screen.getByTestId('audit-next'))
  await waitFor(() => expect(lastAuditUrl(f)).toContain('offset=50'))
})
