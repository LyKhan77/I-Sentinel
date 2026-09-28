import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Mock } from 'vitest'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import UsersPage from '../features/config/UsersPage'
import type { User } from '../api/users'

const NOW = '2026-09-28T03:00:00Z'
const base = (id: number, username: string, role: 'admin' | 'viewer'): User =>
  ({ id, username, role, locale: 'id', is_active: true, created_at: NOW, last_login_at: id === 1 ? NOW : null })
let users: User[]

function stubFetch() {
  const json = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })
  return vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    if (u.endsWith('/users') && method === 'GET') return json(200, users)
    if (u.endsWith('/users') && method === 'POST') {
      if (users.some((x) => x.username === body.username)) return json(409, { detail: 'username taken' })
      const created = base(9, body.username, body.role)
      users = [...users, created]
      return json(200, created)
    }
    const m = u.match(/\/users\/(\d+)$/)
    const id = m ? Number(m[1]) : 0
    if (m && method === 'PATCH') {
      if (id === 2 && body.role === 'viewer') return json(409, { detail: 'cannot demote last admin' })
      users = users.map((x) => (x.id === id ? { ...x, ...('is_active' in body ? { is_active: body.is_active } : {}), ...(body.role ? { role: body.role } : {}) } : x))
      return json(200, users.find((x) => x.id === id))
    }
    if (m && method === 'DELETE') {
      users = users.filter((x) => x.id !== id)
      return json(200, { ok: true })
    }
    return json(404, null)
  })
}

function calls(f: Mock, method: string) {
  return f.mock.calls.filter(([, i]) => (i as RequestInit | undefined)?.method === method)
    .map(([u, i]) => ({ url: String(u), body: JSON.parse(String((i as RequestInit).body ?? 'null')) }))
}

function renderPage() {
  const f = stubFetch()
  vi.stubGlobal('fetch', f)
  render(<I18nProvider><UsersPage meId={1} /></I18nProvider>)
  return f
}

beforeEach(() => {
  users = [base(1, 'admin', 'admin'), base(2, 'admin2', 'admin'), base(3, 'tv-1', 'viewer')]
})
afterEach(() => vi.unstubAllGlobals())

test('tabel: akun sendiri ditandai dan aksi berbahayanya nonaktif', async () => {
  renderPage()
  const row = await screen.findByTestId('user-row-1')
  expect(row).toHaveTextContent('(Anda)')
  for (const a of ['role', 'reset', 'deactivate', 'delete']) expect(screen.getByTestId(`user-${a}-1`)).toBeDisabled()
  expect(screen.getByTestId('user-delete-3')).toBeEnabled()
  expect(screen.getByTestId('user-row-3')).toHaveTextContent('—') // belum pernah login
})

test('tambah user: validasi klien, lalu POST dan baris baru; username terpakai → pesan', async () => {
  const f = renderPage()
  await screen.findByTestId('user-row-1')
  await userEvent.click(screen.getByTestId('user-add'))
  const dialog = screen.getByRole('dialog')
  await userEvent.type(within(dialog).getByLabelText('Username'), 'tv-2')
  await userEvent.type(within(dialog).getByLabelText('Password awal', { selector: 'input' }), 'pendek7')
  expect(screen.getByTestId('user-form-problem')).toHaveTextContent('minimal 8')
  await userEvent.type(within(dialog).getByLabelText('Password awal', { selector: 'input' }), 'x')
  await userEvent.type(within(dialog).getByLabelText('Ulangi password', { selector: 'input' }), 'pendek7x')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Simpan' }))
  expect(await screen.findByTestId('user-row-9')).toHaveTextContent('tv-2')
  expect(calls(f, 'POST')[0].body).toEqual({ username: 'tv-2', role: 'viewer', password: 'pendek7x' })

  await userEvent.click(screen.getByTestId('user-add'))
  const d2 = screen.getByRole('dialog')
  await userEvent.type(within(d2).getByLabelText('Username'), 'tv-1')
  await userEvent.type(within(d2).getByLabelText('Password awal', { selector: 'input' }), 'rahasia123')
  await userEvent.type(within(d2).getByLabelText('Ulangi password', { selector: 'input' }), 'rahasia123')
  await userEvent.click(within(d2).getByRole('button', { name: 'Simpan' }))
  expect(await within(d2).findByText('Username sudah dipakai')).toBeInTheDocument()
})

test('reset password, nonaktifkan (konfirmasi), aktifkan, hapus', async () => {
  const f = renderPage()
  await screen.findByTestId('user-row-3')

  await userEvent.click(screen.getByTestId('user-reset-3'))
  const d = screen.getByRole('dialog')
  await userEvent.type(within(d).getByLabelText('Password awal', { selector: 'input' }), 'baru-rahasia-1')
  await userEvent.type(within(d).getByLabelText('Ulangi password', { selector: 'input' }), 'baru-rahasia-1')
  await userEvent.click(within(d).getByRole('button', { name: 'Reset password' }))
  await waitFor(() => expect(calls(f, 'PATCH')[0]).toEqual({ url: '/api/v1/users/3', body: { password: 'baru-rahasia-1' } }))

  await userEvent.click(screen.getByTestId('user-deactivate-3'))
  await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Nonaktifkan' }))
  expect(await screen.findByTestId('user-activate-3')).toBeInTheDocument()
  expect(screen.getByTestId('user-row-3')).toHaveTextContent('Nonaktif')
  expect(calls(f, 'PATCH')[1].body).toEqual({ is_active: false })

  await userEvent.click(screen.getByTestId('user-activate-3'))
  expect(await screen.findByTestId('user-deactivate-3')).toBeInTheDocument()
  expect(calls(f, 'PATCH')[2].body).toEqual({ is_active: true })

  await userEvent.click(screen.getByTestId('user-delete-3'))
  await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Hapus' }))
  await waitFor(() => expect(screen.queryByTestId('user-row-3')).not.toBeInTheDocument())
})

test('penolakan server (admin terakhir) tampil sebagai pesan', async () => {
  renderPage()
  await screen.findByTestId('user-row-2')
  await userEvent.click(screen.getByTestId('user-role-2'))
  expect(await screen.findByText('Harus tersisa minimal satu admin aktif')).toBeInTheDocument()
})
