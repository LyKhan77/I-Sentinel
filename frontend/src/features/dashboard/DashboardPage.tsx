import { useCallback, useEffect, useState } from 'react'
import { Camera, Network_4, WarningAlt } from '@carbon/icons-react'
import { SkeletonText, Tile } from '@carbon/react'
import { useT } from '../../app/i18n'
import { listCameras, listNodes } from '../../api/cameras'
import { eventStats, listEvents, type EventOut, type EventStats } from '../../api/events'

// warna dot severity, konsisten dgn mockup: merah critical, kuning warning, abu info/low
const SEV_COLOR: Record<string, string> = { critical: '#fa4d56', warning: '#f1c21b' }

function TileStat({
  icon,
  label,
  value,
  sub,
  loading,
}: {
  icon: React.ReactNode
  label: string
  value: React.ReactNode
  sub: React.ReactNode
  loading: boolean
}) {
  return (
    <Tile style={{ background: '#262626', border: '1px solid #393939' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#8d8d8d', fontSize: 12, letterSpacing: 0.32 }}>
        {icon}
        <span style={{ textTransform: 'uppercase' }}>{label}</span>
      </div>
      {loading ? (
        <SkeletonText heading width="30%" />
      ) : (
        <div style={{ fontSize: 30, fontWeight: 300, marginTop: 6 }}>{value}</div>
      )}
      {loading ? (
        <SkeletonText width="70%" />
      ) : (
        <div style={{ fontSize: 12, color: '#c6c6c6', marginTop: 6 }}>{sub}</div>
      )}
    </Tile>
  )
}

export default function DashboardPage() {
  const { t } = useT()
  const [loading, setLoading] = useState(true)
  const [cams, setCams] = useState<{ total: number; online: number }>({ total: 0, online: 0 })
  const [nodes, setNodes] = useState<{ total: number; online: number }>({ total: 0, online: 0 })
  const [stats, setStats] = useState<EventStats | null>(null)
  const [latest, setLatest] = useState<EventOut[]>([])

  const refresh = useCallback(async () => {
    const [camsL, nodesL, statsL, latestL] = await Promise.all([
      listCameras().catch(() => []),
      listNodes().catch(() => []),
      eventStats().catch(() => null),
      listEvents({ limit: 3 }).catch(() => []),
    ])
    const camOnline = camsL.filter((c) => c.status === 'online').length
    setCams({ total: camsL.length, online: camOnline })
    setNodes({ total: nodesL.length, online: nodesL.filter((n) => n.status === 'online').length })
    setStats(statsL)
    setLatest(latestL)
    setLoading(false)
  }, [])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 15000)
    return () => clearInterval(timer)
  }, [refresh])

  const breakText = stats
    ? Object.entries(stats.by_type)
        .map(([k, v]) => `${k} ${v}`)
        .join(' · ') || t('dash.noEvents')
    : null

  return (
    <div style={{ padding: 32, maxWidth: 1200 }}>
      <h1 style={{ fontWeight: 300, margin: 0, marginBottom: 16 }}>{t('nav.dashboard')}</h1>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 1 }}>
        <TileStat
          loading={loading}
          icon={<Camera size={16} />}
          label={t('dash.cameras')}
          value={`${cams.online}/${cams.total}`}
          sub={
            cams.total > 0 ? (
              <>
                <span style={{ color: '#42be65' }}>●</span> {cams.online} {t('dash.online')}{' '}
                <span style={{ color: '#fa4d56', marginLeft: 10 }}>●</span> {cams.total - cams.online} {t('dash.offline')}
              </>
            ) : (
              t('dash.noCameras')
            )
          }
        />
        <TileStat
          loading={loading}
          icon={<WarningAlt size={16} />}
          label={t('dash.eventsToday')}
          value={stats ? stats.total : '—'}
          sub={breakText ?? t('dash.noEvents')}
        />
        <TileStat
          loading={loading}
          icon={<Network_4 size={16} />}
          label={t('dash.nodes')}
          value={`${nodes.online}/${nodes.total}`}
          sub={
            nodes.total > 0 ? (
              <>
                <span style={{ color: nodes.online === nodes.total ? '#42be65' : '#f1c21b' }}>●</span>{' '}
                {nodes.online}/{nodes.total} {t('dash.online')}
              </>
            ) : (
              t('dash.noNodes')
            )
          }
        />
      </div>

      <h3 style={{ fontWeight: 400, margin: '24px 0 8px' }}>{t('dash.latestAlerts')}</h3>
      {loading ? (
        <SkeletonText width="100%" />
      ) : latest.length === 0 ? (
        <p style={{ color: '#8d8d8d' }}>{t('dash.noEvents')}</p>
      ) : (
        latest.map((e) => (
          <div
            key={e.event_id}
            style={{
              background: '#262626',
              border: '1px solid #393939',
              borderLeft: `3px solid ${SEV_COLOR[e.severity] ?? '#8d8d8d'}`,
              padding: '10px 16px',
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              fontSize: 13,
              color: '#c6c6c6',
              marginTop: 8,
            }}
          >
            <span style={{ color: SEV_COLOR[e.severity] ?? '#8d8d8d' }}>●</span>
            <span>{e.type}</span>
            <span style={{ color: '#8d8d8d' }}>cam {e.camera_id}</span>
            <span style={{ color: '#8d8d8d', marginLeft: 'auto', fontSize: 12 }}>
              {new Date(e.ts_event).toLocaleTimeString()}
            </span>
          </div>
        ))
      )}
    </div>
  )
}
