import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { listCameras } from '../../api/cameras'
import { listEvents, type EventOut } from '../../api/events'
import { useLiveEvents } from '../../api/useWs'
import { beep } from './beep'
import { dayStart } from './labels'

export const NOTIFY_TYPES: Record<string, true> = {
  intrusion: true,
  loitering: true,
  running: true,
  idle_zone: true,
  crowd: true,
  system: true,
}
export const ACTIVE_MS = 30_000
export const RECENT_MAX = 500 // pengaman memori; lonceng hanya menampilkan hari ini & kemarin
export const TOAST_MAX = 3
export const BEEP_GAP_MS = 5_000
export const STALE_MS = 60_000
const HISTORY_LIMIT = 200 // batas backend
export const SEEN_KEY = 'isentinel_notif_seen'
export const MUTE_KEY = 'isentinel_notif_mute'

export type CamAlert = { eventId: number; type: string; severity: string; zoneName: string | null; until: number }
export type NodeAlert = { eventId: number; node: string; until: number }
export type EventAlerts = {
  recent: EventOut[]
  unread: number
  markAllRead: () => void
  active: Record<number, CamAlert>
  nodes: NodeAlert[]
  toasts: EventOut[]
  dismissToast: (id: number) => void
  muted: boolean
  setMuted: (v: boolean) => void
  cameraName: (id: number | null) => string
}

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // storage diblokir → berlaku untuk sesi ini saja
  }
}

/**
 * Pesan WS/polling → event pemicu notifikasi, atau null (detections, kind:alert, attendance, ...).
 * Bentuk divalidasi runtime: pesan datang dari hub backend, bukan dari kode bertipe.
 */
export function asNotifyEvent(m: unknown): EventOut | null {
  if (typeof m !== 'object' || m === null) return null
  if (!('id' in m) || !('event_id' in m) || !('type' in m)) return null
  if (typeof m.id !== 'number' || typeof m.event_id !== 'string' || typeof m.type !== 'string') return null
  if (NOTIFY_TYPES[m.type] !== true) return null
  const payloadRaw: unknown = 'payload' in m ? m.payload : null
  // bentuk isi payload bebas per analyzer; konsumen membacanya dengan typeof
  const payload =
    typeof payloadRaw === 'object' && payloadRaw !== null && !Array.isArray(payloadRaw)
      ? (payloadRaw as Record<string, unknown>)
      : null
  return {
    id: m.id,
    event_id: m.event_id,
    type: m.type,
    camera_id: 'camera_id' in m && typeof m.camera_id === 'number' ? m.camera_id : null,
    zone_id: 'zone_id' in m && typeof m.zone_id === 'number' ? m.zone_id : null,
    severity: 'severity' in m && typeof m.severity === 'string' ? m.severity : 'info',
    ts_event: 'ts_event' in m && typeof m.ts_event === 'string' ? m.ts_event : new Date().toISOString(),
    payload,
    clip_path: 'clip_path' in m && typeof m.clip_path === 'string' ? m.clip_path : null,
    snapshot_path: 'snapshot_path' in m && typeof m.snapshot_path === 'string' ? m.snapshot_path : null,
  }
}

// tanpa provider (tes lama, komponen dipakai terpisah) → state kosong, aksi no-op
const INERT: EventAlerts = {
  recent: [], unread: 0, markAllRead: () => {}, active: {}, nodes: [], toasts: [],
  dismissToast: () => {}, muted: false, setMuted: () => {}, cameraName: (id) => `#${id ?? '?'}`,
}
const Ctx = createContext<EventAlerts>(INERT)
export const useEventAlerts = () => useContext(Ctx)

/**
 * Satu langganan event untuk seluruh app: riwayat (dimuat saat mount) hanya mengisi daftar lonceng;
 * event yang tiba sesudahnya memicu toast, bunyi, dan alert aktif per kamera / node.
 */
export function EventAlertsProvider({ children }: { children: ReactNode }) {
  const [recent, setRecent] = useState<EventOut[]>([])
  const [seenId, setSeenId] = useState<number | null>(() => {
    const raw = read(SEEN_KEY)
    const n = raw === null ? NaN : Number(raw)
    return Number.isFinite(n) ? n : null
  })
  const [active, setActive] = useState<Record<number, CamAlert>>({})
  const [nodes, setNodes] = useState<NodeAlert[]>([])
  const [toasts, setToasts] = useState<EventOut[]>([])
  const [muted, setMutedState] = useState(() => read(MUTE_KEY) === '1')
  const [camNames, setCamNames] = useState<Record<number, string>>({})
  const seen = useRef(new Set<number>())
  const buffer = useRef<EventOut[] | null>([]) // null = riwayat sudah diproses
  const historyFailed = useRef(false)
  const historyFrom = useRef(dayStart(1).getTime()) // awal jendela riwayat (ms); event sebelumnya = riwayat
  const lastBeep = useRef(-Infinity)
  const mutedRef = useRef(muted)
  useEffect(() => {
    mutedRef.current = muted
  }, [muted])

  // lonceng hanya hari ini & kemarin: event sebelum 00:00 kemarin dibuang (juga saat hari berganti)
  const addRecent = (list: EventOut[]) => {
    const from = dayStart(1).getTime()
    setRecent((prev) => [...list, ...prev]
      .filter((e) => Date.parse(e.ts_event) >= from)
      .sort((a, b) => b.id - a.id)
      .slice(0, RECENT_MAX))
  }

  const fire = (e: EventOut) => {
    const now = Date.now()
    addRecent([e])
    if (e.type === 'system') {
      if (e.payload?.kind !== 'health') {
        const node = String(e.payload?.node ?? '?')
        setNodes((prev) => [
          ...prev.filter((n) => n.node !== node),
          ...(e.payload?.reason === 'online' ? [] : [{ eventId: e.id, node, until: now + ACTIVE_MS }]),
        ])
      }
    } else if (e.camera_id != null) {
      const zoneName = typeof e.payload?.zone_name === 'string' && e.payload.zone_name ? e.payload.zone_name : null
      setActive((prev) => ({
        ...prev,
        [e.camera_id!]: { eventId: e.id, type: e.type, severity: e.severity, zoneName, until: now + ACTIVE_MS },
      }))
    }
    setToasts((prev) => [...prev, e].slice(-TOAST_MAX))
    if (!mutedRef.current && now - lastBeep.current >= BEEP_GAP_MS) {
      lastBeep.current = now
      beep()
    }
  }

  // riwayat gagal dimuat → event aliran yang sudah basi = riwayat, bukan kejadian baru.
  // Nilai balik = id event yang diperlakukan sebagai riwayat (0 bila event baru).
  const route = (e: EventOut) => {
    const ts = Date.parse(e.ts_event)
    // Sebelum jendela riwayat (00:00 kemarin) = bukan kejadian baru: poll pertama useLiveEvents memuat 50 event
    // terbaru SEMUA waktu (bukan hanya jendela lonceng), jadi event lama itu tidak ada di riwayat.
    if (ts < historyFrom.current || (historyFailed.current && Date.now() - ts >= STALE_MS)) {
      addRecent([e])
      return e.id
    }
    fire(e)
    return 0
  }

  useLiveEvents((m) => {
    const e = asNotifyEvent(m)
    if (!e || seen.current.has(e.id)) return
    seen.current.add(e.id)
    if (seen.current.size > 2000) seen.current = new Set([...seen.current].slice(-1000)) // TV 24/7
    if (buffer.current) buffer.current.push(e)
    else route(e)
  })

  useEffect(() => {
    let alive = true
    const flush = (historyIds: Set<number>) => {
      const pending = buffer.current ?? []
      buffer.current = null
      let maxStale = 0
      for (const e of pending) {
        if (historyIds.has(e.id)) continue
        maxStale = Math.max(maxStale, route(e))
      }
      return maxStale
    }
    // riwayat = event pemicu sejak 00:00 kemarin; filter jenis di backend agar absensi tidak memakan limit
    const from = dayStart(1)
    historyFrom.current = from.getTime()
    listEvents({ since: from.toISOString(), types: Object.keys(NOTIFY_TYPES), limit: HISTORY_LIMIT })
      .then((list) => {
        if (!alive) return
        const hist = list.map(asNotifyEvent).filter((e): e is EventOut => e !== null)
        for (const e of hist) seen.current.add(e.id)
        addRecent(hist)
        flush(new Set(hist.map((e) => e.id)))
        // kunjungan pertama: riwayat dianggap sudah dibaca (tanpa badge "99+" palsu)
        const max = hist.reduce((m, e) => Math.max(m, e.id), 0)
        setSeenId((s) => s ?? max)
        if (read(SEEN_KEY) === null) write(SEEN_KEY, String(max))
      })
      .catch(() => {
        if (!alive) return
        historyFailed.current = true
        const maxStale = flush(new Set())
        // kunjungan pertama: event basi yang masuk daftar sudah lewat, bukan belum dibaca
        setSeenId((s) => s ?? maxStale)
        if (maxStale > 0 && read(SEEN_KEY) === null) write(SEEN_KEY, String(maxStale))
      })
    listCameras()
      .then((cs) => { if (alive) setCamNames(Object.fromEntries(cs.map((c) => [c.id, c.name]))) })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, []) // sekali saat mount

  // alert kedaluwarsa dibersihkan tiap detik; state baru hanya bila ada yang berubah
  useEffect(() => {
    const timer = setInterval(() => {
      const now = Date.now()
      setActive((prev) => {
        const keep = Object.entries(prev).filter(([, a]) => a.until > now)
        return keep.length === Object.keys(prev).length ? prev : (Object.fromEntries(keep) as Record<number, CamAlert>)
      })
      setNodes((prev) => {
        const keep = prev.filter((n) => n.until > now)
        return keep.length === prev.length ? prev : keep
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  const value: EventAlerts = {
    recent,
    // jendela dihitung saat render: lewat tengah malam tanpa event baru, event lusa tidak ikut dihitung
    unread: seenId === null ? 0
      : recent.filter((e) => e.id > seenId && Date.parse(e.ts_event) >= dayStart(1).getTime()).length,
    markAllRead: () => {
      // riwayat belum dimuat (lonceng dibuka dari halaman lambat) → jangan simpan penanda "0" palsu;
      // penyemaian kunjungan pertama terjadi saat riwayat selesai dimuat
      if (seenId === null) return
      const max = Math.max(recent[0]?.id ?? 0, seenId)
      setSeenId(max)
      write(SEEN_KEY, String(max))
    },
    active,
    nodes,
    toasts,
    dismissToast: (id) => setToasts((prev) => prev.filter((e) => e.id !== id)),
    muted,
    setMuted: (v) => {
      setMutedState(v)
      write(MUTE_KEY, v ? '1' : '0')
    },
    cameraName: (id) => (id != null && camNames[id]) || `#${id ?? '?'}`,
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
