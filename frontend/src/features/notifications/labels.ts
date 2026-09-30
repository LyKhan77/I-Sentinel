import type { EventOut } from '../../api/events'
import type { TKey } from '../../app/i18n'

export type Sev = 'critical' | 'warning' | 'info'
const SEVS: readonly string[] = ['critical', 'warning', 'info']

/** Severity tak dikenal → warning (warna tetap terlihat). */
export const sevClass = (s: string): Sev => (SEVS.includes(s) ? (s as Sev) : 'warning')

/** Event system "pulih" (node online kembali). */
export const isNodeOnline = (e: EventOut): boolean => e.type === 'system' && e.payload?.reason === 'online'

/** System event emitted by Monitoring health rules, not a node-offline transition. */
export const isHealthEvent = (e: EventOut): boolean => e.type === 'system' && e.payload?.kind === 'health'

/** Judul event di lonceng/toast: system pulih punya label sendiri. */
export const eventTitleKey = (e: EventOut): TKey =>
  isHealthEvent(e) ? (`health.rule.${e.payload?.rule}` as TKey)
    : isNodeOnline(e) ? 'notif.type.systemOnline' : typeKey(e.type)

/** Health recovery has an explicit normal-state title in toast and bell history. */
export function eventTitle(e: EventOut, t: (k: TKey) => string): string {
  const title = t(eventTitleKey(e))
  return isHealthEvent(e) && e.payload?.state === 'resolved'
    ? t('health.normal').replace('{rule}', title) : title
}

/** Label jenis event: behavior memakai label zona; system = "Node offline". */
export const typeKey = (type: string): TKey =>
  type === 'system' ? 'notif.type.system' : (`zones.behavior.${type}` as TKey)

/** Lokasi event: "Node X offline"/"Node X pulih" untuk system, selain itu "kamera · zona". */
export function eventWhere(e: EventOut, t: (k: TKey) => string, cameraName: (id: number | null) => string): string {
  if (isHealthEvent(e)) return String(e.payload?.label ?? '')
  if (e.type === 'system') {
    const node = String(e.payload?.node ?? '?')
    return t(isNodeOnline(e) ? 'notif.nodeOnline' : 'notif.nodeOffline').replace('{node}', node)
  }
  const zone = typeof e.payload?.zone_name === 'string' && e.payload.zone_name ? e.payload.zone_name : null
  return zone ? `${cameraName(e.camera_id)} · ${zone}` : cameraName(e.camera_id)
}

/** 00:00 waktu lokal, `daysAgo` hari lalu (0 = hari ini, 1 = kemarin). */
export function dayStart(daysAgo: number, now = new Date()): Date {
  const d = new Date(now)
  d.setHours(0, 0, 0, 0)
  d.setDate(d.getDate() - daysAgo)
  return d
}
