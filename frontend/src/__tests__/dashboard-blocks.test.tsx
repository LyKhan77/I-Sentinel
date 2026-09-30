import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ReactElement } from 'react'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import StatusStrip from '../features/dashboard/StatusStrip'
import KpiTiles from '../features/dashboard/KpiTiles'
import type { DashboardData } from '../features/dashboard/useDashboardData'
import { emptyData, mon, alert, att, stats, storage } from './dashboardFixtures'

function show(ui: ReactElement) {
  return render(<I18nProvider><MemoryRouter>{ui}</MemoryRouter></I18nProvider>)
}
const strip = (data: DashboardData) => show(<StatusStrip data={data} />)
const tiles = (data: DashboardData) => show(<KpiTiles data={data} />)

const FAILED_MONITORING = { monitoring: true, alerts: false, stats: false, attendance: false, storage: false }
const FAILED_STATS = { monitoring: false, alerts: false, stats: true, attendance: false, storage: false }
const FAILED_ATTENDANCE = { monitoring: false, alerts: false, stats: false, attendance: true, storage: false }

describe('StatusStrip', () => {
  test('shows normal when healthy and no alerts', () => {
    strip(emptyData({ monitoring: mon() }))
    expect(screen.getByText('Semua sistem normal')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /Monitoring/ })
    expect(link).toHaveAttribute('href', '/monitoring')
  })

  test('shows alert count', () => {
    strip(emptyData({ monitoring: mon(), alerts: [alert({ severity: 'critical' }), alert({ id: 2 })] }))
    expect(screen.getByText('2 peringatan aktif')).toBeInTheDocument()
  })

  test('shows unavailable when monitoring failed', () => {
    strip(emptyData({ monitoring: null, failed: FAILED_MONITORING }))
    expect(screen.getByText('Status sistem tidak tersedia')).toBeInTheDocument()
  })

  test('shows stale note when a source failed but data exists', () => {
    strip(emptyData({
      monitoring: mon(), attendance: null,
      failed: FAILED_ATTENDANCE, updatedAt: new Date(),
    }))
    expect(screen.getByText(/Gagal memperbarui — data terakhir/)).toBeInTheDocument()
  })

  test('shows health label when unhealthy and no alerts', () => {
    strip(emptyData({ monitoring: mon({ summary: { health: 'critical' } }) }))
    expect(screen.getByText('Kritis')).toBeInTheDocument()
    expect(screen.queryByText('Semua sistem normal')).toBeNull()
  })
})

describe('KpiTiles', () => {
  test('camera tile shows healthy/total and problem count', () => {
    tiles(emptyData({ monitoring: mon() }))
    const tile = screen.getByRole('link', { name: /^Kamera/ })
    expect(tile).toHaveAttribute('href', '/monitoring')
    expect(within(tile).getByText('1/3')).toBeInTheDocument()
    expect(within(tile).getByText('2 bermasalah')).toBeInTheDocument()
  })

  test('event tile shows total and critical count', () => {
    tiles(emptyData({ stats: stats() }))
    const tile = screen.getByRole('link', { name: /^Event hari ini/ })
    expect(tile).toHaveAttribute('href', '/events')
    expect(within(tile).getByText('47')).toBeInTheDocument()
    expect(within(tile).getByText('3 critical')).toBeInTheDocument()
  })

  test('attendance tile shows present, late and needs-correction', () => {
    tiles(emptyData({ attendance: [att('ontime'), att('late'), att('no_exit'), att('no_entry')] }))
    const tile = screen.getByRole('link', { name: /^Kehadiran hari ini/ })
    expect(tile).toHaveAttribute('href', '/attendance')
    expect(within(tile).getByText('4')).toBeInTheDocument()
    expect(within(tile).getByText('1 telat · 2 perlu koreksi')).toBeInTheDocument()
  })

  test('disk tile shows percent and free space', () => {
    tiles(emptyData({ storage: storage() }))
    const tile = screen.getByRole('link', { name: /^Disk/ })
    expect(tile).toHaveAttribute('href', '/configuration?tab=storage')
    expect(within(tile).getByText('62%')).toBeInTheDocument()
    expect(within(tile).getByText('38 GB kosong')).toBeInTheDocument()
  })

  test('zero from a successful source renders 0, not a dash', () => {
    tiles(emptyData({
      stats: stats({ total: 0, by_type: {}, by_severity: { critical: 0, warning: 0, info: 0 } }),
      attendance: [],
    }))
    const evTile = screen.getByRole('link', { name: /^Event hari ini/ })
    const attTile = screen.getByRole('link', { name: /^Kehadiran hari ini/ })
    expect(within(evTile).getByText('0')).toBeInTheDocument()
    expect(within(evTile).queryByText('—')).toBeNull()
    expect(within(attTile).getByText('0')).toBeInTheDocument()
    expect(within(attTile).queryByText('—')).toBeNull()
  })

  test('failed source renders dash and Gagal memuat, never 0', () => {
    tiles(emptyData({ stats: null, failed: FAILED_STATS }))
    const tile = screen.getByRole('link', { name: /^Event hari ini/ })
    expect(within(tile).getByText('—')).toBeInTheDocument()
    expect(within(tile).getByText('Gagal memuat')).toBeInTheDocument()
    expect(within(tile).queryByText('0')).toBeNull()
  })

  test('one failed source does not blank the other tiles', () => {
    tiles(emptyData({ monitoring: mon(), attendance: null, failed: FAILED_ATTENDANCE }))
    expect(within(screen.getByRole('link', { name: /^Kamera/ })).getByText('1/3')).toBeInTheDocument()
    expect(within(screen.getByRole('link', { name: /^Kehadiran hari ini/ })).getByText('—')).toBeInTheDocument()
  })

  test('loading renders skeletons', () => {
    const { container } = tiles(emptyData({ loading: true }))
    expect(container.querySelectorAll('.cds--skeleton__text').length).toBeGreaterThan(0)
  })
})
