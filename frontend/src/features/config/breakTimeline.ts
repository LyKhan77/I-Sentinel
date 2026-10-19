import type { Break } from '../../api/zones'

/** Jam 00:00–23:59, format dan batas sama dengan validator server. */
export const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/

/** Istirahat tidak valid: bukan HH:MM, atau mulai >= selesai (bandingan string HH:MM seperti server). */
export const badBreak = (b: Break) => !HHMM.test(b.start) || !HHMM.test(b.end) || b.start >= b.end

export type Seg = { left: number; width: number } // persen terhadap lebar bilah
export type Timeline = { fromLabel: string; toLabel: string; work: Seg; quiet: Seg[]; outside: boolean }

const DAY = 1440
const PAD = 60 // menit di kiri/kanan jam kerja pada sumbu

const toMin = (hhmm: string) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5))
const label = (m: number) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`

/**
 * Hitung bilah waktu editor istirahat. `work` null (gate absensi: jam kerja tidak dipakai) atau tidak valid
 * = sumbu 00:00–24:00 dan bilah kerja penuh; selain itu sumbu = jam kerja ±1 jam, diperluas bila ada
 * istirahat valid di luar jam kerja. Istirahat tidak valid tidak digambar dan tidak mempengaruhi sumbu.
 */
export function buildTimeline(work: { start: string; end: string } | null, breaks: Break[]): Timeline {
  const ok = work !== null && HHMM.test(work.start) && HHMM.test(work.end) && work.start < work.end
  const valid = breaks.filter((b) => !badBreak(b))
  let from = 0
  let to = DAY
  if (ok) {
    from = Math.max(0, toMin(work.start) - PAD)
    to = Math.min(DAY, toMin(work.end) + PAD)
    for (const b of valid) {
      from = Math.min(from, toMin(b.start))
      to = Math.max(to, toMin(b.end))
    }
  }
  const span = to - from
  const seg = (a: number, b: number): Seg => ({ left: ((a - from) / span) * 100, width: ((b - a) / span) * 100 })
  return {
    fromLabel: label(from),
    toLabel: to === DAY ? '24:00' : label(to),
    work: ok ? seg(toMin(work.start), toMin(work.end)) : { left: 0, width: 100 },
    quiet: valid.map((b) => seg(toMin(b.start), toMin(b.end))),
    outside: ok && valid.some((b) => b.start < work.start || b.end > work.end),
  }
}
