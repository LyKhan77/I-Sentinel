import { useEffect, useState } from 'react'
import {
  Button, Checkbox, InlineNotification, Modal, MultiSelect, RadioButton, RadioButtonGroup,
  Table, TableBody, TableCell, TableContainer, TableHead, TableHeader, TableRow, TextInput,
} from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { listCameras, type Camera } from '../../api/cameras'
import { listEmployees, type Employee } from '../../api/employees'
import { cleanupEvents, type CleanupFilter, type CleanupMode, type CleanupResult } from '../../api/storage'
import { formatBytes } from './bytes'

// jenis yang bisa dipilih; attendance sengaja tidak ada (backend juga selalu mengecualikannya)
const TYPES = ['intrusion', 'loitering', 'running', 'idle_zone', 'crowd', 'system'] as const
// label: behavior memakai label zona; system = log node offline (hanya terhapus bila dipilih)
const typeLabel = (k: string): TKey => (k === 'system' ? 'storage.cleanup.type.system' : (`zones.behavior.${k}` as TKey))
// kata konfirmasi mode attendance_data — tidak diterjemahkan, sengaja fixed (kata kunci keamanan)
const CONFIRM_WORD = 'HAPUS'

function today(): string {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 10)
}

function yesterday(): string {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  d.setDate(d.getDate() - 1)
  return d.toISOString().slice(0, 10)
}

// teks per mode: event behavior (hapus event + media) vs media absensi saja (rekap tetap)
const TEXT: Record<'events' | 'attendance_media', { delete: TKey; summary: TKey; confirm: TKey; done: TKey }> = {
  events: { delete: 'storage.cleanup.delete', summary: 'storage.cleanup.summary',
    confirm: 'storage.cleanup.confirmBody', done: 'storage.cleanup.done' },
  attendance_media: { delete: 'storage.cleanup.media.delete', summary: 'storage.cleanup.media.summary',
    confirm: 'storage.cleanup.media.confirmBody', done: 'storage.cleanup.media.done' },
}

const EMPTY_FILTER: CleanupFilter = {
  date_from: '', date_to: '', camera_ids: [], types: [], employee_ids: [], all_employees: false, mode: 'events',
}

/** Hapus event behavior / media absensi / data absensi per rentang tanggal: pratinjau wajib, konfirmasi merah. */
export default function EventCleanupCard({ onDone }: { onDone: () => void }) {
  const { t, locale } = useT()
  const [cams, setCams] = useState<Camera[]>([])
  const [employees, setEmployees] = useState<Employee[]>([])
  const [filter, setFilter] = useState<CleanupFilter>(EMPTY_FILTER)
  const [preview, setPreview] = useState<{ key: string; result: CleanupResult } | null>(null)
  const [confirm, setConfirm] = useState(false)
  const [confirmWord, setConfirmWord] = useState('')
  const [done, setDone] = useState<CleanupResult | null>(null)
  const [error, setError] = useState<TKey | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    listCameras().then(setCams).catch(() => setCams([]))
    listEmployees().then(setEmployees).catch(() => setEmployees([]))
  }, [])

  const isData = filter.mode === 'attendance_data'
  // per mode: Jenis/kamera tidak berlaku (backend 422 bila dikirim) → kirim kosong
  const request: CleanupFilter = {
    ...filter,
    types: filter.mode === 'events' ? filter.types : [],
    camera_ids: isData ? [] : filter.camera_ids,
    employee_ids: isData && !filter.all_employees ? filter.employee_ids : [],
    all_employees: isData ? filter.all_employees : false,
  }
  const key = JSON.stringify(request) // mode/filter berubah → pratinjau basi
  const text = !isData ? TEXT[filter.mode as 'events' | 'attendance_media'] : null
  const datesValid = !!filter.date_from && !!filter.date_to && filter.date_from <= filter.date_to
  const employeeSelectionOk = !isData || (filter.employee_ids.length > 0) !== filter.all_employees
  const ready = datesValid && employeeSelectionOk
  const previewed = preview?.key === key ? preview.result : null // filter berubah → pratinjau basi
  const previewRows = previewed
    ? (isData ? (previewed.attendance_events ?? 0) + (previewed.days ?? 0) : previewed.events)
    : 0
  const summary = (r: CleanupResult) => isData
    ? t('storage.cleanup.data.summary')
      .replace('{att}', String(r.attendance_events ?? 0)).replace('{days}', String(r.days ?? 0))
      .replace('{events}', String(r.events)).replace('{files}', String(r.files))
      .replace('{size}', formatBytes(r.bytes, locale))
    : t(text!.summary).replace('{events}', String(r.events)).replace('{files}', String(r.files))
      .replace('{size}', formatBytes(r.bytes, locale))
  const deleteLabel = isData ? t('storage.cleanup.data.delete') : t(text!.delete).replace('{n}', String(previewed?.events ?? 0))
  const doneTitle = isData ? t('storage.cleanup.data.done') : t(text!.done)

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
        setConfirmWord('')
        onDone()
      }
    } catch (e) {
      setError((e as Error).message === 'invalid' ? 'storage.cleanup.invalid' : 'common.error')
      setConfirm(false)
    } finally {
      setBusy(false)
    }
  }

  const openConfirm = () => {
    setConfirmWord('')
    setConfirm(true)
  }

  return (
    <section className="st-card" data-testid="storage-cleanup">
      <h3 className="st-card__title">{t('storage.cleanup.title')}</h3>
      <p className="en-muted">{t('storage.cleanup.hint')}</p>
      <RadioButtonGroup legendText={t('storage.cleanup.mode')} name="cleanup-mode" valueSelected={filter.mode}
        onChange={(v) => setFilter((f) => ({ ...f, mode: v as CleanupMode }))}>
        <RadioButton id="cleanup-mode-events" value="events" labelText={t('storage.cleanup.mode.events')} />
        <RadioButton id="cleanup-mode-media" value="attendance_media" labelText={t('storage.cleanup.mode.media')} />
        <RadioButton id="cleanup-mode-data" value="attendance_data" labelText={t('storage.cleanup.mode.data')} />
      </RadioButtonGroup>
      <div className="st-card__grid">
        <TextInput id="cleanup-from" type="date" labelText={t('storage.cleanup.from')} max={isData ? yesterday() : today()}
          value={filter.date_from} onChange={(e) => setFilter({ ...filter, date_from: e.target.value })} />
        <TextInput id="cleanup-to" type="date" labelText={t('storage.cleanup.to')} max={isData ? yesterday() : today()}
          value={filter.date_to} onChange={(e) => setFilter({ ...filter, date_to: e.target.value })} />
        {!isData && (
          <MultiSelect<Camera> id="cleanup-cams" titleText={t('storage.cleanup.cameras')} label={t('storage.cleanup.all')}
            items={cams} itemToString={(c) => c?.name ?? ''}
            onChange={({ selectedItems }) => setFilter((f) => ({ ...f, camera_ids: (selectedItems ?? []).map((c) => c.id) }))} />
        )}
        {filter.mode === 'events' && (
          <MultiSelect<string> id="cleanup-types" titleText={t('storage.cleanup.types')} label={t('storage.cleanup.all')}
            items={[...TYPES]} itemToString={(k) => (k ? t(typeLabel(k)) : '')}
            onChange={({ selectedItems }) => setFilter((f) => ({ ...f, types: [...(selectedItems ?? [])] }))} />
        )}
        {isData && (
          <>
            <MultiSelect<Employee> id="cleanup-employees" key={String(filter.all_employees)}
              titleText={t('storage.cleanup.employees')} label={t('storage.cleanup.all')}
              items={employees} disabled={filter.all_employees}
              itemToString={(e) => (e ? `${e.name} (${e.employee_code})` : '')}
              onChange={({ selectedItems }) => setFilter((f) => ({ ...f, employee_ids: (selectedItems ?? []).map((e) => e.id) }))} />
            <Checkbox id="cleanup-all-employees" labelText={t('storage.cleanup.allEmployees')}
              checked={filter.all_employees}
              onChange={(_e, { checked }) => setFilter((f) => ({ ...f, all_employees: checked, employee_ids: checked ? [] : f.employee_ids }))} />
          </>
        )}
      </div>
      <div className="st-card__actions">
        <Button kind="secondary" size="sm" data-testid="cleanup-preview" disabled={!ready || busy} onClick={() => run(true)}>
          {t('storage.cleanup.preview')}
        </Button>
        <Button kind="danger" size="sm" data-testid="cleanup-delete" disabled={!previewed || previewRows === 0 || busy}
          onClick={openConfirm}>
          {deleteLabel}
        </Button>
      </div>
      {previewed && (
        <div data-testid="cleanup-preview-result">
          <p>{summary(previewed)}</p>
          {isData && previewed.employees && previewed.employees.length > 0 && (
            <TableContainer title="" style={{ overflowX: 'auto' }}>
              <Table size="sm">
                <TableHead>
                  <TableRow>
                    <TableHeader>{t('storage.cleanup.data.col.employee')}</TableHeader>
                    <TableHeader>{t('storage.cleanup.data.col.history')}</TableHeader>
                    <TableHeader>{t('storage.cleanup.data.col.days')}</TableHeader>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {previewed.employees.map((e) => (
                    <TableRow key={e.id}>
                      <TableCell>{e.name}</TableCell>
                      <TableCell>{e.attendance_events}</TableCell>
                      <TableCell>{e.days}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </div>
      )}
      {done && (
        <InlineNotification kind="success" lowContrast title={doneTitle} subtitle={summary(done)}
          onCloseButtonClick={() => setDone(null)} />
      )}
      {error && <InlineNotification kind="error" lowContrast title={t(error)} onCloseButtonClick={() => setError(null)} />}
      {confirm && previewed && !isData && (
        <Modal open danger size="sm" modalHeading={t('storage.cleanup.confirmTitle')}
          primaryButtonText={deleteLabel}
          secondaryButtonText={t('common.cancel')} primaryButtonDisabled={busy}
          onRequestClose={() => setConfirm(false)} onRequestSubmit={() => run(false)}>
          <p>
            {t(text!.confirm).replace('{n}', String(previewed.events))
              .replace('{from}', filter.date_from).replace('{to}', filter.date_to)}
          </p>
        </Modal>
      )}
      {confirm && previewed && isData && (
        <Modal open danger size="sm" modalHeading={t('storage.cleanup.confirmTitle')}
          primaryButtonText={deleteLabel}
          secondaryButtonText={t('common.cancel')} primaryButtonDisabled={busy || confirmWord !== CONFIRM_WORD}
          onRequestClose={() => { setConfirm(false); setConfirmWord('') }} onRequestSubmit={() => run(false)}>
          <p>{t('storage.cleanup.data.confirmBody').replace('{from}', filter.date_from).replace('{to}', filter.date_to)}</p>
          <TextInput id="cleanup-confirm-word" labelText={t('storage.cleanup.data.confirmType').replace('{word}', CONFIRM_WORD)}
            value={confirmWord} onChange={(e) => setConfirmWord(e.target.value)} />
        </Modal>
      )}
    </section>
  )
}
