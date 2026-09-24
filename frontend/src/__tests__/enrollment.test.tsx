import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import EnrollmentPage from '../features/enrollment/EnrollmentPage'

const ME = { id: 1, username: 'admin', role: 'admin' }

const EMPLOYEES = [
  { id: 1, name: 'Budi Santoso', employee_code: 'EMP-0012', active: true, shift_id: 1, shift_name: 'Shift 1', photo_count: 3, face_ready: true },
  { id: 2, name: 'Sari Dewi', employee_code: 'EMP-0044', active: true, shift_id: 2, shift_name: 'Shift 2', photo_count: 0, face_ready: false },
  { id: 3, name: 'Joko Lama', employee_code: 'EMP-0003', active: false, shift_id: null, shift_name: null, photo_count: 1, face_ready: false },
]

const SHIFTS = [{ id: 1, name: 'Shift 1', start_time: '07:00', end_time: '16:00', tolerance_min: 15, workdays: [1, 2, 3, 4, 5] }]

const PHOTOS = [{ id: 5, quality: 0.97, created_at: '2025-01-10T08:00:00Z', path: 'faces/1/a.jpg' }]

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
    if (u.endsWith('/shifts')) return resp(200, SHIFTS)
    if (u.endsWith('/photos/batch') && init?.method === 'POST') return resp(200, { results: [{ ok: true, quality: 0.9 }] })
    if (u.endsWith('/photos')) return resp(200, PHOTOS)
    if (u.endsWith('/biometrics') && init?.method === 'DELETE') return resp(200, { deleted: 3 })
    const one = u.match(/\/employees\/(\d+)$/)
    if (one && init?.method === 'PATCH') {
      const emp = EMPLOYEES.find((e) => e.id === Number(one[1]))
      return resp(200, { ...emp, ...JSON.parse(String(init.body)) })
    }
    if (one && init?.method === 'DELETE') return resp(200, { ok: true })
    if (u.endsWith('/employees')) return resp(200, EMPLOYEES)
    return resp(404, null)
  }))
  return calls
}

function renderPage() {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/enrollment']}>
        <EnrollmentPage />
      </MemoryRouter>
    </I18nProvider>,
  )
}

const bodyOf = (c: Call | undefined) => JSON.parse(String(c!.init!.body))

test('daftar: badge wajah dari photo_count tanpa panggilan enrollment-status', async () => {
  const calls = stubFetch()
  renderPage()
  expect((await screen.findAllByText('Budi Santoso')).length).toBeGreaterThanOrEqual(1)
  expect(screen.getByTestId('en-face-1')).toHaveTextContent('3 Foto')
  expect(screen.getByTestId('en-face-2')).toHaveTextContent('BELUM')
  const dot1 = screen.getByTestId('en-dot-1')
  const dot2 = screen.getByTestId('en-dot-2')
  expect(dot1.style.background).not.toBe(dot2.style.background)
  expect(calls.some((c) => c.url.endsWith('/enrollment-status'))).toBe(false)
})

test('filter status: default Aktif, Nonaktif menampilkan karyawan nonaktif dengan tag', async () => {
  stubFetch()
  renderPage()
  await screen.findAllByText('Budi Santoso')
  expect(screen.queryByTestId('en-row-3')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'inactive' } })
  expect(await screen.findByTestId('en-row-3')).toBeInTheDocument()
  expect(screen.getByTestId('en-inactive-3')).toHaveTextContent('Nonaktif')
  expect(screen.queryByTestId('en-row-1')).not.toBeInTheDocument()
})

test('NIK bisa diedit dan dikirim di PATCH', async () => {
  const calls = stubFetch()
  renderPage()
  await screen.findAllByText('Budi Santoso')
  const code = within(screen.getByTestId('en-card-identity')).getByLabelText('NIK')
  expect(code).not.toBeDisabled()
  fireEvent.change(code, { target: { value: ' EMP-0099 ' } })
  fireEvent.click(screen.getByTestId('en-save'))
  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/employees/1') && c.init?.method === 'PATCH')
    expect(bodyOf(patch)).toEqual({ name: 'Budi Santoso', employee_code: 'EMP-0099', shift_id: 1 })
  })
})

test('NIK duplikat saat simpan → pesan inline di field NIK', async () => {
  stubFetch((u, init) => (u.endsWith('/employees/1') && init?.method === 'PATCH' ? resp(409, { detail: 'dup' }) : undefined))
  renderPage()
  await screen.findAllByText('Budi Santoso')
  fireEvent.change(within(screen.getByTestId('en-card-identity')).getByLabelText('NIK'), { target: { value: 'EMP-0044' } })
  fireEvent.click(screen.getByTestId('en-save'))
  expect(await screen.findByText('NIK sudah dipakai')).toBeInTheDocument()
})

test('hapus foto wajah ada di kartu Wajah, menyebut nama, dan memanggil biometrics karyawan itu', async () => {
  const calls = stubFetch()
  renderPage()
  await screen.findAllByText('Budi Santoso')
  const purge = within(screen.getByTestId('en-card-face')).getByTestId('en-purge')
  expect(purge).toHaveTextContent('Budi Santoso')
  fireEvent.click(purge)
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveTextContent('3 foto')
  expect(dialog).toHaveTextContent('Budi Santoso')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Hapus foto' }))
  await waitFor(() => expect(calls.some((c) => c.url.endsWith('/employees/1/biometrics') && c.init?.method === 'DELETE')).toBe(true))
})

test('hapus foto wajah nonaktif bila belum ada foto', async () => {
  stubFetch()
  renderPage()
  fireEvent.click(await screen.findByTestId('en-row-2'))
  await waitFor(() => expect(within(screen.getByTestId('en-card-face')).getByTestId('en-purge')).toBeDisabled())
})

test('nonaktifkan butuh konfirmasi; detail tetap pada karyawan itu', async () => {
  const calls = stubFetch((u, init) => {
    if (u.endsWith('/employees') && !init?.method && calls.some((c) => c.init?.method === 'PATCH')) {
      return resp(200, EMPLOYEES.map((e) => (e.id === 1 ? { ...e, active: false } : e)))
    }
    return undefined
  })
  renderPage()
  await screen.findAllByText('Budi Santoso')
  fireEvent.click(screen.getByTestId('en-toggle-active'))
  expect(calls.some((c) => c.init?.method === 'PATCH')).toBe(false)
  const dialog = await screen.findByRole('dialog')
  expect(dialog).toHaveTextContent('tidak akan dikenali di gate')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Nonaktifkan' }))
  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/employees/1') && c.init?.method === 'PATCH')
    expect(bodyOf(patch)).toEqual({ active: false })
  })
  // baris keluar dari filter Aktif, tapi panel detail tetap pada Budi dengan tombol Aktifkan
  await waitFor(() => expect(screen.queryByTestId('en-row-1')).not.toBeInTheDocument())
  expect(screen.getByTestId('en-toggle-active')).toHaveTextContent('Aktifkan')
})

test('hapus karyawan ber-riwayat absensi → ditawarkan Nonaktifkan', async () => {
  const calls = stubFetch((u, init) => (u.endsWith('/employees/1') && init?.method === 'DELETE' ? resp(409, { detail: 'history' }) : undefined))
  renderPage()
  await screen.findAllByText('Budi Santoso')
  fireEvent.click(screen.getByTestId('en-delete'))
  let dialog = await screen.findByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Hapus karyawan' }))
  await waitFor(() => expect(screen.getByRole('dialog')).toHaveTextContent('sudah punya riwayat absensi'))
  dialog = screen.getByRole('dialog')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Nonaktifkan' }))
  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/employees/1') && c.init?.method === 'PATCH')
    expect(bodyOf(patch)).toEqual({ active: false })
  })
})

test('hapus karyawan nonaktif ber-riwayat → tidak menawarkan Nonaktifkan lagi', async () => {
  stubFetch((u, init) => (u.endsWith('/employees/3') && init?.method === 'DELETE' ? resp(409, { detail: 'history' }) : undefined))
  renderPage()
  await screen.findAllByText('Budi Santoso')
  fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'inactive' } })
  fireEvent.click(await screen.findByTestId('en-row-3'))
  fireEvent.click(screen.getByTestId('en-delete'))
  fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Hapus karyawan' }))
  await waitFor(() => expect(screen.getByRole('dialog')).toHaveTextContent('sudah nonaktif'))
  expect(within(screen.getByRole('dialog')).queryByRole('button', { name: 'Nonaktifkan' })).not.toBeInTheDocument()
})

test('tambah karyawan: Simpan nonaktif selama nama/NIK kosong; 409 → pesan di NIK', async () => {
  stubFetch((u, init) => (u.endsWith('/employees') && init?.method === 'POST' ? resp(409, { detail: 'dup' }) : undefined))
  renderPage()
  await screen.findAllByText('Budi Santoso')
  fireEvent.click(screen.getByTestId('en-add'))
  const dialog = await screen.findByRole('dialog')
  const save = within(dialog).getByRole('button', { name: 'Simpan' })
  expect(save).toBeDisabled()
  fireEvent.change(within(dialog).getByLabelText('Nama'), { target: { value: 'Ani' } })
  fireEvent.change(within(dialog).getByLabelText('NIK'), { target: { value: 'EMP-0012' } })
  expect(save).not.toBeDisabled()
  fireEvent.click(save)
  expect(await within(dialog).findByText('NIK sudah dipakai')).toBeInTheDocument()
})

test('upload multi-file: batch sekali + hasil per foto', async () => {
  const calls = stubFetch((u, init) =>
    u.endsWith('/photos/batch') && init?.method === 'POST'
      ? resp(200, { results: [{ ok: true, quality: 0.91 }, { ok: false, reason: 'no_face' }] })
      : undefined,
  )
  renderPage()
  await screen.findAllByText('Budi Santoso')
  const ok = new File(['a'], 'a.jpg', { type: 'image/jpeg' })
  const bad = new File(['b'], 'b.jpg', { type: 'image/jpeg' })
  fireEvent.change(screen.getByTestId('en-upload-input'), { target: { files: [ok, bad] } })
  await waitFor(() => {
    const post = calls.find((c) => c.url.endsWith('/employees/1/photos/batch'))
    expect((post!.init!.body as FormData).getAll('files')).toEqual([ok, bad])
  })
  const list = await screen.findByTestId('en-batch-results')
  expect(list).toHaveTextContent('Tersimpan (hasil crop)')
  expect(list).toHaveTextContent('Skor: 0.91')
  expect(list).toHaveTextContent('Wajah tidak terdeteksi')
})
