import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import AppShell from '../app/AppShell'
import ChangePasswordModal from '../features/auth/ChangePasswordModal'
import LoginPage from '../features/auth/LoginPage'
import { passwordProblem } from '../features/auth/password'

afterEach(() => vi.unstubAllGlobals())

const json = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })

test('passwordProblem: panjang minimal, batas byte, konfirmasi', () => {
  expect(passwordProblem('pendek7', 'pendek7')).toBe('pw.err.short')
  expect(passwordProblem('é'.repeat(37), 'é'.repeat(37))).toBe('pw.err.long')
  expect(passwordProblem('rahasia123', 'rahasia124')).toBe('pw.err.mismatch')
  expect(passwordProblem('rahasia123', 'rahasia123')).toBeNull()
})

async function fill(current: string, next: string) {
  await userEvent.type(screen.getByLabelText('Password lama', { selector: 'input' }), current)
  await userEvent.type(screen.getByLabelText('Password baru', { selector: 'input' }), next)
  await userEvent.type(screen.getByLabelText('Ulangi password baru', { selector: 'input' }), next)
  await userEvent.click(screen.getByRole('button', { name: 'Simpan' }))
}

test('ganti password: lama salah → pesan; sukses → onClose(true) dengan body benar', async () => {
  const f = vi.fn(async () => json(400, { detail: 'current password is incorrect' }))
  vi.stubGlobal('fetch', f)
  const onClose = vi.fn()
  render(<I18nProvider><ChangePasswordModal onClose={onClose} /></I18nProvider>)
  await fill('salah-sekali', 'baru-rahasia-1')
  expect(await screen.findByText('Password lama salah')).toBeInTheDocument()
  expect(onClose).not.toHaveBeenCalled()

  f.mockImplementation(async () => json(200, { ok: true }))
  await userEvent.click(screen.getByRole('button', { name: 'Simpan' }))
  await vi.waitFor(() => expect(onClose).toHaveBeenCalledWith(true))
  const [url, init] = f.mock.calls.at(-1) as unknown as [string, RequestInit]
  expect(url).toBe('/api/v1/auth/change-password')
  expect(JSON.parse(String(init.body))).toEqual({ current_password: 'salah-sekali', new_password: 'baru-rahasia-1' })
})

test('login akun nonaktif menampilkan pesan khusus', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json(403, { detail: 'account disabled' })))
  render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/login']}>
        <Routes><Route path="/login" element={<LoginPage />} /></Routes>
      </MemoryRouter>
    </I18nProvider>,
  )
  await userEvent.type(screen.getByLabelText(/username|nama pengguna/i), 'tv-1')
  await userEvent.type(screen.getByLabelText(/password|kata sandi/i, { selector: 'input' }), 'rahasia123')
  await userEvent.click(screen.getByRole('button', { name: /masuk|login|sign in/i }))
  expect(await screen.findByText('Akun dinonaktifkan — hubungi admin')).toBeInTheDocument()
})

test('kartu akun sidebar membuka modal ganti password', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json(200, { id: 1, username: 'admin', role: 'admin' })))
  render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes><Route path="/" element={<AppShell />}><Route path="dashboard" element={<div />} /></Route></Routes>
      </MemoryRouter>
    </I18nProvider>,
  )
  await userEvent.click(await screen.findByTestId('change-password-open'))
  expect(screen.getByLabelText('Password lama', { selector: 'input' })).toBeInTheDocument()
})
