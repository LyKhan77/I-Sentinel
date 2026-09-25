import { useEffect, useState } from 'react'
import { Button, NumberInput, Toggle } from '@carbon/react'
import { listCameras, updateCamera, type Camera, type CameraPayload } from '../../api/cameras'
import { getDetectorSettings, putDetectorSettings, type DetectorSettings } from '../../api/detection'
import { listZones, type Zone } from '../../api/zones'
import { useT } from '../../app/i18n'

type DetectionPatch = Pick<CameraPayload, 'ai_fps' | 'confidence' | 'motion_enabled'>

// Aturan sama dengan vision (node.py): zona visual (behaviors kosong) dan gate absensi tanpa arah
// tidak membuat worker. behaviors null = zona pra-R5 → vision memakai fallback legacy.
function runsAi(z: Zone): boolean {
  if (!z.active) return false
  const kinds = z.behaviors ?? []
  if (z.type === 'attendance' || kinds.some((b) => b.kind === 'attendance')) {
    return z.direction === 'entry' || z.direction === 'exit'
  }
  return z.behaviors == null || kinds.length > 0
}

export default function DetectionPage() {
  const { t } = useT()
  const [cameras, setCameras] = useState<Camera[]>([])
  const [activeZones, setActiveZones] = useState<Map<number, number>>(new Map())
  const [settings, setSettings] = useState<DetectorSettings | null>(null)
  const [advanced, setAdvanced] = useState(false)

  useEffect(() => {
    // semua kamera tampil; Status AI = jumlah zona yang benar-benar dijalankan vision
    Promise.all([listCameras(), getDetectorSettings(), listZones()])
      .then(([cams, value, zones]) => {
        const counts = new Map<number, number>()
        for (const z of zones) if (runsAi(z)) counts.set(z.camera_id, (counts.get(z.camera_id) ?? 0) + 1)
        setCameras(cams)
        setActiveZones(counts)
        setSettings(value)
      })
      .catch(() => {})
  }, [])
  if (!settings) return null

  const aiStatus = (camera: Camera) => {
    if (!camera.enabled) return t('detection.statusDisabled')
    const n = activeZones.get(camera.id) ?? 0
    return n > 0 ? t('detection.statusActive').replace('{n}', String(n)) : t('detection.statusIdle')
  }

  const patch = async (camera: Camera, values: DetectionPatch) => {
    setCameras((rows) => rows.map((row) => (row.id === camera.id ? { ...row, ...values } : row)))
    await updateCamera(camera.id, values)
  }
  const save = async () =>
    setSettings(await putDetectorSettings({
      default_ai_fps: settings.default_ai_fps, default_confidence: settings.default_confidence,
      motion_enabled: settings.motion_enabled, motion_threshold: settings.motion_threshold,
      motion_min_area: settings.motion_min_area, motion_force_interval_s: settings.motion_force_interval_s,
      face_min_width_px: settings.face_min_width_px, face_min_det_score: settings.face_min_det_score,
      face_max_yaw: settings.face_max_yaw, face_blur_min: settings.face_blur_min,
      face_min_frames: settings.face_min_frames,
    }))

  return (
    <section className="det-page">
      <div className="det-global">
        <div className="det-tile"><small>{t('detection.model')}</small><strong>YOLO26s</strong><span>TensorRT FP16 · 640px</span></div>
        <div className="det-tile"><small>{t('detection.fps')}</small><strong>{settings.default_ai_fps} FPS</strong><span>{t('detection.perCamera')}</span></div>
        <div className="det-tile"><small>{t('detection.confidence')}</small><strong>{settings.default_confidence}</strong><span>person threshold</span></div>
        <div className="det-tile"><small>{t('detection.tracker')}</small><strong>ByteTrack</strong><span>{t('detection.trackerHint')}</span></div>
        <div className="det-tile"><small>{t('detection.faceModel')}</small><strong>InsightFace buffalo_l</strong><span>SCRFD + ArcFace</span></div>
      </div>

      <table className="det-table">
        <thead>
          <tr><th>{t('detection.camera')}</th><th>AI FPS</th><th>{t('detection.confidence')}</th><th>{t('detection.status')}</th><th /></tr>
        </thead>
        <tbody>
          {cameras.map((camera) => (
            <tr key={camera.id}>
              <td>{camera.name}</td>
              <td>
                <input
                  id={`fps-${camera.id}`} className="det-num" type="number" min={0.5} max={25} step={0.5}
                  placeholder={String(settings.default_ai_fps)} value={camera.ai_fps ?? ''}
                  onChange={(e) => patch(camera, { ai_fps: e.target.value === '' ? null : Number(e.target.value) })}
                />
              </td>
              <td>
                <input
                  id={`confidence-${camera.id}`} className="det-num" type="number" min={0.05} max={0.95} step={0.05}
                  placeholder={String(settings.default_confidence)} value={camera.confidence ?? ''}
                  onChange={(e) => patch(camera, { confidence: e.target.value === '' ? null : Number(e.target.value) })}
                />
              </td>
              <td data-testid={`ai-status-${camera.id}`}>{aiStatus(camera)}</td>
              <td className="det-actions">
                <button
                  type="button" className="det-link"
                  onClick={() => patch(camera, { ai_fps: null, confidence: null, motion_enabled: null })}
                >{t('detection.reset')}</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <p>{t('detection.hint')}</p>
      <Button kind="ghost" size="sm" onClick={() => setAdvanced(!advanced)}>Advanced</Button>
      {advanced && (
        <div className="det-advanced">
          <NumberInput id="motion-threshold" label="Motion threshold" value={settings.motion_threshold}
            onChange={(_, { value }) => setSettings({ ...settings, motion_threshold: Number(value) })} />
          <Toggle id="motion-enabled" labelText={t('detection.motion')} toggled={settings.motion_enabled}
            onToggle={(value) => setSettings({ ...settings, motion_enabled: value })} />
          <h4>{t('detection.faceGroup')}</h4>
          <NumberInput id="face-min-width" label={t('detection.faceMinWidth')} min={16} max={1000} step={1}
            value={settings.face_min_width_px}
            onChange={(_, { value }) => setSettings({ ...settings, face_min_width_px: Number(value) })} />
          <NumberInput id="face-min-score" label={t('detection.faceMinScore')} min={0.1} max={0.99} step={0.05}
            value={settings.face_min_det_score}
            onChange={(_, { value }) => setSettings({ ...settings, face_min_det_score: Number(value) })} />
          <NumberInput id="face-max-yaw" label={t('detection.faceMaxYaw')} min={0.05} max={1} step={0.05}
            value={settings.face_max_yaw}
            onChange={(_, { value }) => setSettings({ ...settings, face_max_yaw: Number(value) })} />
          <NumberInput id="face-blur-min" label={t('detection.faceBlurMin')} min={0} step={10}
            value={settings.face_blur_min}
            onChange={(_, { value }) => setSettings({ ...settings, face_blur_min: Number(value) })} />
          <NumberInput id="face-min-frames" label={t('detection.faceMinFrames')} min={1} max={20} step={1}
            value={settings.face_min_frames}
            onChange={(_, { value }) => setSettings({ ...settings, face_min_frames: Number(value) })} />
          <Button size="sm" onClick={save}>{t('detection.save')}</Button>
        </div>
      )}
    </section>
  )
}
