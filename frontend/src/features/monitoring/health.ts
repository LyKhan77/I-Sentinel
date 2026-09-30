import type { TKey } from '../../app/i18n'
import type { Health } from '../../api/monitoring'

export const HEALTH_ORDER: Record<Health, number> = { critical: 0, warning: 1, unknown: 2, ok: 3, disabled: 4 }
export const healthKey = (h: Health): TKey => `mon.health.${h}` as TKey
export const issueKey = (code: string): TKey => `mon.issue.${code}` as TKey
export const stateKey = (s: string | null): TKey => `mon.state.${s ?? 'none'}` as TKey
export const serviceKey = (k: string): TKey => `mon.service.${k}` as TKey
/** Angka tak tersedia → "—". */
export const fmt = (v: number | null | undefined, unit = '', digits = 0) =>
  v == null ? '—' : `${v.toFixed(digits)}${unit}`

/** Umur dalam detik → "N dtk" / "N mnt" / "N jam" (heartbeat lama tidak tampil "3300 dtk"). */
export function ago(s: number, t: (k: TKey) => string): string {
  if (s < 90) return t('mon.ago.s').replace('{n}', String(Math.round(s)))
  if (s < 90 * 60) return t('mon.ago.m').replace('{n}', String(Math.round(s / 60)))
  return t('mon.ago.h').replace('{n}', String(Math.round(s / 3600)))
}
