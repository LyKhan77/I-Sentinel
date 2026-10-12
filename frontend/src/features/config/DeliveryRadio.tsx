import { RadioButton, RadioButtonGroup } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import type { Behavior, BehaviorKind } from '../../api/zones'
import { effectiveDelivery, type Delivery } from './zoneDelivery'

const DELIVERY_OPTIONS: Delivery[] = ['all', 'inbox', 'test']

/**
 * Radio tujuan event satu behavior: *Inbox + Telegram* / *Hanya Inbox* / *Mode uji*.
 *
 * Dipakai bersama blok behavior alert dan blok absensi supaya aturannya satu tempat.
 * Pemanggil memberi `key` yang memuat `rev` (remount saat pilihan selesai/dibatalkan:
 * klik native sempat memindahkan `checked` di DOM sementara state React tidak berubah).
 */
export default function DeliveryRadio({ kind, behavior, zoneTelegram, nowMs, onChoose }: {
  kind: BehaviorKind | 'attendance'
  behavior: Behavior
  zoneTelegram: boolean
  nowMs: number
  onChoose: (value: Delivery) => void
}) {
  const { t } = useT()
  const value = effectiveDelivery(behavior, zoneTelegram, nowMs)
  // absensi: "Inbox + Telegram" hanya mengirim wajah yang dikenali (wajah tak dikenal punya toggle
  // sendiri) dan Mode uji berarti karyawan yang lewat TIDAK tercatat — bantuan harus mengatakannya
  const hint = kind === 'attendance' && value !== 'inbox'
    ? `zones.delivery.${value}HintAttendance`
    : `zones.delivery.${value}Hint`
  return (
    <RadioButtonGroup
      legendText={t('zones.delivery.label')}
      name={`zone-delivery-${kind}`}
      data-testid={`zone-delivery-${kind}`}
      valueSelected={value}
      // Carbon hanya meng-clone RadioButton anak langsung, jadi teks bantu per pilihan
      // ditampilkan pada slot helper milik grup (pilihan aktif)
      helperText={t(hint as TKey)}
      onChange={(v) => onChoose(v as Delivery)}
    >
      {DELIVERY_OPTIONS.map((option) => (
        <RadioButton
          key={option}
          id={`zone-delivery-${kind}-${option}`}
          value={option}
          labelText={t(`zones.delivery.${option}` as TKey)}
        />
      ))}
    </RadioButtonGroup>
  )
}
