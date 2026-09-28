// Pengaturan Live View per layar (?screen=): satu Pi bisa menjalankan dua jendela TV di origin yang sama,
// jadi setiap layar punya kunci localStorage sendiri.
import { useCallback, useState } from 'react'

export type Cols = 2 | 3 | 4
export type ScrollSpeed = 'slow' | 'medium' | 'fast'
export type CameraSel = { mode: 'all' } | { mode: 'some'; ids: number[] }
export type ScreenPrefs = { cols: Cols; cameras: CameraSel; scroll: { on: boolean; speed: ScrollSpeed } }

export const COL_OPTIONS: Cols[] = [3, 2, 4] // urutan mockup 02: default dulu
export const SCROLL_SPEEDS: Record<ScrollSpeed, number> = { slow: 20, medium: 40, fast: 80 } // px per detik
const KEY = 'isentinel_live_screen:'
const LEGACY_COLS_KEY = 'isentinel_live_cols'

export function screenName(raw: string | null | undefined): string {
  return raw && /^[A-Za-z0-9_-]{1,32}$/.test(raw) ? raw : 'default'
}

export function defaultCols(): Cols {
  return window.matchMedia?.('(orientation: portrait)').matches ? 2 : 3
}

const isCols = (v: unknown): v is Cols => v === 2 || v === 3 || v === 4

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export function loadPrefs(screen: string): ScreenPrefs {
  let raw: Record<string, unknown> = {}
  try {
    const v: unknown = JSON.parse(read(KEY + screen) ?? '{}')
    if (v && typeof v === 'object') raw = v as Record<string, unknown>
  } catch {
    // nilai rusak → default
  }
  const legacy = screen === 'default' ? Number(read(LEGACY_COLS_KEY)) : NaN
  const cols = isCols(raw.cols) ? raw.cols : isCols(legacy) ? legacy : defaultCols()
  const c = raw.cameras as { mode?: unknown; ids?: unknown } | undefined
  const cameras: CameraSel = c?.mode === 'some' && Array.isArray(c.ids)
    ? { mode: 'some', ids: c.ids.filter((x): x is number => Number.isInteger(x)) }
    : { mode: 'all' }
  const s = raw.scroll as { on?: unknown; speed?: unknown } | undefined
  const speed = typeof s?.speed === 'string' && Object.hasOwn(SCROLL_SPEEDS, s.speed) ? (s.speed as ScrollSpeed) : 'medium'
  return { cols, cameras, scroll: { on: s?.on === true, speed } }
}

export function savePrefs(screen: string, prefs: ScreenPrefs): void {
  try {
    localStorage.setItem(KEY + screen, JSON.stringify(prefs))
  } catch {
    // storage penuh / mode privat: pengaturan hanya berlaku di sesi ini
  }
}

export function useScreenPrefs(screen: string): [ScreenPrefs, (patch: Partial<ScreenPrefs>) => void] {
  const [prefs, setPrefs] = useState(() => loadPrefs(screen))
  const update = useCallback((patch: Partial<ScreenPrefs>) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch }
      savePrefs(screen, next)
      return next
    })
  }, [screen])
  return [prefs, update]
}

export function isSelected(sel: CameraSel, id: number): boolean {
  return sel.mode === 'all' || sel.ids.includes(id)
}

export function selectCameras<T extends { id: number }>(cams: T[], sel: CameraSel): T[] {
  return cams.filter((c) => isSelected(sel, c.id))
}

/** Pilih/buang `ids`; bila semua kamera terpilih → `all` (kamera baru ikut tampil). */
export function setCameras(sel: CameraSel, cams: { id: number }[], ids: number[], on: boolean): CameraSel {
  const chosen = new Set(cams.filter((c) => isSelected(sel, c.id)).map((c) => c.id))
  for (const id of ids) {
    if (on) chosen.add(id)
    else chosen.delete(id)
  }
  if (cams.length > 0 && cams.every((c) => chosen.has(c.id))) return { mode: 'all' }
  return { mode: 'some', ids: cams.filter((c) => chosen.has(c.id)).map((c) => c.id) }
}
