import { useCallback, useEffect, useState } from 'react'
import { Camera, Network_4, WarningAlt } from '@carbon/icons-react'
import { SkeletonText, Tile, InlineNotification, Tag } from '@carbon/react'
import { useT } from '../../app/i18n'
import {
  listCameras,
  listNodes,
  type Camera as CameraRow,
  type CameraNode,
  type NodeHw,
  type NodeModules,
} from '../../api/cameras'
import { eventStats, listEvents, type EventOut, type EventStats } from '../../api/events'

// warna dot severity, konsisten dgn mockup: merah critical, kuning warning, abu info/low
const SEV_COLOR: Record<string, string> = { critical: '#fa4d56', warning: '#f1c21b' }

function DetectorBadge({ modules }: { modules: NodeModules | null | undefined }) {
  const { t } = useT()
  const det = modules?.detector
  if (!det) return null
  const pinned = !!det.device && det.device !== 'auto'
  return (
    <Tag size="sm" type={pinned ? 'green' : 'cool-gray'} title={pinned ? det.device : t('dash.notPinned')}>
      {t('dash.detector')}: {pinned ? `${t('dash.pinned')} ${det.device}` : t('dash.auto')}
    </Tag>
  )
}

function NodeCard({ node }: { node: CameraNode }) {
  const { t } = useT()
  const hw: NodeHw | null | undefined = node.hw
  const online = node.status === 'online'
  return (
    <Tile style={{ background: '#262626' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ color: online ? '#42be65' : '#fa4d56' }}>●</span>
        <span style={{ fontSize: 14, fontWeight: 600 }}>{node.name}</span>
        <span style={{ fontSize: 12, color: '#8d8d8d' }}>{node.type}</span>
        <span style={{ marginLeft: 'auto' }}>
          <DetectorBadge modules={node.modules} />
        </span>
      </div>
      {hw?.gpus?.length ? (
        hw.gpus.map((g) => (
          <div
            key={g.idx}
            style={{
              marginTop: 10,
              padding: '8px 10px',
              border: '1px solid #393939',
              background: '#161616',
              fontSize: 12,
              color: '#c6c6c6',
            }}
          >
            <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 600, color: '#f4f4f4' }}>GPU{g.idx}</span>
              <span>{g.name}</span>
              <span style={{ marginLeft: 'auto', color: '#8d8d8d' }}>
                {t('dash.vram')} {g.vram_used_mb}/{g.vram_total_mb} MB · {g.util_pct}%
              </span>
            </div>
            {g.processes.length > 0 && (
              <div style={{ marginTop: 4, color: '#8d8d8d' }}>
                {g.processes.map((p) => `pid ${p.pid} ${p.name}${p.mem_mb ? ` ${p.mem_mb} MB` : ''}`).join(' · ')}
              </div>
            )}
          </div>
        ))
      ) : (
        <p style={{ fontSize: 12, color: '#8d8d8d', marginTop: 8 }}>{t('dash.noGpuInfo')}</p>
      )}
    </Tile>
  )
}

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
    <Tile style={{ background: '#262626' }}>
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
  const [nodes, setNodes] = useState<CameraNode[]>([])
  const [stats, setStats] = useState<EventStats | null>(null)
  const [latest, setLatest] = useState<EventOut[]>([])
  const [loadFailed, setLoadFailed] = useState(false)

  const refresh = useCallback(async () => {
    // ambil kegagalan per-request supaya tiap tile punya fallback sendiri,
    // tapi user tetap diberi tahu saat datanya bukan nol tapi gagal dimuat.
    let bad = false
    const grab = async <T,>(p: Promise<T>, fallback: T): Promise<T> => {
      try {
        return await p
      } catch {
        bad = true
        return fallback
      }
    }
    const [camsL, nodesL, statsL, latestL] = await Promise.all([
      grab(listCameras(), [] as CameraRow[]),
      grab(listNodes(), [] as CameraNode[]),
      grab(eventStats(), null as EventStats | null),
      grab(listEvents({ limit: 3 }), [] as EventOut[]),
    ])
    setLoadFailed(bad)
    const camOnline = camsL.filter((c) => c.status === 'online').length
    setCams({ total: camsL.length, online: camOnline })
    setNodes(nodesL)
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
    <div className="app-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('nav.dashboard')}</h1>
          <p className="app-page__sub">{t('dash.sub')}</p>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 1, background: '#393939', border: '1px solid #393939' }}>
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
          value={`${nodes.filter((n) => n.status === 'online').length}/${nodes.length}`}
          sub={
            nodes.length > 0 ? (
              <>
                <span style={{ color: nodes.every((n) => n.status === 'online') ? '#42be65' : '#f1c21b' }}>●</span>{' '}
                {nodes.filter((n) => n.status === 'online').length}/{nodes.length} {t('dash.online')}
              </>
            ) : (
              t('dash.noNodes')
            )
          }
        />
      </div>

      {nodes.length > 0 && (
        <>
          <h3 style={{ fontSize: 16, fontWeight: 600, margin: '32px 0 12px' }}>{t('dash.nodeHw')}</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 8 }}>
            {nodes.map((n) => (
              <NodeCard key={n.id} node={n} />
            ))}
          </div>
        </>
      )}

      <h3 style={{ fontSize: 16, fontWeight: 600, margin: '32px 0 12px' }}>{t('dash.latestAlerts')}</h3>
      {loadFailed && (
        <InlineNotification
          kind="error"
          lowContrast
          title={t('common.error')}
          subtitle={t('common.loadFailed')}
          onCloseButtonClick={() => setLoadFailed(false)}
        />
      )}
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
