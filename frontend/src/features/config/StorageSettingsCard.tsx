import { useState } from 'react'
import { Button, InlineNotification, NumberInput } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { saveStorageSettings, type StorageSettings } from '../../api/storage'

const FIELDS: [keyof StorageSettings, TKey, number, number][] = [
  ['clip_days', 'storage.settings.clipDays', 1, 3650],
  ['snapshot_days', 'storage.settings.snapshotDays', 1, 3650],
  ['disk_alert_percent', 'storage.settings.alertPercent', 50, 99],
]

/** Form retensi clip/snapshot + ambang disk; nilai awal diambil sekali saat mount. */
export default function StorageSettingsCard({ value, isAdmin, onSaved }: {
  value: StorageSettings
  isAdmin: boolean
  onSaved: (s: StorageSettings) => void
}) {
  const { t } = useT()
  const [form, setForm] = useState(value)
  const [status, setStatus] = useState<'ok' | 'invalid' | 'error' | null>(null)
  const [busy, setBusy] = useState(false)

  const save = async () => {
    setBusy(true)
    setStatus(null)
    try {
      onSaved(await saveStorageSettings(form))
      setStatus('ok')
    } catch (e) {
      setStatus((e as Error).message === 'invalid' ? 'invalid' : 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="st-card" data-testid="storage-settings">
      <h3 className="st-card__title">{t('storage.settings.title')}</h3>
      <div className="st-card__grid">
        {FIELDS.map(([key, label, min, max]) => (
          <NumberInput key={key} id={`storage-${key}`} label={t(label)} min={min} max={max} step={1}
            value={form[key]} disabled={!isAdmin}
            onChange={(_, state) => {
              const n = Number(state.value)
              if (Number.isInteger(n)) setForm((f) => ({ ...f, [key]: n }))
            }} />
        ))}
      </div>
      <p className="en-muted">{t('storage.settings.schedule')}</p>
      {status === 'ok' && (
        <InlineNotification kind="success" lowContrast title={t('storage.settings.saved')} onCloseButtonClick={() => setStatus(null)} />
      )}
      {status && status !== 'ok' && (
        <InlineNotification kind="error" lowContrast
          title={t(status === 'invalid' ? 'storage.settings.invalid' : 'common.error')}
          onCloseButtonClick={() => setStatus(null)} />
      )}
      {isAdmin && (
        <Button size="sm" data-testid="storage-settings-save" disabled={busy} onClick={save}>{t('common.save')}</Button>
      )}
    </section>
  )
}
