// Auto-scroll halus vertikal untuk layar TV: turun pelan, jeda di dasar, kembali ke atas, jeda, ulang.
import { useEffect, useRef, useState } from 'react'

export const END_PAUSE_MS = 5000
const MAX_DT_MS = 100 // frame tertunda (tab tidak aktif) tidak membuat lompatan besar

export type ScrollState = { phase: 'down' | 'bottom' | 'top'; pos: number; wait: number }
export const SCROLL_START: ScrollState = { phase: 'down', pos: 0, wait: 0 }

export function stepScroll(s: ScrollState, dtMs: number, max: number, pxPerSec: number): ScrollState {
  if (max <= 0) return SCROLL_START
  const dt = Math.min(dtMs, MAX_DT_MS)
  if (s.phase === 'down') {
    const pos = s.pos + (pxPerSec * dt) / 1000
    return pos >= max ? { phase: 'bottom', pos: max, wait: END_PAUSE_MS } : { ...s, pos }
  }
  const wait = s.wait - dt
  if (wait > 0) return { ...s, wait }
  return s.phase === 'bottom' ? { phase: 'top', pos: 0, wait: END_PAUSE_MS } : SCROLL_START
}

/** Gulir `document.scrollingElement`; saat `paused`, posisi disinkronkan ulang dari scroll manual operator. */
export function useAutoScroll({ on, pxPerSec, paused }: { on: boolean; pxPerSec: number; paused: boolean }) {
  const pausedRef = useRef(paused)
  useEffect(() => {
    pausedRef.current = paused
  }, [paused])
  useEffect(() => {
    if (!on || typeof requestAnimationFrame === 'undefined') return
    let state = SCROLL_START
    let last = performance.now()
    let resync = true
    let raf = 0
    const frame = (now: number) => {
      const dt = now - last
      last = now
      const el = document.scrollingElement as HTMLElement | null
      if (el && !pausedRef.current) {
        if (resync) {
          state = { ...SCROLL_START, pos: el.scrollTop }
          resync = false
        }
        const next = stepScroll(state, dt, el.scrollHeight - el.clientHeight, pxPerSec)
        if (next.phase === 'top') {
          if (state.phase !== 'top') el.scrollTo({ top: 0, behavior: 'smooth' })
        } else {
          el.scrollTop = Math.round(next.pos)
        }
        state = next
      } else {
        resync = true
      }
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [on, pxPerSec])
}

const ACTIVITY = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'wheel'] as const

/** true bila operator tidak beraktivitas selama `ms` (auto-hide toolbar, lanjut auto-scroll). */
export function useIdle(ms: number): boolean {
  const [idle, setIdle] = useState(false)
  useEffect(() => {
    let timer = setTimeout(() => setIdle(true), ms)
    const wake = () => {
      setIdle(false)
      clearTimeout(timer)
      timer = setTimeout(() => setIdle(true), ms)
    }
    ACTIVITY.forEach((e) => window.addEventListener(e, wake, { passive: true }))
    return () => {
      clearTimeout(timer)
      ACTIVITY.forEach((e) => window.removeEventListener(e, wake))
    }
  }, [ms])
  return idle
}
