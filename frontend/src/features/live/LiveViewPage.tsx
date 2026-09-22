import { useCallback, useEffect, useRef, useState } from 'react'
import { Maximize, VideoOff } from '@carbon/icons-react'
import { InlineLoading, InlineNotification, Dropdown, Modal, Toggle } from '@carbon/react'
import { useT } from '../../app/i18n'
import { listCameras, type Camera } from '../../api/cameras'
import { getLive, type LiveInfo } from '../../api/events'
import { listZones, type Zone } from '../../api/zones'
import { useLiveEvents } from '../../api/useWs'
import './go2rtc-player' // sisi efek: daftarkan <video-stream> (custom element player go2rtc)
import type { StreamElement } from './go2rtc-player'

const SNAPSHOT_REFRESH_MS = 2000
// Batas tunggu transport streaming (webrtc → mse) sebelum tile jatuh ke snapshot.
const STREAM_TIMEOUT_MS = 10000
const COLS_KEY = 'isentinel_live_cols'
const COL_OPTIONS = [3, 2, 4] as const // urutan mockup 02: default dulu

type Cols = (typeof COL_OPTIONS)[number]

function initialCols(): Cols {
  const v = Number(localStorage.getItem(COLS_KEY))
  return (COL_OPTIONS as readonly number[]).includes(v) ? (v as Cols) : 3
}

// Tile streaming: <video-stream> (player resmi go2rtc) mode webrtc,mse.
// Kalau playing tidak terjadi dalam STREAM_TIMEOUT_MS → fallback ke snapshot
// proxy 2 detik (jalur lama Fase 4e yang tetap berlaku).
function CameraTile({ cam, live, big, onClick }: { cam: Camera; live: LiveInfo | null; big?: boolean; onClick?: () => void }) {
  const { t } = useT()
  const [streamFailed, setStreamFailed] = useState(false)
  const [tick, setTick] = useState(0)
  const [imgFailed, setImgFailed] = useState(false)
  const elRef = useRef<StreamElement | null>(null)

  const ws = live?.webrtc
  const online = cam.status === 'online'
  // Tanpa WebSocket (mis. environment test) → snapshot langsung.
  const canStream = !!ws && online && typeof WebSocket !== 'undefined'
  const streaming = canStream && !streamFailed

  useEffect(() => {
    if (!canStream || !elRef.current) return
    const el = elRef.current
    let playing = false
    el.mode = 'webrtc,mse'
    el.src = ws
    const video = el.querySelector('video')
    const onPlaying = () => {
      playing = true
      clearTimeout(timer)
    }
    const timer = setTimeout(() => {
      if (!playing) setStreamFailed(true)
    }, STREAM_TIMEOUT_MS)
    video?.addEventListener('playing', onPlaying)
    return () => {
      video?.removeEventListener('playing', onPlaying)
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- ws string stabil per kamera; retry lewat refresh /live
  }, [canStream, ws])

  // Interval cache-busting hanya dipakai mode snapshot.
  const sep = live?.snapshot?.includes('?') ? '&' : '?'
  const snapSrc = live?.snapshot && !imgFailed ? `${live.snapshot}${sep}_t=${tick}` : null
  useEffect(() => {
    if (streaming || !live?.snapshot) return
    const timer = setInterval(() => setTick((v) => v + 1), SNAPSHOT_REFRESH_MS)
    return () => clearInterval(timer)
  }, [streaming, live?.snapshot])

  return (
    <div
      data-testid={`cam-tile-${cam.id}`}
      data-big={big ? 'big' : undefined}
      onClick={onClick}
      style={{
        position: 'relative',
        background: '#000',
        aspectRatio: '16/9',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
        overflow: 'hidden',
      }}
    >
      {streaming ? (
        <video-stream
          ref={elRef}
          style={{ width: '100%', height: '100%', objectFit: 'cover', background: '#000' }}
        />
      ) : snapSrc ? (
        <img
          src={snapSrc}
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

      {snapSrc && !streaming && (
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

// Overlay debugger di modal: SVG koordinat normalisasi (viewBox 0 0 100 100)
// sehingga zona/bbox tidak butuh tahu ukuran video. Polygon zona + bbox person
// realtime (WS type:"detections").
const ZONE_COLORS: Record<string, string> = { absensi: '#42be65', restricted: '#fa4d56' }
const BOX_COLOR = '#ff832b'

type DetBox = { id: number; bbox_norm: number[] }

function DebugOverlay({ camId, showZones, showBbox, boxes }: {
  camId: number; showZones: boolean; showBbox: boolean; boxes: DetBox[]
}) {
  const { t } = useT()
  const [zones, setZones] = useState<Zone[]>([])
  useEffect(() => {
    if (!showZones) return
    let alive = true
    listZones().then((all) => { if (alive) setZones(all.filter((z) => z.camera_id === camId && z.active)) }).catch(() => {})
    return () => { alive = false }
  }, [camId, showZones])
  if (!showZones && !showBbox) return null
  return (
    <svg
      data-testid="debug-overlay"
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
    >
      {showZones && zones.map((z) => (
        <g key={z.id}>
          <polygon
            points={z.polygon.map(([x, y]) => `${x * 100},${y * 100}`).join(' ')}
            fill={`${ZONE_COLORS[z.type] ?? '#8d8d8d'}22`}
            stroke={ZONE_COLORS[z.type] ?? '#8d8d8d'}
            strokeWidth={0.5}
          />
          <text x={z.polygon[0][0] * 100} y={z.polygon[0][1] * 100 - 1} fontSize={3.5}
            fill={ZONE_COLORS[z.type] ?? '#8d8d8d'}>
            {z.name} ({z.type})
          </text>
        </g>
      ))}
      {showBbox && boxes.map((b) => b.bbox_norm?.length === 4 && (
        <g key={b.id}>
          <rect
            x={b.bbox_norm[0] * 100} y={b.bbox_norm[1] * 100}
            width={(b.bbox_norm[2] - b.bbox_norm[0]) * 100}
            height={(b.bbox_norm[3] - b.bbox_norm[1]) * 100}
            fill="none" stroke={BOX_COLOR} strokeWidth={0.6}
          />
          <text x={b.bbox_norm[0] * 100} y={Math.max(4, b.bbox_norm[1] * 100 - 1)}
            fontSize={4} fill={BOX_COLOR}>
            {t('live.trackId').replace('{n}', String(b.id))}
          </text>
        </g>
      ))}
    </svg>
  )}

export default function LiveViewPage() {
  const { t } = useT()
  const [cams, setCams] = useState<Camera[]>([])
  const [lives, setLives] = useState<Record<number, LiveInfo>>({})
  const [debugCam, setDebugCam] = useState<Camera | null>(null)
  const [showZones, setShowZones] = useState(true)
  const [showBbox, setShowBbox] = useState(true)
  const [boxes, setBoxes] = useState<DetBox[]>([])
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [cols, setCols] = useState<Cols>(initialCols)
  const [loc, setLoc] = useState<{ id: string; label: string } | null>(null)

  // deteksi realtime (debugger modal): WS type:"detections"
  useLiveEvents((e) => {
    const m = e as { type?: string; camera_id?: number; boxes?: DetBox[] }
    if (m?.type === 'detections') {
      setBoxes((prev) => (m.camera_id === debugCam?.id ? (m.boxes ?? []) : prev))
    }
  })

  const refresh = useCallback(async () => {
    try {
      const list = await listCameras()
      setCams(list)
      setLoadFailed(false)
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
    } catch {
      setLoadFailed(true) // jangan bilang "belum ada kamera" kalau requestnya yang gagal
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 30000) // refresh info /live (snapshot img sendiri auto 2s)
    return () => clearInterval(timer)
  }, [refresh])

  // Kamera nonaktif tidak punya stream di go2rtc (sync_camera(delete=True) saat
  // disable) → tile-nya selalu 502 dengan badge LIVE yang menyesatkan.
  const active = cams.filter((c) => c.enabled)
  // lokasi kamera unik; item "semua" di depan supaya filter bisa direset
  const allItem = { id: '__all__', label: t('live.allLocations') }
  const locOptions = [
    allItem,
    ...[...new Set(active.map((c) => c.location).filter((l): l is string => !!l))].map((l) => ({ id: l, label: l })),
  ]
  const shown = loc && loc.id !== '__all__' ? active.filter((c) => c.location === loc.label) : active

  const pickCols = (n: Cols) => {
    localStorage.setItem(COLS_KEY, String(n))
    setCols(n)
  }

  if (loading) return <div className="app-page"><InlineLoading description={t('common.loading')} /></div>

  return (
    <div className="app-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('nav.live')}</h1>
          <p className="app-page__sub">{t('live.sub')}</p>
        </div>
        <div className="lv-chips">
          {COL_OPTIONS.map((n) => (
            <button
              key={n}
              type="button"
              data-testid={`live-cols-${n}`}
              aria-pressed={cols === n}
              className={cols === n ? 'lv-chip lv-chip--sel' : 'lv-chip'}
              onClick={() => pickCols(n)}
            >
              {t('live.cols').replace('{n}', String(n))}
            </button>
          ))}
          <div style={{ width: 200 }}>
            <Dropdown
              id="live-location"
              titleText={t('live.location')}
              hideLabel
              size="sm"
              label={t('live.allLocations')}
              items={locOptions}
              selectedItem={loc}
              onChange={({ selectedItem }) => setLoc(selectedItem ?? null)}
            />
          </div>
        </div>
      </div>
      {loadFailed && (
        <InlineNotification
          kind="error"
          lowContrast
          title={t('common.error')}
          subtitle={t('common.loadFailed')}
          onCloseButtonClick={() => setLoadFailed(false)}
        />
      )}
      {shown.length === 0 ? (
        <p style={{ color: '#8d8d8d' }}>{cams.length === 0 ? t('live.noCameras') : t('live.noActiveCameras')}</p>
      ) : (
        <div className="lv-grid" style={{ '--lv-cols': cols } as React.CSSProperties}>
          {shown.map((cam) => (
            <div key={cam.id} onClick={() => { setBoxes([]); setDebugCam(cam) }} title={t('live.openDebug')}>
              <CameraTile cam={cam} live={lives[cam.id] ?? null} />
            </div>
          ))}
        </div>
      )}
      {debugCam && (
        <Modal
          open
          modalHeading={`${t('live.debugTitle')} — ${debugCam.name}`}
          passiveModal
          onRequestClose={() => setDebugCam(null)}
          data-testid="live-modal"
        >
          <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 8 }}>
            <Toggle id="lv-zones" size="sm" labelText={t('live.showZones')}
              toggled={showZones} onToggle={(v) => setShowZones(v)} />
            <Toggle id="lv-bbox" size="sm" labelText={t('live.showBbox')}
              toggled={showBbox} onToggle={(v) => setShowBbox(v)} />
          </div>
          <div style={{ position: 'relative', background: '#000', aspectRatio: '16/9' }}>
            <CameraTile cam={debugCam} live={lives[debugCam.id] ?? null} big />
            <DebugOverlay camId={debugCam.id} showZones={showZones} showBbox={showBbox} boxes={boxes} />
          </div>
        </Modal>
      )}
    </div>
  )
}
