import { useEffect, useRef } from 'react'
import { useLiveEvents } from '../../api/useWs'
import { useEventAlerts } from './EventAlertsProvider'

/**
 * Pesan mentah aliran event (WS detections + hasil polling) untuk komponen di dalam app. Memakai satu aliran milik
 * provider (satu poller 5 s dan satu WebSocket per jendela); tanpa provider (tes, komponen terpisah) membuka
 * langganan sendiri seperti `useLiveEvents`.
 */
export function useSharedLiveEvents(onEvent: (e: unknown) => void) {
  const { subscribeEvents } = useEventAlerts()
  const ref = useRef(onEvent)
  useEffect(() => {
    ref.current = onEvent
  })
  useLiveEvents((e) => ref.current(e), !subscribeEvents)
  useEffect(() => (subscribeEvents ? subscribeEvents((e) => ref.current(e)) : undefined), [subscribeEvents])
}
