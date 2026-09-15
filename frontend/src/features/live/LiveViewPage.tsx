import { useCallback, useEffect, useRef, useState } from 'react'
import { Maximize, VideoOff } from '@carbon/icons-react'
import { InlineLoading } from '@carbon/react'
import { useT } from '../../app/i18n'
import { listCameras, type Camera } from '../../api/cameras'
import { getLive, type LiveInfo } from '../../api/events'

const SNAPSHOT_REFRESH_MS = 2000

// Snapshot auto-refresh (cache-busting) = deliverable Fase 1.
// TODO(Task 9): WebRTC go2rtc — getLive() sudah expose streams/webrtc/mse/hls,
// tinggal render <video> + WsWebRTC client dari {go2rtc_url}/api/ws.js.
function CameraSnapshot({ cam, live, big }: { cam: Camera; live: LiveInfo | null; big?: boolean }) {
  const { t } = useT()
  const [tick, setTick] = useState(0)
  const [imgFailed, setImgFailed] = useState(false)

  useEffect(() => {
    if (!live?.snapshot) return
    const timer = setInterval(() => setTick((v) => v + 1), SNAPSHOT_REFRESH_MS)
    return () => clearInterval(timer)
  }, [live?.snapshot])

  const online = cam.status === 'online'
  const sep = live?.snapshot?.includes('?') ? '&' : '?'
  const src = live?.snapshot && !imgFailed ? `${live.snapshot}${sep}_t=${tick}` : null

  return (
    <div
      data-testid={`cam-tile-${cam.id}`}
      data-big={big ? 'big' : undefined}
      style={{
        position: 'relative',
        background: '#000',
        border: '1px solid #393939',
        aspectRatio: '16/9',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        overflow: 'hidden',
      }}
    >
      {src ? (
        <img
          src={src}
          alt={cam.name}
          onError={() => setImgFailed(true)}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
      ) : (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 6,
            color: '#6f6f6f',
            fontSize: 12,
            letterSpacing: '.32px',
          }}
        >
          <VideoOff size={24} />
          {t('live.offline')}
        </div>
      )}

      {src && (
        <span
          style={{
            position: 'absolute',
            top: 6,
            left: 10,
            fontSize: 10,
            color: '#8d8d8d',
            fontFamily: 'var(--cds-font-family-mono, monospace)',
          }}
        >
          {new Date().toLocaleString('sv-SE')}
        </span>
      )}

      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          bottom: 0,
          padding: '6px 10px',
          background: 'linear-gradient(transparent, rgba(0,0,0,.75))',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontSize: 12,
          color: '#e8e8e8',
        }}
      >
        <span>{cam.name}</span>
        <span
          style={{
            marginLeft: 'auto',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            fontSize: 10,
            letterSpacing: '.64px',
            fontWeight: 600,
            color: online ? '#fa4d56' : '#6f6f6f',
          }}
        >
          <span
            aria-hidden="true"
            style={{ width: 6, height: 6, borderRadius: '50%', background: online ? '#fa4d56' : '#6f6f6f' }}
          />
          {online ? t('live.live') : t('live.offline')}
        </span>
        {big && <Maximize size={14} />}
      </div>
    </div>
  )
}

export default function LiveViewPage() {
  const { t } = useT()
  const [cams, setCams] = useState<Camera[]>([])
  const [lives, setLives] = useState<Record<number, LiveInfo>>({})
  const [focusId, setFocusId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const focusRef = useRef<HTMLDivElement>(null)

  const refresh = useCallback(async () => {
    try {
      const list = await listCameras()
      setCams(list)
      const infos: Record<number, LiveInfo> = {}
      await Promise.all(
        list.map(async (c) => {
          try {
            infos[c.id] = await getLive(c.id)
          } catch {
            // kamera offline / go2rtc belum siap → tile tanpa snapshot
          }
        }),
      )
      setLives(infos)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 30000) // refresh info /live (snapshot img sendiri auto 2s)
    return () => clearInterval(timer)
  }, [refresh])

  // dblclick tile fokus → fullscreen elemen tile
  useEffect(() => {
    const el = focusRef.current
    if (!el) return
    const onDbl = () => {
      if (document.fullscreenElement) document.exitFullscreen()
      else el.requestFullscreen?.()
    }
    el.addEventListener('dblclick', onDbl)
    return () => el.removeEventListener('dblclick', onDbl)
  }, [focusId])

  const focused = focusId != null ? cams.find((c) => c.id === focusId) : null
  const others = focusId != null ? cams.filter((c) => c.id !== focusId) : cams

  if (loading) return <div className="app-page"><InlineLoading description={t('common.loading')} /></div>

  return (
    <div className="app-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('nav.live')}</h1>
          <p className="app-page__sub">{t('live.sub')}</p>
        </div>
      </div>
      {cams.length === 0 ? (
        <p style={{ color: '#8d8d8d' }}>{t('live.noCameras')}</p>
      ) : (
        <>
          {focused && (
            <div
              ref={focusRef}
              onClick={() => setFocusId(null)}
              style={{ marginBottom: 12, border: '1px solid #393939' }}
              title={t('live.clickUnfocus')}
            >
              <CameraSnapshot cam={focused} live={lives[focused.id] ?? null} big />
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12 }}>
            {others.map((cam) => (
              <div key={cam.id} onClick={() => setFocusId(cam.id)} title={t('live.clickFocus')}>
                <CameraSnapshot cam={cam} live={lives[cam.id] ?? null} />
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
