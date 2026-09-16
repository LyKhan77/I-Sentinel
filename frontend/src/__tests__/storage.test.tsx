import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import StoragePage from '../features/config/StoragePage'

const STATS = {
  retention_days: 30,
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
