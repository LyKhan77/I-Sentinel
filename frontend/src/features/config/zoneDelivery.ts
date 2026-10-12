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
    const until = Date.parse(b.test_until ?? '')
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
