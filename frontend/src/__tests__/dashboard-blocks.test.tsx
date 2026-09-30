import { render, screen, within, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ReactElement } from 'react'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import StatusStrip from '../features/dashboard/StatusStrip'
import KpiTiles from '../features/dashboard/KpiTiles'
import EventsPerHour from '../features/dashboard/EventsPerHour'
import RecentEvents from '../features/dashboard/RecentEvents'
import ActiveIssues from '../features/dashboard/ActiveIssues'
import NodeCompact from '../features/dashboard/NodeCompact'
import type { DashboardData } from '../features/dashboard/useDashboardData'
import { emptyData, mon, monNode, alert, att, stats, storage, ev } from './dashboardFixtures'

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

describe('EventsPerHour', () => {
  test('draws only hours up to now', () => {
    const now = new Date(2026, 8, 30, 10, 30)
    const s = stats({ by_hour: Array.from({ length: 24 }, (_, h) => h), critical_by_hour: Array(24).fill(0) })
    show(<EventsPerHour data={emptyData({ stats: s })} now={now} />)
    const d = screen.getByTestId('lc-line-total').getAttribute('d')!
    expect(d.match(/[ML]/g)).toHaveLength(11) // jam 0..10 saja, tanpa garis ke masa depan
    expect(screen.getByTestId('lc-line-critical')).toBeInTheDocument()
  })

  test('all-zero stats still render both lines without crashing', () => {
    const now = new Date(2026, 8, 30, 5, 0)
    show(<EventsPerHour data={emptyData({ stats: stats({ total: 0, by_type: {}, by_severity: { critical: 0, warning: 0, info: 0 } }) })} now={now} />)
    expect(screen.getByTestId('lc-line-total')).toBeInTheDocument()
    expect(screen.getByTestId('lc-line-critical')).toBeInTheDocument()
  })

  test('null stats renders Gagal memuat and no chart', () => {
    show(<EventsPerHour data={emptyData({ stats: null, failed: FAILED_STATS })} />)
    expect(screen.getByText('Gagal memuat')).toBeInTheDocument()
    expect(screen.queryByTestId('lc-line-total')).toBeNull()
  })
})

describe('RecentEvents', () => {
  const camName = (id: number | null) => (id === 1 ? 'Gate-A' : `#${id ?? '?'}`)
  const recent = (events: Parameters<typeof RecentEvents>[0]['events'], now?: Date) =>
    show(<RecentEvents events={events} cameraName={camName} now={now} />)

  test('shows camera name, severity text and link to the event', () => {
    recent([ev(7)])
    expect(screen.getByText('Gate-A')).toBeInTheDocument()
    expect(screen.getByText('Critical')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Gate-A/ })).toHaveAttribute('href', '/events?event=7')
  })

  test('renders at most 8 rows', () => {
    const { container } = recent(Array.from({ length: 10 }, (_, i) => ev(i + 1)))
    expect(container.querySelectorAll('a[href^="/events?event="]')).toHaveLength(8)
  })

  test('unknown severity falls back to a visible tag', () => {
    recent([ev(3, { severity: 'foo' })])
    expect(screen.getByText('Warning')).toBeInTheDocument()
  })

  test('system event without camera shows node text, not #?', () => {
    const { container } = recent([ev(4, { type: 'system', camera_id: null, payload: { node: 'edge-1' } })])
    expect(container.textContent).toContain('edge-1')
    expect(container.textContent).not.toContain('#?')
  })

  test('older-day event shows a date', () => {
    const now = new Date(2026, 8, 30, 12, 0)
    recent([ev(8, { ts_event: '2026-09-29T08:00:00' })], now)
    expect(screen.getByText(/29\/09/)).toBeInTheDocument()
  })

  test('thumbnail falls back when the image errors', () => {
    const { container } = recent([ev(9)])
    const img = container.querySelector('img.ev-thumb')!
    fireEvent.error(img)
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('.ev-thumb--empty')).not.toBeNull()
  })

  test('empty list shows belum ada event', () => {
    recent([])
    expect(screen.getByText('belum ada event')).toBeInTheDocument()
  })
})

const FAILED_ALERTS = { monitoring: false, alerts: true, stats: false, attendance: false, storage: false }

describe('ActiveIssues', () => {
  test('lists critical first and caps at 5', () => {
    const mixed = [
      alert({ id: 1, label: 'CAM-1', severity: 'warning', started_at: '2026-09-30T01:00:00Z' }),
      alert({ id: 2, label: 'CAM-2', severity: 'critical', started_at: '2026-09-29T01:00:00Z' }),
      alert({ id: 3, label: 'CAM-3', severity: 'warning', started_at: '2026-09-30T02:00:00Z' }),
      alert({ id: 4, label: 'CAM-4', severity: 'critical', started_at: '2026-09-30T03:00:00Z' }),
      alert({ id: 5, label: 'CAM-5', severity: 'warning', started_at: '2026-09-30T04:00:00Z' }),
      alert({ id: 6, label: 'CAM-6', severity: 'warning', started_at: '2026-09-30T05:00:00Z' }),
      alert({ id: 7, label: 'CAM-7', severity: 'warning', started_at: '2026-09-30T06:00:00Z' }),
    ]
    const { container } = show(<ActiveIssues data={emptyData({ alerts: mixed })} />)
    const rows = container.querySelectorAll('.dash-row')
    expect(rows).toHaveLength(5)
    expect(rows[0].textContent).toContain('Critical')
    expect(rows[0].textContent).toContain('CAM-4') // critical terbaru; warning berikutnya urut terbaru
    expect(rows[1].textContent).toContain('CAM-2') // critical lama tetap sebelum semua warning
    expect(rows[2].textContent).toContain('CAM-7')
  })

  test('shows rule title and label', () => {
    show(<ActiveIssues data={emptyData({ alerts: [alert()] })} />)
    expect(screen.getByText('Kamera tanpa frame')).toBeInTheDocument()
    expect(screen.getByText('CAM-01')).toBeInTheDocument()
  })

  test('empty shows Tidak ada masalah aktif', () => {
    show(<ActiveIssues data={emptyData({ alerts: [] })} />)
    expect(screen.getByText('Tidak ada masalah aktif')).toBeInTheDocument()
  })

  test('failed and null shows Gagal memuat', () => {
    show(<ActiveIssues data={emptyData({ alerts: null, failed: FAILED_ALERTS })} />)
    expect(screen.getByText('Gagal memuat')).toBeInTheDocument()
  })

  test('links to monitoring for the full list', () => {
    show(<ActiveIssues data={emptyData({ alerts: [] })} />)
    expect(screen.getByRole('link', { name: /Semua/ })).toHaveAttribute('href', '/monitoring')
  })
})

describe('NodeCompact', () => {
  test('online node shows name, online text and GPU summary', () => {
    show(<NodeCompact data={emptyData({ monitoring: mon() })} />)
    expect(screen.getByText('server')).toBeInTheDocument()
    expect(screen.getByText('online')).toBeInTheDocument()
    expect(screen.getByText('GPU0 55% · VRAM 21%')).toBeInTheDocument()
  })

  test('offline node shows offline text', () => {
    show(<NodeCompact data={emptyData({ monitoring: mon({ nodes: [monNode({ status: 'offline' })] }) })} />)
    expect(screen.getByText('offline')).toBeInTheDocument()
  })

  test('node without GPU shows a dash', () => {
    show(<NodeCompact data={emptyData({ monitoring: mon({ nodes: [monNode({ gpus: [] })] }) })} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  test('links to Monitoring detail', () => {
    show(<NodeCompact data={emptyData({ monitoring: mon() })} />)
    expect(screen.getByRole('link', { name: /Detail di Monitoring/ })).toHaveAttribute('href', '/monitoring')
  })

  test('failed monitoring shows Gagal memuat', () => {
    show(<NodeCompact data={emptyData({ monitoring: null, failed: FAILED_MONITORING })} />)
    expect(screen.getByText('Gagal memuat')).toBeInTheDocument()
  })

  test('no nodes shows belum ada node', () => {
    show(<NodeCompact data={emptyData({ monitoring: mon({ nodes: [] }) })} />)
    expect(screen.getByText('belum ada node')).toBeInTheDocument()
  })
})
