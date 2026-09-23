import { useCallback, useEffect, useMemo, useState } from 'react'
import { Dropdown, InlineLoading, InlineNotification, Select, SelectItem, Tag, TextInput } from '@carbon/react'
import { Download } from '@carbon/icons-react'
import { useT, type TKey } from '../../app/i18n'
import { listCameras } from '../../api/cameras'
import { listEvents, type EventOut } from '../../api/events'
import { alertsByEvents, listAlerts, telegramStatus, type AlertStatus, type TelegramStatus } from '../../api/alerts'
import { useLiveEvents } from '../../api/useWs'

const SEV_OPTIONS = ['critical', 'warning', 'info'].map((label) => ({ label }))
const SEV_DOT: Record<string, string> = { critical: 'ev-dot--critical', warning: 'ev-dot--warning', info: 'ev-dot--info' }
const SEV_TAG: Record<string, string> = { critical: 'ev-tag--err', warning: 'ev-tag--warn', info: 'ev-tag--info' }

const ALERT_KEY: Record<AlertStatus, TKey> = {
  sent: 'events.alert.sent',
  rate_limited: 'events.alert.rate_limited',
  failed: 'events.alert.failed',
  not_configured: 'events.alert.not_configured',
}
const ALERT_TAG: Record<AlertStatus, string> = {
  sent: 'ev-tag--ok',
  rate_limited: 'ev-tag--warn',
  failed: 'ev-tag--err',
  not_configured: 'ev-tag--muted',
}
const ALERT_BADGE: Record<AlertStatus, string> = {
  sent: 'ev-badge--sent',
  rate_limited: 'ev-badge--rate_limited',
  failed: 'ev-badge--failed',
  not_configured: 'ev-badge--not_configured',
}

// Rentang waktu toolbar (mockup 03) → param `since`. `all` default: riwayat lama
// tetap tampil, filter lain tetap murni client-side.
const RANGE_IDS = ['all', '24h', '7d', '30d'] as const
type RangeId = (typeof RANGE_IDS)[number]
const RANGE_HOURS: Partial<Record<RangeId, number>> = { '24h': 24, '7d': 24 * 7, '30d': 24 * 30 }

// Tabstrip detail (mockup 03): media dipisah per tab, metadata grid (Details)
// selalu di bawah media. Crop wajah hanya untuk event attendance — satu-satunya
// tipe yang mengirim payload.crop_path; attendance tidak merekam klip, jadi tanpa tab Clip.
type DetailTab = 'snapshot' | 'clip' | 'crop'
const DETAIL_TABS: { id: DetailTab; key: TKey }[] = [
  { id: 'snapshot', key: 'events.tab.snapshot' },
  { id: 'clip', key: 'events.tab.clip' },
  { id: 'crop', key: 'events.tab.crop' },
]

function timeStr(ts: string): string {
  return new Date(ts).toLocaleTimeString('en-GB') // HH:MM:SS
}

function Thumb({ path, alt }: { path: string | null; alt: string }) {
  if (!path) return <span className="ev-thumb ev-thumb--empty" aria-hidden="true" />
  // eslint-disable-next-line jsx-a11y/alt-text -- alt via prop
  return <img className="ev-thumb" src={`/api/v1/media/${path}`} alt={alt} />
}

export default function EventsPage() {
  const { t } = useT()
  const [events, setEvents] = useState<EventOut[]>([])
  const [cams, setCams] = useState<{ id: number; name: string }[]>([])
  const [typeFilter, setTypeFilter] = useState<{ label: string } | null>(null)
  const [camFilter, setCamFilter] = useState<{ id: number; label: string } | null>(null)
  const [sevFilter, setSevFilter] = useState<{ label: string } | null>(null)
  const [range, setRange] = useState<RangeId>('all')
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [alertMap, setAlertMap] = useState<Record<string, AlertStatus>>({})
  const [detailAlert, setDetailAlert] = useState<AlertStatus | null>(null)
  const [tabState, setTabState] = useState<{ id: number; tab: DetailTab } | null>(null)
  const [tg, setTg] = useState<TelegramStatus | null>(null)

  const refresh = useCallback(async () => {
    const hours = RANGE_HOURS[range]
    const since = hours ? new Date(Date.now() - hours * 3_600_000).toISOString() : undefined
    try {
      setEvents(await listEvents({ limit: 200, since }))
      setLoadFailed(false)
    } catch {
      setLoadFailed(true) // jangan tampilkan "Belum ada event" saat requestnya yang gagal
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => {
    refresh()
    listCameras()
      .then((cs) => setCams(cs.map((c) => ({ id: c.id, name: c.name }))))
      .catch(() => setCams([]))
  }, [refresh])

  // poll 5s via useLiveEvents — event dgn id belum ada → prepend (newest first)
  useLiveEvents((raw) => {
    const e = raw as EventOut & { kind?: string }
    if (e?.kind === 'alert') return // buang broadcast alert — eksplisit by kind
    if (typeof e?.id !== 'number') return // buang frame non-event lain
    setEvents((prev) => (prev.some((p) => p.id === e.id) ? prev : [e, ...prev].slice(0, 200)))
  })

  const typeOptions = useMemo(() => [...new Set(events.map((e) => e.type))].map((v) => ({ label: v })), [events])
  const camOptions = useMemo(() => cams.map((c) => ({ id: c.id, label: c.name })), [cams])

  const camName = (e: EventOut) => cams.find((c) => c.id === e.camera_id)?.name ?? `cam ${e.camera_id}`

  // Hasil pencocokan wajah attendance: nama + keterangan cooldown, atau Tidak dikenal.
  const faceMatch = (p: Record<string, unknown> | null): string => {
    const name = typeof p?.employee_name === 'string' ? p.employee_name : null
    if (name && p?.match_reason === 'cooldown') return `${name} · ${t('events.face.cooldown')}`
    if (name && p?.match_reason === 'already_in') return `${name} · ${t('events.face.alreadyIn')}`
    if (name) return name
    if (p?.match_reason === 'no_match' || p?.match_reason === 'low_quality') return t('events.face.unknown')
    return '—'
  }

  // semua filter (termasuk pencarian teks) client-side atas hasil listEvents
  const needle = query.trim().toLowerCase()
  const filtered = events.filter((e) => {
    if (typeFilter && e.type !== typeFilter.label) return false
    if (camFilter && e.camera_id !== camFilter.id) return false
    if (sevFilter && e.severity !== sevFilter.label) return false
    if (!needle) return true
    return [e.type, e.event_id, e.severity, camName(e), e.payload ? JSON.stringify(e.payload) : '']
      .join(' ')
      .toLowerCase()
      .includes(needle)
  })

  // pilihan ikut list ter-filter; default event pertama
  const selected = filtered.find((e) => e.id === selectedId) ?? filtered[0] ?? null
  const cropPath = typeof selected?.payload?.crop_path === 'string' ? selected.payload.crop_path : null
  const isAttendance = selected?.type === 'attendance'

  // tab aktif ikut event terpilih: event berganti → kembali ke Snapshot (derived,
  // tanpa effect yang memicu render kedua)
  const tab: DetailTab = selected && tabState?.id === selected.id ? tabState.tab : 'snapshot'

  // badge alert list: satu request by-events untuk 50 event pertama (hindari N+1)
  useEffect(() => {
    const ids = events.slice(0, 50).map((e) => e.event_id)
    if (ids.length === 0) { setAlertMap({}); return }
    alertsByEvents(ids).then(setAlertMap).catch(() => setAlertMap({}))
  }, [events])

  // event terpilih: dari map, fallback listAlerts bila di luar 50 teratas
  useEffect(() => {
    if (!selected) { setDetailAlert(null); return }
    const fromMap = alertMap[selected.event_id]
    if (fromMap) { setDetailAlert(fromMap); return }
    let alive = true
    listAlerts(selected.id)
      .then((rows) => { if (alive) setDetailAlert(rows[0]?.status ?? null) })
      .catch(() => { if (alive) setDetailAlert(null) })
    return () => { alive = false }
  }, [selected, alertMap])

  useEffect(() => {
    telegramStatus().then(setTg).catch(() => setTg(null))
  }, [])

  return (
    <div className="app-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('nav.events')}</h1>
          <p className="app-page__sub">{t('events.sub')}</p>
        </div>
        {tg && (
          <span
            data-testid="telegram-chip"
            title={t('events.telegram.hint')}
            className={`ev-chip ${tg.configured ? 'ev-chip--ok' : 'ev-chip--muted'}`}
          >
            {tg.configured
              ? `${t('events.telegram.ready')} \u00b7 ${tg.active_chats} ${t('events.telegram.chats')}`
              : t('events.telegram.notConfigured')}
          </span>
        )}
      </div>

      {loadFailed && (
        <InlineNotification
          kind="error"
          lowContrast
          title={t('common.error')}
          subtitle={t('common.loadFailed')}
          onCloseButtonClick={() => setLoadFailed(false)}
        />
      )}

      <div className="ev-toolbar">
        <Dropdown
          className="events-filter"
          id="filter-type"
          titleText={t('events.col.type')}
          label={t('events.filterAll')}
          items={typeOptions}
          selectedItem={typeFilter}
          onChange={({ selectedItem }) => setTypeFilter(selectedItem)}
        />
        <Dropdown
          className="events-filter"
          id="filter-camera"
          titleText={t('events.col.camera')}
          label={t('events.filterAll')}
          items={camOptions}
          selectedItem={camFilter}
          onChange={({ selectedItem }) => setCamFilter(selectedItem)}
        />
        <Dropdown
          className="events-filter"
          id="filter-severity"
          titleText={t('events.col.severity')}
          label={t('events.filterAll')}
          items={SEV_OPTIONS}
          selectedItem={sevFilter}
          onChange={({ selectedItem }) => setSevFilter(selectedItem)}
        />
        <Select
          className="events-filter"
          id="filter-range"
          labelText={t('events.col.range')}
          value={range}
          onChange={(e) => setRange(e.target.value as RangeId)}
        >
          {RANGE_IDS.map((id) => (
            <SelectItem key={id} value={id} text={t(`events.range.${id}` as TKey)} />
          ))}
        </Select>
        <div className="ev-toolbar__search">
          <TextInput
            id="filter-search"
            labelText={t('events.search')}
            placeholder={t('events.searchHint')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {!loading && (
          <span className="ev-count" data-testid="event-count">
            {filtered.length} {t('events.countUnit')}
          </span>
        )}
      </div>

      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : filtered.length === 0 ? (
        <p className="ev-empty">{events.length === 0 ? t('events.empty') : t('events.emptyFiltered')}</p>
      ) : (
        <div className="events-split">
          {/* kiri: daftar event */}
          <ul data-testid="event-list" className="ev-list">
            {filtered.map((e) => (
              <li key={e.id}>
                <button
                  type="button"
                  data-testid={`event-item-${e.id}`}
                  aria-current={selected?.id === e.id ? 'true' : undefined}
                  onClick={() => setSelectedId(e.id)}
                  className={`ev-row${selected?.id === e.id ? ' ev-row--sel' : ''}`}
                >
                  <span className={`ev-dot ${SEV_DOT[e.severity] ?? 'ev-dot--muted'}`} title={e.severity} aria-hidden="true" />
                  {alertMap[e.event_id] === 'rate_limited' && (
                    <span
                      data-testid={`alert-dot-${e.id}`}
                      className="ev-dot ev-dot--warning"
                      title={t('events.alert.rate_limited')}
                      aria-hidden="true"
                    />
                  )}
                  <span className="ev-row__main">
                    <span className="ev-row__title">{e.type}</span>
                    <span className="ev-row__sub">{camName(e)}</span>
                    <span className="ev-row__tags">
                      <span className={`ev-tag ${SEV_TAG[e.severity] ?? 'ev-tag--muted'}`}>{e.severity}</span>
                      {alertMap[e.event_id] && (
                        <span className={`ev-tag ${ALERT_TAG[alertMap[e.event_id]]}`}>{t(ALERT_KEY[alertMap[e.event_id]])}</span>
                      )}
                      {e.zone_id != null && <span className="ev-tag">{t('events.col.zone')} {e.zone_id}</span>}
                    </span>
                  </span>
                  <span className="ev-row__time">
                    <span>{timeStr(e.ts_event)}</span>
                    <span>{new Date(e.ts_event).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}</span>
                  </span>
                  <Thumb path={e.snapshot_path} alt={e.type} />
                </button>
              </li>
            ))}
          </ul>

          {/* kanan: detail panel */}
          {selected && (
            <div data-testid="event-detail" className="ev-detail">
              <div className="ev-detail__head">
                <h2 className="ev-detail__title">
                  {selected.type} · {camName(selected)}
                </h2>
                <Tag type={selected.severity === 'critical' ? 'red' : 'warm-gray'} size="sm">
                  {selected.severity}
                </Tag>
                {detailAlert && (
                  <span data-testid="alert-badge" className={`ev-badge ${ALERT_BADGE[detailAlert]}`}>
                    {t(ALERT_KEY[detailAlert])}
                  </span>
                )}
              </div>

              <div className="ev-tabstrip" role="tablist">
                {DETAIL_TABS.filter((tb) => (tb.id === 'crop' ? isAttendance : tb.id !== 'clip' || !isAttendance)).map((tb) => {
                  const off = tb.id === 'crop' && !cropPath
                  return (
                    <button
                      key={tb.id}
                      type="button"
                      role="tab"
                      data-testid={`event-tab-${tb.id}`}
                      aria-selected={tab === tb.id}
                      disabled={off}
                      onClick={() => setTabState({ id: selected.id, tab: tb.id })}
                      className={`ev-tab${tab === tb.id ? ' on' : ''}${off ? ' ev-tab--off' : ''}`}
                    >
                      {t(tb.key)}
                    </button>
                  )
                })}
              </div>

              {tab === 'clip' &&
                (selected.clip_path ? (
                  <>
                    <video controls src={`/api/v1/media/${selected.clip_path}`} data-testid="event-clip" className="ev-player" />
                    <div className="ev-detail__actions">
                      <a
                        className="ev-detail__download"
                        href={`/api/v1/media/${selected.clip_path}`}
                        download
                        data-testid="event-download"
                      >
                        <Download size={16} /> {t('events.download')}
                      </a>
                    </div>
                  </>
                ) : (
                  <div data-testid="event-clip-placeholder" className="ev-player ev-player--empty">
                    {t('events.clipUnavailable')}
                  </div>
                ))}

              {tab === 'snapshot' &&
                (selected.snapshot_path ? (
                  <img
                    data-testid="event-snapshot"
                    className="ev-snapshot"
                    src={`/api/v1/media/${selected.snapshot_path}`}
                    alt={t('events.snapshot')}
                  />
                ) : (
                  <div data-testid="event-snapshot-placeholder" className="ev-player ev-player--empty">
                    {t('events.snapshotUnavailable')}
                  </div>
                ))}

              {tab === 'crop' &&
                (cropPath ? (
                  <div className="ev-crop" data-testid="event-crop">
                    <img src={`/api/v1/media/${cropPath}`} alt={t('events.crop')} />
                  </div>
                ) : (
                  <div data-testid="event-crop-placeholder" className="ev-player ev-player--empty">
                    {t('events.cropUnavailable')}
                  </div>
                ))}

              <dl className="ev-meta-grid">
                <div className="ev-meta">
                  <dt className="ev-meta__k">{t('events.col.time')}</dt>
                  <dd className="ev-meta__v">{new Date(selected.ts_event).toLocaleString()}</dd>
                </div>
                <div className="ev-meta">
                  <dt className="ev-meta__k">{t('events.col.camera')}</dt>
                  <dd className="ev-meta__v">{camName(selected)}</dd>
                </div>
                <div className="ev-meta">
                  <dt className="ev-meta__k">{t('events.col.zone')}</dt>
                  <dd className="ev-meta__v">{selected.zone_id ?? '—'}</dd>
                </div>
                <div className="ev-meta">
                  <dt className="ev-meta__k">{t('events.col.type')}</dt>
                  <dd className="ev-meta__v">{selected.type}</dd>
                </div>
                {selected.type === 'attendance' && (
                  <div className="ev-meta">
                    <dt className="ev-meta__k">{t('events.col.face')}</dt>
                    <dd className="ev-meta__v" data-testid="event-face-match">{faceMatch(selected.payload)}</dd>
                  </div>
                )}
                <div className="ev-meta">
                  <dt className="ev-meta__k">{t('events.col.severity')}</dt>
                  <dd className="ev-meta__v">
                    <span className={`ev-dot ${SEV_DOT[selected.severity] ?? 'ev-dot--muted'}`} aria-hidden="true" /> {selected.severity}
                  </dd>
                </div>
                <div className="ev-meta">
                  <dt className="ev-meta__k">{t('events.col.eventId')}</dt>
                  <dd className="ev-meta__v">{selected.event_id}</dd>
                </div>
                <div className="ev-meta">
                  <dt className="ev-meta__k">{t('events.col.telegram')}</dt>
                  <dd className="ev-meta__v">{detailAlert ? t(ALERT_KEY[detailAlert]) : '—'}</dd>
                </div>
              </dl>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
