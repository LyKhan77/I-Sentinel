import { useEffect, useState } from 'react'
import { Button, InlineNotification, Modal, MultiSelect, TextInput } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { listCameras, type Camera } from '../../api/cameras'
import { cleanupEvents, type CleanupFilter, type CleanupResult } from '../../api/storage'
import { formatBytes } from './bytes'

// jenis yang bisa dipilih; attendance sengaja tidak ada (backend juga selalu mengecualikannya)
const TYPES = ['intrusion', 'loitering', 'running', 'idle_zone', 'crowd'] as const

function today(): string {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 10)
}

/** Hapus event behavior per rentang tanggal: pratinjau wajib sebelum hapus, konfirmasi merah. */
export default function EventCleanupCard({ onDone }: { onDone: () => void }) {
  const { t, locale } = useT()
  const [cams, setCams] = useState<Camera[]>([])
  const [filter, setFilter] = useState<CleanupFilter>({ date_from: '', date_to: '', camera_ids: [], types: [] })
  const [preview, setPreview] = useState<{ key: string; result: CleanupResult } | null>(null)
  const [confirm, setConfirm] = useState(false)
  const [done, setDone] = useState<CleanupResult | null>(null)
  const [error, setError] = useState<TKey | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    listCameras().then(setCams).catch(() => setCams([]))
  }, [])

  const key = JSON.stringify(filter)
  const ready = !!filter.date_from && !!filter.date_to && filter.date_from <= filter.date_to
  const previewed = preview?.key === key ? preview.result : null // filter berubah → pratinjau basi
  const summary = (r: CleanupResult) => t('storage.cleanup.summary')
    .replace('{events}', String(r.events)).replace('{files}', String(r.files)).replace('{size}', formatBytes(r.bytes, locale))

  const run = async (dryRun: boolean) => {
    setBusy(true)
    setError(null)
    try {
      const r = await cleanupEvents(filter, dryRun)
      if (dryRun) {
        setPreview({ key, result: r })
        setDone(null)
      } else {
        setDone(r)
        setPreview(null)
        setConfirm(false)
        onDone()
      }
    } catch (e) {
      setError((e as Error).message === 'invalid' ? 'storage.cleanup.invalid' : 'common.error')
      setConfirm(false)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="st-card" data-testid="storage-cleanup">
      <h3 className="st-card__title">{t('storage.cleanup.title')}</h3>
      <p className="en-muted">{t('storage.cleanup.hint')}</p>
      <div className="st-card__grid">
        <TextInput id="cleanup-from" type="date" labelText={t('storage.cleanup.from')} max={today()}
          value={filter.date_from} onChange={(e) => setFilter({ ...filter, date_from: e.target.value })} />
        <TextInput id="cleanup-to" type="date" labelText={t('storage.cleanup.to')} max={today()}
          value={filter.date_to} onChange={(e) => setFilter({ ...filter, date_to: e.target.value })} />
        <MultiSelect<Camera> id="cleanup-cams" titleText={t('storage.cleanup.cameras')} label={t('storage.cleanup.all')}
          items={cams} itemToString={(c) => c?.name ?? ''}
          onChange={({ selectedItems }) => setFilter((f) => ({ ...f, camera_ids: (selectedItems ?? []).map((c) => c.id) }))} />
        <MultiSelect<string> id="cleanup-types" titleText={t('storage.cleanup.types')} label={t('storage.cleanup.all')}
          items={[...TYPES]} itemToString={(k) => (k ? t(`zones.behavior.${k}` as TKey) : '')}
          onChange={({ selectedItems }) => setFilter((f) => ({ ...f, types: [...(selectedItems ?? [])] }))} />
      </div>
      <div className="st-card__actions">
        <Button kind="secondary" size="sm" data-testid="cleanup-preview" disabled={!ready || busy} onClick={() => run(true)}>
          {t('storage.cleanup.preview')}
        </Button>
        <Button kind="danger" size="sm" data-testid="cleanup-delete" disabled={!previewed || previewed.events === 0 || busy}
          onClick={() => setConfirm(true)}>
          {t('storage.cleanup.delete').replace('{n}', String(previewed?.events ?? 0))}
        </Button>
      </div>
      {previewed && <p data-testid="cleanup-preview-result">{summary(previewed)}</p>}
      {done && (
        <InlineNotification kind="success" lowContrast title={t('storage.cleanup.done')} subtitle={summary(done)}
          onCloseButtonClick={() => setDone(null)} />
      )}
      {error && <InlineNotification kind="error" lowContrast title={t(error)} onCloseButtonClick={() => setError(null)} />}
      {confirm && previewed && (
        <Modal open danger size="sm" modalHeading={t('storage.cleanup.confirmTitle')}
          primaryButtonText={t('storage.cleanup.delete').replace('{n}', String(previewed.events))}
          secondaryButtonText={t('common.cancel')} primaryButtonDisabled={busy}
          onRequestClose={() => setConfirm(false)} onRequestSubmit={() => run(false)}>
          <p>
            {t('storage.cleanup.confirmBody').replace('{n}', String(previewed.events))
              .replace('{from}', filter.date_from).replace('{to}', filter.date_to)}
          </p>
        </Modal>
      )}
    </section>
  )
}
