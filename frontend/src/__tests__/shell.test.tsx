import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import AppShell from '../app/AppShell'
import LoginPage from '../features/auth/LoginPage'
import { I18nProvider } from '../app/i18n'

test('renders sidebar items and lang toggle', async () => {
  render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/dashboard']}>
        <AppShell />
      </MemoryRouter>
    </I18nProvider>,
  )
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
