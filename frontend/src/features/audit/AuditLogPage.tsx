import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Button,
  Dropdown,
  InlineLoading,
  InlineNotification,
  Select,
  SelectItem,
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
import {
  listAuditActors,
  listAuditLogs,
  verifyAuditChain,
  type AuditLogEntry,
  type AuditVerifyResult,
} from '../../api/auditLogs'

const LIMIT = 50

// senada katalog aksi di design spec; label ditampilkan apa adanya (log teknis)
const ACTIONS: Record<string, string[]> = {
  auth: ['auth.login', 'auth.login_failed', 'auth.lockout', 'auth.password_change'],
  config: [
    'camera.create', 'camera.update', 'camera.delete', 'camera.import',
    'stream_source.create', 'stream_source.update', 'stream_source.delete',
    'credential_profile.create', 'credential_profile.update',
    'location_group.create', 'location_group.update', 'location_group.delete',
    'node.update',
    'zone.create', 'zone.update', 'zone.delete',
    'detector_setting.update', 'ai_settings.update', 'storage_settings.update',
    'storage.sweep', 'storage.cleanup', 'telegram.update',
  ],
  attendance: [
    'employee.create', 'employee.update', 'employee.delete',
    'enrollment.create', 'enrollment.batch', 'enrollment.delete', 'enrollment.purge',
    'shift.create', 'shift.update', 'shift.delete',
    'attendance.correct', 'attendance.import', 'attendance.export',
  ],
}
const CATEGORIES = Object.keys(ACTIONS)

type FilterItem = { value: string; label: string }

function useDebouncedValue<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return debounced
}

export default function AuditLogPage() {
  const { t } = useT()
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = useMemo(
    () => ({
      from: searchParams.get('from') ?? '',
      to: searchParams.get('to') ?? '',
      category: searchParams.get('category') ?? '',
      action: searchParams.get('action') ?? '',
      actor: searchParams.get('actor') ?? '',
      status: searchParams.get('status') ?? '',
      q: searchParams.get('q') ?? '',
    }),
    [searchParams],
  )
  const offset = Number(searchParams.get('offset') ?? 0) || 0
  const debouncedQ = useDebouncedValue(filters.q, 300)

  const [page, setPage] = useState<{ total: number; items: AuditLogEntry[] }>({ total: 0, items: [] })
  const [actors, setActors] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [verifyResult, setVerifyResult] = useState<AuditVerifyResult | null>(null)
  const [verifying, setVerifying] = useState(false)
  const reqRef = useRef(0)

  const setParam = (patch: Record<string, string>) =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [k, v] of Object.entries(patch)) {
          if (v) next.set(k, v)
          else next.delete(k)
        }
        return next
      },
      { replace: true },
    )
  // filter berubah → reset ke halaman pertama
  const setFilter = (patch: Record<string, string>) => {
    setVerifyResult(null)
    setParam({ ...patch, offset: '' })
  }

  const refresh = useCallback(async () => {
    const req = ++reqRef.current
    setLoading(true)
    try {
      const data = await listAuditLogs({
        from: filters.from ? new Date(`${filters.from}T00:00:00`).toISOString() : undefined,
        // date input 'YYYY-MM-DD' → akhir hari agar hari terpilih inklusif
        to: filters.to ? new Date(`${filters.to}T23:59:59.999`).toISOString() : undefined,
        category: filters.category || undefined,
        action: filters.action || undefined,
        actor: filters.actor || undefined,
        status: filters.status || undefined,
        q: debouncedQ || undefined,
        limit: LIMIT,
        offset,
      })
      if (req !== reqRef.current) return
      setPage(data)
      setLoadFailed(false)
    } catch {
      if (req !== reqRef.current) return
      setLoadFailed(true)
    } finally {
      if (req === reqRef.current) setLoading(false)
    }
  }, [filters.from, filters.to, filters.category, filters.action, filters.actor,
      filters.status, debouncedQ, offset])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect -- synchronize the API list with URL filters
    refresh()
    return () => { reqRef.current += 1 }
  }, [refresh])

  useEffect(() => {
    listAuditActors().then(setActors).catch(() => setActors([]))
  }, [])

  const onVerify = async () => {
    setVerifying(true)
    try {
      setVerifyResult(await verifyAuditChain())
    } catch {
      setVerifyResult(null)
      setLoadFailed(true)
    } finally {
      setVerifying(false)
    }
  }

  const categoryItems: FilterItem[] = [
    { value: '', label: t('audit.filterAll') },
    ...CATEGORIES.map((c) => ({ value: c, label: t(`audit.category.${c}` as TKey) })),
  ]
  const actionItems: FilterItem[] = [
    { value: '', label: t('audit.filterAll') },
    ...(ACTIONS[filters.category] ?? Object.values(ACTIONS).flat()).map((a) => ({ value: a, label: a })),
  ]
  const actorItems: FilterItem[] = [
    { value: '', label: t('audit.filterAll') },
    ...actors.map((a) => ({ value: a, label: a })),
  ]
  const statusItems: FilterItem[] = [
    { value: '', label: t('audit.filterAll') },
    { value: 'ok', label: t('audit.status.ok') },
    { value: 'failed', label: t('audit.status.failed') },
  ]

  const headers = [
    { key: 'ts', header: t('audit.col.time') },
    { key: 'actor', header: t('audit.col.actor') },
    { key: 'action', header: t('audit.col.action') },
    { key: 'target', header: t('audit.col.target') },
    { key: 'status', header: t('audit.col.status') },
    { key: 'ip', header: t('audit.col.ip') },
  ]

  const pageEnd = Math.min(offset + page.items.length, page.total)

  return (
    <div className="app-page audit-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('nav.auditLog')}</h1>
          <p className="app-page__sub">{t('audit.sub')}</p>
        </div>
        <Button size="sm" disabled={verifying} onClick={onVerify} data-testid="audit-verify">
          {t('audit.verify')}
        </Button>
      </div>

      {verifyResult?.ok && (
        <InlineNotification
          kind="success"
          lowContrast
          title={t('audit.verifyOkTitle')}
          subtitle={t('audit.verifyOk', { n: String(verifyResult.checked) })}
          onCloseButtonClick={() => setVerifyResult(null)}
          data-testid="audit-verify-ok"
        />
      )}
      {verifyResult && !verifyResult.ok && (
        <InlineNotification
          kind="error"
          lowContrast
          title={t('audit.verifyBrokenTitle')}
          subtitle={t('audit.verifyBroken', { id: String(verifyResult.first_break_id) })}
          onCloseButtonClick={() => setVerifyResult(null)}
          data-testid="audit-verify-broken"
        />
      )}
      {loadFailed && (
        <InlineNotification
          kind="error"
          lowContrast
          title={t('common.error')}
          subtitle={t('common.loadFailed')}
          onCloseButtonClick={() => setLoadFailed(false)}
        />
      )}

      <div className="audit-toolbar">
        <div className="audit-date">
          <label htmlFor="audit-from">{t('audit.filter.from')}</label>
          <input
            id="audit-from"
            type="date"
            value={filters.from}
            onChange={(e) => setFilter({ from: e.target.value })}
            data-testid="audit-filter-from"
          />
        </div>
        <div className="audit-date">
          <label htmlFor="audit-to">{t('audit.filter.to')}</label>
          <input
            id="audit-to"
            type="date"
            value={filters.to}
            onChange={(e) => setFilter({ to: e.target.value })}
            data-testid="audit-filter-to"
          />
        </div>
        <Dropdown<FilterItem>
          className="audit-filter"
          id="audit-category"
          titleText={t('audit.filter.category')}
          label={t('audit.filterAll')}
          items={categoryItems}
          itemToString={(i) => i?.label ?? ''}
          selectedItem={categoryItems.find((i) => i.value === filters.category)}
          onChange={({ selectedItem }) => {
            const category = selectedItem?.value ?? ''
            // kategori berganti → aksi mungkin tidak valid di kategori baru
            setFilter({ category, action: '' })
          }}
        />
        <Dropdown<FilterItem>
          className="audit-filter"
          id="audit-action"
          titleText={t('audit.filter.action')}
          label={t('audit.filterAll')}
          items={actionItems}
          itemToString={(i) => i?.label ?? ''}
          selectedItem={actionItems.find((i) => i.value === filters.action)}
          onChange={({ selectedItem }) => setFilter({ action: selectedItem?.value ?? '' })}
        />
        <Dropdown<FilterItem>
          className="audit-filter"
          id="audit-actor"
          titleText={t('audit.filter.actor')}
          label={t('audit.filterAll')}
          items={actorItems}
          itemToString={(i) => i?.label ?? ''}
          selectedItem={actorItems.find((i) => i.value === filters.actor)}
          onChange={({ selectedItem }) => setFilter({ actor: selectedItem?.value ?? '' })}
        />
        <Select
          className="audit-filter"
          id="audit-status"
          labelText={t('audit.filter.status')}
          value={filters.status}
          onChange={(e) => setFilter({ status: e.target.value })}
        >
          {statusItems.map((i) => (
            <SelectItem key={i.value || 'all'} value={i.value} text={i.label} />
          ))}
        </Select>
        <TextInput
          className="audit-filter audit-filter--search"
          id="audit-q"
          labelText={t('audit.filter.search')}
          value={filters.q}
          onChange={(e) => setFilter({ q: e.target.value })}
        />
      </div>

      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : page.items.length === 0 ? (
        <p className="audit-empty" data-testid="audit-empty">{t('audit.empty')}</p>
      ) : (
        <>
          <TableContainer className="audit-table">
            <Table>
              <TableHead>
                <TableRow>
                  {headers.map((h) => (
                    <TableHeader key={h.key}>{h.header}</TableHeader>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {page.items.map((r) => (
                  <TableRow key={r.id} data-testid={`audit-row-${r.id}`}>
                    <TableCell>{new Date(r.ts).toLocaleString()}</TableCell>
                    <TableCell>{r.actor_label}</TableCell>
                    <TableCell>{r.action}</TableCell>
                    <TableCell>
                      {r.target_label ?? (r.target_type ? `${r.target_type}#${r.target_id ?? ''}` : '—')}
                      {r.changes && (
                        <code className="audit-changes">{JSON.stringify(r.changes)}</code>
                      )}
                    </TableCell>
                    <TableCell>{t(r.status === 'ok' ? 'audit.status.ok' : 'audit.status.failed')}</TableCell>
                    <TableCell>{r.ip ?? '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          <div className="audit-pager">
            <Button kind="secondary" size="sm" disabled={offset === 0}
                    onClick={() => setParam({ offset: String(Math.max(0, offset - LIMIT)) })}
                    data-testid="audit-prev">
              {t('audit.prev')}
            </Button>
            <span data-testid="audit-page-info">
              {t('audit.pageInfo', { from: String(offset + 1), to: String(pageEnd), total: String(page.total) })}
            </span>
            <Button kind="secondary" size="sm" disabled={pageEnd >= page.total}
                    onClick={() => setParam({ offset: String(offset + LIMIT) })}
                    data-testid="audit-next">
              {t('audit.next')}
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
