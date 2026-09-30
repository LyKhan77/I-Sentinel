import { Link } from 'react-router-dom'
import { SkeletonText, Tag } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { fmt } from '../monitoring/health'
import { sevClass } from '../notifications/labels'
import type { DashboardData } from './useDashboardData'

const MAX_ROWS = 5

/**
 * `alerts.active` (sumber yang sama dengan lonceng & Telegram): critical dulu,
 * lalu `started_at` terbaru, maks 5 baris. Detail lengkap di Monitoring.
 */
export default function ActiveIssues({ data }: { data: DashboardData }) {
  const { t } = useT()
  const list = data.alerts
  const rows = !list ? [] : [...list]
    .sort((a, b) => {
      const ac = a.severity === 'critical' ? 0 : 1
      const bc = b.severity === 'critical' ? 0 : 1
      return ac !== bc ? ac - bc : Date.parse(b.started_at) - Date.parse(a.started_at)
    })
    .slice(0, MAX_ROWS)
  return (
    <div className="dash-section">
      <div className="dash-section__head">
        <h3 className="dash-section__title">{t('dash.issues.title')}</h3>
        <Link className="dash-section__link" to="/monitoring">{t('dash.issues.all')}</Link>
      </div>
      {list === null ? (
        <div className="dash-card">
          {data.failed.alerts ? t('dash.unavailable') : <SkeletonText paragraph lineCount={2} width="60%" />}
        </div>
      ) : rows.length === 0 ? (
        <div className="dash-card"><p className="dash-muted">{t('dash.issues.none')}</p></div>
      ) : (
        rows.map((a) => {
          const sev = sevClass(a.severity)
          return (
            <div className="dash-row" key={a.id}>
              <Tag size="sm" type={sev === 'critical' ? 'red' : 'warm-gray'}>{t(`dash.sev.${sev}` as TKey)}</Tag>
              <span className="dash-row__title">{t(`health.rule.${a.rule}` as TKey)}</span>
              <span className="dash-row__label">{a.label}</span>
              <span className="dash-row__value">{fmt(a.value)}/{fmt(a.threshold)} {a.unit}</span>
            </div>
          )
        })
      )}
    </div>
  )
}
