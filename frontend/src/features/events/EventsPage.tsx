import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Button, Dropdown, InlineLoading, InlineNotification, Select, SelectItem, Tag, TextInput } from '@carbon/react'
import { Download, Activity } from '@carbon/icons-react'
import { useT, type TKey } from '../../app/i18n'
import { listCameras } from '../../api/cameras'
import { listZones } from '../../api/zones'
import { listEvents, getEvent, type EventOut } from '../../api/events'
import { alertsByEvents, listAlerts, telegramStatus, type AlertStatus, type TelegramStatus } from '../../api/alerts'
import { useLiveEvents } from '../../api/useWs'
import { eventTitle, eventWhere } from '../notifications/labels'
import { EVENT_TYPES, eventTypeLabel } from './eventTypes'
import {
  RANGE_IDS, SECURITY, parseFilters, writeFilters, typesFor, sinceFor, matchesFilters,
  appendPage, mergeFirstPage, type Filters, type RangeId,
} from './eventFilters'
import EvidencePanel from './EvidencePanel'
import AskAiPanel from './AskAiPanel'
import { getAiStatus, type AiStatus } from '../../api/ai'

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

// Batas API `GET /events` (le=200) = ukuran halaman "Muat lebih banyak".
const LIMIT = 200
// Batas baris di klien (D5): setelah ini tombol "Muat lebih banyak" diganti petunjuk batas.
const MAX_EVENTS = 1000

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
  const [searchParams, setSearchParams] = useSearchParams()
  const [events, setEvents] = useState<EventOut[]>([])
  const [cams, setCams] = useState<{ id: number; name: string }[]>([])
  const [zoneNames, setZoneNames] = useState<Record<number, string>>({})
  // filter Tipe/Kamera/Severity/Rentang/pencarian hidup di URL (D1): dibaca tiap render,
  // ditulis lewat setter bentuk fungsi + replace — deep link, reload, dan Back/Forward
  // memulihkannya; param lain (mis. `event`) terjaga. Pencarian tetap murni client-side.
  const search = searchParams.toString()
  const filters = useMemo(() => parseFilters(new URLSearchParams(search)), [search])
  const { type: typeFilter, camera: camFilter, severity: sevFilter, range, q: query } = filters
  const setFilter = (patch: Partial<Filters>) => setSearchParams((prev) => writeFilters(prev, patch), { replace: true })
  // `?event=<id>` = sumber kebenaran pemilihan (K1): dibaca tiap render, bukan hanya saat
  // mount — klik lonceng/toast saat halaman sudah terbuka tetap berpindah. Tak valid → null.
  const rawParam = searchParams.get('event')
  const nParam = rawParam == null ? NaN : Number(rawParam)
  const eventParam = Number.isInteger(nParam) && nParam > 0 ? nParam : null
  // sematan (K3): event via URL yang tak tampil di daftar diambil sekali lewat id
  const [pinned, setPinned] = useState<{ id: number; status: 'ok' | 'missing' | 'error'; event: EventOut | null } | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [hasMore, setHasMore] = useState(false) // halaman terakhir yang diambil penuh LIMIT
  const [loadingMore, setLoadingMore] = useState(false)
  // generasi daftar: hanya refresh mode 'replace' (filter berubah) yang menaikkannya; respons yang
  // tiba setelah generasi berganti dibuang. Refresh 'merge' dan "Muat lebih banyak" hanya membandingkan,
  // supaya interval klip tertunda tidak menelan halaman yang sedang dimuat.
  const reqRef = useRef(0)
  const [alertMap, setAlertMap] = useState<Record<string, AlertStatus>>({})
  const [detailAlert, setDetailAlert] = useState<AlertStatus | null>(null)
  const [tabState, setTabState] = useState<{ id: number; tab: DetailTab } | null>(null)
  const [tg, setTg] = useState<TelegramStatus | null>(null)
  // jam 5 s untuk `clipPending`: Date.now() langsung di body render melanggar react/purity
  const [nowMs, setNowMs] = useState(() => Date.now())
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null)
  const [aiTick, setAiTick] = useState(0)

  useEffect(() => {
    let alive = true
    getAiStatus().then((value) => { if (alive) setAiStatus(value) }).catch(() => {})
    return () => { alive = false }
  }, [])

  const hasFilter = typeFilter != null || camFilter != null || sevFilter != null || range !== 'all' || query.trim() !== ''
  const resetFilters = () => setFilter({ type: null, camera: null, severity: null, range: 'all', q: '' })

  // mode 'replace' (filter berubah) mengganti daftar + mereset hasMore;
  // mode 'merge' (interval klip tertunda) menggabung halaman pertama tanpa membuang yang termuat
  const refresh = useCallback(async (mode: 'replace' | 'merge' = 'replace') => {
    const since = sinceFor(range, new Date())
    const req = mode === 'replace' ? ++reqRef.current : reqRef.current
    try {
      const rows = await listEvents({
        limit: LIMIT,
        since,
        types: typesFor(typeFilter),
        camera_id: camFilter ?? undefined,
        severities: sevFilter ? [sevFilter] : undefined,
      })
      if (req !== reqRef.current) return // respons basi: permintaan lebih baru sudah jalan
      if (mode === 'merge') {
        setEvents((prev) => mergeFirstPage(prev, rows, MAX_EVENTS))
      } else {
        setEvents(rows)
        setHasMore(rows.length === LIMIT)
      }
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
  }, [refresh])

  // "Muat lebih banyak": halaman berikutnya digabung di akhir (dedupe id),
  // respons yang tiba setelah filter berubah dibuang lewat token yang sama dengan `refresh`
  const loadMore = async () => {
    const offset = events.length
    const req = reqRef.current
    setLoadingMore(true)
    try {
      const rows = await listEvents({
        limit: LIMIT,
        offset,
        since: sinceFor(range, new Date()),
        types: typesFor(typeFilter),
        camera_id: camFilter ?? undefined,
        severities: sevFilter ? [sevFilter] : undefined,
      })
      if (req !== reqRef.current) return
      setEvents((prev) => appendPage(prev, rows, MAX_EVENTS))
      setHasMore(rows.length === LIMIT)
      setLoadFailed(false)
    } catch {
      if (req !== reqRef.current) return
      setLoadFailed(true)
    } finally {
      setLoadingMore(false)
    }
  }

  // kamera dan zona sekali saat mount — bukan tiap filter berubah (`refresh` ikut berubah)
  useEffect(() => {
    listCameras()
      .then((cs) => setCams(cs.map((c) => ({ id: c.id, name: c.name }))))
      .catch(() => setCams([]))
    listZones()
      .then((zs) => setZoneNames(Object.fromEntries(zs.map((z) => [z.id, z.name]))))
      .catch(() => setZoneNames({}))
  }, [])

  // poll 5s via useLiveEvents — event dgn id belum ada → prepend (newest first)
  useLiveEvents((raw) => {
    const msg = raw as { kind?: string; event_id?: number; status?: AlertStatus }
    if (msg?.kind === 'ai') {
      if (typeof msg.event_id === 'number' && selected?.id === msg.event_id) setAiTick((value) => value + 1)
      return
    }
    if (msg?.kind === 'face') {
      // hasil identitas wajah intrusion tertulis → refresh merge supaya payload.face terlihat
      refresh('merge')
      return
    }
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
    if (!matchesFilters(e, filters)) return
    setEvents((prev) => (prev.some((p) => p.id === e.id) ? prev : [e, ...prev].slice(0, MAX_EVENTS)))
  })

  // tiga dropdown memakai bentuk item yang sama: "Semua" + opsi; nilai = primitif
  const typeItems = useMemo<FilterItem[]>(
    () => [
      { value: ALL_VALUE, label: t('events.filterAll') },
      { value: SECURITY, label: t('events.type.security') },
      ...EVENT_TYPES.map((v) => ({ value: v, label: eventTypeLabel(v, t) })),
    ],
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
  // eventWhere menerima nama dari id kamera (payload health sudah membawa labelnya sendiri)
  const camNameById = (id: number | null) => (id == null ? '—' : (cams.find((c) => c.id === id)?.name ?? `cam ${id}`))
  // nama zona utk Inbox; zona yang sudah dihapus → #id (bukan crash)
  const zoneName = (id: number) => zoneNames[id] ?? `#${id}`

  // Hasil pencocokan wajah attendance: nama + keterangan cooldown, atau Tidak dikenal.
  const faceMatch = (p: Record<string, unknown> | null): string => {
    const name = typeof p?.employee_name === 'string' ? p.employee_name : null
    if (name && p?.match_reason === 'cooldown') return `${name} · ${t('events.face.cooldown')}`
    if (name && p?.match_reason === 'already_in') return `${name} · ${t('events.face.alreadyIn')}`
    if (name) return name
    if (p?.match_reason === 'no_match' || p?.match_reason === 'low_quality' || p?.match_reason === 'ambiguous') return t('events.face.unknown')
    return '—'
  }

  // Identitas intrusion critical: string tampil, atau null bila payload.face tidak ada.
  const identityRow = (p: Record<string, unknown> | null): string | null => {
    const face = p?.face
    if (typeof face !== 'object' || face === null) return null
    const f = face as Record<string, unknown>
    const score = typeof f.score === 'number' ? ` · ${f.score.toFixed(2)}` : ''
    switch (f.status) {
      case 'recognized':
        return t('events.identity.recognized', { name: String(f.name ?? '') }) + score
      case 'unknown': return t('events.identity.unknown')
      case 'not_visible': return t('events.identity.notVisible')
      case 'unverified': return t('events.identity.unverified')
      default: return null
    }
  }

  // pencarian teks tetap client-side atas hasil server yang sudah terfilter
  const needle = query.trim().toLowerCase()
  const filtered = events.filter((e) => {
    if (!matchesFilters(e, filters)) return false // daftar langsung menyempit; server tetap otoritas data
    if (!needle) return true
    const haystack = e.type === 'system'
      ? [eventTitle(e, t), eventWhere(e, t, camNameById), e.severity, e.event_id]
      : [e.type, e.event_id, e.severity, camName(e), e.payload ? JSON.stringify(e.payload) : '']
    return haystack.join(' ').toLowerCase().includes(needle)
  })

  const inList = eventParam != null && filtered.some((e) => e.id === eventParam)
  const pinnedEvent = pinned && pinned.id === eventParam && pinned.status === 'ok' ? pinned.event : null
  // event yang dituju belum ada di daftar dan fetch by-id-nya belum selesai: jangan tampilkan event lain
  // sebagai penggantinya (K4) — panel detail menunggu; fallback event pertama hanya bila hasilnya missing/error
  const resolving = eventParam != null && !loading && !inList && (pinned == null || pinned.id !== eventParam)
  // pilihan dari URL (K1); fallback: event tersemat, lalu event pertama daftar
  const selected = resolving ? null : (filtered.find((e) => e.id === eventParam) ?? pinnedEvent ?? filtered[0] ?? null)
  const fromPinned = selected != null && selected === pinnedEvent

  // sematan: fetch by-id tepat sekali per eventParam, hanya bila daftar selesai dimuat dan
  // eventParam tidak ada di daftar (K3). Respons basi dibuang lewat alive + koreksi id.
  useEffect(() => {
    if (eventParam == null || loading || inList) return
    const req = eventParam
    let alive = true
    getEvent(req)
      .then((ev) => { if (alive) setPinned({ id: req, status: ev ? 'ok' : 'missing', event: ev }) })
      .catch(() => { if (alive) setPinned({ id: req, status: 'error', event: null }) })
    return () => { alive = false }
  }, [eventParam, loading, inList])
  const cropPath = typeof selected?.payload?.crop_path === 'string' ? selected.payload.crop_path : null
  const isAttendance = selected?.type === 'attendance'  // event system (node offline/pulih, health alert) tidak punya media: panel Bukti menggantikan tab
  const isSystem = selected?.type === 'system'
  const title = selected ? (isSystem ? eventTitle(selected, t) : selected.type) : ''
  const where = selected ? eventWhere(selected, t, camNameById) : ''

  // klip insiden dipakai beberapa event: mulai putar di detik event ini (media fragment)
  const clipOffset = selected?.payload?.clip_offset_s
  const clipSeek = typeof clipOffset === 'number' && clipOffset > 0 ? `#t=${clipOffset}` : ''
  const clipPending =
    !!selected && !isSystem && !selected.clip_path && !isAttendance &&
    nowMs - new Date(selected.ts_event).getTime() < CLIP_PENDING_MS

  // jam ber-tick supaya event yang menua berhenti dianggap "sedang direkam"
  useEffect(() => {
    const clock = setInterval(() => setNowMs(Date.now()), 5000)
    return () => clearInterval(clock)
  }, [])

  // poll live hanya menambah event baru; clip_path yang datang belakangan perlu refetch
  useEffect(() => {
    if (!clipPending) return
    const timer = setInterval(() => refresh('merge'), 5000)
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

      {eventParam != null && pinned?.id === eventParam && pinned.status === 'missing' && (
        <InlineNotification kind="warning" lowContrast
          title={t('events.deeplinkMissing').replace('{id}', String(eventParam))} />
      )}
      {eventParam != null && pinned?.id === eventParam && pinned.status === 'error' && (
        <InlineNotification kind="error" lowContrast
          title={t('events.deeplinkFailed').replace('{id}', String(eventParam))} />
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
          onChange={({ selectedItem }) => setFilter({ type: (selectedItem?.value as string | null) ?? null })}
        />
        <Dropdown<FilterItem>
          className="events-filter"
          id="filter-camera"
          titleText={t('events.col.camera')}
          label={t('events.filterAll')}
          items={camItems}
          itemToString={(i) => i?.label ?? ''}
          selectedItem={selectedCamItem}
          onChange={({ selectedItem }) => setFilter({ camera: (selectedItem?.value as number | null) ?? null })}
        />
        <Dropdown<FilterItem>
          className="events-filter"
          id="filter-severity"
          titleText={t('events.col.severity')}
          label={t('events.filterAll')}
          items={sevItems}
          itemToString={(i) => i?.label ?? ''}
          selectedItem={selectedSevItem}
          onChange={({ selectedItem }) => setFilter({ severity: (selectedItem?.value as string | null) ?? null })}
        />
        <Select
          className="events-filter"
          id="filter-range"
          labelText={t('events.col.range')}
          value={range}
          onChange={(e) => setFilter({ range: e.target.value as RangeId })}
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
            onChange={(e) => setFilter({ q: e.target.value })}
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
            {hasMore && '+'} {t('events.countUnit')}
          </span>
        )}
      </div>

      {hasMore && events.length < MAX_EVENTS && (
        <p className="ev-limit-hint" data-testid="event-limit-hint">
          {t('events.limitHint').replace('{n}', String(events.length))}
        </p>
      )}

      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : filtered.length === 0 && !selected && !resolving ? (
        <p className="ev-empty">{events.length === 0 ? t('events.empty') : t('events.emptyFiltered')}</p>
      ) : (
        <div className="events-split">
          {/* kiri: daftar event + tombol muat lebih banyak */}
          <div>
          <ul data-testid="event-list" className="ev-list">
            {filtered.map((e) => (
              <li key={e.id}>
                <button
                  type="button"
                  data-testid={`event-item-${e.id}`}
                  aria-current={selected?.id === e.id ? 'true' : undefined}
                  onClick={() => setSearchParams((prev) => {
                    const n = new URLSearchParams(prev)
                    n.set('event', String(e.id))
                    return n
                  }, { replace: true })}
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
                    <span className="ev-row__title">{e.type === 'system' ? eventTitle(e, t) : e.type}</span>
                    <span className="ev-row__sub">{e.type === 'system' ? eventWhere(e, t, camNameById) : camName(e)}</span>
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
                  {e.type === 'system'
                    ? <span className="ev-thumb ev-thumb--icon" aria-hidden="true"><Activity size={20} /></span>
                    : <Thumb path={e.snapshot_path} alt={e.type} />}
                </button>
              </li>
            ))}
          </ul>
          {hasMore && events.length < MAX_EVENTS && !loadingMore && (
            <Button kind="ghost" size="sm" data-testid="events-load-more" onClick={loadMore}>
              {t('events.loadMore')}
            </Button>
          )}
          {loadingMore && <InlineLoading description={t('common.loading')} />}
          {events.length >= MAX_EVENTS && (
            <p className="ev-limit-hint" data-testid="event-cap-hint">
              {t('events.capHint').replace('{n}', String(MAX_EVENTS))}
            </p>
          )}
          </div>

          {/* kanan: detail panel */}
          {resolving && (
            <div data-testid="event-detail-loading" className="ev-detail">
              <InlineLoading description={t('common.loading')} />
            </div>
          )}
          {selected && (
            <div data-testid="event-detail" className="ev-detail">
              <div className="ev-detail__head">
                <h2 className="ev-detail__title">
                  {isSystem ? title : `${title} · ${camName(selected)}`}
                </h2>
                {isSystem && <span className="ev-detail__where">{where}</span>}
                <Tag type={selected.severity === 'critical' ? 'red' : 'warm-gray'} size="sm">
                  {selected.severity}
                </Tag>
                {detailAlert && (
                  <span data-testid="alert-badge" className={`ev-badge ${ALERT_BADGE[detailAlert]}`}>
                    {t(ALERT_KEY[detailAlert])}
                  </span>
                )}
                {fromPinned && (
                  <span className="ev-detail__where" data-testid="event-pinned-note">{t('events.pinnedNote')}</span>
                )}
              </div>

              {isSystem ? (
                <EvidencePanel key={selected.id} event={selected} />
              ) : (
                <>
                  <div className="ev-tabstrip" role="tablist">
                {DETAIL_TABS.filter((tb) => (tb.id === 'crop' ? isAttendance || cropPath != null : tb.id !== 'clip' || !isAttendance)).map((tb) => {
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
                </>
              )}

              <dl className="ev-meta-grid">
                <div className="ev-meta">
                  <dt className="ev-meta__k">{t('events.col.time')}</dt>
                  <dd className="ev-meta__v">{new Date(selected.ts_event).toLocaleString()}</dd>
                </div>
                {!isSystem && (
                  <div className="ev-meta">
                    <dt className="ev-meta__k">{t('events.col.camera')}</dt>
                    <dd className="ev-meta__v">{camName(selected)}</dd>
                  </div>
                )}
                {!isSystem && (
                  <div className="ev-meta">
                    <dt className="ev-meta__k">{t('events.col.zone')}</dt>
                    <dd className="ev-meta__v">{selected.zone_id != null ? zoneName(selected.zone_id) : '—'}</dd>
                  </div>
                )}
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
                {identityRow(selected.payload) && (
                  <div className="ev-meta">
                    <dt className="ev-meta__k">{t('events.identity')}</dt>
                    <dd className="ev-meta__v" data-testid="event-identity">{identityRow(selected.payload)}</dd>
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

              {/* metadata event tetap utama; blok AI (caption + Tanya AI) di bawahnya */}
              {aiStatus?.enabled && selected.type !== 'attendance' && !isSystem && (
                <AskAiPanel key={selected.id} event={selected} status={aiStatus} tick={aiTick} />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
