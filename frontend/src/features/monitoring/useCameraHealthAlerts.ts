import { useEffect, useState } from 'react'
import { getHealthAlerts } from '../../api/monitoring'

export const HEALTH_POLL_MS = 30_000
export type CameraHealth = { rule: string; severity: string }

/** Alert kesehatan aktif per kamera (badge tile Live View/TV). Gagal memuat → tanpa badge. */
export function useCameraHealthAlerts(): Record<number, CameraHealth> {
  const [byCam, setByCam] = useState<Record<number, CameraHealth>>({})
  useEffect(() => {
    let alive = true
    const load = () => getHealthAlerts()
      .then((a) => {
        if (!alive) return
        const out: Record<number, CameraHealth> = {}
        for (const x of a.active) {
          if (x.camera_id == null || !["camera_no_frames", "camera_low_fps"].includes(x.rule)) continue
          // satu badge per kamera: tanpa frame (critical) diutamakan dari fps rendah
          if (!out[x.camera_id] || x.rule === 'camera_no_frames') out[x.camera_id] = { rule: x.rule, severity: x.severity }
        }
        setByCam(out)
      })
      .catch(() => { if (alive) setByCam({}) })
    load()
    const timer = setInterval(load, HEALTH_POLL_MS)
    return () => { alive = false; clearInterval(timer) }
  }, [])
  return byCam
}
