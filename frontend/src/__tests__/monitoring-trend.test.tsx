import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import MonitoringPage from '../features/monitoring/MonitoringPage'

const p = (m: number, v: Record<string, number>) => ({ t: new Date(Date.UTC(2026, 8, 30, 7, m)).toISOString(), ...v })
const cam = (id: number) => ({ id, name: `CAM-${id}`, target_fps: 5, fps: [p(0, { min: 4, avg: 5 })],
  frame_age_s: [p(0, { max: 0.3 })] })
const HIST = {
  range: '6h', bucket_s: 60, from: '2026-09-30T02:00:00Z', to: '2026-09-30T08:00:00Z',
  nodes: [{ id: 1, name: 'server',
    series: { cpu_pct: [p(0, { avg: 20, max: 30 })], ram_pct: [p(0, { avg: 18, max: 18 })],
      ms_avg: [p(0, { avg: 8 })], ms_max: [p(0, { max: 19 })], infer_fps: [p(0, { avg: 40 })],
      mqtt_backlog: [p(0, { max: 0 })],
      gpus: { '0': { util_pct: [p(0, { avg: 40, max: 70 })], vram_pct: [p(0, { max: 21 })], temp_c: [p(0, { max: 61 })] } } },
    cameras: [cam(1), cam(2), cam(3), cam(4), cam(5)],
    offline: [{ from: '2026-09-30T07:30:00Z', to: '2026-09-30T07:31:00Z' }] }],
}
const EMPTY = { ...HIST, nodes: [{ ...HIST.nodes[0], cameras: [], offline: [],
  series: { cpu_pct: [], ram_pct: [], ms_avg: [], ms_max: [], infer_fps: [], mqtt_backlog: [], gpus: {} } }] }

let reply: () => Promise<unknown>
let calls: string[]
beforeEach(() => {
  calls = []
  reply = async () => ({ ok: true, status: 200, json: () => Promise.resolve(HIST) })
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    calls.push(String(url))
    if (String(url).includes('/monitoring/history')) return reply()
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  }))
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function Loc() {
  const l = useLocation()
  return <span data-testid="loc">{l.search}</span>
}
const renderAt = (entry: string) => render(
  <I18nProvider><MemoryRouter initialEntries={[entry]}><MonitoringPage /><Loc /></MemoryRouter></I18nProvider>)

test('?tab=trend membuka Tren: default 6 jam, grafik node + maks 4 kamera, arsir offline; S1 tidak di-polling', async () => {
  renderAt('/monitoring?tab=trend')
  expect(await screen.findByTestId('trend-chart-cpu')).toBeInTheDocument()
  expect(calls.some((u) => u.includes('/monitoring/history?range=6h'))).toBe(true)
  expect(calls.some((u) => /\/monitoring$/.test(u.split('?')[0]))).toBe(false)
  for (const k of ['gpu-0', 'gputemp', 'latency', 'inferfps', 'backlog']) {
    expect(screen.getByTestId(`trend-chart-${k}`)).toBeInTheDocument()
  }
  expect(screen.getAllByTestId(/^trend-cam-\d+$/)).toHaveLength(4)
  expect(screen.getAllByTestId('lc-offline').length).toBeGreaterThan(0)
  expect(screen.getByTestId('trend-range-6h')).toHaveAttribute('aria-pressed', 'true')
})

test('ganti rentang → request baru + URL', async () => {
  renderAt('/monitoring?tab=trend')
  await screen.findByTestId('trend-chart-cpu')
  await userEvent.click(screen.getByTestId('trend-range-24h'))
  await waitFor(() => expect(calls.some((u) => u.includes('range=24h'))).toBe(true))
  expect(screen.getByTestId('loc')).toHaveTextContent('tab=trend')
  expect(screen.getByTestId('loc')).toHaveTextContent('range=24h')
})

test('belum ada sampel → teks kosong', async () => {
  reply = async () => ({ ok: true, status: 200, json: () => Promise.resolve(EMPTY) })
  renderAt('/monitoring?tab=trend')
  expect(await screen.findByTestId('trend-empty')).toBeInTheDocument()
})

test('refresh 60 s; gagal → pesan error, grafik lama tetap', async () => {
  vi.useFakeTimers()
  renderAt('/monitoring?tab=trend')
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
  expect(screen.getByTestId('trend-chart-cpu')).toBeInTheDocument()
  reply = async () => ({ ok: false, status: 500, json: () => Promise.resolve(null) })
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
  expect(screen.getByTestId('trend-error')).toBeInTheDocument()
  expect(screen.getByTestId('trend-chart-cpu')).toBeInTheDocument()
})

test('klik tab Tren dari Kondisi saat ini mengubah URL', async () => {
  renderAt('/monitoring')
  await userEvent.click(screen.getByRole('tab', { name: 'Tren' }))
  expect(screen.getByTestId('loc')).toHaveTextContent('tab=trend')
})

test('ganti node: centakan MultiSelect mengikuti kamera node baru', async () => {
  const HIST2 = { ...HIST, nodes: [HIST.nodes[0],
    { ...HIST.nodes[0], id: 2, name: 'edge-1', cameras: [cam(6), cam(7), cam(8), cam(9)] }] }
  reply = async () => ({ ok: true, status: 200, json: () => Promise.resolve(HIST2) })
  const { container } = renderAt('/monitoring?tab=trend')
  await screen.findByTestId('trend-chart-cpu')
  Element.prototype.scrollIntoView = vi.fn()
  fireEvent.click(container.querySelector('#trend-node .cds--list-box__field')!)
  fireEvent.click(await screen.findByRole('option', { name: 'edge-1' }))
  expect(await screen.findByTestId('trend-cam-6')).toBeInTheDocument()
  fireEvent.click(container.querySelector('#trend-cams .cds--list-box__field')!)
  await screen.findByRole('option', { name: 'CAM-9' }) // menu node baru terbuka
  const checked = [...container.querySelectorAll('#trend-cams li[aria-checked="true"]')]
    .map((el) => el.getAttribute('aria-label'))
  expect(checked).toEqual(['CAM-6', 'CAM-7', 'CAM-8', 'CAM-9']) // default maks 4 node baru
  delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView
})
