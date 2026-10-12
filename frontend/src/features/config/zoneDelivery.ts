import type { Behavior } from '../../api/zones'

export type Delivery = 'all' | 'inbox' | 'test'

/**
 * Tujuan efektif satu behavior — padanan `effective_delivery` di backend:
 * `test` yang sudah lewat `test_until` kembali ke `revert_to` (bawaan `all`).
 * Tanpa `delivery`: diturunkan dari `telegram` item, lalu flag zona.
 */
export function effectiveDelivery(b: Behavior | null | undefined, zoneTelegram: boolean, nowMs: number): Delivery {
  if (!b) return zoneTelegram ? 'all' : 'inbox'
  if (b.delivery === 'test') {
    // belum ada `test_until`: pilihan yang baru dipilih dan belum disimpan (server yang menstempelnya saat
    // Simpan) — tampil sebagai `test`, kalau tidak radio mental kembali dan Mode uji tampak tak bisa diklik
    if (b.test_until == null) return 'test'
    const until = Date.parse(b.test_until)
    if (!Number.isNaN(until) && nowMs < until) return 'test'
    return b.revert_to === 'inbox' ? 'inbox' : 'all'
  }
  if (b.delivery === 'all' || b.delivery === 'inbox') return b.delivery
  return (b.telegram ?? zoneTelegram) ? 'all' : 'inbox'
}

/** Akhir Mode uji bila masih berlaku; `null` = tidak sedang uji (badge UJI tidak tampil). */
export function testUntil(b: Behavior | null | undefined, nowMs: number): Date | null {
  if (!b || b.delivery !== 'test') return null
  const until = Date.parse(b.test_until ?? '')
  return Number.isNaN(until) || until <= nowMs ? null : new Date(until)
}

export type UnknownDelivery = 'all' | 'inbox' | 'none'

/**
 * Tujuan wajah tidak dikenal satu zona — padanan `unknown_delivery` di backend.
 *
 * Nilai tersimpan: kunci `unknown_delivery` bila sah, selain itu turunan toggle lama
 * `telegram_unknown` (hanya `false` → `inbox`). *Inbox + Telegram* yang tidak mungkin
 * dikirim (tujuan utama bukan *Inbox + Telegram*) tampil sebagai *Hanya Inbox*:
 * hanya tampilan, nilai tersimpan tidak diubah.
 */
export function effectiveUnknownDelivery(b: Behavior | null | undefined, main: Delivery): UnknownDelivery {
  const raw = b?.unknown_delivery
  const stored: UnknownDelivery = raw === 'all' || raw === 'inbox' || raw === 'none'
    ? raw
    : b?.telegram_unknown === false ? 'inbox' : 'all'
  return stored === 'all' && main !== 'all' ? 'inbox' : stored
}
