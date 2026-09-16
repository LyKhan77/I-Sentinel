import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, vi } from 'vitest'
import '@testing-library/jest-dom/vitest'
import AppShell from '../app/AppShell'
import LoginPage from '../features/auth/LoginPage'
import { I18nProvider } from '../app/i18n'

const COLLAPSE_KEY = 'isentinel_sidenav_collapsed'
const LOCALE_KEY = 'isentinel_locale'
const ADMIN = { id: 1, username: 'admin', role: 'admin' }
const defaultMatchMedia = window.matchMedia
const defaultFetch = window.fetch

// Stub setupTests selalu `matches: false` → shell tampil sebagai mobile.
// Test rail butuh layout desktop, jadi matchMedia diganti per-test.
function stubDesktopLayout() {
  window.matchMedia = ((query: string) => ({
    matches: query.includes('1056px'), // breakpoint lg Carbon = DESKTOP_QUERY shell
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}

// Route yang benar-benar dipakai shell, bukan state internal React Router.
function LocationProbe() {
  const { pathname } = useLocation()
  return <span data-testid="location">{pathname}</span>
}

function renderShell(entry = '/dashboard') {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[entry]}>
        <AppShell />
        <LocationProbe />
      </MemoryRouter>
    </I18nProvider>,
  )
}

// Carbon menunda perubahan state rail ~enterDelayMs (100ms). Klaim "rail tetap
// collapse" baru valid setelah jendela itu benar-benar lewat — kalau listener
// Carbon masih terpasang, kelas expanded muncul di jendela ini dan test gagal.
async function settleRailExpansionDelay() {
  let elapsed = false
  setTimeout(() => {
    elapsed = true
  }, 150)
  await waitFor(() => expect(elapsed).toBe(true))
}

// /auth/me selesai langsung; /auth/logout menahan respons sampai test
// melepasnya, supaya "sudah pindah ke /login atau belum" bisa diamati.
function stubDeferredLogout() {
  const calls: { url: string; method?: string }[] = []
  let release!: (res: Response) => void
  const pending = new Promise<Response>((resolve) => {
    release = resolve
  })
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const u = String(url)
      if (u.endsWith('/auth/logout')) {
        calls.push({ url: u, method: init?.method })
        return pending
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(ADMIN) })
    }),
  )
  return { calls, release: (res: Response) => release(res) }
}

afterEach(() => {
  localStorage.clear()
  window.matchMedia = defaultMatchMedia
  window.fetch = defaultFetch
})

test('renders sidebar items and lang toggle', async () => {
  renderShell()
  expect(screen.getByText('Dashboard')).toBeInTheDocument()
  // getMe() async (fetch stub di setupTests) → admin item muncul setelah state settle
  await waitFor(() => expect(screen.getAllByText('Konfigurasi').length).toBeGreaterThan(0)) // locale default id
  expect(screen.getByText('ID')).toBeInTheDocument()
})

test('login page validates empty submit', async () => {
  render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/login']}>
        <LoginPage />
      </MemoryRouter>
    </I18nProvider>,
  )
  // klik tombol tanpa isi → pesan validasi muncul, tidak ada fetch
  await userEvent.click(screen.getByRole('button'))
  expect(screen.getAllByText(/wajib/i).length).toBeGreaterThan(0)
})

test('rail stays collapsed after pointer and keyboard activation of a link', async () => {
  stubDesktopLayout()
  localStorage.setItem(COLLAPSE_KEY, '1')
  const user = userEvent.setup()
  renderShell('/events')

  const nav = screen.getByRole('navigation', { name: 'I-Sentinel' })
  expect(nav).toHaveClass('cds--side-nav--rail')
  expect(screen.getByTestId('location').textContent).toBe('/events')

  // klik pointer → route benar-benar pindah, rail tidak melebar
  await user.click(within(nav).getByRole('link', { name: 'Dashboard' }))
  await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/dashboard'))
  await settleRailExpansionDelay()
  expect(nav).toHaveClass('cds--side-nav--rail')
  expect(nav).not.toHaveClass('cds--side-nav--expanded')

  // Enter di link ter-fokus → route pindah juga, preferensi collapse tetap
  within(nav).getByRole('link', { name: 'Live View' }).focus()
  await user.keyboard('{Enter}')
  await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/live'))
  await settleRailExpansionDelay()
  expect(nav).toHaveClass('cds--side-nav--rail')
  expect(nav).not.toHaveClass('cds--side-nav--expanded')
  expect(localStorage.getItem(COLLAPSE_KEY)).toBe('1')
})

test('header toggle is the only writer of the collapsed preference', async () => {
  stubDesktopLayout()
  localStorage.setItem(LOCALE_KEY, 'en')
  localStorage.setItem(COLLAPSE_KEY, '1')
  const user = userEvent.setup()
  renderShell()

  const nav = screen.getByRole('navigation', { name: 'I-Sentinel' })
  expect(nav).toHaveClass('cds--side-nav--rail')

  await user.click(screen.getByRole('button', { name: 'Expand sidebar' }))
  await waitFor(() => expect(nav).toHaveClass('cds--side-nav--expanded'))
  expect(nav).not.toHaveClass('cds--side-nav--rail')
  expect(localStorage.getItem(COLLAPSE_KEY)).toBe('0')

  await user.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
  await waitFor(() => expect(nav).toHaveClass('cds--side-nav--rail'))
  expect(localStorage.getItem(COLLAPSE_KEY)).toBe('1')
})

test('exposes one Configuration destination and logout in the account card', async () => {
  stubDesktopLayout()
  renderShell()

  const nav = screen.getByRole('navigation', { name: 'I-Sentinel' })
  await waitFor(() => expect(within(nav).getAllByRole('link', { name: 'Konfigurasi' })).toHaveLength(1))
  expect(within(nav).getByRole('link', { name: 'Konfigurasi' })).toHaveAttribute(
    'href',
    '/configuration?tab=cameras',
  )
  // empat link legacy /config/* sudah tidak ada
  expect(nav.querySelectorAll('a[href^="/config/"]')).toHaveLength(0)

  const logoutButton = await screen.findByRole('button', { name: 'Keluar' })
  expect(nav).toContainElement(logoutButton)
  expect(logoutButton.closest('.app-sidenav-user')).not.toBeNull()
  expect(logoutButton).toHaveAttribute('title', 'Keluar')
  // label visual ada di dalam tombol; CSS rail-lah yang menyembunyikannya
  expect(within(logoutButton).getByText('Keluar')).toHaveClass('app-sidenav-user__logout-text')

  expect(within(screen.getByRole('banner')).queryByRole('button', { name: 'Keluar' })).toBeNull()
})

test('logout waits for the API response before navigating to /login', async () => {
  stubDesktopLayout()
  const { calls, release } = stubDeferredLogout()
  const user = userEvent.setup()
  renderShell('/dashboard')

  const logoutButton = await screen.findByRole('button', { name: 'Keluar' })
  await user.click(logoutButton)

  await waitFor(() => expect(calls).toHaveLength(1))
  expect(calls[0]).toEqual({ url: '/api/v1/auth/logout', method: 'POST' })
  // respons belum dilepas → user tetap di halaman, belum dilempar ke /login
  expect(screen.getByTestId('location').textContent).toBe('/dashboard')

  release({ ok: true, status: 200 } as Response)
  await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/login'))
})
