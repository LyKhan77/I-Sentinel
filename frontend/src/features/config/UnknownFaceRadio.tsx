import { RadioButton, RadioButtonGroup } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import type { Behavior } from '../../api/zones'
import { effectiveUnknownDelivery, type Delivery, type UnknownDelivery } from './zoneDelivery'

const UNKNOWN_OPTIONS: UnknownDelivery[] = ['all', 'inbox', 'none']

/**
 * Tujuan wajah tidak dikenal satu zona absensi: *Inbox + Telegram* / *Hanya Inbox* / *Tidak dikirim*.
 *
 * *Inbox + Telegram* butuh tujuan event utama *Inbox + Telegram* (alert Telegram bertaut ke baris
 * event), jadi opsinya dinonaktifkan bila tujuan utamanya bukan itu; pilihan yang tampil jatuh ke
 * *Hanya Inbox* tanpa mengubah nilai tersimpan. *Tidak dikirim* membuang event di API: tanpa baris
 * Inbox, tanpa Telegram, dan tanpa skor pantauan untuk zona itu.
 */
export default function UnknownFaceRadio({ behavior, mainDelivery, onChoose }: {
  behavior: Behavior | null | undefined
  mainDelivery: Delivery
  onChoose: (value: UnknownDelivery) => void
}) {
  const { t } = useT()
  const value = effectiveUnknownDelivery(behavior, mainDelivery)
  const hint = t(`zones.unknown.${value}Hint` as TKey)
  return (
    <RadioButtonGroup
      legendText={t('zones.unknown.label')}
      name="zone-unknown"
      data-testid="zone-unknown"
      valueSelected={value}
      // Carbon hanya meng-clone RadioButton anak langsung, jadi teks bantu per pilihan
      // ditampilkan pada slot helper milik grup (pilihan aktif)
      helperText={mainDelivery === 'all' ? hint : `${hint} ${t('zones.unknown.needsTelegram')}`}
      onChange={(v) => onChoose(v as UnknownDelivery)}
    >
      {UNKNOWN_OPTIONS.map((option) => (
        <RadioButton
          key={option}
          id={`zone-unknown-${option}`}
          value={option}
          disabled={option === 'all' && mainDelivery !== 'all'}
          labelText={t(`zones.unknown.${option}` as TKey)}
        />
      ))}
    </RadioButtonGroup>
  )
}
