import { useCallback, useEffect, useMemo, useState, Fragment } from 'react'
import {
  Dropdown,
  InlineLoading,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '@carbon/react'
import { useT } from '../../app/i18n'
import { listCameras } from '../../api/cameras'
import { listEvents, type EventOut } from '../../api/events'
import { useLiveEvents } from '../../api/useWs'

const SEV_COLOR: Record<string, string> = { critical: '#fa4d56', warning: '#f1c21b' }

function payloadSummary(e: EventOut): string {
  if (!e.payload) return '—'
  const s = JSON.stringify(e.payload)
  return s.length > 60 ? `${s.slice(0, 57)}…` : s
}

export default function EventsPage() {
  const { t } = useT()
  const [events, setEvents] = useState<EventOut[]>([])
  const [cams, setCams] = useState<{ id: number; name: string }[]>([])
  const [typeFilter, setTypeFilter] = useState<{ label: string } | null>(null)
  const [camFilter, setCamFilter] = useState<{ id: number; label: string } | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    const list = await listEvents({ limit: 100 }).catch(() => [])
    setEvents(list)
    setLoading(false)
  }, [])

  useEffect(() => {
    refresh()
    listCameras()
      .then((cs) => setCams(cs.map((c) => ({ id: c.id, name: c.name }))))
      .catch(() => setCams([]))
  }, [refresh])

  // poll 5s via useLiveEvents — event dgn id belum ada → prepend (newest first)
  useLiveEvents((raw) => {
    const e = raw as EventOut
    setEvents((prev) => (prev.some((p) => p.id === e.id) ? prev : [e, ...prev].slice(0, 200)))
  })

  const typeOptions = useMemo(() => [...new Set(events.map((e) => e.type))].map((v) => ({ label: v })), [events])
  const camOptions = useMemo(() => cams.map((c) => ({ id: c.id, label: c.name })), [cams])

  const filtered = events.filter(
    (e) => (!typeFilter || e.type === typeFilter.label) && (!camFilter || e.camera_id === camFilter.id),
  )

  const headers = [
    t('events.col.time'),
    t('events.col.type'),
    t('events.col.severity'),
    t('events.col.camera'),
    t('events.col.payload'),
  ]

  return (
    <div style={{ padding: 32, maxWidth: 1200 }}>
      <h1 style={{ fontWeight: 300, margin: 0, marginBottom: 16 }}>{t('nav.events')}</h1>

      <div style={{ display: 'flex', gap: 12, maxWidth: 480, marginBottom: 16 }}>
        <Dropdown
          id="filter-type"
          titleText={t('events.col.type')}
          label={t('events.filterAll')}
          items={typeOptions}
          selectedItem={typeFilter}
          onChange={({ selectedItem }) => setTypeFilter(selectedItem)}
        />
        <Dropdown
          id="filter-camera"
          titleText={t('events.col.camera')}
          label={t('events.filterAll')}
          items={camOptions}
          selectedItem={camFilter}
          onChange={({ selectedItem }) => setCamFilter(selectedItem)}
        />
      </div>

      {loading ? (
        <InlineLoading description={t('common.loading')} />
      ) : filtered.length === 0 ? (
        <p style={{ color: '#8d8d8d' }}>{t('events.empty')}</p>
      ) : (
        <TableContainer>
          <Table size="sm">
            <TableHead>
              <TableRow>
                {headers.map((h) => (
                  <TableHeader key={h}>{h}</TableHeader>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {filtered.map((e) => (
                <Fragment key={e.id}>
                  <TableRow
                    key={e.id}
                    onClick={() => setExpandedId(expandedId === e.id ? null : e.id)}
                    style={{ cursor: 'pointer' }}
                  >
                    <TableCell>{new Date(e.ts_event).toLocaleString()}</TableCell>
                    <TableCell>{e.type}</TableCell>
                    <TableCell>
                      <span style={{ color: SEV_COLOR[e.severity] ?? '#8d8d8d' }}>● {e.severity}</span>
                    </TableCell>
                    <TableCell>{cams.find((c) => c.id === e.camera_id)?.name ?? `cam ${e.camera_id}`}</TableCell>
                    <TableCell>{payloadSummary(e)}</TableCell>
                  </TableRow>
                  {expandedId === e.id && (
                    <TableRow>
                      <TableCell colSpan={5}>
                        <div style={{ fontSize: 12, color: '#8d8d8d', marginBottom: 4 }}>event_id: {e.event_id}</div>
                        <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 12 }}>
                          {JSON.stringify(e.payload, null, 2)}
                        </pre>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </div>
  )
}
