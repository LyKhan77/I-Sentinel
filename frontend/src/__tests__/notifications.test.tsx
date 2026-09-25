import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import ConfigurationPage from '../features/config/ConfigurationPage'

const EMPTY = { has_token: false, chat_id: null, chat_title: null, app_url: null, last_alert: null }
type Call = { url: string; init?: RequestInit }

function stub(state: Record<string, unknown>) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    const u = String(url)
    if (u.endsWith('/telegram/settings') && init?.method === 'PUT') {
      Object.assign(state, JSON.parse(String(init.body)), { has_token: true })
      delete state.token
      return { ok: true, status: 200, json: async () => state }
    }
    if (u.endsWith('/telegram/settings')) return { ok: true, status: 200, json: async () => state }
    if (u.endsWith('/telegram/discover')) {
      return { ok: true, status: 200, json: async () => ({ chats: [{ chat_id: '-1001', title: 'Satpam', type: 'supergroup' }] }) }
    }
    if (u.endsWith('/telegram/test')) return { ok: true, status: 200, json: async () => ({ status: 'sent', error: null }) }
    return { ok: true, status: 200, json: async () => ({ id: 1, username: 'admin', role: 'admin' }) }
  }))
  return calls
}

function renderTab() {
  render(<I18nProvider><MemoryRouter initialEntries={['/configuration?tab=notifications']}><ConfigurationPage /></MemoryRouter></I18nProvider>)
}

test('setup flow: token, detect group, choose, test message', async () => {
  const state = { ...EMPTY }
  const calls = stub(state)
  renderTab()

  const tokenInput = await screen.findByLabelText('Token bot', { selector: 'input' })
  await userEvent.type(tokenInput, '123456:' + 'A'.repeat(35))
  await userEvent.click(screen.getByRole('button', { name: 'Simpan token' }))
  expect(await screen.findByText('Token tersimpan ✓')).toBeInTheDocument()
  const put = calls.find((c) => c.init?.method === 'PUT')
  expect(JSON.parse(String(put!.init!.body))).toEqual({ token: '123456:' + 'A'.repeat(35) })

  await userEvent.click(screen.getByRole('button', { name: 'Deteksi grup' }))
  await userEvent.click(await screen.findByLabelText('Satpam'))
  await userEvent.click(screen.getByRole('button', { name: 'Simpan grup' }))
  await waitFor(() => {
    const puts = calls.filter((c) => c.init?.method === 'PUT').map((c) => JSON.parse(String(c.init!.body)))
    expect(puts).toContainEqual({ chat_id: '-1001', chat_title: 'Satpam', app_url: window.location.origin })
  })

  await userEvent.click(screen.getByRole('button', { name: 'Kirim pesan uji' }))
  expect(await screen.findByText('Pesan uji terkirim ✓')).toBeInTheDocument()
})

test('configured state hides the token field until Ganti', async () => {
  stub({ ...EMPTY, has_token: true, chat_id: '-1001', chat_title: 'Satpam', app_url: 'http://10.0.0.1:5173',
    last_alert: { status: 'failed', error: 'Forbidden: bot was kicked', created_at: '2026-09-25T04:00:00Z' } })
  renderTab()
  expect(await screen.findByText('Token tersimpan ✓')).toBeInTheDocument()
  expect(screen.queryByLabelText('Token bot', { selector: 'input' })).not.toBeInTheDocument()
  expect(screen.getByText(/Satpam/)).toBeInTheDocument()
  expect(screen.getByText(/Forbidden: bot was kicked/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Ganti token' }))
  expect(screen.getByLabelText('Token bot', { selector: 'input' })).toBeInTheDocument()
})
