import { useCallback, useEffect, useState } from 'react'
import {
  Button,
  Checkbox,
  InlineLoading,
  InlineNotification,
  Modal,
  NumberInput,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TextInput,
} from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { createShift, deleteShift, listShifts, updateShift, type Shift, type ShiftPayload } from '../../api/employees'

type ShiftForm = Required<ShiftPayload>

const DAYS = [1, 2, 3, 4, 5, 6, 7] as const
const EMPTY: ShiftForm = { name: '', start_time: '07:00', end_time: '16:00', tolerance_min: 15, workdays: [1, 2, 3, 4, 5] }
const HEADERS = ['sh.col.name', 'sh.col.time', 'sh.col.tolerance', 'sh.col.workdays'] as const

// ponytail: "HH:MM" sebanding leksikografis; shift lintas tengah malam sengaja ditolak (spec §2)
function formProblem(f: ShiftForm): TKey | null {
  if (!f.name.trim()) return 'sh.err.name'
  if (!f.start_time || !f.end_time || f.end_time <= f.start_time) return 'sh.err.endAfterStart'
  if (f.workdays.length === 0) return 'sh.err.workdays'
  return null
}

export default function ShiftsTab({ isAdmin }: { isAdmin: boolean }) {
  const { t } = useT()
  const [shifts, setShifts] = useState<Shift[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<Shift | 'new' | null>(null)
  const [form, setForm] = useState<ShiftForm>(EMPTY)
  const [serverError, setServerError] = useState<TKey | null>(null)
  const [deleting, setDeleting] = useState<Shift | null>(null)
  const [deleteError, setDeleteError] = useState<TKey | null>(null)

  const refresh = useCallback(async () => {
    try {
      setShifts(await listShifts())
    } catch {
      setError(t('sh.loadError'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- refresh async: semua setState terjadi setelah await, bukan sinkron di effect
    refresh()
  }, [refresh])

  const openForm = (s: Shift | 'new') => {
    setEditing(s)
    setForm(s === 'new' ? EMPTY : { name: s.name, start_time: s.start_time, end_time: s.end_time, tolerance_min: s.tolerance_min, workdays: s.workdays })
    setServerError(null)
  }

  const save = async () => {
    const payload = { ...form, name: form.name.trim() }
    try {
      if (editing === 'new') await createShift(payload)
      else if (editing) await updateShift(editing.id, payload)
      setEditing(null)
      await refresh()
    } catch (e) {
      const code = (e as Error).message
      setServerError(code === 'duplicate' ? 'sh.err.duplicate' : code === 'invalid' ? 'sh.err.invalid' : 'en.saveError')
    }
  }

  const remove = async () => {
    if (!deleting) return
    try {
      await deleteShift(deleting.id)
      setDeleting(null)
      await refresh()
    } catch (e) {
      setDeleteError((e as Error).message === 'in_use' ? 'sh.err.inUse' : 'en.saveError')
    }
  }

  const toggleDay = (d: number, on: boolean) =>
    setForm((f) => ({ ...f, workdays: on ? [...f.workdays, d].sort((a, b) => a - b) : f.workdays.filter((x) => x !== d) }))

  const dayNames = (ws: number[]) => ws.map((d) => t(`sh.day.${d}` as TKey)).join(', ')
  const problem = formProblem(form)

  return (
    <div>
      {error && <InlineNotification kind="error" lowContrast title={t('common.error')} subtitle={error} onCloseButtonClick={() => setError(null)} />}
      {isAdmin && (
        <div className="en-toolbar">
          <Button size="sm" data-testid="sh-add" onClick={() => openForm('new')}>
            {t('sh.add')}
          </Button>
        </div>
      )}

      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : shifts.length === 0 ? (
        <p className="en-muted">{t('sh.empty')}</p>
      ) : (
        <div className="en-table-scroll">
          <TableContainer>
            <Table size="sm">
              <TableHead>
                <TableRow>
                  {HEADERS.map((h) => (
                    <TableHeader key={h}>{t(h)}</TableHeader>
                  ))}
                  {isAdmin && <TableHeader>{t('sh.col.actions')}</TableHeader>}
                </TableRow>
              </TableHead>
              <TableBody>
                {shifts.map((s) => (
                  <TableRow key={s.id} data-testid={`sh-row-${s.id}`}>
                    <TableCell>{s.name}</TableCell>
                    <TableCell>
                      {s.start_time}–{s.end_time}
                    </TableCell>
                    <TableCell>{t('sh.minutes').replace('{n}', String(s.tolerance_min))}</TableCell>
                    <TableCell>{dayNames(s.workdays)}</TableCell>
                    {isAdmin && (
                      <TableCell>
                        <Button kind="ghost" size="sm" data-testid={`sh-edit-${s.id}`} onClick={() => openForm(s)}>
                          {t('sh.edit')}
                        </Button>
                        <Button
                          kind="danger--ghost"
                          size="sm"
                          data-testid={`sh-delete-${s.id}`}
                          onClick={() => {
                            setDeleting(s)
                            setDeleteError(null)
                          }}
                        >
                          {t('sh.delete')}
                        </Button>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </div>
      )}

      {editing !== null && (
        <Modal
          open
          modalHeading={t(editing === 'new' ? 'sh.addTitle' : 'sh.editTitle')}
          primaryButtonText={t('common.save')}
          secondaryButtonText={t('common.cancel')}
          primaryButtonDisabled={problem !== null}
          onRequestClose={() => setEditing(null)}
          onRequestSubmit={save}
          size="sm"
        >
          <div className="en-form">
            <TextInput id="sh-name" labelText={t('sh.name')} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <div className="en-form__row">
              <TextInput id="sh-start" type="time" labelText={t('sh.start')} value={form.start_time} onChange={(e) => setForm({ ...form, start_time: e.target.value })} />
              <TextInput id="sh-end" type="time" labelText={t('sh.end')} value={form.end_time} onChange={(e) => setForm({ ...form, end_time: e.target.value })} />
            </div>
            <NumberInput
              id="sh-tolerance"
              label={t('sh.tolerance')}
              min={0}
              max={120}
              step={1}
              value={form.tolerance_min}
              onChange={(_, state) => {
                const n = Number(state.value)
                if (Number.isInteger(n) && n >= 0 && n <= 120) setForm((f) => ({ ...f, tolerance_min: n }))
              }}
            />
            <fieldset className="en-days">
              <legend className="cds--label">{t('sh.workdays')}</legend>
              {DAYS.map((d) => (
                <Checkbox
                  key={d}
                  id={`sh-day-${d}`}
                  labelText={t(`sh.day.${d}` as TKey)}
                  checked={form.workdays.includes(d)}
                  onChange={(_, { checked }) => toggleDay(d, checked)}
                />
              ))}
            </fieldset>
            {problem && (
              <p className="en-form__hint" data-testid="sh-form-problem">
                {t(problem)}
              </p>
            )}
            {serverError && <InlineNotification kind="error" lowContrast hideCloseButton title={t(serverError)} />}
          </div>
        </Modal>
      )}

      {deleting && (
        <Modal
          open
          danger
          modalHeading={t('sh.deleteTitle')}
          primaryButtonText={t('sh.delete')}
          secondaryButtonText={t('common.cancel')}
          onRequestClose={() => setDeleting(null)}
          onRequestSubmit={remove}
          size="sm"
        >
          <p>{t('sh.deleteBody').replace('{name}', deleting.name)}</p>
          {deleteError && <InlineNotification kind="error" lowContrast hideCloseButton title={t(deleteError)} />}
        </Modal>
      )}
    </div>
  )
}
