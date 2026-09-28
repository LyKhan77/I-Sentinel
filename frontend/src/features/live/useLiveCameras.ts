import { useCallback, useEffect, useState } from 'react'
import { listCameras, type Camera } from '../../api/cameras'
import { getLive, type LiveInfo } from '../../api/events'

/** Daftar kamera + URL live, di-refresh tiap 30 s (juga menjaga sesi bergulir tetap hidup). */
export function useLiveCameras() {
  const [cams, setCams] = useState<Camera[]>([])
  const [lives, setLives] = useState<Record<number, LiveInfo>>({})
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
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
  return { cams, lives, loading, loadFailed, dismissError: () => setLoadFailed(false) }
}
