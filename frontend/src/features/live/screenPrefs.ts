// Pengaturan Live View per layar (?screen=): satu Pi bisa menjalankan dua jendela TV di origin yang sama,
// jadi setiap layar punya kunci localStorage sendiri.
import { useCallback, useState } from 'react'

export type Cols = 1 | 2 | 3 | 4
export type ScrollSpeed = 'slow' | 'medium' | 'fast'
export type CameraSel = { mode: 'all' } | { mode: 'some'; ids: number[] }
export type ScreenPrefs = { cols: Cols; cameras: CameraSel; scroll: { on: boolean; speed: ScrollSpeed } }

export const COL_OPTIONS: Cols[] = [3, 2, 4, 1] // urutan mockup 02: default dulu; 1 kolom ditambahkan di akhir agar posisi chip lama tetap
export const SCROLL_SPEEDS: Record<ScrollSpeed, number> = { slow: 20, medium: 40, fast: 80 } // px per detik
const KEY = 'isentinel_live_screen:'
const LEGACY_COLS_KEY = 'isentinel_live_cols'

export function screenName(raw: string | null | undefined): string {
  return raw && /^[A-Za-z0-9_-]{1,32}$/.test(raw) ? raw : 'default'
}

export function defaultCols(): Cols {
  return window.matchMedia?.('(orientation: portrait)').matches ? 2 : 3
}

const isCols = (v: unknown): v is Cols => v === 1 || v === 2 || v === 3 || v === 4

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

/** Override dari parameter URL `/live/tv` (`cameras` ada = mode URL aktif; `undefined` = parameter tidak ada). */
export type TvUrlOverrides = { cameras?: number[]; cols?: Cols; scroll?: boolean; speed?: ScrollSpeed }

/** Parse parameter URL mode TV. Fungsi murni: tidak menyentuh `localStorage`. */
export function parseTvUrl(params: URLSearchParams): TvUrlOverrides {
  const out: TvUrlOverrides = {}
  const rawCams = params.get('cameras')
  if (rawCams !== null) {
    const seen = new Set<number>()
    const ids: number[] = []
    for (const token of rawCams.split(',')) {
      const v = token.trim()
      if (!/^\d+$/.test(v)) continue
      const id = Number(v)
      if (id <= 0 || seen.has(id)) continue
      seen.add(id)
      ids.push(id)
    }
    out.cameras = ids
  }
  const rawCols = params.get('cols')
  if (rawCols !== null) {
    const n = Number(rawCols)
    if (isCols(n)) out.cols = n
  }
  const rawScroll = params.get('scroll')
  if (rawScroll !== null) {
    const v = rawScroll.trim().toLowerCase()
    if (v === 'on') out.scroll = true
    else if (v === 'off') out.scroll = false
  }
  const rawSpeed = params.get('speed')
  if (rawSpeed !== null) {
    const v = rawSpeed.trim().toLowerCase()
    if (Object.hasOwn(SCROLL_SPEEDS, v)) out.speed = v as ScrollSpeed
  }
  return out
}

/** Pilih kamera menurut urutan `ids`; ID yang tidak ada di `cams` dilewati. */
export function selectByIds<T extends { id: number }>(cams: T[], ids: number[]): T[] {
  const byId = new Map(cams.map((c) => [c.id, c]))
  const out: T[] = []
  for (const id of ids) {
    const cam = byId.get(id)
    if (cam) out.push(cam)
  }
  return out
}

/** Gabungkan pengaturan tersimpan dengan override URL; `cameras` tidak disentuh dan tidak ada tulis ke `localStorage`. */
export function withOverrides(prefs: ScreenPrefs, o: TvUrlOverrides): ScreenPrefs {
  return {
    cols: o.cols ?? prefs.cols,
    cameras: prefs.cameras,
    scroll: { on: o.scroll ?? prefs.scroll.on, speed: o.speed ?? prefs.scroll.speed },
  }
}

/** Keadaan lengkap satu jendela TV yang ditulis ke URL. */
export type TvState = { cameras: number[]; cols: Cols; scroll: boolean; speed: ScrollSpeed }

/**
 * Urutan ID kamera sesudah pilihan di pemilih berubah: ID yang masih terpilih menjaga urutan `current`,
 * ID baru ditambahkan di akhir menurut urutan `active`. Mode `all` memakai aturan yang sama.
 */
export function orderCameraIds(current: number[], sel: CameraSel, active: { id: number }[]): number[] {
  const picked = active.filter((c) => isSelected(sel, c.id)).map((c) => c.id)
  const pickedSet = new Set(picked)
  const kept = current.filter((id) => pickedSet.has(id))
  const keptSet = new Set(kept)
  return [...kept, ...picked.filter((id) => !keptSet.has(id))]
}

/**
 * Query string (tanpa `?`) jendela TV: parameter lain dari `base` (termasuk `screen`) dipertahankan berurutan,
 * lalu `cameras` (koma apa adanya agar mudah disalin), `cols`, `scroll`, `speed`. `base` tidak dimutasi.
 */
export function tvSearch(base: URLSearchParams, s: TvState): string {
  const managed = new Set(['cameras', 'cols', 'scroll', 'speed'])
  const parts: string[] = []
  for (const [k, v] of base) {
    if (!managed.has(k)) parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
  }
  parts.push(`cameras=${s.cameras.join(',')}`, `cols=${s.cols}`, `scroll=${s.scroll ? 'on' : 'off'}`, `speed=${s.speed}`)
  return parts.join('&')
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
