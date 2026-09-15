import { useCallback, useEffect, useMemo, useState } from 'react'
import { Dropdown, InlineLoading, InlineNotification, Tag } from '@carbon/react'
import { Download } from '@carbon/icons-react'
import { useT, type TKey } from '../../app/i18n'
import { listCameras } from '../../api/cameras'
import { listEvents, type EventOut } from '../../api/events'
import { alertsByEvents, listAlerts, telegramStatus, type AlertStatus, type TelegramStatus } from '../../api/alerts'
import { useLiveEvents } from '../../api/useWs'

const SEV_COLOR: Record<string, string> = { critical: '#fa4d56', warning: '#f1c21b' }
const SEV_OPTIONS = ['critical', 'warning', 'info'].map((label) => ({ label }))

const ALERT_BG: Record<AlertStatus, string> = {
  sent: '#24a148',
  rate_limited: '#f1c21b',
  failed: '#fa4d56',
  not_configured: '#8d8d8d',
}
const ALERT_KEY: Record<AlertStatus, TKey> = {
  sent: 'events.alert.sent',
  rate_limited: 'events.alert.rate_limited',
  failed: 'events.alert.failed',
  not_configured: 'events.alert.not_configured',
}

function timeStr(ts: string): string {
  return new Date(ts).toLocaleTimeString('en-GB') // HH:MM:SS
}

function Thumb({ path, alt }: { path: string | null; alt: string }) {
  if (!path) return <div style={{ width: 72, height: 40, background: 'var(--cds-layer)', flexShrink: 0, borderRadius: 0 }} />
  // eslint-disable-next-line jsx-a11y/alt-text -- alt via prop
  return <img src={`/api/v1/media/${path}`} alt={alt} style={{ width: 72, height: 40, objectFit: 'cover', flexShrink: 0, borderRadius: 0 }} />
}

export default function EventsPage() {
  const { t } = useT()
  const [events, setEvents] = useState<EventOut[]>([])
  const [cams, setCams] = useState<{ id: number; name: string }[]>([])
  const [typeFilter, setTypeFilter] = useState<{ label: string } | null>(null)
  const [camFilter, setCamFilter] = useState<{ id: number; label: string } | null>(null)
  const [sevFilter, setSevFilter] = useState<{ label: string } | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [alertMap, setAlertMap] = useState<Record<string, AlertStatus>>({})
  const [detailAlert, setDetailAlert] = useState<AlertStatus | null>(null)
  const [tg, setTg] = useState<TelegramStatus | null>(null)

  const refresh = useCallback(async () => {
    try {
      setEvents(await listEvents({ limit: 100 }))
      setLoadFailed(false)
    } catch {
      setLoadFailed(true) // jangan tampilkan "Belum ada event" saat requestnya yang gagal
    } finally {
      setLoading(false)
    }
  }, [])

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

  const filtered = events.filter(
    (e) =>
      (!typeFilter || e.type === typeFilter.label) &&
      (!camFilter || e.camera_id === camFilter.id) &&
      (!sevFilter || e.severity === sevFilter.label),
  )

  // pilihan ikut list ter-filter; default event pertama
  const selected = filtered.find((e) => e.id === selectedId) ?? filtered[0] ?? null
  const camName = (e: EventOut) => cams.find((c) => c.id === e.camera_id)?.name ?? `cam ${e.camera_id}`

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
            style={{
              fontSize: 11,
              padding: '3px 8px',
              whiteSpace: 'nowrap',
              border: `1px solid ${tg.configured ? '#42be65' : '#8d8d8d'}`,
              color: tg.configured ? '#42be65' : '#8d8d8d',
            }}
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

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
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
      </div>

      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : filtered.length === 0 ? (
        <p style={{ color: '#8d8d8d' }}>{t('events.empty')}</p>
      ) : (
        <div className="events-split">
          {/* kiri: daftar event */}
          <ul data-testid="event-list" style={{ listStyle: 'none', margin: 0, padding: 0, maxHeight: 640, overflowY: 'auto' }}>
            {filtered.map((e) => (
              <li
                key={e.id}
                data-testid={`event-item-${e.id}`}
                onClick={() => setSelectedId(e.id)}
                style={{
                  display: 'flex',
                  gap: 10,
                  alignItems: 'center',
                  padding: '8px 10px',
                  cursor: 'pointer',
                  borderRadius: 0,
                  background: selected?.id === e.id ? 'var(--cds-layer-selected)' : 'transparent',
                }}
              >
                <span
                  title={e.severity}
                  style={{ width: 10, height: 10, borderRadius: '50%', background: SEV_COLOR[e.severity] ?? '#8d8d8d', flexShrink: 0 }}
                />
                {alertMap[e.event_id] === 'rate_limited' && (
                  <span
                    data-testid={`alert-dot-${e.id}`}
                    title={t('events.alert.rate_limited')}
                    style={{ width: 8, height: 8, borderRadius: '50%', background: ALERT_BG.rate_limited, flexShrink: 0 }}
                  />
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <span>{e.type}</span>
                    <span style={{ fontSize: 11, color: 'var(--cds-text-helper)' }}>{timeStr(e.ts_event)}</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--cds-text-secondary)' }}>{camName(e)}</div>
                </div>
                <Thumb path={e.snapshot_path} alt={e.type} />
              </li>
            ))}
          </ul>

          {/* kanan: detail panel */}
          {selected && (
            <div data-testid="event-detail" style={{ border: '1px solid var(--cds-border-subtle)', borderRadius: 0, padding: 16 }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 12 }}>
                <h2 style={{ fontWeight: 400, margin: 0, flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>
                  {selected.type} · {camName(selected)}
                </h2>
                <Tag type={selected.severity === 'critical' ? 'red' : 'warm-gray'} size="sm">
                  {selected.severity}
                </Tag>
                {detailAlert && (
                  <span
                    data-testid="alert-badge"
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      padding: '2px 8px',
                      borderRadius: 0,
                      background: ALERT_BG[detailAlert],
                      color: detailAlert === 'rate_limited' ? '#161616' : '#fff',
                    }}
                  >
                    {t(ALERT_KEY[detailAlert])}
                  </span>
                )}
              </div>

              {selected.clip_path ? (
                <video controls src={`/api/v1/media/${selected.clip_path}`} data-testid="event-clip" style={{ width: '100%', maxHeight: 360, background: '#000' }} />
              ) : (
                <div
                  data-testid="event-clip-placeholder"
                  style={{ display: 'grid', placeItems: 'center', height: 120, background: 'var(--cds-layer)', color: 'var(--cds-text-helper)', borderRadius: 0 }}
                >
                  {t('events.clipUnavailable')}
                </div>
              )}

              {selected.snapshot_path && (
                <img src={`/api/v1/media/${selected.snapshot_path}`} alt={t('events.snapshot')} style={{ width: '100%', maxHeight: 360, objectFit: 'contain', marginTop: 12 }} />
              )}

              <dl style={{ display: 'grid', gridTemplateColumns: 'auto minmax(0, 1fr)', gap: '4px 16px', fontSize: 13, marginTop: 16, overflowWrap: 'anywhere' }}>
                <dt style={{ color: 'var(--cds-text-helper)' }}>{t('events.col.type')}</dt>
                <dd style={{ margin: 0 }}>{selected.type}</dd>
                <dt style={{ color: 'var(--cds-text-helper)' }}>{t('events.col.camera')}</dt>
                <dd style={{ margin: 0 }}>{camName(selected)}</dd>
                <dt style={{ color: 'var(--cds-text-helper)' }}>{t('events.col.severity')}</dt>
                <dd style={{ margin: 0, color: SEV_COLOR[selected.severity] ?? undefined }}>● {selected.severity}</dd>
                <dt style={{ color: 'var(--cds-text-helper)' }}>{t('events.col.time')}</dt>
                <dd style={{ margin: 0 }}>{new Date(selected.ts_event).toLocaleString()}</dd>
                <dt style={{ color: 'var(--cds-text-helper)' }}>{t('events.col.eventId')}</dt>
                <dd style={{ margin: 0 }}>{selected.event_id}</dd>
                <dt style={{ color: 'var(--cds-text-helper)' }}>{t('events.col.zone')}</dt>
                <dd style={{ margin: 0 }}>{selected.zone_id ?? '—'}</dd>
              </dl>

              {selected.clip_path && (
                <a
                  href={`/api/v1/media/${selected.clip_path}`}
                  download
                  data-testid="event-download"
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 16, color: 'var(--cds-link-primary)' }}
                >
                  <Download size={16} /> {t('events.download')}
                </a>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
