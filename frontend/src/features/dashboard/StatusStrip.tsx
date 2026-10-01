import { Link } from 'react-router-dom'
import { SkeletonText } from '@carbon/react'
import { useT } from '../../app/i18n'
import { healthKey } from '../monitoring/health'
import type { DashboardData, Source } from './useDashboardData'

/**
 * Satu baris status: titik + TEKS (status tidak pernah hanya warna), catatan
 * kesegaran data, dan tautan Monitoring (§3.3). Urutan evaluasi: unavailable →
 * alert aktif → health ≠ ok → alert tak termuat → normal. "Normal" hanya bila
 * kedua sumber (monitoring + alert) benar-benar termuat.
 */
export default function StatusStrip({ data }: { data: DashboardData }) {
  const { t, locale } = useT()
  const m = data.monitoring
  if (data.loading && (!m || data.alerts === null)) {
    return (
      <div className="dash-strip">
        <SkeletonText heading width="30%" />
      </div>
    )
  }
  let text: string
  let dot: 'ok' | 'warning' | 'critical' | 'neutral'
  if (!m) {
    text = t('dash.status.unavailable')
    dot = 'neutral'
  } else if (data.alerts && data.alerts.length > 0) {
    text = t('dash.status.alerts').replace('{n}', String(data.alerts.length))
    dot = data.alerts.some((a) => a.severity === 'critical') ? 'critical' : 'warning'
  } else if (m.summary.health !== 'ok') {
    text = t('dash.status.health').replace('{state}', t(healthKey(m.summary.health)))
    dot = m.summary.health === 'critical' ? 'critical' : 'warning'
  } else if (data.alerts === null) {
    text = t('dash.status.alertsUnavailable')
    dot = 'neutral'
  } else {
    text = t('dash.status.ok')
    dot = 'ok'
  }
  const hhmm = (d: Date) => d.toLocaleTimeString(locale === 'en' ? 'en' : 'id-ID', { hour: '2-digit', minute: '2-digit' })
  // catatan basi memakai sukses terakhir sumber yang gagal (bukan refresh terbaru sumber lain)
  const failedSources = (Object.keys(data.failed) as Source[]).filter((s) => data.failed[s])
  let note: string | null = null
  if (failedSources.length > 0) {
    const times = failedSources.map((s) => data.lastOk[s]).filter((d): d is Date => d !== null)
    const since = times.length > 0 ? new Date(Math.min(...times.map((d) => d.getTime()))) : data.updatedAt
    if (since) note = t('dash.status.stale').replace('{time}', hhmm(since))
  } else if (data.updatedAt) {
    note = t('dash.status.updated').replace('{time}', hhmm(data.updatedAt))
  }
  return (
    <div className="dash-strip">
      <span className={`dash-dot dash-dot--${dot}`} aria-hidden="true" />
      <span className="dash-strip__text">{text}</span>
      {note && <span className="dash-strip__note">{note}</span>}
      <Link className="dash-strip__link" to="/monitoring">{t('nav.monitoring')} →</Link>
    </div>
  )
}
