import { useEffect, useRef } from 'react'
import { listEvents } from './events'

// Sumber data live = polling 5s (default, selalu jalan).
// WS /api/v1/ws/events dicoba sebagai enhancement: auth backend Task 1 hanya
// menerima ?token=<jwt> sedangkan JWT kita httpOnly cookie (tidak bisa dibaca JS).
// Bila handshake WS ditolak → onError/onClose membiarkan polling tetap jalan.
export function useLiveEvents(onEvent: (e: unknown) => void) {
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent
  const sinceRef = useRef<string | null>(null)

  useEffect(() => {
    let alive = true

    const poll = async () => {
      try {
        const events = await listEvents(sinceRef.current ? { since: sinceRef.current, limit: 50 } : { limit: 50 })
        if (!alive || events.length === 0) return
        // ts_event terbaru jadi kursor since (ISO string, komparator leksikal aman utk ISO UTC)
        sinceRef.current = events[0].ts_event
        for (const e of events) onEventRef.current(e)
      } catch {
        // poll gagal (mis. offline) → coba lagi di tick berikutnya
      }
    }

    poll()
    const timer = setInterval(poll, 5000)

    // WS enhancement — cookie ikut terkirim di handshake browser; jika backend
    // menolak tanpa ?token, koneksi tutup dan polling di atas tetap sumber data.
    let ws: WebSocket | null = null
    try {
      const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api/v1/ws/events`
      ws = new WebSocket(wsUrl)
      ws.onmessage = (ev) => {
        try {
          onEventRef.current(JSON.parse(ev.data))
        } catch {
          // frame bukan JSON → abaikan
        }
      }
      ws.onerror = () => ws?.close()
    } catch {
      // WebSocket tak tersedia (mis. lingkungan test) → polling saja
    }

    return () => {
      alive = false
      clearInterval(timer)
      ws?.close()
    }
  }, [])
}
