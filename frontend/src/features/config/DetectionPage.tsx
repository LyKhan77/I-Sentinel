import { useEffect, useState } from 'react'
import { Button, NumberInput, Toggle } from '@carbon/react'
import { listCameras, updateCamera, type Camera, type CameraPayload } from '../../api/cameras'
import { getDetectorSettings, putDetectorSettings, type DetectorSettings } from '../../api/detection'
import { useT } from '../../app/i18n'

const KINDS = ['intrusion', 'loitering', 'running', 'attendance'] as const
type DetectionPatch = Pick<CameraPayload, 'ai_fps' | 'confidence' | 'analyzers' | 'motion_enabled'>

export default function DetectionPage() {
  const { t } = useT()
  const [cameras, setCameras] = useState<Camera[]>([])
  const [settings, setSettings] = useState<DetectorSettings | null>(null)
  const [advanced, setAdvanced] = useState(false)
  useEffect(() => { Promise.all([listCameras(), getDetectorSettings()]).then(([cams, value]) => { setCameras(cams); setSettings(value) }).catch(() => {}) }, [])
  if (!settings) return null
  const patch = async (camera: Camera, values: DetectionPatch) => {
    setCameras((rows) => rows.map((row) => row.id === camera.id ? { ...row, ...values } : row))
    await updateCamera(camera.id, values)
  }
  const save = async () => setSettings(await putDetectorSettings({ default_ai_fps: settings.default_ai_fps, default_confidence: settings.default_confidence, motion_enabled: settings.motion_enabled, motion_threshold: settings.motion_threshold, motion_min_area: settings.motion_min_area, motion_force_interval_s: settings.motion_force_interval_s }))
  return <section className="det-page"><div className="det-global"><div className="det-tile"><small>{t('detection.model')}</small><strong>YOLO26s</strong><span>TensorRT FP16 · 640px</span></div><div className="det-tile"><small>{t('detection.fps')}</small><strong>{settings.default_ai_fps} FPS</strong><span>{t('detection.perCamera')}</span></div><div className="det-tile"><small>{t('detection.confidence')}</small><strong>{settings.default_confidence}</strong><span>person threshold</span></div><div className="det-tile"><small>{t('detection.tracker')}</small><strong>ByteTrack</strong><span>buffer 30 frame</span></div></div><table className="det-table"><thead><tr><th>{t('detection.camera')}</th><th>AI FPS</th><th>{t('detection.confidence')}</th><th>{t('detection.analyzers')}</th><th /></tr></thead><tbody>{cameras.map((camera) => <tr key={camera.id}><td>{camera.name}</td><td><NumberInput id={`fps-${camera.id}`} allowEmpty hideSteppers value={camera.ai_fps ?? ''} onChange={(_, { value }) => patch(camera, { ai_fps: value === '' ? null : Number(value) })} /></td><td><NumberInput id={`confidence-${camera.id}`} allowEmpty hideSteppers value={camera.confidence ?? ''} onChange={(_, { value }) => patch(camera, { confidence: value === '' ? null : Number(value) })} /></td><td>{KINDS.map((kind) => <Button key={kind} kind={(camera.analyzers ?? KINDS).includes(kind) ? 'tertiary' : 'ghost'} size="sm" onClick={() => { const active = camera.analyzers ?? [...KINDS]; patch(camera, { analyzers: active.includes(kind) ? active.filter((item) => item !== kind) : [...active, kind] }) }}>{kind}</Button>)}</td><td><Button kind="ghost" size="sm" onClick={() => patch(camera, { ai_fps: null, confidence: null, analyzers: null, motion_enabled: null })}>{t('detection.reset')}</Button></td></tr>)}</tbody></table><p>{t('detection.hint')}</p><Button kind="ghost" onClick={() => setAdvanced(!advanced)}>Advanced</Button>{advanced && <div className="det-advanced"><NumberInput id="motion-threshold" label="Motion threshold" value={settings.motion_threshold} onChange={(_, { value }) => setSettings({ ...settings, motion_threshold: Number(value) })}/><Toggle id="motion-enabled" labelText={t('detection.motion')} toggled={settings.motion_enabled} onToggle={(value) => setSettings({ ...settings, motion_enabled: value })}/><Button onClick={save}>{t('detection.save')}</Button></div>}</section>
}
