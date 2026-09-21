import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Button,
  InlineLoading,
  InlineNotification,
  Modal,
  Select,
  SelectItem,
  TextInput,
} from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { getMe, type Me } from '../../api/client'
import {
  createEmployee,
  createShift,
  deletePhoto,
  enrollmentStatus,
  listEmployees,
  listPhotos,
  listShifts,
  purgeBiometrics,
  updateEmployee,
  uploadPhotosBatch,
  type BatchPhotoResult,
  type Employee,
  type EnrollmentStatus,
  type Photo,
  type Shift,
} from '../../api/employees'

function initials(name: string) {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')
}

const EMPTY_STATUS: EnrollmentStatus = { photos: 0, active: false }

export default function EnrollmentPage() {
  const { t } = useT()
  const [employees, setEmployees] = useState<Employee[]>([])
  const [shifts, setShifts] = useState<Shift[]>([])
  const [status, setStatus] = useState<Record<number, EnrollmentStatus>>({})
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [photos, setPhotos] = useState<Photo[]>([])
  const [me, setMe] = useState<Me | null>(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({ name: '', shiftId: '' })
  const [adding, setAdding] = useState(false)
  const [newEmp, setNewEmp] = useState({ name: '', employee_code: '', shift_id: '' })
  const [purging, setPurging] = useState(false)
  const [newShift, setNewShift] = useState({ name: '', start: '07:00', end: '16:00' })
  const [showAddShift, setShowAddShift] = useState(false)
  const [batchResults, setBatchResults] = useState<BatchPhotoResult[] | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const isAdmin = me?.role === 'admin'
  const selected = employees.find((e) => e.id === selectedId) ?? null

  const loadStatuses = useCallback(async (list: Employee[]) => {
    const entries = await Promise.all(
      list.map(async (e) => [e.id, await enrollmentStatus(e.id).catch(() => EMPTY_STATUS)] as const),
    )
    setStatus(Object.fromEntries(entries))
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [emps, shs] = await Promise.all([listEmployees(), listShifts()])
      setEmployees(emps)
      setShifts(shs)
      await loadStatuses(emps)
      if (selectedId == null && emps.length > 0) setSelectedId(emps[0].id)
    } catch {
      setError(t('en.loadError'))
    } finally {
      setLoading(false)
    }
    // ponytail: selectedId sengaja tidak di deps — hanya auto-select saat belum ada pilihan
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadStatuses, t])

  useEffect(() => {
    getMe().then(setMe).catch(() => setMe(null))
    refresh()
  }, [refresh])

  useEffect(() => {
    if (selectedId == null) {
      setPhotos([])
      return
    }
    listPhotos(selectedId)
      .then(setPhotos)
      .catch(() => setPhotos([]))
  }, [selectedId])

  useEffect(() => {
    if (selected) setForm({ name: selected.name, shiftId: selected.shift_id != null ? String(selected.shift_id) : '' })
  }, [selected])

  const reloadPhotos = async () => {
    if (selectedId == null) return
    setPhotos(await listPhotos(selectedId).catch(() => []))
    await loadStatuses(employees)
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
    if (selectedId == null) return
    try {
      await purgeBiometrics(selectedId)
      setPurging(false)
      await reloadPhotos()
    } catch {
      setError(t('en.saveError'))
      setPurging(false)
    }
  }

  const saveEmployee = async () => {
    if (!selected) return
    try {
      await updateEmployee(selected.id, { name: form.name, shift_id: form.shiftId ? Number(form.shiftId) : null })
      await refresh()
    } catch {
      setError(t('en.saveError'))
    }
  }

  const toggleActive = async () => {
    if (!selected) return
    try {
      await updateEmployee(selected.id, { active: !selected.active })
      await refresh()
    } catch {
      setError(t('en.saveError'))
    }
  }

  const addEmployee = async () => {
    try {
      const created = await createEmployee({
        name: newEmp.name,
        employee_code: newEmp.employee_code,
        shift_id: newEmp.shift_id ? Number(newEmp.shift_id) : null,
      })
      setAdding(false)
      setNewEmp({ name: '', employee_code: '', shift_id: '' })
      setSelectedId(created.id)
      await refresh()
    } catch {
      setError(t('en.createError'))
    }
  }

  const addShift = async () => {
    try {
      await createShift({ name: newShift.name, start_time: newShift.start, end_time: newShift.end })
      setNewShift({ name: '', start: '07:00', end: '16:00' })
      setShowAddShift(false)
      await refresh()
    } catch {
      setError(t('en.saveError'))
    }
  }

  const filtered = employees.filter((e) => {
    const q = query.trim().toLowerCase()
    return !q || e.name.toLowerCase().includes(q) || e.employee_code.toLowerCase().includes(q)
  })

  const st = (id: number) => status[id] ?? EMPTY_STATUS

  return (
    <div className="app-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('en.title')}</h1>
          <p className="app-page__sub">{t('en.sub')}</p>
        </div>
        {isAdmin && (
          <Button data-testid="en-add" onClick={() => setAdding(true)}>
            {t('en.add')}
          </Button>
        )}
      </div>

      {error && <InlineNotification kind="error" lowContrast title={t('common.error')} subtitle={error} onCloseButtonClick={() => setError(null)} />}

      <div style={{ width: 260, marginBottom: 14 }}>
        <TextInput id="en-search" labelText={t('en.search')} value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>

      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.2fr) minmax(320px, 1fr)', gap: 0, border: '1px solid #393939' }}>
          <div style={{ borderRight: '1px solid #393939', minWidth: 0 }}>
            {filtered.map((e) => {
              const s = st(e.id)
              return (
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
                  <div style={{ padding: '10px 14px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
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
                            background: s.active ? '#42be65' : '#6f6f6f',
                            border: '2px solid #161616',
                          }}
                        />
                      </div>
                      {e.name}
                    </div>
                  </div>
                  <div style={{ padding: '10px 14px', fontFamily: 'monospace', fontSize: 11, color: '#8d8d8d' }}>{e.employee_code}</div>
                  <div style={{ padding: '10px 14px' }}>{e.shift_name ?? '—'}</div>
                  <div style={{ padding: '10px 14px' }}>
                    <span
                      data-testid={`en-face-${e.id}`}
                      style={{
                        fontSize: 11,
                        padding: '2px 8px',
                        border: `1px solid ${s.active ? '#42be65' : '#f1c21b'}`,
                        color: s.active ? '#42be65' : '#f1c21b',
                        display: 'inline-block',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {s.active ? t('en.face.count').replace('{n}', String(s.photos)) : t('en.face.none')}
                    </span>
                  </div>
                </div>
              )
            })}
            {filtered.length === 0 && <div style={{ padding: 16, color: '#8d8d8d' }}>{t('en.empty')}</div>}
          </div>

          <div style={{ padding: 16, minWidth: 0 }}>
            {!selected ? (
              <p style={{ color: '#8d8d8d' }}>{t('en.selectHint')}</p>
            ) : (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
                  <div style={{ width: 40, height: 40, background: '#333', color: '#c6c6c6', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 600 }}>
                    {initials(selected.name)}
                  </div>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 600 }}>{selected.name}</div>
                    <div style={{ fontSize: 12, color: '#8d8d8d', fontFamily: 'monospace' }}>
                      {selected.employee_code} · {selected.active ? t('en.active') : t('en.inactive')} · {selected.shift_name ?? '—'}
                    </div>
                  </div>
                </div>

                <div style={{ border: '1px solid #393939', background: '#262626', padding: 14, marginBottom: 12 }}>
                  <h4 style={{ fontSize: 12, color: '#8d8d8d', letterSpacing: '.32px', fontWeight: 400, margin: '0 0 10px' }}>
                    {t('en.faceTitle').replace('{n}', String(photos.length))}
                  </h4>
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
                  <Button kind="tertiary" size="sm" style={{ marginTop: 10 }} disabled={!isAdmin} onClick={() => { setBatchResults(null); fileRef.current?.click() }}>
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
                </div>

                <div style={{ border: '1px solid #393939', background: '#262626', padding: 14, marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <TextInput id="en-name" labelText={t('en.name')} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                  <TextInput id="en-code" labelText={t('en.code')} value={selected.employee_code} readOnly disabled />
                  <Select id="en-shift" labelText={t('en.shift.select')} value={form.shiftId} onChange={(e) => setForm({ ...form, shiftId: e.target.value })}>
                    <SelectItem value="" text="—" />
                    {shifts.map((s) => (
                      <SelectItem key={s.id} value={String(s.id)} text={`${s.name} · ${s.start_time}–${s.end_time}`} />
                    ))}
                  </Select>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <Button kind="primary" size="sm" data-testid="en-save" disabled={!isAdmin} onClick={saveEmployee}>
                      {t('en.save')}
                    </Button>
                    <Button kind="ghost" size="sm" disabled={!isAdmin} onClick={toggleActive}>
                      {selected.active ? t('en.deactivate') : t('en.activate')}
                    </Button>
                  </div>
                </div>

                <div style={{ border: '1px solid #393939', background: '#262626', padding: 14, marginBottom: 12 }}>
                  <h4 style={{ fontSize: 12, color: '#8d8d8d', letterSpacing: '.32px', fontWeight: 400, margin: '0 0 10px' }}>{t('en.shift')}</h4>
                  {shifts.map((s) => (
                    <div key={s.id} data-testid={`en-shift-row-${s.id}`} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '6px 0', borderBottom: '1px solid #2d2d2d' }}>
                      <span>{s.name}</span>
                      <span style={{ fontFamily: 'monospace', color: '#c6c6c6' }}>
                        {s.start_time} – {s.end_time}
                      </span>
                    </div>
                  ))}
                  {showAddShift ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 10 }}>
                      <TextInput id="en-shift-name" labelText={t('en.shift.name')} value={newShift.name} onChange={(e) => setNewShift({ ...newShift, name: e.target.value })} />
                      <div style={{ display: 'flex', gap: 8 }}>
                        <TextInput id="en-shift-start" labelText={t('en.shift.start')} value={newShift.start} onChange={(e) => setNewShift({ ...newShift, start: e.target.value })} />
                        <TextInput id="en-shift-end" labelText={t('en.shift.end')} value={newShift.end} onChange={(e) => setNewShift({ ...newShift, end: e.target.value })} />
                      </div>
                      <Button kind="primary" size="sm" data-testid="en-shift-add-save" disabled={!isAdmin} onClick={addShift}>
                        {t('en.save')}
                      </Button>
                    </div>
                  ) : (
                    isAdmin && (
                      <Button kind="ghost" size="sm" style={{ marginTop: 8 }} data-testid="en-shift-add" onClick={() => setShowAddShift(true)}>
                        {t('en.shift.add')}
                      </Button>
                    )
                  )}
                </div>

                {isAdmin && (
                  <Button kind="danger--tertiary" size="sm" data-testid="en-purge" onClick={() => setPurging(true)}>
                    {t('en.purge')}
                  </Button>
                )}
              </>
            )}
          </div>
        </div>
      )}

      <Modal
        open={adding}
        modalHeading={t('en.addTitle')}
        primaryButtonText={t('common.save')}
        secondaryButtonText={t('common.cancel')}
        onRequestClose={() => setAdding(false)}
        onRequestSubmit={addEmployee}
        size="sm"
      >
        <TextInput id="new-name" labelText={t('en.name')} value={newEmp.name} onChange={(e) => setNewEmp({ ...newEmp, name: e.target.value })} />
        <TextInput id="new-code" labelText={t('en.code')} value={newEmp.employee_code} onChange={(e) => setNewEmp({ ...newEmp, employee_code: e.target.value })} />
        <Select id="new-shift" labelText={t('en.shift.select')} value={newEmp.shift_id} onChange={(e) => setNewEmp({ ...newEmp, shift_id: e.target.value })}>
          <SelectItem value="" text="—" />
          {shifts.map((s) => (
            <SelectItem key={s.id} value={String(s.id)} text={`${s.name} · ${s.start_time}–${s.end_time}`} />
          ))}
        </Select>
      </Modal>

      <Modal
        open={purging}
        modalHeading={t('en.purgeConfirmTitle')}
        primaryButtonText={t('en.purge')}
        secondaryButtonText={t('common.cancel')}
        onRequestClose={() => setPurging(false)}
        onRequestSubmit={doPurge}
        danger
        size="sm"
      >
        <p>
          {t('en.purgeConfirmBody')
            .replace('{n}', String(selected ? st(selected.id).photos : 0))
            .replace('{name}', selected?.name ?? '')}
        </p>
      </Modal>
    </div>
  )
}
