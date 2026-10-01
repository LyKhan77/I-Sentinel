import { Link } from 'react-router-dom'
import { SkeletonText } from '@carbon/react'
import { useT } from '../../app/i18n'
import { formatBytes } from '../config/bytes'
import { summarizeAttendance, summarizeCameras } from './summary'
import type { DashboardData, Source } from './useDashboardData'

/**
 * 4 tile KPI, tiap tile satu `<Link>` (titik masuk Events/Attendance/Monitoring/
 * Storage). Sumber gagal menampilkan "—" + "Gagal memuat" — tidak pernah 0 palsu;
 * 0 dari sumber yang sukses tetap tampil 0.
 */
export default function KpiTiles({ data }: { data: DashboardData }) {
  const { t, locale } = useT()
  const cam = data.monitoring ? summarizeCameras(data.monitoring) : null
  const att = data.attendance ? summarizeAttendance(data.attendance) : null
  const disk = data.storage
  const tiles: { source: Source; to: string; label: string; value: string; sub: string }[] = [
    {
      source: 'monitoring',
      to: '/monitoring',
      label: t('dash.cameras'),
      value: cam ? `${cam.healthy}/${cam.total}` : '—',
      sub: !cam ? ''
        : cam.total === 0 ? t('dash.noCameras')
        : cam.problems > 0 ? t('dash.cam.problems').replace('{n}', String(cam.problems))
        : t('dash.cam.allHealthy'),
    },
    {
      source: 'stats',
      // angka tile = security tanpa absensi sejak tengah malam → tautan memakai filter yang sama (D2/D3)
      to: '/events?type=security&range=today',
      label: t('dash.eventsToday'),
      value: data.stats ? String(data.stats.total) : '—',
      sub: data.stats ? t('dash.ev.critical').replace('{n}', String(data.stats.by_severity.critical ?? 0)) : '',
    },
    {
      source: 'attendance',
      to: '/attendance',
      label: t('dash.att.title'),
      value: att ? String(att.present) : '—',
      sub: att ? t('dash.att.sub').replace('{late}', String(att.late)).replace('{fix}', String(att.needsFix)) : '',
    },
    {
      source: 'storage',
      to: '/configuration?tab=storage',
      label: t('dash.disk.title'),
      value: disk ? `${Math.round(disk.disk.percent)}%` : '—',
      sub: disk ? t('dash.disk.free').replace('{size}', formatBytes(disk.disk.free, locale)) : '',
    },
  ]
  return (
    <div className="dash-kpis">
      {tiles.map((tile) => {
        const missing = data[tile.source] === null
        if (missing && data.loading) {
          return (
            <div className="dash-tile" key={tile.to}>
              <div className="dash-tile__label">{tile.label}</div>
              <SkeletonText heading width="30%" />
              <SkeletonText width="60%" />
            </div>
          )
        }
        return (
          <Link className="dash-tile" key={tile.to} to={tile.to}>
            <div className="dash-tile__label">{tile.label}</div>
            <div className="dash-tile__value">{tile.value}</div>
            <div className="dash-tile__sub">{missing && data.failed[tile.source] ? t('dash.unavailable') : tile.sub}</div>
          </Link>
        )
      })}
    </div>
  )
}
