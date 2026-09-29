import { useEffect, useState } from 'react'
import { Button, InlineNotification, Modal, MultiSelect, RadioButton, RadioButtonGroup, TextInput } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { listCameras, type Camera } from '../../api/cameras'
import { cleanupEvents, type CleanupFilter, type CleanupMode, type CleanupResult } from '../../api/storage'
import { formatBytes } from './bytes'

// jenis yang bisa dipilih; attendance sengaja tidak ada (backend juga selalu mengecualikannya)
const TYPES = ['intrusion', 'loitering', 'running', 'idle_zone', 'crowd', 'system'] as const
// label: behavior memakai label zona; system = log node offline (hanya terhapus bila dipilih)
const typeLabel = (k: string): TKey => (k === 'system' ? 'storage.cleanup.type.system' : (`zones.behavior.${k}` as TKey))

function today(): string {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 10)
}

// teks per mode: event behavior (hapus event + media) vs media absensi saja (rekap tetap)
const TEXT: Record<CleanupMode, { delete: TKey; summary: TKey; confirm: TKey; done: TKey }> = {
  events: { delete: 'storage.cleanup.delete', summary: 'storage.cleanup.summary',
    confirm: 'storage.cleanup.confirmBody', done: 'storage.cleanup.done' },
  attendance_media: { delete: 'storage.cleanup.media.delete', summary: 'storage.cleanup.media.summary',
    confirm: 'storage.cleanup.media.confirmBody', done: 'storage.cleanup.media.done' },
}

/** Hapus event behavior / media absensi per rentang tanggal: pratinjau wajib, konfirmasi merah. */
export default function EventCleanupCard({ onDone }: { onDone: () => void }) {
  const { t, locale } = useT()
  const [cams, setCams] = useState<Camera[]>([])
  const [filter, setFilter] = useState<CleanupFilter>({ date_from: '', date_to: '', camera_ids: [], types: [], mode: 'events' })
  const [preview, setPreview] = useState<{ key: string; result: CleanupResult } | null>(null)
  const [confirm, setConfirm] = useState(false)
  const [done, setDone] = useState<CleanupResult | null>(null)
  const [error, setError] = useState<TKey | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    listCameras().then(setCams).catch(() => setCams([]))
  }, [])

  // mode media: Jenis tidak berlaku (backend 422 bila dikirim) → kirim kosong
  const request: CleanupFilter = filter.mode === 'attendance_media' ? { ...filter, types: [] } : filter
  const key = JSON.stringify(request) // mode ikut kunci → ganti mode = pratinjau basi
  const text = TEXT[filter.mode]
  const ready = !!filter.date_from && !!filter.date_to && filter.date_from <= filter.date_to
  const previewed = preview?.key === key ? preview.result : null // filter berubah → pratinjau basi
  const summary = (r: CleanupResult) => t(text.summary)
    .replace('{events}', String(r.events)).replace('{files}', String(r.files)).replace('{size}', formatBytes(r.bytes, locale))

  const run = async (dryRun: boolean) => {
    setBusy(true)
    setError(null)
    try {
      const r = await cleanupEvents(request, dryRun)
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
      <RadioButtonGroup legendText={t('storage.cleanup.mode')} name="cleanup-mode" valueSelected={filter.mode}
        onChange={(v) => setFilter((f) => ({ ...f, mode: v as CleanupMode }))}>
        <RadioButton id="cleanup-mode-events" value="events" labelText={t('storage.cleanup.mode.events')} />
        <RadioButton id="cleanup-mode-media" value="attendance_media" labelText={t('storage.cleanup.mode.media')} />
      </RadioButtonGroup>
      <div className="st-card__grid">
        <TextInput id="cleanup-from" type="date" labelText={t('storage.cleanup.from')} max={today()}
          value={filter.date_from} onChange={(e) => setFilter({ ...filter, date_from: e.target.value })} />
        <TextInput id="cleanup-to" type="date" labelText={t('storage.cleanup.to')} max={today()}
          value={filter.date_to} onChange={(e) => setFilter({ ...filter, date_to: e.target.value })} />
        <MultiSelect<Camera> id="cleanup-cams" titleText={t('storage.cleanup.cameras')} label={t('storage.cleanup.all')}
          items={cams} itemToString={(c) => c?.name ?? ''}
          onChange={({ selectedItems }) => setFilter((f) => ({ ...f, camera_ids: (selectedItems ?? []).map((c) => c.id) }))} />
        {filter.mode === 'events' && (
          <MultiSelect<string> id="cleanup-types" titleText={t('storage.cleanup.types')} label={t('storage.cleanup.all')}
            items={[...TYPES]} itemToString={(k) => (k ? t(typeLabel(k)) : '')}
            onChange={({ selectedItems }) => setFilter((f) => ({ ...f, types: [...(selectedItems ?? [])] }))} />
        )}
      </div>
      <div className="st-card__actions">
        <Button kind="secondary" size="sm" data-testid="cleanup-preview" disabled={!ready || busy} onClick={() => run(true)}>
          {t('storage.cleanup.preview')}
        </Button>
        <Button kind="danger" size="sm" data-testid="cleanup-delete" disabled={!previewed || previewed.events === 0 || busy}
          onClick={() => setConfirm(true)}>
          {t(text.delete).replace('{n}', String(previewed?.events ?? 0))}
        </Button>
      </div>
      {previewed && <p data-testid="cleanup-preview-result">{summary(previewed)}</p>}
      {done && (
        <InlineNotification kind="success" lowContrast title={t(text.done)} subtitle={summary(done)}
          onCloseButtonClick={() => setDone(null)} />
      )}
      {error && <InlineNotification kind="error" lowContrast title={t(error)} onCloseButtonClick={() => setError(null)} />}
      {confirm && previewed && (
        <Modal open danger size="sm" modalHeading={t('storage.cleanup.confirmTitle')}
          primaryButtonText={t(text.delete).replace('{n}', String(previewed.events))}
          secondaryButtonText={t('common.cancel')} primaryButtonDisabled={busy}
          onRequestClose={() => setConfirm(false)} onRequestSubmit={() => run(false)}>
          <p>
            {t(text.confirm).replace('{n}', String(previewed.events))
              .replace('{from}', filter.date_from).replace('{to}', filter.date_to)}
          </p>
        </Modal>
      )}
    </section>
  )
}
