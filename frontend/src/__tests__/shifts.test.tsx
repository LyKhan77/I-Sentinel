import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import EnrollmentPage from '../features/enrollment/EnrollmentPage'

const ME = { id: 1, username: 'admin', role: 'admin' }
const SHIFTS = [{ id: 1, name: 'Shift 1', start_time: '07:00', end_time: '16:00', tolerance_min: 15, workdays: [1, 2, 3, 4, 5] }]

type Call = { url: string; init?: RequestInit }
const resp = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })
type Route = (u: string, init?: RequestInit) => ReturnType<typeof resp> | undefined

function stubFetch(route?: Route) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    calls.push({ url: u, init })
    const hit = route?.(u, init)
    if (hit) return hit
    if (u.endsWith('/auth/me')) return resp(200, ME)
    if (u.endsWith('/shifts') && init?.method === 'POST') return resp(200, { id: 2, ...JSON.parse(String(init.body)) })
    if (/\/shifts\/\d+$/.test(u) && init?.method === 'PATCH') return resp(200, { ...SHIFTS[0], ...JSON.parse(String(init.body)) })
    if (/\/shifts\/\d+$/.test(u) && init?.method === 'DELETE') return resp(200, { ok: true })
    if (u.endsWith('/shifts')) return resp(200, SHIFTS)
    if (u.endsWith('/employees')) return resp(200, [])
    return resp(404, null)
  }))
  return calls
}

function renderShifts() {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/enrollment?tab=shifts']}>
        <EnrollmentPage />
      </MemoryRouter>
    </I18nProvider>,
  )
}

test('tab Shift menampilkan jam, toleransi, dan hari kerja', async () => {
  stubFetch()
  renderShifts()
  const row = await screen.findByTestId('sh-row-1')
  expect(row).toHaveTextContent('07:00–16:00')
  expect(row).toHaveTextContent('15 mnt')
  expect(row).toHaveTextContent('Sen, Sel, Rab, Kam, Jum')
})

test('tambah shift: selesai <= mulai ditolak di form, valid → POST lengkap', async () => {
  const calls = stubFetch()
  renderShifts()
  fireEvent.click(await screen.findByTestId('sh-add'))
  const dialog = await screen.findByRole('dialog')
  fireEvent.change(within(dialog).getByLabelText('Nama shift'), { target: { value: 'Pagi' } })
  fireEvent.change(within(dialog).getByLabelText('Selesai'), { target: { value: '06:00' } })
  expect(within(dialog).getByTestId('sh-form-problem')).toHaveTextContent('Jam selesai harus setelah jam mulai')
  expect(within(dialog).getByRole('button', { name: 'Simpan' })).toBeDisabled()

  fireEvent.change(within(dialog).getByLabelText('Selesai'), { target: { value: '15:00' } })
  fireEvent.click(within(dialog).getByLabelText('Sab'))
  fireEvent.click(within(dialog).getByRole('button', { name: 'Simpan' }))
  await waitFor(() => {
    const post = calls.find((c) => c.url.endsWith('/shifts') && c.init?.method === 'POST')
    expect(post).toBeDefined()
    expect(JSON.parse(String(post!.init!.body))).toEqual({
      name: 'Pagi', start_time: '07:00', end_time: '15:00', tolerance_min: 15, workdays: [1, 2, 3, 4, 5, 6],
    })
  })
})

test('edit shift mengirim PATCH ke shift yang dipilih', async () => {
  const calls = stubFetch()
  renderShifts()
  fireEvent.click(await screen.findByTestId('sh-edit-1'))
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByLabelText('Nama shift')).toHaveValue('Shift 1')
  fireEvent.click(within(dialog).getByLabelText('Jum'))
  fireEvent.click(within(dialog).getByRole('button', { name: 'Simpan' }))
  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/shifts/1') && c.init?.method === 'PATCH')
    expect(JSON.parse(String(patch!.init!.body)).workdays).toEqual([1, 2, 3, 4])
  })
})

test('nama shift duplikat → pesan spesifik di modal', async () => {
  stubFetch((u, init) => (u.endsWith('/shifts') && init?.method === 'POST' ? resp(409, { detail: 'dup' }) : undefined))
  renderShifts()
  fireEvent.click(await screen.findByTestId('sh-add'))
  const dialog = await screen.findByRole('dialog')
  fireEvent.change(within(dialog).getByLabelText('Nama shift'), { target: { value: 'Shift 1' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Simpan' }))
  expect(await within(dialog).findByText('Nama shift sudah dipakai')).toBeInTheDocument()
})

test('hapus shift yang masih dipakai → 409 dijelaskan', async () => {
  stubFetch((u, init) => (/\/shifts\/1$/.test(u) && init?.method === 'DELETE' ? resp(409, { detail: 'in use' }) : undefined))
  renderShifts()
  fireEvent.click(await screen.findByTestId('sh-delete-1'))
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveTextContent('Shift 1')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Hapus' }))
  expect(await within(dialog).findByText(/Shift masih dipakai karyawan/)).toBeInTheDocument()
})
