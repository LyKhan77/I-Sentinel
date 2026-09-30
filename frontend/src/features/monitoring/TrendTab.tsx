import { useEffect, useState, type ReactElement } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Dropdown, InlineNotification, MultiSelect } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { getMonitoringHistory, type HistPoint, type HistoryRange, type MonitoringHistory } from '../../api/monitoring'
import LineChart, { PALETTE, type ChartSeries } from '../../components/LineChart'

export const TREND_POLL_MS = 60_000
const RANGES: HistoryRange[] = ['1h', '6h', '24h', '7d']
const MAX_CAMS = 4

const pts = (arr: HistPoint[], k: 'avg' | 'max' | 'min') =>
  arr.filter((p) => p[k] != null).map((p) => ({ t: Date.parse(p.t), v: p[k] as number }))

/** Tab Tren: grafik riwayat per node (hardware, inferensi, kamera). Refresh 60 s; gagal → data terakhir tetap. */
export default function TrendTab() {
  const { t, locale } = useT()
  const [params, setParams] = useSearchParams()
  const raw = params.get('range')
  const range: HistoryRange = RANGES.includes(raw as HistoryRange) ? (raw as HistoryRange) : '6h'
  const [data, setData] = useState<MonitoringHistory | null>(null)
  const [failed, setFailed] = useState(false)
  const [nodeId, setNodeId] = useState<number | null>(null)
  const [camIds, setCamIds] = useState<number[] | null>(null) // null = default (maks 4 pertama)

  useEffect(() => {
    let alive = true
    const load = () => getMonitoringHistory(range)
      .then((d) => { if (alive) { setData(d); setFailed(false) } })
      .catch(() => { if (alive) setFailed(true) })
    load()
    const timer = setInterval(load, TREND_POLL_MS)
    return () => { alive = false; clearInterval(timer) }
  }, [range])

  const node = data?.nodes.find((n) => n.id === nodeId) ?? data?.nodes[0]
  const from = data ? Date.parse(data.from) : 0
  const to = data ? Date.parse(data.to) : 0
  const bucketMs = (data?.bucket_s ?? 60) * 1000
  const shaded = (node?.offline ?? []).map((o) => ({ from: Date.parse(o.from), to: o.to ? Date.parse(o.to) : to }))
  const s = node?.series
  const empty = !!node && !!s && Object.entries(s).every(([k, v]) =>
    k === 'gpus' ? Object.keys(v as object).length === 0 : (v as HistPoint[]).length === 0) && node.cameras.length === 0
  const cams = node ? node.cameras.filter((c) => (camIds ?? node.cameras.slice(0, MAX_CAMS).map((x) => x.id)).includes(c.id)) : []
  const common = { from, to, bucketMs, shaded, locale }
  const line = (key: string, label: string, i: number, points: ChartSeries['points'], dashed = false): ChartSeries =>
    ({ key, label, color: PALETTE[i % PALETTE.length], points, dashed })

  const card = (key: string, title: string, chart: ReactElement) => (
    <section key={key} className="mon-card" data-testid={`trend-chart-${key}`}>
      <h3 className="mon-card__title">{title}</h3>
      {chart}
    </section>
  )

  return (
    <div className="mon-page">
      <div className="trend-toolbar">
        <div className="lv-chips" role="group" aria-label={t('mon.tab.trend')}>
          {RANGES.map((r) => (
            <button key={r} type="button" data-testid={`trend-range-${r}`} aria-pressed={range === r}
              className={range === r ? 'lv-chip lv-chip--sel' : 'lv-chip'}
              onClick={() => setParams({ tab: 'trend', range: r })}>{t(`trend.range.${r}` as TKey)}</button>
          ))}
        </div>
        {data && data.nodes.length > 1 && (
          <Dropdown id="trend-node" titleText={t('trend.node')} label="" size="sm" items={data.nodes}
            itemToString={(n) => n?.name ?? ''} selectedItem={node}
            onChange={({ selectedItem }) => { setNodeId(selectedItem?.id ?? null); setCamIds(null) }} />
        )}
        {data && (
          <span className="en-muted">
            {t('trend.updated').replace('{time}', new Date(data.to).toLocaleTimeString(locale))} · {t('trend.offlineNote')}
          </span>
        )}
      </div>
      {failed && <div data-testid="trend-error"><InlineNotification kind="error" lowContrast hideCloseButton title={t('trend.error')} /></div>}
      {empty && <p className="en-muted" data-testid="trend-empty">{t('trend.empty')}</p>}
      {node && s && !empty && (
        <>
          <div className="trend-grid">
            {card('cpu', t('trend.chart.cpu'), <LineChart {...common} title={t('trend.chart.cpu')} yMin={0} yMax={100} unit=" %"
              series={[line('cpu', t('trend.s.cpu'), 0, pts(s.cpu_pct, 'avg')), line('ram', t('trend.s.ram'), 1, pts(s.ram_pct, 'avg'))]} />)}
            {Object.entries(s.gpus).map(([idx, g]) => card(`gpu-${idx}`, t('trend.chart.gpu').replace('{idx}', idx),
              <LineChart {...common} title={t('trend.chart.gpu').replace('{idx}', idx)} yMin={0} yMax={100} unit=" %"
                series={[line('util', t('trend.s.util'), 0, pts(g.util_pct, 'avg')), line('vram', t('trend.s.vram'), 1, pts(g.vram_pct, 'max'))]} />))}
            {card('gputemp', t('trend.chart.gputemp'), <LineChart {...common} title={t('trend.chart.gputemp')} unit=" °C"
              series={Object.entries(s.gpus).map(([idx, g], i) => line(`temp-${idx}`, `GPU ${idx}`, i, pts(g.temp_c, 'max')))} />)}
            {card('latency', t('trend.chart.latency'), <LineChart {...common} title={t('trend.chart.latency')} unit=" ms"
              series={[line('msavg', t('trend.s.avg'), 0, pts(s.ms_avg, 'avg')), line('msmax', t('trend.s.max'), 3, pts(s.ms_max, 'max'))]} />)}
            {card('inferfps', t('trend.chart.inferfps'), <LineChart {...common} title={t('trend.chart.inferfps')}
              series={[line('ifps', t('trend.chart.inferfps'), 2, pts(s.infer_fps, 'avg'))]} />)}
            {card('backlog', t('trend.chart.backlog'), <LineChart {...common} title={t('trend.chart.backlog')}
              series={[line('backlog', t('trend.chart.backlog'), 4, pts(s.mqtt_backlog, 'max'))]} />)}
          </div>
          {node.cameras.length > 0 && (
            <section className="mon-card">
              <header className="mon-card__head">
                <h3 className="mon-card__title">{t('trend.cameras')}</h3>
                <MultiSelect<NonNullable<typeof node>['cameras'][number]> key={node.id} id="trend-cams" titleText="" label={t('trend.cameras')}
                  size="sm" items={node.cameras} itemToString={(c) => c?.name ?? ''} initialSelectedItems={cams}
                  onChange={({ selectedItems }) => setCamIds((selectedItems ?? []).slice(0, MAX_CAMS).map((c) => c.id))} />
              </header>
              <div className="trend-cams">
                {cams.map((c) => (
                  <div key={c.id} className="trend-cam" data-testid={`trend-cam-${c.id}`}>
                    <h4 className="mon-group__title">{c.name}</h4>
                    <div className="trend-cam__charts">
                      <LineChart {...common} height={140} title={`${c.name} ${t('trend.chart.camfps')}`} yMin={0}
                        series={[line('fps', t('trend.s.fps'), 1, pts(c.fps, 'min'))]}
                        refLine={c.target_fps != null ? { v: c.target_fps, label: t('trend.s.target') } : undefined} />
                      <LineChart {...common} height={140} title={`${c.name} ${t('trend.chart.camage')}`} yMin={0} unit=" s"
                        series={[line('age', t('trend.chart.camage'), 3, pts(c.frame_age_s, 'max'))]} />
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}
