import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import ConfigurationPage from '../features/config/ConfigurationPage'

const camera = { id: 1, name: 'CAM-01', location: null, host: '1.2.3.4', rtsp_main: null, rtsp_sub: null, main_path: null, sub_path: null, node_id: 1, source_id: null, location_group_id: null, credential_override_id: null, source: null, location_group: null, credential_override: null, enabled: true, status: 'online', probe_main: null, probe_sub: null, ai_fps: null, confidence: null, analyzers: null, motion_enabled: null }
const settings = { default_ai_fps: 5, default_confidence: 0.4, motion_enabled: true, motion_threshold: 25, motion_min_area: 0.01, motion_force_interval_s: 2, updated_at: '2026-09-22T00:00:00Z' }
// tabel deteksi hanya menampilkan kamera yang punya zona, jadi tiap tes perlu stub /zones
const zone = { id: 9, camera_id: 1, name: 'Z', type: 'behavior', polygon: [], behaviors: [], trigger_seconds: 0, active: true }

test('detection tab updates analyzer and global motion settings', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    const body = url.includes('/detector-settings') ? settings : url.includes('/zones') ? [zone] : url.includes('/cameras') ? [camera] : { id: 1, username: 'admin', role: 'admin' }
    return { ok: true, status: 200, json: async () => body }
  }))
  render(<I18nProvider><MemoryRouter initialEntries={['/configuration?tab=detection']}><ConfigurationPage /></MemoryRouter></I18nProvider>)

  expect(await screen.findByText('Deteksi & Model')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'intrusion' }))
  await waitFor(() => expect(calls.some((c) => c.url.endsWith('/cameras/1') && c.init?.method === 'PATCH')).toBe(true))
  await userEvent.click(screen.getByText('Advanced'))
  await userEvent.clear(screen.getByLabelText('Motion threshold'))
  await userEvent.type(screen.getByLabelText('Motion threshold'), '30')
  await userEvent.click(screen.getByRole('button', { name: 'Simpan setelan global' }))
  await waitFor(() => expect(calls.some((c) => c.url.endsWith('/detector-settings') && c.init?.method === 'PUT')).toBe(true))
})

test('kolom override kosong bukan keadaan invalid — kosong berarti pakai nilai global', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const body = url.includes('/detector-settings') ? settings : url.includes('/zones') ? [zone] : url.includes('/cameras') ? [camera] : { id: 1, username: 'admin', role: 'admin' }
    return { ok: true, status: 200, json: async () => body }
  }))
  render(<I18nProvider><MemoryRouter initialEntries={['/configuration?tab=detection']}><ConfigurationPage /></MemoryRouter></I18nProvider>)

  expect(await screen.findByText('Deteksi & Model')).toBeInTheDocument()
  await waitFor(() => expect(document.querySelector('#fps-1')).not.toBeNull())
  const fps = document.querySelector('#fps-1') as HTMLInputElement

  expect(fps.value).toBe('')
  expect(fps.getAttribute('data-invalid')).toBeNull()
  expect(fps.closest('.cds--number')?.className ?? '').not.toContain('invalid')
})

test('tabel hanya memuat kamera yang punya zona, chip ringkas, override kosong memakai placeholder global', async () => {
  const cams = [camera, { ...camera, id: 2, name: 'CAM-02' }]
  const zones = [{ id: 9, camera_id: 1, name: 'Z', type: 'behavior', polygon: [], behaviors: [], trigger_seconds: 0, active: true }]
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const body = url.includes('/detector-settings') ? settings
      : url.includes('/zones') ? zones
      : url.includes('/cameras') ? cams
      : { id: 1, username: 'admin', role: 'admin' }
    return { ok: true, status: 200, json: async () => body }
  }))
  render(<I18nProvider><MemoryRouter initialEntries={['/configuration?tab=detection']}><ConfigurationPage /></MemoryRouter></I18nProvider>)

  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  expect(screen.queryByText('CAM-02')).toBeNull()

  const fps = document.querySelector('#fps-1') as HTMLInputElement
  expect(fps.value).toBe('')
  expect(fps.placeholder).toBe('5')
  expect((document.querySelector('#confidence-1') as HTMLInputElement).placeholder).toBe('0.4')

  const chips = document.querySelectorAll('.det-chip')
  expect(chips.length).toBe(4)
  expect(document.querySelectorAll('.det-table .cds--btn').length).toBe(0)
})
