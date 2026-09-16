import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach } from 'vitest'
import '@testing-library/jest-dom/vitest'
import AppShell from '../app/AppShell'
import LoginPage from '../features/auth/LoginPage'
import { I18nProvider } from '../app/i18n'

const COLLAPSE_KEY = 'isentinel_sidenav_collapsed'
const defaultMatchMedia = window.matchMedia

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

function renderShell(entry = '/dashboard') {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[entry]}>
        <AppShell />
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

afterEach(() => {
  localStorage.removeItem(COLLAPSE_KEY)
  window.matchMedia = defaultMatchMedia
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

test('rail stays collapsed after pointer and keyboard focus on a link', async () => {
  stubDesktopLayout()
  localStorage.setItem(COLLAPSE_KEY, '1')
  const user = userEvent.setup()
  renderShell('/events')

  const nav = screen.getByRole('navigation', { name: 'I-Sentinel' })
  expect(nav).toHaveClass('cds--side-nav--rail')

  await user.click(within(nav).getByRole('link', { name: 'Dashboard' }))
  await settleRailExpansionDelay()
  expect(nav).toHaveClass('cds--side-nav--rail')
  expect(nav).not.toHaveClass('cds--side-nav--expanded')

  within(nav).getByRole('link', { name: 'Live' }).focus()
  await settleRailExpansionDelay()
  expect(nav).not.toHaveClass('cds--side-nav--expanded')
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
  expect(logoutButton.closest('.app-sidenav-user')).not.toBeNull()
  expect(within(screen.getByRole('banner')).queryByRole('button', { name: 'Keluar' })).toBeNull()
})
