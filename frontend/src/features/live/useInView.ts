import { useEffect, useState, type RefObject } from 'react'

// Pra-muat ± 1 baris tile di bawah layar: tile sudah menyambung sebelum auto-scroll membawanya masuk.
const ROOT_MARGIN = '0px 0px 50% 0px'

/** Tile dekat viewport? Tanpa IntersectionObserver (jsdom/browser lama) selalu true. */
export function useInView(ref: RefObject<Element | null>, always = false): boolean {
  const supported = typeof IntersectionObserver !== 'undefined'
  const [inView, setInView] = useState(always || !supported)
  useEffect(() => {
    if (always || !supported || !ref.current) return
    const io = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { rootMargin: ROOT_MARGIN })
    io.observe(ref.current)
    return () => io.disconnect()
  }, [ref, always, supported])
  return inView
}
