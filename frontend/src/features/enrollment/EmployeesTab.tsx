import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, InlineLoading, InlineNotification, Modal, Select, SelectItem, Tag, TextInput } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import {
  createEmployee,
  deleteEmployee,
  deletePhoto,
  listEmployees,
  listPhotos,
  listShifts,
  purgeBiometrics,
  updateEmployee,
  uploadPhotosBatch,
  type BatchPhotoResult,
  type Employee,
  type Photo,
  type Shift,
} from '../../api/employees'

type StatusFilter = 'active' | 'inactive' | 'all'
type EmpForm = { name: string; code: string; shiftId: string }

const EMPTY_FORM: EmpForm = { name: '', code: '', shiftId: '' }

function initials(name: string) {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')
}

const shiftLabel = (s: Shift) => `${s.name} · ${s.start_time}–${s.end_time}`
const shiftIdOf = (f: EmpForm) => (f.shiftId ? Number(f.shiftId) : null)
const isBlank = (f: EmpForm) => !f.name.trim() || !f.code.trim()

export default function EmployeesTab({ isAdmin }: { isAdmin: boolean }) {
  const { t } = useT()
  const [employees, setEmployees] = useState<Employee[]>([])
  const [shifts, setShifts] = useState<Shift[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [photos, setPhotos] = useState<Photo[]>([])
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('active')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState<EmpForm>(EMPTY_FORM)
  const [codeTaken, setCodeTaken] = useState(false)
  const [adding, setAdding] = useState(false)
  const [newEmp, setNewEmp] = useState<EmpForm>(EMPTY_FORM)
  const [newCodeTaken, setNewCodeTaken] = useState(false)
  const [purging, setPurging] = useState(false)
  const [deactivating, setDeactivating] = useState(false)
  const [deleting, setDeleting] = useState<'confirm' | 'blocked' | null>(null)
  const [batchResults, setBatchResults] = useState<BatchPhotoResult[] | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const selected = employees.find((e) => e.id === selectedId) ?? null

  const refresh = useCallback(async () => {
    try {
      const [emps, shs] = await Promise.all([listEmployees(), listShifts()])
      setEmployees(emps)
      setShifts(shs)
      // pertahankan pilihan; pilih karyawan aktif pertama hanya bila belum ada
      setSelectedId((cur) => cur ?? emps.find((e) => e.active)?.id ?? emps[0]?.id ?? null)
    } catch {
      setError(t('en.loadError'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- refresh async: semua setState terjadi setelah await, bukan sinkron di effect
    refresh()
  }, [refresh])

  useEffect(() => {
    if (selectedId == null) {
      // oxlint-disable-next-line react/set-state-in-effect -- reset daftar foto saat tidak ada karyawan terpilih (sinkronisasi, bukan cascade)
      setPhotos([])
      return
    }
    listPhotos(selectedId)
      .then(setPhotos)
      .catch(() => setPhotos([]))
  }, [selectedId])

  // deps primitif: refresh() membuat objek karyawan baru, tapi form hanya di-reset bila pilihan atau data
  // tersimpan berubah — suntingan yang belum disimpan tidak hilang saat upload/hapus foto
  const selName = selected?.name
  const selCode = selected?.employee_code
  const selShift = selected?.shift_id
  useEffect(() => {
    if (selName == null || selCode == null) return
    // oxlint-disable-next-line react/set-state-in-effect -- isi form dari karyawan terpilih (sinkronisasi form dengan selection)
    setForm({ name: selName, code: selCode, shiftId: selShift != null ? String(selShift) : '' })
    setCodeTaken(false)
  }, [selName, selCode, selShift])

  const reloadPhotos = async () => {
    if (selectedId == null) return
    setPhotos(await listPhotos(selectedId).catch(() => []))
    await refresh()
  }

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    e.target.value = ''
    if (files.length === 0 || selectedId == null) return
    setError(null)
    try {
      const { results } = await uploadPhotosBatch(selectedId, files)
      setBatchResults(results)
      await reloadPhotos()
    } catch {
      setError(t('en.uploadError'))
    }
  }

  const onDeletePhoto = async (p: Photo) => {
    if (selectedId == null) return
    try {
      await deletePhoto(selectedId, p.id)
      await reloadPhotos()
    } catch {
      setError(t('en.saveError'))
    }
  }

  const doPurge = async () => {
    if (!selected) return
    try {
      await purgeBiometrics(selected.id)
    } catch {
      setError(t('en.saveError'))
    }
    setPurging(false)
    await reloadPhotos()
  }

  const saveEmployee = async () => {
    if (!selected) return
    setCodeTaken(false)
    try {
      await updateEmployee(selected.id, { name: form.name.trim(), employee_code: form.code.trim(), shift_id: shiftIdOf(form) })
      await refresh()
    } catch (e) {
      if ((e as Error).message === 'duplicate') setCodeTaken(true)
      else setError(t('en.saveError'))
    }
  }

  const setActive = async (active: boolean) => {
    if (!selected) return
    setDeactivating(false)
    setDeleting(null)
    try {
      await updateEmployee(selected.id, { active })
      await refresh()
    } catch {
      setError(t('en.saveError'))
    }
  }

  const doDelete = async () => {
    if (!selected) return
    try {
      await deleteEmployee(selected.id)
      setDeleting(null)
      setSelectedId(null)
      await refresh()
    } catch (e) {
      if ((e as Error).message === 'has_attendance') {
        setDeleting('blocked')
      } else {
        setDeleting(null)
        setError(t('en.saveError'))
      }
    }
  }

  const addEmployee = async () => {
    setNewCodeTaken(false)
    try {
      const created = await createEmployee({ name: newEmp.name.trim(), employee_code: newEmp.code.trim(), shift_id: shiftIdOf(newEmp) })
      setAdding(false)
      setNewEmp(EMPTY_FORM)
      setStatusFilter((f) => (f === 'inactive' ? 'active' : f))
      setSelectedId(created.id)
      await refresh()
    } catch (e) {
      if ((e as Error).message === 'duplicate') setNewCodeTaken(true)
      else setError(t('en.createError'))
    }
  }

  const q = query.trim().toLowerCase()
  const filtered = employees.filter(
    (e) =>
      (statusFilter === 'all' || e.active === (statusFilter === 'active')) &&
      (!q || e.name.toLowerCase().includes(q) || e.employee_code.toLowerCase().includes(q)),
  )

  const shiftOptions = (
    <>
      <SelectItem value="" text="—" />
      {shifts.map((s) => (
        <SelectItem key={s.id} value={String(s.id)} text={shiftLabel(s)} />
      ))}
    </>
  )

  return (
    <div>
      {error && <InlineNotification kind="error" lowContrast title={t('common.error')} subtitle={error} onCloseButtonClick={() => setError(null)} />}

      <div className="en-toolbar">
        <TextInput id="en-search" labelText={t('en.search')} value={query} onChange={(e) => setQuery(e.target.value)} />
        <Select id="en-status-filter" labelText={t('en.filter.status')} value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}>
          <SelectItem value="active" text={t('en.filter.active')} />
          <SelectItem value="inactive" text={t('en.filter.inactive')} />
          <SelectItem value="all" text={t('en.filter.all')} />
        </Select>
        {isAdmin && (
          <Button
            data-testid="en-add"
            onClick={() => {
              setNewEmp(EMPTY_FORM)
              setNewCodeTaken(false)
              setAdding(true)
            }}
          >
            {t('en.add')}
          </Button>
        )}
      </div>

      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : (
        <div className="en-layout">
          <div className="en-list">
            {filtered.map((e) => (
              <div
                key={e.id}
                data-testid={`en-row-${e.id}`}
                onClick={() => setSelectedId(e.id)}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '2fr 1fr 1fr 1fr',
                  alignItems: 'center',
                  fontSize: 13,
                  borderBottom: '1px solid #2d2d2d',
                  background: e.id === selectedId ? '#262626' : 'transparent',
                  borderLeft: e.id === selectedId ? '3px solid #4589ff' : '3px solid transparent',
                  cursor: 'pointer',
                }}
              >
                <div style={{ padding: '10px 14px', minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <div style={{ position: 'relative', width: 28, height: 28, background: '#333', color: '#c6c6c6', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 600, flexShrink: 0 }}>
                      {initials(e.name)}
                      <span
                        data-testid={`en-dot-${e.id}`}
                        style={{
                          position: 'absolute',
                          right: -2,
                          bottom: -2,
                          width: 9,
                          height: 9,
                          borderRadius: 9999,
                          background: e.face_ready ? '#42be65' : '#6f6f6f',
                          border: '2px solid #161616',
                        }}
                      />
                    </div>
                    {e.name}
                    {!e.active && (
                      <Tag type="gray" size="sm" data-testid={`en-inactive-${e.id}`}>
                        {t('en.inactive')}
                      </Tag>
                    )}
                  </div>
                </div>
                <div style={{ padding: '10px 14px', fontFamily: 'monospace', fontSize: 11, color: '#8d8d8d', overflowWrap: 'anywhere' }}>{e.employee_code}</div>
                <div style={{ padding: '10px 14px' }}>{e.shift_name ?? '—'}</div>
                <div style={{ padding: '10px 14px' }}>
                  <span
                    data-testid={`en-face-${e.id}`}
                    style={{
                      fontSize: 11,
                      padding: '2px 8px',
                      border: `1px solid ${e.face_ready ? '#42be65' : '#f1c21b'}`,
                      color: e.face_ready ? '#42be65' : '#f1c21b',
                      display: 'inline-block',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {e.face_ready ? t('en.face.count').replace('{n}', String(e.photo_count)) : t('en.face.none')}
                  </span>
                </div>
              </div>
            ))}
            {filtered.length === 0 && <div style={{ padding: 16 }} className="en-muted">{t('en.empty')}</div>}
          </div>

          <div className="en-detail">
            {!selected ? (
              <p className="en-muted">{t('en.selectHint')}</p>
            ) : (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
                  <div style={{ width: 40, height: 40, background: '#333', color: '#c6c6c6', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 600, flexShrink: 0 }}>
                    {initials(selected.name)}
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 16, fontWeight: 600 }}>{selected.name}</div>
                    <div style={{ fontSize: 12, color: '#8d8d8d', fontFamily: 'monospace' }}>
                      {selected.employee_code} · {selected.active ? t('en.active') : t('en.inactive')} · {selected.shift_name ?? '—'}
                    </div>
                  </div>
                </div>

                <section className="en-card" data-testid="en-card-identity">
                  <h4 className="en-card__title">{t('en.card.identity')}</h4>
                  <div className="en-form">
                    <TextInput
                      id="en-name"
                      labelText={t('en.name')}
                      value={form.name}
                      disabled={!isAdmin}
                      invalid={!form.name.trim()}
                      invalidText={t('en.err.required')}
                      onChange={(e) => setForm({ ...form, name: e.target.value })}
                    />
                    <TextInput
                      id="en-code"
                      labelText={t('en.code')}
                      value={form.code}
                      disabled={!isAdmin}
                      invalid={!form.code.trim() || codeTaken}
                      invalidText={codeTaken ? t('en.err.codeDup') : t('en.err.required')}
                      onChange={(e) => {
                        setForm({ ...form, code: e.target.value })
                        setCodeTaken(false)
                      }}
                    />
                    <Select id="en-shift" labelText={t('en.shift.select')} value={form.shiftId} disabled={!isAdmin} onChange={(e) => setForm({ ...form, shiftId: e.target.value })}>
                      {shiftOptions}
                    </Select>
                    <div>
                      <Button kind="primary" size="sm" data-testid="en-save" disabled={!isAdmin || isBlank(form)} onClick={saveEmployee}>
                        {t('en.save')}
                      </Button>
                    </div>
                  </div>
                </section>

                <section className="en-card" data-testid="en-card-face">
                  <h4 className="en-card__title">{t('en.faceTitle').replace('{n}', String(photos.length))}</h4>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6 }}>
                    {photos.map((p) => (
                      <div key={p.id} data-testid={`en-photo-${p.id}`} style={{ position: 'relative', aspectRatio: '3/4', background: '#0d1117', border: '1px solid #393939' }}>
                        {p.path && <img src={`/api/v1/media/${p.path}`} alt={selected.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />}
                        <span style={{ position: 'absolute', bottom: 0, left: 0, right: 0, fontSize: 9, color: '#8d8d8d', textAlign: 'center', padding: 2, background: 'rgba(0,0,0,.6)' }}>
                          {p.quality != null ? `${Math.round(p.quality * 100)}%` : '—'}
                        </span>
                        {isAdmin && (
                          <button
                            type="button"
                            title={t('en.photoDelete')}
                            data-testid={`en-photo-del-${p.id}`}
                            onClick={() => onDeletePhoto(p)}
                            style={{ position: 'absolute', top: 2, right: 2, background: 'rgba(0,0,0,.6)', color: '#fa4d56', border: '1px solid #fa4d56', cursor: 'pointer', fontSize: 10, lineHeight: '14px', padding: '0 4px' }}
                          >
                            ×
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                  <input ref={fileRef} type="file" accept="image/*" multiple data-testid="en-upload-input" style={{ display: 'none' }} onChange={onUpload} />
                  <Button
                    kind="tertiary"
                    size="sm"
                    style={{ marginTop: 10 }}
                    disabled={!isAdmin}
                    onClick={() => {
                      setBatchResults(null)
                      fileRef.current?.click()
                    }}
                  >
                    {t('en.upload')}
                  </Button>
                  {batchResults && (
                    <ul data-testid="en-batch-results" style={{ margin: '8px 0 0', padding: 0, listStyle: 'none', fontSize: 12 }}>
                      {batchResults.map((r, i) => (
                        <li key={i} style={{ color: r.ok ? '#42be65' : '#fa4d56' }}>
                          {r.ok
                            ? `${t('en.batch.ok')} — ${t('en.face.quality')}: ${(r.quality ?? 0).toFixed(2)}${r.duplicate_of ? ` — ⚠ ${t('en.dup.warn')} #${r.duplicate_of.employee_id} (${r.duplicate_of.score})` : ''}`
                            : `${t(`en.batch.${r.reason === 'max_photos' ? 'max' : r.reason === 'too_large' ? 'tooLarge' : r.reason}` as TKey)}`}
                        </li>
                      ))}
                    </ul>
                  )}
                  {isAdmin && (
                    <div className="en-card__danger">
                      <Button kind="danger--ghost" size="sm" data-testid="en-purge" disabled={selected.photo_count === 0} onClick={() => setPurging(true)}>
                        {t('en.purge').replace('{name}', selected.name)}
                      </Button>
                    </div>
                  )}
                </section>

                {isAdmin && (
                  <section className="en-card" data-testid="en-card-status">
                    <h4 className="en-card__title">{t('en.card.status')}</h4>
                    <div className="en-actions">
                      <Button kind="tertiary" size="sm" data-testid="en-toggle-active" onClick={() => (selected.active ? setDeactivating(true) : setActive(true))}>
                        {selected.active ? t('en.deactivate') : t('en.activate')}
                      </Button>
                      <Button kind="danger--tertiary" size="sm" data-testid="en-delete" onClick={() => setDeleting('confirm')}>
                        {t('en.delete')}
                      </Button>
                    </div>
                  </section>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {adding && (
        <Modal
          open
          modalHeading={t('en.addTitle')}
          primaryButtonText={t('common.save')}
          secondaryButtonText={t('common.cancel')}
          primaryButtonDisabled={isBlank(newEmp)}
          onRequestClose={() => setAdding(false)}
          onRequestSubmit={addEmployee}
          size="sm"
        >
          <div className="en-form">
            <TextInput id="new-name" labelText={t('en.name')} value={newEmp.name} onChange={(e) => setNewEmp({ ...newEmp, name: e.target.value })} />
            <TextInput
              id="new-code"
              labelText={t('en.code')}
              value={newEmp.code}
              invalid={newCodeTaken}
              invalidText={t('en.err.codeDup')}
              onChange={(e) => {
                setNewEmp({ ...newEmp, code: e.target.value })
                setNewCodeTaken(false)
              }}
            />
            <Select id="new-shift" labelText={t('en.shift.select')} value={newEmp.shiftId} onChange={(e) => setNewEmp({ ...newEmp, shiftId: e.target.value })}>
              {shiftOptions}
            </Select>
          </div>
        </Modal>
      )}

      {purging && selected && (
        <Modal
          open
          danger
          modalHeading={t('en.purgeConfirmTitle')}
          primaryButtonText={t('en.purgeConfirm')}
          secondaryButtonText={t('common.cancel')}
          onRequestClose={() => setPurging(false)}
          onRequestSubmit={doPurge}
          size="sm"
        >
          <p>{t('en.purgeConfirmBody').replace('{n}', String(selected.photo_count)).replace('{name}', selected.name)}</p>
        </Modal>
      )}

      {deactivating && selected && (
        <Modal
          open
          modalHeading={t('en.deactivateTitle')}
          primaryButtonText={t('en.deactivate')}
          secondaryButtonText={t('common.cancel')}
          onRequestClose={() => setDeactivating(false)}
          onRequestSubmit={() => setActive(false)}
          size="sm"
        >
          <p>{t('en.deactivateBody').replace('{name}', selected.name)}</p>
        </Modal>
      )}

      {deleting && selected && (
        <Modal
          open
          danger={deleting === 'confirm'}
          passiveModal={deleting === 'blocked' && !selected.active}
          modalHeading={t('en.deleteTitle')}
          primaryButtonText={deleting === 'confirm' ? t('en.delete') : t('en.deactivate')}
          secondaryButtonText={t('common.cancel')}
          onRequestClose={() => setDeleting(null)}
          onRequestSubmit={deleting === 'confirm' ? doDelete : () => setActive(false)}
          size="sm"
        >
          <p>
            {deleting === 'confirm'
              ? t('en.deleteBody').replace('{name}', selected.name).replace('{n}', String(selected.photo_count))
              : t(selected.active ? 'en.deleteBlocked' : 'en.deleteBlockedInactive').replace('{name}', selected.name)}
          </p>
        </Modal>
      )}
    </div>
  )
}
