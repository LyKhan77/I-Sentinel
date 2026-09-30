import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import StoragePage from '../features/config/StoragePage'

const STATS = {
  retention_days: 30,
  settings: { clip_days: 30, snapshot_days: 30, attendance_days: 90, disk_alert_percent: 85 },
  disk_alert: { threshold: 85, over: false },
  storage_root: '/data/isentinel',
  disk: { total: 1000, used: 500, free: 500, percent: 50.0 },
  kinds: { clips: { files: 0, bytes: 0 }, snapshots: { files: 0, bytes: 0 }, crops: { files: 0, bytes: 0 } },
  last_sweep: null,
}

const EMPLOYEES = [
  { id: 2, name: 'Budi', employee_code: 'B-1', active: true, shift_id: null, shift_name: null, photo_count: 3, face_ready: true },
  { id: 1, name: 'Ani', employee_code: 'A-1', active: true, shift_id: null, shift_name: null, photo_count: 3, face_ready: true },
]

const json = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })

const DATA_RESULT = {
  events: 2, files: 1, bytes: 1024, attendance_events: 3, days: 2,
  employees: [
    { id: 1, name: 'Ani', attendance_events: 2, days: 1 },
    { id: 2, name: 'Budi', attendance_events: 1, days: 1 },
  ],
}

function stub() {
  const f = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    if (u.endsWith('/auth/me')) return json(200, { id: 1, username: 'admin', role: 'admin' })
    if (u.endsWith('/storage/cleanup') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body))
      return json(200, { ...DATA_RESULT, dry_run: body.dry_run })
    }
    if (u.endsWith('/storage/stats')) return json(200, STATS)
    if (u.endsWith('/cameras')) return json(200, [])
    if (u.endsWith('/employees')) return json(200, EMPLOYEES)
    return json(404, null)
  })
  vi.stubGlobal('fetch', f)
  return f
}

const renderStorage = () => render(<I18nProvider><StoragePage /></I18nProvider>)
afterEach(() => vi.unstubAllGlobals())

const cleanupCalls = (f: ReturnType<typeof stub>) => f.mock.calls
  .filter(([u]) => String(u).endsWith('/storage/cleanup'))
  .map(([, i]) => JSON.parse(String((i as RequestInit).body)))

async function fillDates(from: string, to: string) {
  fireEvent.change(await screen.findByLabelText('Dari tanggal'), { target: { value: from } })
  fireEvent.change(screen.getByLabelText('Sampai tanggal'), { target: { value: to } })
}

async function selectDataMode() {
  await screen.findByTestId('storage-cleanup')
  await userEvent.click(screen.getByLabelText('Data absensi (rekap & riwayat)'))
}

test('mode data absensi: sembunyikan kamera/jenis, tampilkan karyawan + checkbox semua', async () => {
  stub()
  renderStorage()
  await selectDataMode()
  expect(screen.queryByRole('combobox', { name: /Kamera/ })).not.toBeInTheDocument()
  expect(screen.queryByRole('combobox', { name: /Jenis/ })).not.toBeInTheDocument()
  expect(screen.getByRole('combobox', { name: /Karyawan/ })).toBeInTheDocument()
  expect(screen.getByLabelText('Semua karyawan')).toBeInTheDocument()
})

test('pratinjau nonaktif sampai karyawan dipilih atau semua dicentang', async () => {
  stub()
  renderStorage()
  await selectDataMode()
  await fillDates('2026-09-01', '2026-09-10')
  expect(screen.getByTestId('cleanup-preview')).toBeDisabled()

  await userEvent.click(screen.getByLabelText('Semua karyawan'))
  expect(screen.getByTestId('cleanup-preview')).toBeEnabled()

  await userEvent.click(screen.getByLabelText('Semua karyawan')) // uncentang lagi
  expect(screen.getByTestId('cleanup-preview')).toBeDisabled()

  await userEvent.click(screen.getByRole('combobox', { name: /Karyawan/ }))
  await userEvent.click(await screen.findByRole('option', { name: 'Ani (A-1)' }))
  expect(screen.getByTestId('cleanup-preview')).toBeEnabled()
})

test('payload attendance_data: employee_ids/all_employees, dry_run true lalu false, tabel per karyawan', async () => {
  const f = stub()
  renderStorage()
  await selectDataMode()
  await fillDates('2026-09-01', '2026-09-10')
  await userEvent.click(screen.getByRole('combobox', { name: /Karyawan/ }))
  await userEvent.click(await screen.findByRole('option', { name: 'Ani (A-1)' }))

  await userEvent.click(screen.getByTestId('cleanup-preview'))
  await screen.findByTestId('cleanup-preview-result')
  const previewCall = cleanupCalls(f).at(-1)!
  expect(previewCall).toMatchObject({
    mode: 'attendance_data', employee_ids: [1], all_employees: false, camera_ids: [], types: [], dry_run: true,
  })
  expect(screen.getByTestId('cleanup-preview-result')).toHaveTextContent('3 riwayat')
  expect(screen.getByTestId('cleanup-preview-result')).toHaveTextContent('2 hari rekap')
  const rows = within(screen.getByTestId('cleanup-preview-result')).getAllByRole('row')
  expect(rows.length).toBe(3) // header + 2 karyawan
  expect(rows[1]).toHaveTextContent('Ani')
  expect(rows[2]).toHaveTextContent('Budi')

  await userEvent.click(screen.getByTestId('cleanup-delete'))
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).getByRole('button', { name: 'Hapus data absensi' })).toBeDisabled()
  await userEvent.type(within(dialog).getByLabelText(/Ketik HAPUS/), 'HAPUS')
  expect(within(dialog).getByRole('button', { name: 'Hapus data absensi' })).toBeEnabled()
  await userEvent.click(within(dialog).getByRole('button', { name: 'Hapus data absensi' }))
  expect(await screen.findByText('Data absensi dihapus')).toBeInTheDocument()
  expect(cleanupCalls(f).at(-1)).toMatchObject({ mode: 'attendance_data', dry_run: false })
})

test('konfirmasi tetap terkunci bila kata yang diketik salah', async () => {
  stub()
  renderStorage()
  await selectDataMode()
  await fillDates('2026-09-01', '2026-09-10')
  await userEvent.click(screen.getByLabelText('Semua karyawan'))
  await userEvent.click(screen.getByTestId('cleanup-preview'))
  await screen.findByTestId('cleanup-preview-result')
  await userEvent.click(screen.getByTestId('cleanup-delete'))
  const dialog = screen.getByRole('dialog')
  await userEvent.type(within(dialog).getByLabelText(/Ketik HAPUS/), 'hapus')
  expect(within(dialog).getByRole('button', { name: 'Hapus data absensi' })).toBeDisabled()
})

test('mode lain tidak mengirim employee_ids/all_employees terisi', async () => {
  const f = stub()
  renderStorage()
  await waitFor(() => expect(screen.getByTestId('storage-cleanup')).toBeInTheDocument())
  await fillDates('2026-09-01', '2026-09-10')
  await userEvent.click(screen.getByTestId('cleanup-preview'))
  await screen.findByTestId('cleanup-preview-result')
  const call = cleanupCalls(f).at(-1)!
  expect(call.employee_ids).toEqual([])
  expect(call.all_employees).toBe(false)
})
