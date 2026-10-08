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
import { Edit } from '@carbon/icons-react'
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

const STATUSES: AttendanceStatus[] = ['ontime', 'late', 'waiting', 'no_exit', 'no_entry', 'absent']
const STATUS_COLOR: Record<AttendanceStatus, string> = {
  ontime: '#42be65',
  late: '#f1c21b',
  waiting: '#4589ff',
  no_exit: '#ff832b',
  no_entry: '#ff832b',
  absent: '#fa4d56',
}

function todayIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function fmtDay(iso: string, locale: string) {
  const d = new Date(`${iso}T00:00:00`)
  const opts: Intl.DateTimeFormatOptions = { weekday: 'short', day: 'numeric', month: 'short' }
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric'
  return d.toLocaleDateString(locale, opts)
}

const hhmm = (raw: string | null) => (raw ? raw.slice(0, 5) : '—')

type StatusFilter = 'all' | 'present' | 'inside' | 'fix' | 'absent'

const STATUS_GROUP: Record<AttendanceStatus, Exclude<StatusFilter, 'all'>> = {
  ontime: 'present',
  late: 'present',
  waiting: 'inside',
  no_exit: 'fix',
  no_entry: 'fix',
  absent: 'absent',
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

function Tile({ label, value, sub, color, testId, active, onClick }: {
  label: string; value: string; sub?: string; color?: string; testId: string
  active?: boolean; onClick?: () => void
}) {
  const inner = (
    <>
      <div style={{ fontSize: 11, color: '#8d8d8d', letterSpacing: '.32px' }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 300, marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 12, marginTop: 4, color: color ?? '#8d8d8d' }}>{sub}</div>}
    </>
  )
  const style = {
    background: '#262626',
    border: `1px solid ${active ? '#4589ff' : '#393939'}`,
    padding: '14px 16px',
    textAlign: 'left' as const,
    cursor: onClick ? 'pointer' : 'default',
    color: 'inherit',
    font: 'inherit',
    width: '100%',
  }
  if (!onClick) return <div data-testid={testId} style={style}>{inner}</div>
  return (
    <button type="button" data-testid={testId} style={style} aria-pressed={active ?? false} onClick={onClick}>
      {inner}
    </button>
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
  const { t, locale } = useT()
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
  const [now, setNow] = useState(() => new Date())
  const [form, setForm] = useState<{ entry: string; exit: string; status: AttendanceStatus; note: string }>({
    entry: '',
    exit: '',
    status: 'ontime',
    note: '',
  })
  const [formError, setFormError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const fileRef = useRef<HTMLInputElement>(null)

  const isAdmin = me?.role === 'admin'

  useEffect(() => {
    const iv = setInterval(() => setNow(new Date()), 60_000)
    return () => clearInterval(iv)
  }, [])

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
    // "berjalan" hanya untuk waiting hari ini yang punya jam masuk; hari lampau/koreksi → —
    if (r.status === 'waiting' && r.date === todayIso() && r.first_entry) {
      const start = new Date(`${r.date}T${r.first_entry}`)
      const mins = Math.max(0, Math.floor((now.getTime() - start.getTime()) / 60000))
      return t('at.duration.running')
        .replace('{h}', String(Math.floor(mins / 60)))
        .replace('{m}', String(mins % 60))
    }
    if (r.duration_min == null) return '—'
    return t('at.duration.hm').replace('{h}', String(Math.floor(r.duration_min / 60))).replace('{m}', String(r.duration_min % 60))
  }

  const exitEarlyLabel = (min: number) =>
    t('at.exitEarly').replace('{d}', t('at.duration.hm').replace('{h}', String(Math.floor(min / 60))).replace('{m}', String(min % 60)))

  const hadir = rows.filter((r) => r.status === 'ontime' || r.status === 'late').length
  const ontime = rows.filter((r) => r.status === 'ontime').length
  const late = rows.filter((r) => r.status === 'late').length
  const inside = rows.filter((r) => r.status === 'waiting').length
  const absent = rows.filter((r) => r.status === 'absent').length
  const fix = rows.filter((r) => r.status === 'no_exit' || r.status === 'no_entry').length
  let maxLate: AttendanceRow | null = null
  for (const r of rows) {
    if ((r.late_minutes ?? 0) > 0 && (maxLate === null || (r.late_minutes ?? 0) > (maxLate.late_minutes ?? 0))) maxLate = r
  }

  const toggleFilter = (key: Exclude<StatusFilter, 'all'>) =>
    setStatusFilter((f) => (f === key ? 'all' : key))
  const visibleRows = statusFilter === 'all' ? rows : rows.filter((r) => STATUS_GROUP[r.status] === statusFilter)

  const chipKeys: StatusFilter[] = ['all', 'present', 'inside', 'fix', 'absent']

  const headers = [
    ...(tab !== 'daily' ? ['at.col.date' as const] : []),
    'at.col.employee',
    'at.col.shift',
    'at.col.entry',
    'at.col.exit',
    'at.col.duration',
    'at.col.status',
  ] as const

  return (
    <div className="app-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('at.title')}</h1>
          <p className="app-page__sub">{t('at.sub')}</p>
        </div>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', borderBottom: '1px solid #393939', marginBottom: 14 }}>
        <TabButton active={tab === 'daily'} label={t('at.tab.daily')} onClick={() => setTab('daily')} testId="tab-daily" />
        <TabButton active={tab === 'range'} label={t('at.tab.range')} onClick={() => setTab('range')} testId="tab-range" />
        <TabButton active={tab === 'employee'} label={t('at.tab.employee')} onClick={() => setTab('employee')} testId="tab-employee" />
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, padding: '6px 0' }}>
          {isAdmin && (
            <>
              <input ref={fileRef} type="file" accept=".csv" data-testid="import-input" style={{ display: 'none' }} onChange={onImport} />
              <Button kind="ghost" size="sm" data-testid="import-btn" onClick={() => fileRef.current?.click()}>
                {t('at.import')}
              </Button>
            </>
          )}
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
      {info && <InlineNotification kind="success" lowContrast title={t('at.import.successTitle')} subtitle={info} onCloseButtonClick={() => setInfo(null)} />}

      {tab === 'daily' && (
        <div data-testid="at-summary" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 1, background: '#393939', border: '1px solid #393939', marginBottom: 14 }}>
          <Tile
            testId="tile-hadir"
            label={t('at.summary.hadir')}
            value={String(hadir)}
            sub={`${t('at.summary.ontime').replace('{n}', String(ontime))} · ${t('at.summary.late').replace('{n}', String(late))}`}
            color="#42be65"
            active={statusFilter === 'present'}
            onClick={() => toggleFilter('present')}
          />
          <Tile
            testId="tile-inside"
            label={t('at.summary.inside')}
            value={String(inside)}
            sub={t('at.summary.noExit')}
            active={statusFilter === 'inside'}
            onClick={() => toggleFilter('inside')}
          />
          <Tile
            testId="tile-fix"
            label={t('at.summary.fix')}
            value={String(fix)}
            sub={t('at.summary.fixSub')}
            color="#ff832b"
            active={statusFilter === 'fix'}
            onClick={() => toggleFilter('fix')}
          />
          <Tile
            testId="tile-absent"
            label={t('at.summary.absent')}
            value={String(absent)}
            sub={t('at.summary.noEntry')}
            active={statusFilter === 'absent'}
            onClick={() => toggleFilter('absent')}
          />
          <Tile
            testId="tile-late-max"
            label={t('at.summary.lateMax')}
            value={maxLate ? `${maxLate.late_minutes} mnt` : '—'}
            sub={maxLate ? `${maxLate.name ?? ''} · ${maxLate.shift_name ?? ''}` : undefined}
          />
        </div>
      )}

      {tab !== 'daily' && (
        <div className="lv-chips" style={{ marginBottom: 12 }} role="group" aria-label={t('at.filter.label')}>
          {chipKeys.map((k) => (
            <button
              key={k}
              type="button"
              data-testid={`status-filter-${k}`}
              aria-pressed={statusFilter === k}
              className={`lv-chip${statusFilter === k ? ' lv-chip--sel' : ''}`}
              onClick={() => setStatusFilter(k)}
            >
              {t(`at.filter.${k}` as TKey)}
            </button>
          ))}
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
                  <TableHeader key={h} data-testid={h === 'at.col.date' ? 'at-col-date' : undefined}>
                    {t(h)}
                  </TableHeader>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {visibleRows.map((r) => (
                <TableRow
                  key={r.id}
                  data-testid={`at-row-${r.id}`}
                  onClick={() => openOverride(r)}
                  style={{ cursor: isAdmin ? 'pointer' : 'default' }}
                >
                  {tab !== 'daily' && (
                    <TableCell data-testid={`at-date-${r.id}`}>{fmtDay(r.date, locale)}</TableCell>
                  )}
                  <TableCell>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div style={{ width: 28, height: 28, background: '#333', color: '#c6c6c6', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10, fontWeight: 600, flexShrink: 0 }}>
                        {initials(r.name)}
                      </div>
                      <div>
                        {r.name}
                        <div style={{ fontSize: 11, color: '#8d8d8d', fontFamily: 'monospace' }}>{r.employee_code}</div>
                      </div>
                      {r.override_note && (
                        <span
                          data-testid={`corrected-${r.id}`}
                          title={r.override_note}
                          aria-label={t('at.corrected')}
                          style={{ display: 'inline-flex', color: '#ff832b', flexShrink: 0 }}
                        >
                          <Edit size={16} />
                        </span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>{r.shift_name ?? '—'}</TableCell>
                  <TableCell style={{ fontFamily: 'monospace' }}>{hhmm(r.first_entry)}</TableCell>
                  <TableCell style={{ fontFamily: 'monospace' }}>
                    {hhmm(r.last_exit)}
                    {r.exit_early_min != null && (
                      <div
                        data-testid={`exit-early-${r.id}`}
                        style={{ fontSize: 11, padding: '2px 8px', marginTop: 4, border: '1px solid #f1c21b', color: '#f1c21b', display: 'inline-block' }}
                      >
                        {exitEarlyLabel(r.exit_early_min)}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <span data-testid={`at-dur-${r.id}`}>{duration(r)}</span>
                  </TableCell>
                  <TableCell>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <StatusBadge status={r.status} label={statusLabel(r)} />
                      {isAdmin && (r.status === 'no_exit' || r.status === 'no_entry' || r.exit_early_min != null) && (
                        <Button
                          kind="ghost"
                          size="sm"
                          data-testid={`fix-${r.id}`}
                          onClick={(e) => {
                            e.stopPropagation()
                            openOverride(r)
                          }}
                        >
                          {t('at.fix')}
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {visibleRows.length === 0 && (
                <TableRow>
                  <TableCell colSpan={headers.length}>
                    {rows.length === 0 ? t('at.noRows') : t('at.noRowsFiltered')}
                  </TableCell>
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
