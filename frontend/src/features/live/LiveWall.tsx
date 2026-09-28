import { useEffect, useRef, useState } from 'react'
import { Maximize, VideoOff } from '@carbon/icons-react'
import { Modal, Toggle } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import type { Camera } from '../../api/cameras'
import type { LiveInfo } from '../../api/events'
import { listZones, type Zone } from '../../api/zones'
import { useLiveEvents } from '../../api/useWs'
import { playerMode } from './playerMode'
import { useInView } from './useInView'
import './go2rtc-player' // sisi efek: daftarkan <video-stream> (custom element player go2rtc)
import type { StreamElement } from './go2rtc-player'

const SNAPSHOT_REFRESH_MS = 2000
// Batas tunggu transport streaming (webrtc → mse) sebelum tile jatuh ke snapshot.
const STREAM_TIMEOUT_MS = 10000
const STREAM_RETRY_MS = 60000 // tile gagal stream mencoba lagi (TV 24/7 pulih sendiri)

// Tile streaming: <video-stream> (player resmi go2rtc) mode webrtc,mse.
// Kalau playing tidak terjadi dalam STREAM_TIMEOUT_MS → fallback ke snapshot
// proxy 2 detik; dicoba ulang tiap STREAM_RETRY_MS (TV 24/7 pulih sendiri).
// Hanya tile dekat viewport yang men-decode video (Pi 5 tanpa decoder H.264 hardware).
export function CameraTile({ cam, live, big, tv: _tv, onClick }: { cam: Camera; live: LiveInfo | null; big?: boolean; tv?: boolean; onClick?: () => void }) {
  const { t } = useT()
  const rootRef = useRef<HTMLDivElement | null>(null)
  const inView = useInView(rootRef, !!big) // tile modal selalu terlihat
  const [streamFailed, setStreamFailed] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [tick, setTick] = useState(0)
  const [imgFailed, setImgFailed] = useState(false)
  const [mode, setMode] = useState<'WebRTC' | 'MSE' | null>(null)
  const elRef = useRef<StreamElement | null>(null)

  const ws = live?.webrtc
  const online = cam.status === 'online'
  // Tanpa WebSocket (mis. environment test) → snapshot langsung.
  const canStream = !!ws && online && typeof WebSocket !== 'undefined'
  const streaming = canStream && !streamFailed && inView

  // deps [streaming, ws]: <video-stream> di-mount ulang saat masuk layar / coba ulang → src harus diset lagi
  useEffect(() => {
    if (!streaming || !elRef.current) return
    const el = elRef.current
    let ok = false
    el.mode = 'webrtc,mse'
    el.src = ws
    const video = el.querySelector('video')
    const onPlaying = () => {
      ok = true
      setPlaying(true)
      clearTimeout(timer)
    }
    const timer = setTimeout(() => {
      if (!ok) setStreamFailed(true)
    }, STREAM_TIMEOUT_MS)
    video?.addEventListener('playing', onPlaying)
    return () => {
      video?.removeEventListener('playing', onPlaying)
      clearTimeout(timer)
      setPlaying(false)
    }
  }, [streaming, ws])

  useEffect(() => {
    if (!streamFailed) return
    const timer = setTimeout(() => setStreamFailed(false), STREAM_RETRY_MS)
    return () => clearTimeout(timer)
  }, [streamFailed])

  // Badge transport aktif (hanya tile besar): baca video srcObject/src tiap detik.
  useEffect(() => {
    if (!big || !streaming) return
    const timer = setInterval(() => setMode(playerMode(elRef.current?.querySelector('video') ?? null)), 1000)
    return () => clearInterval(timer)
  }, [big, streaming])

  // Interval cache-busting hanya dipakai mode snapshot.
  const sep = live?.snapshot?.includes('?') ? '&' : '?'
  const snapSrc = live?.snapshot && !imgFailed ? `${live.snapshot}${sep}_t=${tick}` : null
  // snapshot berkala hanya untuk tile terlihat yang tidak streaming; tile di luar layar = gambar terakhir
  useEffect(() => {
    if (streaming || !inView || !live?.snapshot) return
    const timer = setInterval(() => setTick((v) => v + 1), SNAPSHOT_REFRESH_MS)
    return () => clearInterval(timer)
  }, [streaming, inView, live?.snapshot])
  const showSnap = !!snapSrc && (!streaming || !playing)

  return (
    <div
      ref={rootRef}
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
      {streaming && (
        // fill (bukan cover): frame penuh — overlay zona debugger memakai geometri frame yang sama dengan vision
        <video-stream
          ref={elRef}
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'fill',
            background: '#000', opacity: playing ? 1 : 0 }}
        />
      )}
      {showSnap ? (
        <img
          src={snapSrc!}
          alt={cam.name}
          onError={() => setImgFailed(true)}
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'fill' }}
        />
      ) : !streaming && (
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

      {showSnap && !streaming && (
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

      {big && mode && (
        <span data-testid="player-mode" style={{ position: 'absolute', bottom: 6, left: 10, fontSize: 10,
          color: '#c6c6c6', fontFamily: 'var(--cds-font-family-mono, monospace)' }}>{mode}</span>
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
// sehingga zona/bbox tidak butuh tahu ukuran video. Polygon zona + deteksi realtime.
const ZONE_COLORS: Record<string, string> = { attendance: '#42be65', behavior: '#fa4d56' }
const BOX_COLORS = { person: '#ff832b', face: '#78a9ff' } as const

type DetectionKind = keyof typeof BOX_COLORS
type DetBox = { id: number; bbox_norm: number[]; label?: string | null; kind: DetectionKind; at: number }
const BOX_TTL_MS = 1000
// Nama dari event attendance yang sudah dicocokkan backend. Hanya event segar yang dipakai
// dan disimpan sebentar: id track wajah mulai dari 1 lagi setelah node restart.
const NAME_TTL_MS = 30000
type FaceName = { name: string; at: number }
const FACE_GATE_CODES = ['zone', 'small', 'score', 'yaw', 'blur'] as const

function DebugOverlay({ camId, showZones, showDetection, boxes, names }: {
  camId: number; showZones: boolean; showDetection: boolean; boxes: DetBox[]; names: Record<string, FaceName>
}) {
  const { t } = useT()
  const boxLabel = (b: DetBox) =>
    b.kind === 'face' && names[`${camId}:${b.id}`]
      ? names[`${camId}:${b.id}`].name
      : b.kind === 'face' && b.label && (FACE_GATE_CODES as readonly string[]).includes(b.label)
      ? t(`live.faceGate.${b.label}` as TKey)
      : b.label ?? t('live.trackId').replace('{n}', String(b.id))
  const [zones, setZones] = useState<Zone[]>([])
  useEffect(() => {
    if (!showZones) return
    let alive = true
    listZones().then((all) => { if (alive) setZones(all.filter((z) => z.camera_id === camId && z.active)) }).catch(() => {})
    return () => { alive = false }
  }, [camId, showZones])
  if (!showZones && !showDetection) return null
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
      {showDetection && boxes.map((b) => b.bbox_norm?.length === 4 && (
        <g key={`${b.kind}-${b.id}`}>
          <rect
            data-testid={`debug-box-${b.kind}-${b.id}`}
            x={b.bbox_norm[0] * 100} y={b.bbox_norm[1] * 100}
            width={(b.bbox_norm[2] - b.bbox_norm[0]) * 100}
            height={(b.bbox_norm[3] - b.bbox_norm[1]) * 100}
            style={{ transition: 'x 150ms linear, y 150ms linear, width 150ms linear, height 150ms linear' }}
            fill="none" stroke={BOX_COLORS[b.kind]} strokeWidth={0.6}
          />
          <text x={b.bbox_norm[0] * 100} y={Math.max(4, b.bbox_norm[1] * 100 - 1)}
            fontSize={4} fill={BOX_COLORS[b.kind]}>
            {boxLabel(b)}
          </text>
        </g>
      ))}
    </svg>
  )
}

/** Grid tile + modal debugger; dipakai Live View biasa dan mode TV. */
export default function LiveWall({ cams, lives, cols, tv, onDebugChange }: {
  cams: Camera[]
  lives: Record<number, LiveInfo>
  cols: number
  tv?: boolean
  onDebugChange?: (open: boolean) => void
}) {
  const { t } = useT()
  const [debugCam, setDebugCamState] = useState<Camera | null>(null)
  const [showZones, setShowZones] = useState(true)
  const [showDetection, setShowDetection] = useState(true)
  const [boxes, setBoxes] = useState<DetBox[]>([])
  const [faceNames, setFaceNames] = useState<Record<string, FaceName>>({})

  // deteksi realtime (debugger modal): WS type:"detections"
  useLiveEvents((e) => {
    const m = e as { type?: string; camera_id?: number; kind?: DetectionKind; boxes?: Omit<DetBox, 'kind'>[] }
    if (m?.type === 'detections') {
      // person & face tiba sebagai pesan terpisah: ganti hanya kotak kind yang sama
      const kind = m.kind ?? 'person'
      const at = Date.now()
      setBoxes((prev) => (m.camera_id === debugCam?.id
        ? [...prev.filter((b) => b.kind !== kind), ...(m.boxes ?? []).map((box) => ({ ...box, kind, at }))]
        : prev))
    }
    const ev = e as { type?: string; camera_id?: number; ts_event?: string; payload?: Record<string, unknown> | null }
    const p = ev?.payload
    if (ev?.type === 'attendance' && ev.camera_id != null && p && typeof p.track_id === 'number'
      && ev.ts_event && Date.now() - Date.parse(ev.ts_event) < NAME_TTL_MS) {
      const name = typeof p.employee_name === 'string' ? p.employee_name
        : p.match_reason === 'no_match' || p.match_reason === 'low_quality' ? t('events.face.unknown') : null
      if (name) setFaceNames((prev) => ({ ...prev, [`${ev.camera_id}:${p.track_id}`]: { name, at: Date.now() } }))
    }
  })

  // Kotak basi (tanpa update WS >1 s) dihapus sendiri supaya overlay tidak menampilkan
  // orang/wajah yang sudah keluar frame.
  useEffect(() => {
    const timer = setInterval(() => {
      setBoxes((prev) => {
        const now = Date.now()
        const fresh = prev.filter((b) => now - b.at < BOX_TTL_MS)
        return fresh.length === prev.length ? prev : fresh
      })
      setFaceNames((prev) => {
        const now = Date.now()
        const keys = Object.keys(prev).filter((k) => now - prev[k].at < NAME_TTL_MS)
        return keys.length === Object.keys(prev).length ? prev : Object.fromEntries(keys.map((k) => [k, prev[k]]))
      })
    }, 250)
    return () => clearInterval(timer)
  }, [])

  const setDebugCam = (cam: Camera | null) => {
    setDebugCamState(cam)
    onDebugChange?.(cam !== null)
  }

  return (
    <>
      <div className={tv ? 'lv-grid lv-grid--tv' : 'lv-grid'} style={{ '--lv-cols': cols } as React.CSSProperties}>
        {cams.map((cam) => (
          <div key={cam.id} onClick={() => { setBoxes([]); setDebugCam(cam) }} title={t('live.openDebug')}>
            <CameraTile cam={cam} live={lives[cam.id] ?? null} tv={tv} />
          </div>
        ))}
      </div>
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
            <Toggle id="lv-detection" size="sm" labelText={t('live.showDetection')}
              toggled={showDetection} onToggle={(v) => setShowDetection(v)} />
          </div>
          <div style={{ position: 'relative', background: '#000', aspectRatio: '16/9' }}>
            <CameraTile cam={debugCam} live={lives[debugCam.id] ?? null} big />
            <DebugOverlay camId={debugCam.id} showZones={showZones} showDetection={showDetection} boxes={boxes} names={faceNames} />
          </div>
        </Modal>
      )}
    </>
  )
}
