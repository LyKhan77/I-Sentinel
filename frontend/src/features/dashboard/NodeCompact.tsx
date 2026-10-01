import { Link } from 'react-router-dom'
import { SkeletonText, Tag } from '@carbon/react'
import { useT } from '../../app/i18n'
import { healthKey } from '../monitoring/health'
import type { MonGpu } from '../../api/monitoring'
import type { DashboardData } from './useDashboardData'

const pct = (v: number | null) => (v == null ? '—' : `${v}%`)

function gpuSummary(gpu: MonGpu | undefined): string {
  if (!gpu) return '—'
  const vram = gpu.vram_used_mb != null && gpu.vram_total_mb
    ? Math.round((gpu.vram_used_mb / gpu.vram_total_mb) * 100)
    : null
  return `GPU${gpu.idx ?? 0} ${pct(gpu.util_pct)} · VRAM ${pct(vram)}`
}

/**
 * Kartu GPU lama dipangkas jadi satu baris ringkas per node (K5): titik + teks
 * status, nama, Tag health, util/VRAM GPU pertama. Detail di Monitoring.
 */
export default function NodeCompact({ data }: { data: DashboardData }) {
  const { t } = useT()
  const m = data.monitoring
  return (
    <div className="dash-section">
      <div className="dash-section__head">
        <h3 className="dash-section__title">{t('dash.nodes.title')}</h3>
        <Link className="dash-section__link" to="/monitoring">{t('dash.nodes.detail')}</Link>
      </div>
      {!m ? (
        <div className="dash-card">
          {data.failed.monitoring ? t('dash.unavailable') : <SkeletonText paragraph lineCount={2} width="50%" />}
        </div>
      ) : m.nodes.length === 0 ? (
        <div className="dash-card"><p className="dash-muted">{t('dash.noNodes')}</p></div>
      ) : (
        m.nodes.map((n) => {
          const online = n.status === 'online'
          return (
            <div className="dash-row" key={n.id}>
              <span className={`dash-dot dash-dot--${online ? 'ok' : 'critical'}`} aria-hidden="true" />
              <span>{online ? t('dash.online') : t('dash.offline')}</span>
              <span className="dash-row__title">{n.name}</span>
              <Tag size="sm" type={n.health === 'critical' ? 'red' : 'warm-gray'}>{t(healthKey(n.health))}</Tag>
              <span className="dash-row__value">{gpuSummary(n.gpus[0])}</span>
            </div>
          )
        })
      )}
    </div>
  )
}
