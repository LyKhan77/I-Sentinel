import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import MonitoringPage from '../features/monitoring/MonitoringPage'

const cam = (id: number, health: string, issues: string[] = [], over = {}) => ({
  id, name: `CAM-${id}`, location: 'Gudang', node_id: 1, node_name: 'server', enabled: health !== 'disabled',
  health, issues,
  ai: { state: 'streaming', fps: 5, target_fps: 5, last_frame_age_s: 0.3, reconnects_1h: 0, motion_skip_pct: 40 },
  stream: { registered: true }, ...over,
})

const DATA = {
  generated_at: '2026-09-29T08:00:00Z',
  summary: { health: 'critical', cameras: { ok: 1, warning: 1, critical: 1, disabled: 0 },
             nodes: { ok: 1, warning: 0, critical: 0 }, services: { ok: 5, warning: 1, critical: 0 } },
  server: { cpu_pct: 20, ram_used_mb: 4000, ram_total_mb: 16000, disk_used_pct: 65, disk_free_gb: 300 },
  nodes: [{ id: 1, name: 'server', status: 'online', last_seen: '2026-09-29T07:59:57Z', age_s: 3, health: 'ok',
            issues: [], host: { cpu_pct: 41, ram_used_mb: 9000, ram_total_mb: 64000, disk_used_pct: 65, disk_free_gb: 310 },
            gpus: [{ idx: 0, name: 'RTX 4090', util_pct: 55, vram_used_mb: 5000, vram_total_mb: 24000, temp_c: 61, power_w: 120 }],
            inference: { detector: { model: 'yolo26s.engine', device: 'auto', ms_avg: 7.9, ms_max: 15.2, infer_fps: 48 },
                         face: { loaded: true, queue: 0 }, mqtt_backlog: 0 } }],
  cameras: [cam(1, 'ok'), cam(2, 'critical', ['no_frames'], { ai: { state: 'stalled', fps: 0, target_fps: 5, last_frame_age_s: 45, reconnects_1h: 2, motion_skip_pct: null } }),
            cam(3, 'warning', ['low_fps'])],
  services: [{ key: 'database', health: 'ok', detail: null, latency_ms: 1.2 },
             { key: 'retention', health: 'warning', detail: null, latency_ms: null }],
}

let reply: () => Promise<unknown>
beforeEach(() => {
  reply = async () => ({ ok: true, status: 200, json: () => Promise.resolve(DATA) })
  vi.stubGlobal('fetch', vi.fn(async (url: string) =>
    String(url).includes('/monitoring') ? reply() : { ok: false, status: 404, json: () => Promise.resolve(null) }))
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const renderPage = () => render(
  <I18nProvider><MemoryRouter><MonitoringPage /></MemoryRouter></I18nProvider>)

test('ringkasan, node, dan kamera urut kritis → peringatan → sehat', async () => {
  renderPage()
  expect(await screen.findByTestId('mon-summary')).toHaveTextContent('Kritis')
  expect(screen.getByTestId('mon-node-1')).toHaveTextContent('RTX 4090')
  expect(screen.getByTestId('mon-node-1')).toHaveTextContent('61')
  expect(screen.getByTestId('mon-server')).toBeInTheDocument()
  const rows = screen.getAllByTestId(/^mon-cam-\d+$/)
  expect(rows.map((r) => r.dataset.testid)).toEqual(['mon-cam-2', 'mon-cam-3', 'mon-cam-1'])
  expect(within(rows[0]).getByText('Tidak ada frame')).toBeInTheDocument()
})

test('filter "Hanya bermasalah" menyembunyikan kamera sehat', async () => {
  renderPage()
  await screen.findByTestId('mon-cam-1')
  await userEvent.click(screen.getByRole('switch', { name: /Hanya bermasalah/ }))
  expect(screen.queryByTestId('mon-cam-1')).toBeNull()
  expect(screen.getByTestId('mon-cam-2')).toBeInTheDocument()
})

test('polling 10 s; fetch gagal → pesan error, data lama tetap tampil', async () => {
  vi.useFakeTimers()
  renderPage()
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
  expect(screen.getByTestId('mon-cam-1')).toBeInTheDocument()
  reply = async () => ({ ok: false, status: 500, json: () => Promise.resolve(null) })
  await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
  expect(screen.getByTestId('mon-error')).toBeInTheDocument()
  expect(screen.getByTestId('mon-cam-1')).toBeInTheDocument()
})
