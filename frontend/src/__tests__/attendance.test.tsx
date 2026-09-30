import { render, screen, waitFor, fireEvent, act, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import AttendancePage from '../features/attendance/AttendancePage'
import type { AttendanceRow } from '../api/attendance'

const ME = { id: 1, username: 'admin', role: 'admin' }
const VIEWER = { id: 2, username: 'viewer', role: 'viewer' }

const ROWS: AttendanceRow[] = [
  { id: 11, employee_id: 1, employee_code: 'EMP-0012', name: 'Budi Santoso', date: '2025-01-15', first_entry: '07:58:41', last_exit: '16:10:00', duration_min: 491, status: 'ontime', late_minutes: 0, override_note: null, shift_name: 'Shift 1' },
  { id: 12, employee_id: 2, employee_code: 'EMP-0031', name: 'Rian Wijaya', date: '2025-01-15', first_entry: '07:47:02', last_exit: '12:04:55', duration_min: 257, status: 'late', late_minutes: 47, override_note: null, shift_name: 'Shift 1' },
  { id: 13, employee_id: 3, employee_code: 'EMP-0044', name: 'Sari Dewi', date: '2025-01-15', first_entry: '', last_exit: '', duration_min: null, status: 'absent', late_minutes: null, override_note: null, shift_name: 'Shift 2' },
  { id: 14, employee_id: 4, employee_code: 'EMP-0055', name: 'Tono Prabowo', date: '2025-01-15', first_entry: '15:01:00', last_exit: '', duration_min: null, status: 'waiting', late_minutes: null, override_note: null, shift_name: 'Shift 2' },
]

// 2026-09-29 = Selasa; dipakai untuk kolom Tanggal & format lokal
const RANGE_ROWS: AttendanceRow[] = [
  { id: 31, employee_id: 1, employee_code: 'EMP-1', name: 'Ani Rahma', date: '2026-09-29', first_entry: '07:58:41', last_exit: '16:10:00', duration_min: 492, status: 'ontime', late_minutes: 0, override_note: null, shift_name: 'Pagi' },
  { id: 32, employee_id: 2, employee_code: 'EMP-2', name: 'Bima Putra', date: '2026-09-29', first_entry: '07:05:00', last_exit: '', duration_min: null, status: 'no_exit', late_minutes: null, override_note: null, shift_name: 'Pagi' },
  { id: 33, employee_id: 3, employee_code: 'EMP-3', name: 'Cici Lestari', date: '2026-09-29', first_entry: '', last_exit: '16:05:00', duration_min: null, status: 'no_entry', late_minutes: null, override_note: null, shift_name: 'Pagi' },
]

type Call = { url: string; init?: RequestInit }

const resp = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })

function stubFetch(me = ME, rows: AttendanceRow[] = ROWS) {
  const calls: Call[] = []
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    calls.push({ url: u, init })
    if (u.endsWith('/auth/me')) return resp(200, me)
    if (u.includes('/attendance/rekap.csv')) return resp(200, '')
    if (/\/attendance\/\d+$/.test(u) && init?.method === 'PATCH') return resp(200, rows[1])
    if (u.includes('/attendance')) return resp(200, rows)
    if (u.endsWith('/employees')) return resp(200, [])
    return resp(404, null)
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

afterEach(() => {
  vi.useRealTimers()
})

function renderPage() {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/attendance']}>
        <AttendancePage />
      </MemoryRouter>
    </I18nProvider>,
  )
}

test('renders attendance rows with status badges', async () => {
  stubFetch()
  renderPage()

  expect(await screen.findByText('Budi Santoso')).toBeInTheDocument()
  expect(screen.getByText('Rian Wijaya')).toBeInTheDocument()
  expect(screen.getByTestId('status-ontime')).toHaveTextContent('TEPAT WAKTU')
  expect(screen.getByTestId('status-late')).toHaveTextContent('TELAT 47 MNT')
  expect(screen.getByTestId('status-absent')).toHaveTextContent('TIDAK HADIR')
  expect(screen.getByTestId('status-waiting')).toHaveTextContent('DI DALAM')
})

test('daily summary tiles count statuses', async () => {
  stubFetch()
  renderPage()

  await screen.findByText('Budi Santoso')
  expect(screen.getByTestId('tile-hadir')).toHaveTextContent('2') // ontime + late
  expect(screen.getByTestId('tile-inside')).toHaveTextContent('1') // waiting
  expect(screen.getByTestId('tile-absent')).toHaveTextContent('1')
  expect(screen.getByTestId('tile-late-max')).toHaveTextContent('47 mnt')
})

test('viewer (non-admin) has no import button', async () => {
  stubFetch(VIEWER)
  renderPage()

  await screen.findByText('Budi Santoso')
  expect(screen.queryByTestId('import-btn')).not.toBeInTheDocument()
  expect(screen.getByTestId('export-btn')).toBeInTheDocument()
})

test('override modal blocks submit without note, then PATCHes when filled', async () => {
  const calls = stubFetch()
  renderPage()

  await userEvent.click(await screen.findByTestId('at-row-12'))
  const note = await screen.findByTestId('ov-note')

  // catatan kosong → submit diblokir, tidak ada PATCH
  await userEvent.click(screen.getByRole('button', { name: 'Simpan koreksi' }))
  expect(await screen.findByText('Catatan wajib diisi untuk koreksi manual')).toBeInTheDocument()
  expect(calls.some((c) => c.url.endsWith('/attendance/12') && c.init?.method === 'PATCH')).toBe(false)

  // isi catatan → PATCH terkirim
  fireEvent.change(note, { target: { value: 'koreksi manual' } })
  await userEvent.click(screen.getByRole('button', { name: 'Simpan koreksi' }))
  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/attendance/12') && c.init?.method === 'PATCH')
    expect(patch).toBeDefined()
    expect(JSON.parse(String(patch!.init!.body)).override_note).toBe('koreksi manual')
  })
})


test('tab Harian tanpa kolom Tanggal; tab Rentang dengan kolom Tanggal lokal', async () => {
  stubFetch(ME, RANGE_ROWS)
  renderPage()

  await screen.findByText('Ani Rahma')
  expect(screen.queryByTestId('at-col-date')).not.toBeInTheDocument()

  await userEvent.click(screen.getByTestId('tab-range'))
  expect(await screen.findByTestId('at-col-date')).toBeInTheDocument()
  const cell = screen.getByTestId('at-date-31')
  const expected = new Date('2026-09-29T00:00:00').toLocaleDateString('id', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
  expect(cell).toHaveTextContent(expected)
  expect(cell).toHaveTextContent('29')
  expect(cell).toHaveTextContent('Sep')
})

test('entry/exit tampil HH:MM tanpa detik; judul kolom memuat WIB', async () => {
  stubFetch(ME, RANGE_ROWS)
  renderPage()

  const row = await screen.findByTestId('at-row-31')
  expect(within(row).getByText('07:58')).toBeInTheDocument()
  expect(within(row).getByText('16:10')).toBeInTheDocument()
  expect(within(row).queryByText('07:58:41')).not.toBeInTheDocument()
  expect(screen.getByRole('columnheader', { name: /ENTRY \(WIB\)/ })).toBeInTheDocument()
  expect(screen.getByRole('columnheader', { name: /EXIT \(WIB\)/ })).toBeInTheDocument()
})

test('durasi: menit tersimpan, berjalan hanya untuk waiting hari ini', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date(2026, 8, 30, 12, 0, 0)) // Sel, 30 Sep 2026 12:00 lokal
  const durRows: AttendanceRow[] = [
    { id: 41, employee_id: 1, employee_code: 'E-1', name: 'Dodi', date: '2026-09-30', first_entry: '10:00:00', last_exit: '', duration_min: null, status: 'waiting', late_minutes: null, override_note: null, shift_name: 'Pagi' },
    { id: 42, employee_id: 2, employee_code: 'E-2', name: 'Eka', date: '2026-09-29', first_entry: '10:00:00', last_exit: '', duration_min: null, status: 'waiting', late_minutes: null, override_note: null, shift_name: 'Pagi' },
    { id: 43, employee_id: 3, employee_code: 'E-3', name: 'Fajar', date: '2026-09-30', first_entry: '07:00:00', last_exit: '', duration_min: null, status: 'no_exit', late_minutes: null, override_note: null, shift_name: 'Pagi' },
    { id: 44, employee_id: 4, employee_code: 'E-4', name: 'Gita', date: '2026-09-30', first_entry: '07:30:00', last_exit: '16:42:00', duration_min: 492, status: 'ontime', late_minutes: 0, override_note: null, shift_name: 'Pagi' },
  ]
  stubFetch(ME, durRows)
  renderPage()
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })

  expect(screen.getByTestId('at-dur-41')).toHaveTextContent('2j 0m')
  expect(screen.getByTestId('at-dur-41')).toHaveTextContent('berjalan')
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
  expect(screen.getByTestId('at-dur-41')).toHaveTextContent('2j 1m')

  expect(screen.getByTestId('at-dur-42')).toHaveTextContent('—') // waiting kemarin
  expect(screen.getByTestId('at-dur-43')).toHaveTextContent('—') // no_exit
  expect(screen.getByTestId('at-dur-44')).toHaveTextContent('8j 12m')
})

test('label status perlu koreksi untuk no_exit dan no_entry', async () => {
  stubFetch(ME, RANGE_ROWS)
  renderPage()

  await screen.findByText('Ani Rahma')
  expect(screen.getByTestId('status-no_exit')).toHaveTextContent('TANPA EXIT — PERLU KOREKSI')
  expect(screen.getByTestId('status-no_entry')).toHaveTextContent('TANPA ENTRY — PERLU KOREKSI')
})

test('modal koreksi menawarkan status no_entry', async () => {
  stubFetch(ME, RANGE_ROWS)
  renderPage()

  await userEvent.click(await screen.findByTestId('at-row-31'))
  await screen.findByTestId('ov-note')
  const options = screen.getAllByRole('option')
  expect(options.some((o) => o.textContent === 'TANPA ENTRY — PERLU KOREKSI')).toBe(true)
})
