import { useEffect, useState, type RefObject } from 'react'

// Pra-muat ± 1 baris tile di bawah layar: tile sudah menyambung sebelum auto-scroll membawanya masuk.
const PRELOAD_MARGIN = '0px 0px 50% 0px'

/**
 * Elemen dekat viewport? Default dengan margin pra-muat; '0px' = benar-benar terlihat.
 * Tanpa IntersectionObserver (jsdom/browser lama) selalu true.
 */
export function useInView(ref: RefObject<Element | null>, always = false, rootMargin = PRELOAD_MARGIN): boolean {
  const supported = typeof IntersectionObserver !== 'undefined'
  const [inView, setInView] = useState(always || !supported)
  useEffect(() => {
    if (always || !supported || !ref.current) return
    const io = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { rootMargin })
    io.observe(ref.current)
    return () => io.disconnect()
  }, [ref, always, supported, rootMargin])
  return inView
}
