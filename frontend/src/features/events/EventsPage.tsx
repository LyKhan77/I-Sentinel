import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Button, Dropdown, InlineLoading, InlineNotification, Select, SelectItem, Tag, TextInput } from '@carbon/react'
import { Download } from '@carbon/icons-react'
import { useT, type TKey } from '../../app/i18n'
import { listCameras } from '../../api/cameras'
import { listZones } from '../../api/zones'
import { listEvents, type EventOut } from '../../api/events'
import { alertsByEvents, listAlerts, telegramStatus, type AlertStatus, type TelegramStatus } from '../../api/alerts'
import { useLiveEvents } from '../../api/useWs'
import { EVENT_TYPES, eventTypeLabel } from './eventTypes'

const SEV_VALUES = ['critical', 'warning', 'info']
const SEV_DOT: Record<string, string> = { critical: 'ev-dot--critical', warning: 'ev-dot--warning', info: 'ev-dot--info' }
const SEV_TAG: Record<string, string> = { critical: 'ev-tag--err', warning: 'ev-tag--warn', info: 'ev-tag--info' }

// Dropdown filter: SATU bentuk item untuk ketiganya (Tipe/Kamera/Severity) supaya
// "Semua" selalu item pertama dan nilai filter disimpan sebagai primitif
// (`value: null` = tanpa filter) — dependensi `refresh` jadi stabil.
type FilterItem = { value: string | number | null; label: string }
const ALL_VALUE = null

const ALERT_KEY: Record<AlertStatus, TKey> = {
  sent: 'events.alert.sent',
  rate_limited: 'events.alert.rate_limited',
  failed: 'events.alert.failed',
  not_configured: 'events.alert.not_configured',
  queued: 'events.alert.queued',
}
const ALERT_TAG: Record<AlertStatus, string> = {
  sent: 'ev-tag--ok',
  rate_limited: 'ev-tag--warn',
  failed: 'ev-tag--err',
  not_configured: 'ev-tag--muted',
  queued: 'ev-tag--muted',
}
const ALERT_BADGE: Record<AlertStatus, string> = {
  sent: 'ev-badge--sent',
  rate_limited: 'ev-badge--rate_limited',
  failed: 'ev-badge--failed',
  not_configured: 'ev-badge--not_configured',
  queued: 'ev-badge--not_configured',
}

// Rentang waktu toolbar (mockup 03) → param `since`. `all` default: riwayat lama
// tetap tampil. Tipe/Kamera/Severity/Rentang semuanya difilter di server;
// pencarian teks tetap murni client-side.
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

// Clip insiden baru ada ±post (default 8 s) setelah orang terakhir terlihat (maks 120 s) — tunggu 3 menit.
const CLIP_PENDING_MS = 3 * 60_000

// Batas API `GET /events` (le=200): daftar lebih panjang dari ini tidak terjangkau.
const LIMIT = 200

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
  // tautan dalam caption Telegram: /events?event=<id> → event itu terbuka di panel detail
  const [searchParams] = useSearchParams()
  const [events, setEvents] = useState<EventOut[]>([])
  const [cams, setCams] = useState<{ id: number; name: string }[]>([])
  const [zoneNames, setZoneNames] = useState<Record<number, string>>({})
  const [typeFilter, setTypeFilter] = useState<string | null>(null)
  const [camFilter, setCamFilter] = useState<number | null>(null)
  const [sevFilter, setSevFilter] = useState<string | null>(null)
  const [range, setRange] = useState<RangeId>('all')
  const [query, setQuery] = useState('')
  // `?event=<id>` (tautan caption) dibaca saat init; tanpa param → null → default event pertama
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    const raw = searchParams.get('event')
    const n = raw == null ? NaN : Number(raw)
    return Number.isInteger(n) && n > 0 ? n : null
  })
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  // nomor permintaan: respons lama yang tiba belakangan dibuang (filter berubah cepat)
  const reqRef = useRef(0)
  const [alertMap, setAlertMap] = useState<Record<string, AlertStatus>>({})
  const [detailAlert, setDetailAlert] = useState<AlertStatus | null>(null)
  const [tabState, setTabState] = useState<{ id: number; tab: DetailTab } | null>(null)
  const [tg, setTg] = useState<TelegramStatus | null>(null)
  // jam 5 s untuk `clipPending`: Date.now() langsung di body render melanggar react/purity
  const [nowMs, setNowMs] = useState(() => Date.now())

  const hasFilter = typeFilter != null || camFilter != null || sevFilter != null || range !== 'all' || query.trim() !== ''
  const resetFilters = () => {
    setTypeFilter(null)
    setCamFilter(null)
    setSevFilter(null)
    setRange('all')
    setQuery('')
  }

  const refresh = useCallback(async () => {
    const hours = RANGE_HOURS[range]
    const since = hours ? new Date(Date.now() - hours * 3_600_000).toISOString() : undefined
    const req = ++reqRef.current
    try {
      const rows = await listEvents({
        limit: LIMIT,
        since,
        types: typeFilter ? [typeFilter] : undefined,
        camera_id: camFilter ?? undefined,
        severities: sevFilter ? [sevFilter] : undefined,
      })
      if (req !== reqRef.current) return // respons basi: permintaan lebih baru sudah jalan
      setEvents(rows)
      setLoadFailed(false)
    } catch {
      if (req !== reqRef.current) return
      setLoadFailed(true) // jangan tampilkan "Belum ada event" saat requestnya yang gagal
    } finally {
      if (req === reqRef.current) setLoading(false)
    }
  }, [range, typeFilter, camFilter, sevFilter])

  useEffect(() => {
    refresh()
    listCameras()
      .then((cs) => setCams(cs.map((c) => ({ id: c.id, name: c.name }))))
      .catch(() => setCams([]))
    listZones()
      .then((zs) => setZoneNames(Object.fromEntries(zs.map((z) => [z.id, z.name]))))
      .catch(() => setZoneNames({}))
  }, [refresh])

  // poll 5s via useLiveEvents — event dgn id belum ada → prepend (newest first)
  useLiveEvents((raw) => {
    const msg = raw as { kind?: string; event_id?: number; status?: AlertStatus }
    if (msg?.kind === 'alert') {
      // broadcast status akhir alert (alert_dispatcher) → update chip tanpa reload
      const status = msg.status
      if (typeof msg.event_id !== 'number' || !status || !(status in ALERT_KEY)) return // status/id tak dikenal → abaikan
      const match = events.find((p) => p.id === msg.event_id)
      if (!match) return // event belum ada di list ter-load → abaikan
      setAlertMap((am) => ({ ...am, [match.event_id]: status }))
      return
    }
    const e = raw as EventOut
    if (typeof e?.id !== 'number') return // buang frame non-event lain
    // filter aktif dikirim ke server; event live dari tipe/kamera/severity lain tidak boleh ikut masuk
    if (typeFilter && e.type !== typeFilter) return
    if (camFilter != null && e.camera_id !== camFilter) return
    if (sevFilter && e.severity !== sevFilter) return
    setEvents((prev) => (prev.some((p) => p.id === e.id) ? prev : [e, ...prev].slice(0, LIMIT)))
  })

  // tiga dropdown memakai bentuk item yang sama: "Semua" + opsi; nilai = primitif
  const typeItems = useMemo<FilterItem[]>(
    () => [{ value: ALL_VALUE, label: t('events.filterAll') }, ...EVENT_TYPES.map((v) => ({ value: v, label: eventTypeLabel(v, t) }))],
    [t],
  )
  const camItems = useMemo<FilterItem[]>(
    () => [{ value: ALL_VALUE, label: t('events.filterAll') }, ...cams.map((c) => ({ value: c.id, label: c.name }))],
    [cams, t],
  )
  const sevItems = useMemo<FilterItem[]>(
    () => [{ value: ALL_VALUE, label: t('events.filterAll') }, ...SEV_VALUES.map((v) => ({ value: v, label: v }))],
    [t],
  )
  const selectedTypeItem = typeItems.find((i) => i.value === typeFilter) ?? typeItems[0]
  const selectedCamItem = camItems.find((i) => i.value === camFilter) ?? camItems[0]
  const selectedSevItem = sevItems.find((i) => i.value === sevFilter) ?? sevItems[0]

  const camName = (e: EventOut) => cams.find((c) => c.id === e.camera_id)?.name ?? `cam ${e.camera_id}`
  // nama zona utk Inbox; zona yang sudah dihapus → #id (bukan crash)
  const zoneName = (id: number) => zoneNames[id] ?? `#${id}`

  // Hasil pencocokan wajah attendance: nama + keterangan cooldown, atau Tidak dikenal.
  const faceMatch = (p: Record<string, unknown> | null): string => {
    const name = typeof p?.employee_name === 'string' ? p.employee_name : null
    if (name && p?.match_reason === 'cooldown') return `${name} · ${t('events.face.cooldown')}`
    if (name && p?.match_reason === 'already_in') return `${name} · ${t('events.face.alreadyIn')}`
    if (name) return name
    if (p?.match_reason === 'no_match' || p?.match_reason === 'low_quality') return t('events.face.unknown')
    return '—'
  }

  // pencarian teks tetap client-side atas hasil server yang sudah terfilter
  const needle = query.trim().toLowerCase()
  const filtered = events.filter((e) => {
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

  // klip insiden dipakai beberapa event: mulai putar di detik event ini (media fragment)
  const clipOffset = selected?.payload?.clip_offset_s
  const clipSeek = typeof clipOffset === 'number' && clipOffset > 0 ? `#t=${clipOffset}` : ''
  const clipPending =
    !!selected && !selected.clip_path && !isAttendance &&
    nowMs - new Date(selected.ts_event).getTime() < CLIP_PENDING_MS

  // jam ber-tick supaya event yang menua berhenti dianggap "sedang direkam"
  useEffect(() => {
    const clock = setInterval(() => setNowMs(Date.now()), 5000)
    return () => clearInterval(clock)
  }, [])

  // poll live hanya menambah event baru; clip_path yang datang belakangan perlu refetch
  useEffect(() => {
    if (!clipPending) return
    const timer = setInterval(refresh, 5000)
    return () => clearInterval(timer)
  }, [clipPending, refresh])

  // tab aktif ikut event terpilih: event berganti → kembali ke Snapshot (derived,
  // tanpa effect yang memicu render kedua)
  const tab: DetailTab = selected && tabState?.id === selected.id ? tabState.tab : 'snapshot'

  // badge alert list: satu request by-events untuk 50 event pertama (hindari N+1)
  useEffect(() => {
    const ids = events.slice(0, 50).map((e) => e.event_id)
    if (ids.length === 0) { setAlertMap({}); return }
    alertsByEvents(ids).then(setAlertMap).catch(() => setAlertMap({}))
  }, [events])

  // fallback saat WS mati (polling saja): re-cek status yang masih 'queued' tiap 10s,
  // berhenti begitu tak ada lagi yang queued (WS push sudah menutup celah ini lebih cepat)
  useEffect(() => {
    const queuedIds = events.slice(0, 50).filter((e) => alertMap[e.event_id] === 'queued').map((e) => e.event_id)
    if (queuedIds.length === 0) return
    const timer = setInterval(() => {
      alertsByEvents(queuedIds).then((res) => setAlertMap((am) => ({ ...am, ...res }))).catch(() => {})
    }, 10000)
    return () => clearInterval(timer)
  }, [events, alertMap])

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
        <Dropdown<FilterItem>
          className="events-filter"
          id="filter-type"
          titleText={t('events.col.type')}
          label={t('events.filterAll')}
          items={typeItems}
          itemToString={(i) => i?.label ?? ''}
          selectedItem={selectedTypeItem}
          onChange={({ selectedItem }) => setTypeFilter((selectedItem?.value as string | null) ?? null)}
        />
        <Dropdown<FilterItem>
          className="events-filter"
          id="filter-camera"
          titleText={t('events.col.camera')}
          label={t('events.filterAll')}
          items={camItems}
          itemToString={(i) => i?.label ?? ''}
          selectedItem={selectedCamItem}
          onChange={({ selectedItem }) => setCamFilter((selectedItem?.value as number | null) ?? null)}
        />
        <Dropdown<FilterItem>
          className="events-filter"
          id="filter-severity"
          titleText={t('events.col.severity')}
          label={t('events.filterAll')}
          items={sevItems}
          itemToString={(i) => i?.label ?? ''}
          selectedItem={selectedSevItem}
          onChange={({ selectedItem }) => setSevFilter((selectedItem?.value as string | null) ?? null)}
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
        {hasFilter && (
          <Button
            kind="ghost"
            size="sm"
            data-testid="filter-reset"
            className="ev-toolbar__reset"
            onClick={resetFilters}
          >
            {t('events.filterReset')}
          </Button>
        )}
        {!loading && (
          <span className="ev-count" data-testid="event-count">
            {filtered.length}
            {events.length >= LIMIT && '+'} {t('events.countUnit')}
          </span>
        )}
      </div>

      {events.length >= LIMIT && (
        <p className="ev-limit-hint" data-testid="event-limit-hint">
          {t('events.limitHint').replace('{n}', String(LIMIT))}
        </p>
      )}

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
                      {e.zone_id != null && <span className="ev-tag">{t('events.col.zone')} {zoneName(e.zone_id)}</span>}
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
                    <video controls src={`/api/v1/media/${selected.clip_path}${clipSeek}`} data-testid="event-clip" className="ev-player" />
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
                    {t(clipPending ? 'events.clipRecording' : 'events.clipUnavailable')}
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
                  <dd className="ev-meta__v">{selected.zone_id != null ? zoneName(selected.zone_id) : '—'}</dd>
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
