import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Button,
  InlineLoading,
  InlineNotification,
  Modal,
  Select,
  SelectItem,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TextArea,
  TextInput,
} from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { getMe, type Me } from '../../api/client'
import { listEmployees, type Employee } from '../../api/employees'
import {
  attendanceExportUrl,
  attendanceImport,
  attendanceList,
  attendancePatch,
  type AttendancePatchBody,
  type AttendanceRow,
  type AttendanceStatus,
} from '../../api/attendance'

const STATUSES: AttendanceStatus[] = ['ontime', 'late', 'waiting', 'no_exit', 'absent']
const STATUS_COLOR: Record<AttendanceStatus, string> = {
  ontime: '#42be65',
  late: '#f1c21b',
  waiting: '#8d8d8d',
  no_exit: '#ff832b',
  absent: '#fa4d56',
}

function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function initials(name: string | null) {
  if (!name) return '?'
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')
}

function StatusBadge({ status, label }: { status: AttendanceStatus; label: string }) {
  const color = STATUS_COLOR[status]
  return (
    <span
      data-testid={`status-${status}`}
      style={{ fontSize: 11, padding: '2px 8px', border: `1px solid ${color}`, color, display: 'inline-block', whiteSpace: 'nowrap' }}
    >
      {label}
    </span>
  )
}

function Tile({ label, value, sub, color, testId }: { label: string; value: string; sub?: string; color?: string; testId: string }) {
  return (
    <div style={{ background: '#262626', border: '1px solid #393939', padding: '14px 16px' }}>
      <div style={{ fontSize: 11, color: '#8d8d8d', letterSpacing: '.32px' }}>{label}</div>
      <div data-testid={testId} style={{ fontSize: 26, fontWeight: 300, marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 12, marginTop: 4, color: color ?? '#8d8d8d' }}>{sub}</div>}
    </div>
  )
}

function TabButton({ active, label, onClick, testId }: { active: boolean; label: string; onClick: () => void; testId: string }) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      style={{
        background: 'none',
        border: 'none',
        borderBottom: `2px solid ${active ? '#4589ff' : 'transparent'}`,
        color: active ? '#f4f4f4' : '#8d8d8d',
        fontWeight: active ? 600 : 400,
        fontSize: 13,
        padding: '10px 16px',
        cursor: 'pointer',
      }}
    >
      {label}
    </button>
  )
}

export default function AttendancePage() {
  const { t } = useT()
  const [tab, setTab] = useState<'daily' | 'range' | 'employee'>('daily')
  const [date, setDate] = useState(todayIso)
  const [from, setFrom] = useState(todayIso)
  const [to, setTo] = useState(todayIso)
  const [employeeId, setEmployeeId] = useState<number | null>(null)
  const [employees, setEmployees] = useState<Employee[]>([])
  const [rows, setRows] = useState<AttendanceRow[]>([])
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [editing, setEditing] = useState<AttendanceRow | null>(null)
  const [form, setForm] = useState<{ entry: string; exit: string; status: AttendanceStatus; note: string }>({
    entry: '',
    exit: '',
    status: 'ontime',
    note: '',
  })
  const [formError, setFormError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const isAdmin = me?.role === 'admin'

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params =
        tab === 'daily' ? { date } : tab === 'range' ? { from, to } : { from, to, employee_id: employeeId ?? undefined }
      setRows(await attendanceList(params))
    } catch {
      setError(t('at.loadError'))
    } finally {
      setLoading(false)
    }
  }, [tab, date, from, to, employeeId, t])

  useEffect(() => {
    getMe().then(setMe).catch(() => setMe(null))
    listEmployees().then(setEmployees).catch(() => {})
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const onImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setError(null)
    try {
      const res = await attendanceImport(file)
      setInfo(
        t('at.importDone').replace('{created}', String(res.created)).replace('{updated}', String(res.updated)).replace('{skipped}', String(res.skipped)),
      )
      await refresh()
    } catch {
      setError(t('at.importError'))
    }
  }

  const exportRange = tab === 'daily' ? { from: date, to: date } : { from, to }

  const openOverride = (row: AttendanceRow) => {
    if (!isAdmin) return
    setEditing(row)
    setForm({
      entry: row.first_entry ? `${row.date}T${row.first_entry.slice(0, 5)}` : '',
      exit: row.last_exit ? `${row.date}T${row.last_exit.slice(0, 5)}` : '',
      status: row.status,
      note: '',
    })
    setFormError(null)
  }

  const submitOverride = async () => {
    if (!editing) return
    if (!form.note.trim()) {
      setFormError(t('at.override.noteRequired'))
      return
    }
    const body: AttendancePatchBody = { override_note: form.note.trim(), status: form.status }
    if (form.entry) body.first_entry = form.entry
    if (form.exit) body.last_exit = form.exit
    try {
      await attendancePatch(editing.id, body)
      setEditing(null)
      await refresh()
    } catch {
      setError(t('at.saveError'))
    }
  }

  const statusLabel = (r: AttendanceRow) =>
    r.status === 'late' ? t('at.status.late').replace('{n}', String(r.late_minutes ?? 0)) : t(`at.status.${r.status}` as TKey)

  const duration = (r: AttendanceRow) => {
    if (r.duration_min == null) return r.status === 'waiting' ? t('at.duration.running') : '—'
    return t('at.duration.hm').replace('{h}', String(Math.floor(r.duration_min / 60))).replace('{m}', String(r.duration_min % 60))
  }

  const hadir = rows.filter((r) => r.status === 'ontime' || r.status === 'late').length
  const ontime = rows.filter((r) => r.status === 'ontime').length
  const late = rows.filter((r) => r.status === 'late').length
  const inside = rows.filter((r) => r.status === 'waiting').length
  const absent = rows.filter((r) => r.status === 'absent').length
  let maxLate: AttendanceRow | null = null
  for (const r of rows) {
    if ((r.late_minutes ?? 0) > 0 && (maxLate === null || (r.late_minutes ?? 0) > (maxLate.late_minutes ?? 0))) maxLate = r
  }

  const headers = ['at.col.employee', 'at.col.shift', 'at.col.entry', 'at.col.exit', 'at.col.duration', 'at.col.status'] as const

  return (
    <div style={{ padding: 32, maxWidth: 1200 }}>
      <h1 style={{ fontWeight: 300, margin: 0, marginBottom: 8 }}>{t('at.title')}</h1>

      <div style={{ display: 'flex', alignItems: 'center', borderBottom: '1px solid #393939', marginBottom: 14 }}>
        <TabButton active={tab === 'daily'} label={t('at.tab.daily')} onClick={() => setTab('daily')} testId="tab-daily" />
        <TabButton active={tab === 'range'} label={t('at.tab.range')} onClick={() => setTab('range')} testId="tab-range" />
        <TabButton active={tab === 'employee'} label={t('at.tab.employee')} onClick={() => setTab('employee')} testId="tab-employee" />
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, padding: '6px 0' }}>
          <input ref={fileRef} type="file" accept=".csv" data-testid="import-input" style={{ display: 'none' }} onChange={onImport} />
          <Button kind="ghost" size="sm" onClick={() => fileRef.current?.click()}>
            {t('at.import')}
          </Button>
          <Button kind="ghost" size="sm" data-testid="export-btn" onClick={() => window.open(attendanceExportUrl(exportRange.from, exportRange.to), '_blank')}>
            {t('at.export')}
          </Button>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
        {tab === 'daily' && (
          <div style={{ width: 200 }}>
            <TextInput id="at-date" type="date" labelText={t('at.date')} value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
        )}
        {tab === 'range' && (
          <>
            <div style={{ width: 200 }}>
              <TextInput id="at-from" type="date" labelText={t('at.from')} value={from} onChange={(e) => setFrom(e.target.value)} />
            </div>
            <div style={{ width: 200 }}>
              <TextInput id="at-to" type="date" labelText={t('at.to')} value={to} onChange={(e) => setTo(e.target.value)} />
            </div>
          </>
        )}
        {tab === 'employee' && (
          <>
            <div style={{ width: 260 }}>
              <Select
                id="at-employee"
                labelText={t('at.employee')}
                value={employeeId ?? ''}
                onChange={(e) => setEmployeeId(e.target.value ? Number(e.target.value) : null)}
              >
                <SelectItem value="" text="—" />
                {employees.map((emp) => (
                  <SelectItem key={emp.id} value={String(emp.id)} text={`${emp.name} · ${emp.employee_code}`} />
                ))}
              </Select>
            </div>
            <div style={{ width: 200 }}>
              <TextInput id="at-from" type="date" labelText={t('at.from')} value={from} onChange={(e) => setFrom(e.target.value)} />
            </div>
            <div style={{ width: 200 }}>
              <TextInput id="at-to" type="date" labelText={t('at.to')} value={to} onChange={(e) => setTo(e.target.value)} />
            </div>
          </>
        )}
      </div>

      {error && <InlineNotification kind="error" lowContrast title={t('common.error')} subtitle={error} onCloseButtonClick={() => setError(null)} />}
      {info && <InlineNotification kind="success" lowContrast title={t('common.save')} subtitle={info} onCloseButtonClick={() => setInfo(null)} />}

      {tab === 'daily' && (
        <div data-testid="at-summary" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 1, background: '#393939', border: '1px solid #393939', marginBottom: 14 }}>
          <Tile
            testId="tile-hadir"
            label={t('at.summary.hadir')}
            value={String(hadir)}
            sub={`${t('at.summary.ontime').replace('{n}', String(ontime))} · ${t('at.summary.late').replace('{n}', String(late))}`}
            color="#42be65"
          />
          <Tile testId="tile-inside" label={t('at.summary.inside')} value={String(inside)} sub={t('at.summary.noExit')} />
          <Tile testId="tile-absent" label={t('at.summary.absent')} value={String(absent)} sub={t('at.summary.noEntry')} />
          <Tile
            testId="tile-late-max"
            label={t('at.summary.lateMax')}
            value={maxLate ? `${maxLate.late_minutes} mnt` : '—'}
            sub={maxLate ? `${maxLate.name ?? ''} · ${maxLate.shift_name ?? ''}` : undefined}
          />
        </div>
      )}

      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : (
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                {headers.map((h) => (
                  <TableHeader key={h}>{t(h)}</TableHeader>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((r) => (
                <TableRow
                  key={r.id}
                  data-testid={`at-row-${r.id}`}
                  onClick={() => openOverride(r)}
                  style={{ cursor: isAdmin ? 'pointer' : 'default' }}
                >
                  <TableCell>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div style={{ width: 28, height: 28, background: '#333', color: '#c6c6c6', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 600, flexShrink: 0 }}>
                        {initials(r.name)}
                      </div>
                      <div>
                        {r.name}
                        <div style={{ fontSize: 11, color: '#8d8d8d', fontFamily: 'monospace' }}>{r.employee_code}</div>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>{r.shift_name ?? '—'}</TableCell>
                  <TableCell style={{ fontFamily: 'monospace' }}>{r.first_entry || '—'}</TableCell>
                  <TableCell style={{ fontFamily: 'monospace' }}>{r.last_exit || '—'}</TableCell>
                  <TableCell>{duration(r)}</TableCell>
                  <TableCell>
                    <StatusBadge status={r.status} label={statusLabel(r)} />
                  </TableCell>
                </TableRow>
              ))}
              {rows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={headers.length}>{t('at.noRows')}</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Modal
        open={editing != null}
        modalHeading={editing ? `${t('at.override.title')} — ${editing.name ?? ''} ${editing.date}` : t('at.override.title')}
        primaryButtonText={t('at.override.submit')}
        secondaryButtonText={t('common.cancel')}
        onRequestClose={() => setEditing(null)}
        onRequestSubmit={submitOverride}
        size="sm"
      >
        {formError && <InlineNotification kind="error" lowContrast title={t('common.error')} subtitle={formError} />}
        <TextInput
          id="ov-entry"
          type="datetime-local"
          labelText={t('at.override.entry')}
          value={form.entry}
          onChange={(e) => setForm({ ...form, entry: e.target.value })}
        />
        <TextInput
          id="ov-exit"
          type="datetime-local"
          labelText={t('at.override.exit')}
          value={form.exit}
          onChange={(e) => setForm({ ...form, exit: e.target.value })}
        />
        <Select id="ov-status" labelText={t('at.override.status')} value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as AttendanceStatus })}>
          {STATUSES.map((s) => (
            <SelectItem key={s} value={s} text={t(`at.status.${s}` as TKey)} />
          ))}
        </Select>
        <TextArea id="ov-note" data-testid="ov-note" labelText={t('at.override.note')} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
      </Modal>
    </div>
  )
}
