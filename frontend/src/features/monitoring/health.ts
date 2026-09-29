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
