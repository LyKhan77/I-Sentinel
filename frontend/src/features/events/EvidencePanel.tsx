import { useEffect, useState } from 'react'
import { InlineLoading } from '@carbon/react'
import { useT } from '../../app/i18n'
import type { EventOut } from '../../api/events'
import { getMonitoringHistoryWindow, type NodeHistory } from '../../api/monitoring'
import LineChart, { PALETTE } from '../../components/LineChart'
import { systemEvidence, type ChartSpec } from './systemEvidence'

type Load = { state: 'loading' | 'ok' | 'error'; node: NodeHistory | null }

/** Satu grafik dari spec: seri diambil dari node terpilih, arsir periode offline node itu. */
function Chart({ spec, node, from, to, marker, locale }: {
  spec: ChartSpec
  node: NodeHistory
  from: number
  to: number
  marker: { t: number; label: string }
  locale: string
}) {
  const { t } = useT()
  const series = spec.series.map((s, i) => ({
    key: s.key, label: t(s.labelKey), color: PALETTE[i % PALETTE.length], points: s.pick(node),
  }))
  return (
    <section className="ev-evidence__chart" data-testid={`evidence-chart-${spec.key}`}>
      <h4 className="ev-evidence__chart-title">{t(spec.titleKey)}</h4>
      <LineChart
        title={t(spec.titleKey)}
        series={series}
        from={from}
        to={to}
        bucketMs={60_000}
        yMin={spec.yMin}
        yMax={spec.unit === '%' ? 100 : undefined}
        unit={spec.unit ? ` ${spec.unit}` : ''}
        shaded={node.offline.map((o) => ({ from: Date.parse(o.from), to: o.to ? Date.parse(o.to) : to }))}
        markers={[marker]}
        refLine={spec.refLine ? { v: spec.refLine.v, label: t(spec.refLine.labelKey) } : undefined}
        locale={locale}
      />
    </section>
  )
}

/**
 * Panel Bukti untuk event `system`: fakta selalu tampil, grafik tren diambil sekali per
 * event terpilih (`key={event.id}` di induk) dari jendela yang diturunkan `systemEvidence`.
 */
export default function SystemEvidence({ event }: { event: EventOut }) {
  const { t, locale } = useT()
  // Date.now() di badan render melanggar react/purity; satu nilai per mount
  const [now] = useState(() => Date.now())
  const ev = systemEvidence(event, t, now)
  const window = ev.window
  const nodeId = ev.nodeId
  const from = window?.from
  const to = window?.to
  const wants = from != null && to != null && nodeId != null && ev.charts.length > 0
  // status awal diturunkan dari rencana fetch — bukan setState di badan efek
  const [load, setLoad] = useState<Load>(() => ({ state: wants ? 'loading' : 'ok', node: null }))

  // dependensi primitif: `ev.window` objek baru tiap render → refetch tanpa henti bila dipakai langsung
  useEffect(() => {
    if (!wants || from == null || to == null || nodeId == null) return
    let alive = true
    getMonitoringHistoryWindow({ from: new Date(from), to: new Date(to), nodeId })
      .then((res) => {
        if (!alive) return
        setLoad({ state: 'ok', node: res.nodes.find((n) => n.id === nodeId) ?? res.nodes[0] ?? null })
      })
      .catch(() => { if (alive) setLoad({ state: 'error', node: null }) })
    return () => { alive = false }
  }, [wants, from, to, nodeId])

  const hasPoints = !!load.node && ev.charts.some((c) => c.series.some((s) => s.pick(load.node as NodeHistory).length > 0))
  const marker = { t: Date.parse(event.ts_event), label: t('events.evidence.marker') }

  return (
    <section className="ev-evidence" data-testid="event-evidence">
      <h3 className="ev-evidence__title">{t('events.evidence.title')}</h3>
      {ev.facts.length > 0 && (
        <dl className="ev-evidence__facts">
          {ev.facts.map((f) => (
            <div key={f.labelKey} className="ev-meta">
              <dt className="ev-meta__k">{t(f.labelKey)}</dt>
              <dd className="ev-meta__v">{f.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {ev.kind === 'unknown' ? (
        <p className="ev-evidence__note">{t('events.evidence.unknown')}</p>
      ) : ev.expired ? (
        <p className="ev-evidence__note" data-testid="evidence-expired">{t('events.evidence.expired')}</p>
      ) : ev.charts.length === 0 ? (
        <p className="ev-evidence__note">{t('events.evidence.unknown')}</p>
      ) : load.state === 'loading' ? (
        <div data-testid="evidence-loading"><InlineLoading description={t('events.evidence.loading')} /></div>
      ) : load.state === 'error' ? (
        <p className="ev-evidence__note" data-testid="evidence-error">{t('events.evidence.chartFailed')}</p>
      ) : !hasPoints ? (
        <p className="ev-evidence__note" data-testid="evidence-empty">{t('events.evidence.noData')}</p>
      ) : (
        <div className="ev-evidence__charts">
          {ev.charts.map((c) => (
            <Chart key={c.key} spec={c} node={load.node as NodeHistory} from={from as number} to={to as number}
              marker={marker} locale={locale} />
          ))}
        </div>
      )}
    </section>
  )
}
