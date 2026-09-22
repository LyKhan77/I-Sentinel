import { useEffect, useRef, useState } from 'react'
import { Button, InlineLoading } from '@carbon/react'
import { Draw, Close } from '@carbon/icons-react'
import { useT, type TKey } from '../app/i18n'
import { getLive } from '../api/events'
import type { Zone, ZoneType } from '../api/zones'

// warna fill per tipe zone (mockup 06)
export const ZONE_COLOR: Record<ZoneType, string> = {
  behavior: '#fa4d56',
  attendance: '#4589ff',
}

type Props = {
  cameraId: number
  initialZones: Zone[]
  onChange: (zones: Zone[]) => void
  selectedId: number | null
  onSelect: (id: number | null) => void
}

// ponytail: pointer math pakai getBoundingClientRect manual — jsdom tanpa layout, test set rect via defineProperty
function localPoint(e: { clientX: number; clientY: number }, el: SVGSVGElement): [number, number] {
  const r = el.getBoundingClientRect()
  const x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width))
  const y = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))
  return [x, y]
}

export default function ZoneEditor({ cameraId, initialZones, onChange, selectedId, onSelect }: Props) {
  const { t } = useT()
  const [snapshot, setSnapshot] = useState<string | null | undefined>(undefined) // undefined=loading, null=gagal
  const [drawing, setDrawing] = useState(false)
  const [points, setPoints] = useState<[number, number][]>([])
  const [tick, setTick] = useState(0)
  const [imgFailed, setImgFailed] = useState(false) // URL snapshot ada tapi gambarnya gagal dimuat (go2rtc belum siap)
  const svgRef = useRef<SVGSVGElement>(null)
  const dragRef = useRef<{ zoneIdx: number; ptIdx: number } | null>(null)

  // snapshot URL dari /live, cache-bust 5s (pola LiveViewPage)
  useEffect(() => {
    let live = true
    getLive(cameraId)
      .then((info) => {
        if (!live || !info.snapshot) return
        const sep = info.snapshot.includes('?') ? '&' : '?'
        setSnapshot(`${info.snapshot}${sep}_t=`)
      })
      .catch(() => live && setSnapshot(null))
    return () => {
      live = false
    }
  }, [cameraId])

  useEffect(() => {
    const timer = setInterval(() => setTick((v) => v + 1), 5000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    setDrawing(false)
    setPoints([])
    setImgFailed(false)
  }, [cameraId])

  const clickFrame = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!drawing) return
    const pt = localPoint(e, e.currentTarget)
    if (points.length >= 3) {
      const first = points[0]
      if (Math.hypot(pt[0] - first[0], pt[1] - first[1]) < 0.03) {
        finish()
        return
      }
    }
    setPoints([...points, pt])
  }

  const finish = () => {
    if (points.length < 3) return
    const zone: Zone = {
      id: -Date.now(), // ponytail: id sementara negatif sampai POST; backend assign id asli
      camera_id: cameraId,
      name: `${t('zones.defaultName')} ${initialZones.length + 1}`,
      type: 'behavior',
      direction: null,
      polygon: points,
      schedule: null,
      severity: 'warning',
      rate_limit_min: 5,
      trigger_seconds: 0,
      behaviors: [],
      snapshot: true,
      clip: true,
      telegram: false,
      active: true,
    }
    onChange([...initialZones, zone])
    onSelect(zone.id)
    setDrawing(false)
    setPoints([])
  }

  const movePoint = (e: React.PointerEvent, zoneIdx: number, ptIdx: number) => {
    if (!dragRef.current || !svgRef.current) return
    e.currentTarget.setPointerCapture(e.pointerId)
    const pt = localPoint(e, svgRef.current)
    const zones = initialZones.map((z, i) => {
      if (i !== zoneIdx) return z
      const polygon = z.polygon.map((p, j) => (j === ptIdx ? pt : p))
      return { ...z, polygon }
    })
    onChange(zones)
  }

  const removePoint = (e: React.MouseEvent, zoneIdx: number, ptIdx: number) => {
    e.preventDefault() // contextmenu
    const zone = initialZones[zoneIdx]
    if (zone.polygon.length <= 3) return // min 3 titik
    onChange(
      initialZones.map((z, i) =>
        i === zoneIdx ? { ...z, polygon: z.polygon.filter((_, j) => j !== ptIdx) } : z,
      ),
    )
  }

  const toPct = (pts: [number, number][]) => pts.map(([x, y]) => `${x * 100},${y * 100}`).join(' ')
  const ringAt = points[0]
  const canFinish = points.length >= 3

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        {drawing ? (
          <>
            <Button
              kind="danger"
              size="sm"
              renderIcon={Close}
              data-testid="zone-draw-cancel"
              onClick={() => {
                setDrawing(false)
                setPoints([])
              }}
            >
              {t('common.cancel')}
            </Button>
            {canFinish && (
              <Button kind="primary" size="sm" data-testid="zone-draw-finish" onClick={finish}>
                {t('zones.finish')}
              </Button>
            )}
          </>
        ) : (
          <Button
            kind="primary"
            size="sm"
            renderIcon={Draw}
            data-testid="zone-draw-start"
            onClick={() => {
              onSelect(null)
              setDrawing(true)
            }}
          >
            {t('zones.draw')}
          </Button>
        )}
        {drawing && (
          <span style={{ alignSelf: 'center', fontSize: 12, color: 'var(--cds-text-helper)' }}>
            {t('zones.drawingHint')}
          </span>
        )}
      </div>

      <div style={{ position: 'relative', width: '100%', aspectRatio: '16 / 9', background: '#000' }}>
        {snapshot === undefined ? (
          <InlineLoading description={t('common.loading')} />
        ) : snapshot === null || imgFailed ? (
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#8d8d8d' }}>
            {t('live.noSnapshot')}
          </div>
        ) : (
          <img
            src={`${snapshot}${tick}`}
            alt=""
            onError={() => setImgFailed(true)}
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }}
          />
        )}
        <svg
          ref={svgRef}
          data-testid="zone-svg"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', cursor: drawing ? 'crosshair' : 'default' }}
          onClick={clickFrame}
        >
          {initialZones.map((z, zi) => (
            <g key={z.id} onClick={() => !drawing && onSelect(z.id)}>
              <polygon
                points={toPct(z.polygon)}
                fill={ZONE_COLOR[z.type]}
                fillOpacity={z.id === selectedId ? 0.35 : 0.15}
                stroke={ZONE_COLOR[z.type]}
                strokeWidth={z.id === selectedId ? 0.6 : 0.4}
                style={{ cursor: 'pointer' }}
              />
              {z.id === selectedId &&
                z.polygon.map(([x, y], pi) => (
                  <circle
                    key={pi}
                    data-testid={`zone-handle-${zi}-${pi}`}
                    cx={x * 100}
                    cy={y * 100}
                    r={1.2}
                    fill="#fff"
                    stroke={ZONE_COLOR[z.type]}
                    strokeWidth={0.4}
                    style={{ cursor: 'move' }}
                    onPointerDown={() => (dragRef.current = { zoneIdx: zi, ptIdx: pi })}
                    onPointerMove={(e) => movePoint(e, zi, pi)}
                    onPointerUp={() => (dragRef.current = null)}
                    onContextMenu={(e) => removePoint(e, zi, pi)}
                  />
                ))}
            </g>
          ))}
          {/* preview polyline mode gambar */}
          {points.length > 0 && (
            <polyline points={toPct([...points, ringAt!])} fill="none" stroke="#ffffff" strokeWidth={0.4} strokeDasharray="2 1.5" />
          )}
          {points.map(([x, y], i) => (
            <circle key={i} cx={x * 100} cy={y * 100} r={0.7} fill="#fff" />
          ))}
          {/* ring titik pertama: ≥3 titik, hijau pulsing — klik = tutup polygon */}
          {canFinish && ringAt && (
            <circle
              data-testid="zone-start-ring"
              cx={ringAt[0] * 100}
              cy={ringAt[1] * 100}
              r={2.4}
              fill="none"
              stroke="#42be65"
              strokeWidth={0.8}
              onClick={(e) => {
                e.stopPropagation()
                finish()
              }}
              style={{ cursor: 'pointer', animation: 'zoneRingPulse 1.2s ease-in-out infinite' }}
            />
          )}
        </svg>
      </div>

      {/* daftar zone samping */}
      {initialZones.length > 0 && (
        <ul style={{ listStyle: 'none', padding: 0, marginTop: 12 }}>
          {initialZones.map((z) => (
            <li
              key={z.id}
              data-testid={`zone-list-item-${z.id}`}
              onClick={() => (z.id < 0 ? null : onSelect(z.id === selectedId ? null : z.id))}
              style={{
                display: 'flex',
                gap: 8,
                alignItems: 'center',
                padding: '6px 8px',
                cursor: 'pointer',
                background: z.id === selectedId ? 'var(--cds-layer-selected)' : 'transparent',
                borderRadius: 0,
              }}
            >
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: ZONE_COLOR[z.type], flexShrink: 0 }} />
              <span style={{ flex: 1 }}>{z.name}</span>
              <span style={{ fontSize: 11, color: 'var(--cds-text-helper)' }}>{t(`zones.type.${z.type}` as TKey)}</span>
              {!z.active && <span style={{ fontSize: 11, color: '#fa4d56' }}>OFF</span>}
            </li>
          ))}
        </ul>
      )}
      <style>{`@keyframes zoneRingPulse { 0%,100% { stroke-opacity: 1; } 50% { stroke-opacity: 0.3; } }`}</style>
    </div>
  )
}
