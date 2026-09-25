import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import LoginPage from '../features/auth/LoginPage'
import { apiFetch } from '../api/client'

function Probe() {
  const loc = useLocation()
  return <div data-testid="location">{loc.pathname + loc.search}</div>
}

function renderLogin(entry: string) {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true, status: 200, json: async () => ({ id: 1, username: 'admin', role: 'admin', token: 't' }),
  })))
  render(
    <I18nProvider>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="*" element={<Probe />} />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  )
}

async function submit() {
  await userEvent.type(screen.getByLabelText(/username|nama pengguna/i), 'admin')
  await userEvent.type(screen.getByLabelText(/password|kata sandi/i, { selector: 'input' }), 'secret')
  await userEvent.click(screen.getByRole('button', { name: /masuk|login|sign in/i }))
}

test('401 sends the user to login carrying the original path (Telegram event link)', async () => {
  const assign = vi.fn()
  const original = window.location
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...original, pathname: '/events', search: '?event=5', assign },
  })
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 401, json: async () => null })))
  try {
    await apiFetch('/events?limit=1')
    expect(assign).toHaveBeenCalledWith('/login?next=%2Fevents%3Fevent%3D5')
  } finally {
    Object.defineProperty(window, 'location', { configurable: true, value: original })
  }
})

test('after login the user lands on ?next', async () => {
  renderLogin('/login?next=%2Fevents%3Fevent%3D5')
  await submit()
  await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/events?event=5'))
})

test.each(['https://evil.example', '//evil.example', '/\\evil.example'])(
  'external next %s is ignored (no open redirect)',
  async (next) => {
    renderLogin(`/login?next=${encodeURIComponent(next)}`)
    await submit()
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/dashboard'))
  },
)
