import { useCallback, useEffect, useRef, useState } from 'react'
import { listCameras, type Camera } from '../../api/cameras'
import { getLive, type LiveInfo } from '../../api/events'

/** Kamera yang perlu info /live: aktif dan (bila `wanted` diberikan) ada di `wanted`. */
function targetIds(list: Camera[], wanted: number[] | null | undefined): number[] {
  const w = wanted ? new Set(wanted) : null
  return list.filter((c) => c.enabled && (!w || w.has(c.id))).map((c) => c.id)
}

/**
 * Daftar kamera + URL live, di-refresh tiap 30 s (juga menjaga sesi bergulir tetap hidup).
 * `wanted` = ID kamera yang ditampilkan jendela ini; hanya itu (yang aktif) yang diambil `/live`-nya.
 * `null`/`undefined` = semua kamera aktif. Himpunan yang berubah langsung mengambil ID yang belum punya info saja
 * (ID yang gagal diambil dianggap belum punya info dan dicoba lagi).
 */
export function useLiveCameras(wanted?: number[] | null) {
  const [cams, setCams] = useState<Camera[]>([])
  const [lives, setLives] = useState<Record<number, LiveInfo>>({})
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const wantedRef = useRef(wanted)
  useEffect(() => {
    wantedRef.current = wanted // sebelum efek di bawah (urutan deklarasi), tanpa menulis ref saat render
  })
  const camsRef = useRef<Camera[]>([])
  const livesRef = useRef<Record<number, LiveInfo>>({})

  const fetchLives = useCallback(async (ids: number[]) => {
    const got: Record<number, LiveInfo> = {}
    await Promise.all(
      ids.map(async (id) => {
        try {
          got[id] = await getLive(id)
        } catch {
          // kamera offline / go2rtc belum siap → tile tanpa snapshot
        }
      }),
    )
    return got
  }, [])

  const refresh = useCallback(async () => {
    try {
      const list = await listCameras()
      camsRef.current = list
      setCams(list)
      setLoadFailed(false)
      const infos = await fetchLives(targetIds(list, wantedRef.current))
      livesRef.current = infos
      setLives(infos)
    } catch {
      setLoadFailed(true) // jangan bilang "belum ada kamera" kalau requestnya yang gagal
    } finally {
      setLoading(false)
    }
  }, [fetchLives])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 30000) // refresh info /live (snapshot img sendiri auto 2s)
    return () => clearInterval(timer)
  }, [refresh])

  // Himpunan tampil berubah (pemilih kamera / URL): ambil hanya ID yang belum punya info, buang yang tak tampil.
  const wantedKey = wanted == null ? '*' : [...wanted].sort((a, b) => a - b).join(',')
  useEffect(() => {
    const list = camsRef.current
    if (list.length === 0) return // belum dimuat: refresh pertama yang mengisi
    const ids = targetIds(list, wantedRef.current)
    const idSet = new Set(ids)
    const keep: Record<number, LiveInfo> = {}
    for (const [k, v] of Object.entries(livesRef.current)) if (idSet.has(Number(k))) keep[Number(k)] = v
    const missing = ids.filter((id) => !(id in keep))
    let cancelled = false
    void (async () => {
      const got = missing.length ? await fetchLives(missing) : {}
      if (cancelled) return
      const next = { ...keep, ...got }
      livesRef.current = next
      setLives(next)
    })()
    return () => {
      cancelled = true
    }
  }, [wantedKey, fetchLives])

  return { cams, lives, loading, loadFailed, dismissError: () => setLoadFailed(false) }
}
