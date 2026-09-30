import { Link } from 'react-router-dom'
import { SkeletonText } from '@carbon/react'
import { useT } from '../../app/i18n'
import { healthKey } from '../monitoring/health'
import type { DashboardData } from './useDashboardData'

/**
 * Satu baris status: titik + TEKS (status tidak pernah hanya warna), catatan
 * kesegaran data, dan tautan Monitoring (§3.3). Urutan evaluasi: unavailable →
 * alert aktif → health ≠ ok → normal.
 */
export default function StatusStrip({ data }: { data: DashboardData }) {
  const { t, locale } = useT()
  const m = data.monitoring
  if (data.loading && !m) {
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
    text = t(healthKey(m.summary.health))
    dot = m.summary.health === 'critical' ? 'critical' : 'warning'
  } else {
    text = t('dash.status.ok')
    dot = 'ok'
  }
  let note: string | null = null
  if (data.updatedAt) {
    const time = data.updatedAt.toLocaleTimeString(locale === 'en' ? 'en' : 'id-ID', { hour: '2-digit', minute: '2-digit' })
    note = Object.values(data.failed).some(Boolean)
      ? t('dash.status.stale').replace('{time}', time)
      : t('dash.status.updated').replace('{time}', time)
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
