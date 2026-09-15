import { render, screen, waitFor, fireEvent } from '@testing-library/react'
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

type Call = { url: string; init?: RequestInit }

const resp = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })

function stubFetch(me = ME) {
  const calls: Call[] = []
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    calls.push({ url: u, init })
    if (u.endsWith('/auth/me')) return resp(200, me)
    if (u.includes('/attendance/rekap.csv')) return resp(200, '')
    if (/\/attendance\/\d+$/.test(u) && init?.method === 'PATCH') return resp(200, ROWS[1])
    if (u.includes('/attendance')) return resp(200, ROWS)
    if (u.endsWith('/employees')) return resp(200, [])
    return resp(404, null)
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

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
  expect(screen.getByTestId('status-waiting')).toHaveTextContent('MENUNGGU')
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
