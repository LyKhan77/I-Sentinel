import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import StoragePage from '../features/config/StoragePage'

const STATS = {
  retention_days: 30,
  settings: { clip_days: 30, snapshot_days: 30, attendance_days: 90, disk_alert_percent: 85 },
  disk_alert: { threshold: 85, over: true },
  storage_root: '/data/isentinel',
  disk: { total: 1000, used: 850, free: 150, percent: 85.0 },
  kinds: {
    clips: { files: 10, bytes: 2048 },
    snapshots: { files: 5, bytes: 1024 },
    crops: { files: 0, bytes: 0 },
  },
  last_sweep: { at: '2026-09-15T03:00:00+00:00', files_deleted: 3, bytes_freed: 4096, events_marked: 2, orphans_deleted: 1, dry_run: false },
}

test('menampilkan retensi, disk, per-jenis, dan sweep terakhir', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: () => Promise.resolve(STATS) })))
  render(
    <I18nProvider>
      <StoragePage />
    </I18nProvider>,
  )
  expect(await screen.findByTestId('storage-disk-percent')).toHaveTextContent('85')
  expect(screen.getByTestId('storage-retention')).toHaveTextContent('30')
  // Intl(id-ID) memangkas trailing `,0` pada maximumFractionDigits: 2048 → "2 kB"
  expect(screen.getByTestId('kind-clips')).toHaveTextContent('2 kB')
  expect(screen.getByTestId('storage-last-sweep')).toBeInTheDocument()
})

const json = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })

function stub(role: 'admin' | 'viewer', putStatus = 200) {
  const f = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    if (u.endsWith('/auth/me')) return json(200, { id: 1, username: 'u', role })
    if (u.endsWith('/storage/settings') && init?.method === 'PUT') {
      return putStatus === 200 ? json(200, JSON.parse(String(init.body))) : json(putStatus, { detail: [] })
    }
    if (u.endsWith('/storage/cleanup') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body))
      return json(200, { events: 3, files: 4, bytes: 2048, dry_run: body.dry_run })
    }
    if (u.endsWith('/storage/stats')) return json(200, STATS)
    if (u.endsWith('/cameras')) return json(200, [])
    return json(404, null)
  })
  vi.stubGlobal('fetch', f)
  return f
}

const renderStorage = () => render(<I18nProvider><StoragePage /></I18nProvider>)

afterEach(() => vi.unstubAllGlobals())

test('banner disk hampir penuh dan tile retensi clip/snapshot', async () => {
  stub('viewer')
  renderStorage()
  expect(await screen.findByTestId('disk-alert')).toHaveTextContent('Disk hampir penuh (85%)')
  expect(screen.getByTestId('storage-retention')).toHaveTextContent('Clip 30 hari · Snapshot 30 hari · Absensi 90 hari')
})

test('admin menyimpan pengaturan retensi', async () => {
  const f = stub('admin')
  renderStorage()
  const clip = await screen.findByLabelText('Retensi clip (hari)')
  await waitFor(() => expect(screen.getByTestId('storage-settings-save')).toBeInTheDocument())
  fireEvent.change(clip, { target: { value: '7' } })
  fireEvent.change(screen.getByLabelText('Retensi media absensi (hari)'), { target: { value: '60' } })
  await userEvent.click(screen.getByTestId('storage-settings-save'))
  expect(await screen.findByText('Pengaturan tersimpan')).toBeInTheDocument()
  const put = f.mock.calls.find(([, i]) => (i as RequestInit | undefined)?.method === 'PUT')!
  expect(JSON.parse(String((put[1] as RequestInit).body))).toEqual({ clip_days: 7, snapshot_days: 30, attendance_days: 60, disk_alert_percent: 85 })
  expect(screen.getByTestId('storage-retention')).toHaveTextContent('Clip 7 hari · Snapshot 30 hari · Absensi 60 hari')
})

test('422 dari server tampil sebagai pesan rentang', async () => {
  stub('admin', 422)
  renderStorage()
  await waitFor(() => expect(screen.getByTestId('storage-settings-save')).toBeInTheDocument())
  await userEvent.click(screen.getByTestId('storage-settings-save'))
  expect(await screen.findByText(/Nilai di luar rentang/)).toBeInTheDocument()
})

test('viewer: pengaturan hanya-baca, tanpa tombol simpan dan tanpa kartu cleanup', async () => {
  stub('viewer')
  renderStorage()
  expect(await screen.findByLabelText('Retensi clip (hari)')).toBeDisabled()
  expect(screen.queryByTestId('storage-settings-save')).not.toBeInTheDocument()
  expect(screen.queryByTestId('storage-cleanup')).not.toBeInTheDocument()
})

async function fillDates(from: string, to: string) {
  fireEvent.change(await screen.findByLabelText('Dari tanggal'), { target: { value: from } })
  fireEvent.change(screen.getByLabelText('Sampai tanggal'), { target: { value: to } })
}

const cleanupCalls = (f: ReturnType<typeof stub>) => f.mock.calls
  .filter(([u]) => String(u).endsWith('/storage/cleanup'))
  .map(([, i]) => JSON.parse(String((i as RequestInit).body)))

test('cleanup: pratinjau lalu konfirmasi hapus', async () => {
  const f = stub('admin')
  renderStorage()
  await fillDates('2026-09-01', '2026-09-10')
  expect(screen.getByTestId('cleanup-delete')).toBeDisabled()
  await userEvent.click(screen.getByTestId('cleanup-preview'))
  expect(await screen.findByTestId('cleanup-preview-result')).toHaveTextContent('3 event · 4 file · 2 kB')
  expect(cleanupCalls(f)[0]).toEqual({ date_from: '2026-09-01', date_to: '2026-09-10', camera_ids: [], types: [], dry_run: true })
  await userEvent.click(screen.getByTestId('cleanup-delete'))
  const dialog = screen.getByRole('dialog')
  expect(dialog).toHaveTextContent('3 event dari 2026-09-01 sampai 2026-09-10')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Hapus 3 event' }))
  expect(await screen.findByText('Event dihapus')).toBeInTheDocument()
  expect(cleanupCalls(f)[1].dry_run).toBe(false)
})

test('hapus nonaktif sampai pratinjau untuk filter yang sama', async () => {
  stub('admin')
  renderStorage()
  await fillDates('2026-09-01', '2026-09-10')
  await userEvent.click(screen.getByTestId('cleanup-preview'))
  await screen.findByTestId('cleanup-preview-result')
  expect(screen.getByTestId('cleanup-delete')).toBeEnabled()
  fireEvent.change(screen.getByLabelText('Sampai tanggal'), { target: { value: '2026-09-20' } })
  expect(screen.getByTestId('cleanup-delete')).toBeDisabled()
  expect(screen.queryByTestId('cleanup-preview-result')).not.toBeInTheDocument()
})

test('rentang terbalik: pratinjau nonaktif', async () => {
  stub('admin')
  renderStorage()
  await fillDates('2026-09-10', '2026-09-01')
  expect(screen.getByTestId('cleanup-preview')).toBeDisabled()
})
