import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import EnrollmentPage from '../features/enrollment/EnrollmentPage'

const ME = { id: 1, username: 'admin', role: 'admin' }

const EMPLOYEES = [
  { id: 1, name: 'Budi Santoso', employee_code: 'EMP-0012', active: true, shift_id: 1, shift_name: 'Shift 1' },
  { id: 2, name: 'Sari Dewi', employee_code: 'EMP-0044', active: true, shift_id: 2, shift_name: 'Shift 2' },
]

const SHIFTS = [{ id: 1, name: 'Shift 1', start_time: '07:00', end_time: '16:00', tolerance_min: 15, workdays: [1, 2, 3, 4, 5] }]

const STATUS: Record<number, { photos: number; active: boolean }> = {
  1: { photos: 3, active: true },
  2: { photos: 0, active: false },
}

const PHOTOS = [{ id: 5, quality: 0.97, created_at: '2025-01-10T08:00:00Z', path: 'faces/1/a.jpg' }]

type Call = { url: string; init?: RequestInit }

const resp = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })

function stubFetch() {
  const calls: Call[] = []
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    calls.push({ url: u, init })
    if (u.endsWith('/auth/me')) return resp(200, ME)
    if (u.endsWith('/shifts')) return resp(200, SHIFTS)
    if (u.endsWith('/enrollment-status')) return resp(200, STATUS[Number(u.match(/employees\/(\d+)/)?.[1])] ?? { photos: 0, active: false })
    if (u.endsWith('/photos/batch') && init?.method === 'POST') return resp(200, { results: [{ ok: true, quality: 0.9 }] })
    if (u.endsWith('/photos') && init?.method === 'POST') return resp(200, { embedding_id: 9, quality: 0.9 })
    if (u.endsWith('/photos')) return resp(200, PHOTOS)
    if (u.endsWith('/employees')) return resp(200, EMPLOYEES)
    return resp(404, null)
  })
  vi.stubGlobal('fetch', fetchMock)
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

test('renders employee list with face count badge and status dot', async () => {
  stubFetch()
  renderPage()

  expect((await screen.findAllByText('Budi Santoso')).length).toBeGreaterThanOrEqual(1)
  expect(screen.getByTestId('en-face-1')).toHaveTextContent('3 Foto')
  expect(screen.getByTestId('en-face-2')).toHaveTextContent('BELUM')

  // dot hijau (aktif) vs abu (belum cukup foto)
  const dot1 = screen.getByTestId('en-dot-1')
  const dot2 = screen.getByTestId('en-dot-2')
  expect(dot1.style.background).not.toBe(dot2.style.background)
  expect(dot1.style.background).toMatch(/66, 190, 101|42be65/)
})

test('upload input posts multipart to enrollment API', async () => {
  const calls = stubFetch()
  renderPage()

  await screen.findAllByText('Budi Santoso')
  const file = new File(['face-bytes'], 'face.jpg', { type: 'image/jpeg' })
  fireEvent.change(screen.getByTestId('en-upload-input'), { target: { files: [file] } })

  await waitFor(() => {
    const post = calls.find((c) => c.url.endsWith('/employees/1/photos/batch') && c.init?.method === 'POST')
    expect(post).toBeDefined()
    expect(post!.init!.body).toBeInstanceOf(FormData)
    expect((post!.init!.body as FormData).getAll('files')).toEqual([file])
  })
})

test('multi-file upload: batch dipanggil sekali + hasil per foto tampil', async () => {
  const calls = stubFetch()
  renderPage()
  await screen.findAllByText('Budi Santoso')

  const ok = new File(['a'], 'a.jpg', { type: 'image/jpeg' })
  const bad = new File(['b'], 'b.jpg', { type: 'image/jpeg' })
  // stub batch: file kedua gagal (no_face)
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    calls.push({ url: u, init })
    if (u.endsWith('/auth/me')) return resp(200, ME)
    if (u.endsWith('/shifts')) return resp(200, SHIFTS)
    if (u.endsWith('/enrollment-status')) return resp(200, { photos: 0, active: false })
    if (u.endsWith('/photos/batch') && init?.method === 'POST') {
      return resp(200, { results: [{ ok: true, quality: 0.91 }, { ok: false, reason: 'no_face' }] })
    }
    if (u.endsWith('/photos')) return resp(200, PHOTOS)
    if (u.endsWith('/employees')) return resp(200, EMPLOYEES)
    return resp(404, null)
  }))
  fireEvent.change(screen.getByTestId('en-upload-input'), { target: { files: [ok, bad] } })

  await waitFor(() => {
    const post = calls.find((c) => c.url.endsWith('/employees/1/photos/batch'))
    expect(post).toBeDefined()
    expect((post!.init!.body as FormData).getAll('files')).toHaveLength(2)
  })
  const list = await screen.findByTestId('en-batch-results')
  expect(list).toHaveTextContent('Tersimpan (hasil crop)')
  expect(list).toHaveTextContent('Skor: 0.91')
  expect(list).toHaveTextContent('Wajah tidak terdeteksi')
})
