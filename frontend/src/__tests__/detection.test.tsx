import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import ConfigurationPage from '../features/config/ConfigurationPage'

const camera = { id: 1, name: 'CAM-01', location: null, host: '1.2.3.4', rtsp_main: null, rtsp_sub: null, main_path: null, sub_path: null, node_id: 1, source_id: null, location_group_id: null, credential_override_id: null, source: null, location_group: null, credential_override: null, enabled: true, status: 'online', probe_main: null, probe_sub: null, ai_fps: null, confidence: null, analyzers: null, motion_enabled: null }
const settings = { default_ai_fps: 5, default_confidence: 0.4, motion_enabled: true, motion_threshold: 25, motion_min_area: 0.01, motion_force_interval_s: 2, face_min_width_px: 80, face_min_det_score: 0.6, face_max_yaw: 0.35, face_blur_min: 120, face_min_frames: 3, updated_at: '2026-09-22T00:00:00Z' }
// kolom Status AI dihitung dari zona aktif, jadi tiap tes perlu stub /zones
const zone = { id: 9, camera_id: 1, name: 'Z', type: 'behavior', polygon: [], behaviors: [], trigger_seconds: 0, active: true }

test('detection tab saves per-camera fps and global motion settings', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    const body = url.includes('/detector-settings') ? settings : url.includes('/zones') ? [zone] : url.includes('/cameras') ? [camera] : { id: 1, username: 'admin', role: 'admin' }
    return { ok: true, status: 200, json: async () => body }
  }))
  render(<I18nProvider><MemoryRouter initialEntries={['/configuration?tab=detection']}><ConfigurationPage /></MemoryRouter></I18nProvider>)

  expect(await screen.findByText('Deteksi & Model')).toBeInTheDocument()
  await waitFor(() => expect(document.querySelector('#fps-1')).not.toBeNull())
  await userEvent.type(document.querySelector('#fps-1') as HTMLInputElement, '8')
  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/cameras/1') && c.init?.method === 'PATCH')
    expect(JSON.parse(String(patch!.init!.body))).toEqual({ ai_fps: 8 })
  })
  await userEvent.click(screen.getByText('Advanced'))
  await userEvent.clear(screen.getByLabelText('Motion threshold'))
  await userEvent.type(screen.getByLabelText('Motion threshold'), '30')
  await userEvent.click(screen.getByRole('button', { name: 'Simpan setelan global' }))
  await waitFor(() => expect(calls.some((c) => c.url.endsWith('/detector-settings') && c.init?.method === 'PUT')).toBe(true))
  const put = calls.find((c) => c.url.endsWith('/detector-settings') && c.init?.method === 'PUT')
  const sent = JSON.parse(String(put?.init?.body))
  expect(sent).toMatchObject({
    motion_threshold: 30, face_min_width_px: 80, face_min_det_score: 0.6,
    face_max_yaw: 0.35, face_blur_min: 120, face_min_frames: 3,
  })
  expect(sent).not.toHaveProperty('updated_at')
})

test('grup Wajah attendance di Advanced ikut tersimpan', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    const body = url.includes('/detector-settings') ? settings : url.includes('/zones') ? [zone] : url.includes('/cameras') ? [camera] : { id: 1, username: 'admin', role: 'admin' }
    return { ok: true, status: 200, json: async () => body }
  }))
  render(<I18nProvider><MemoryRouter initialEntries={['/configuration?tab=detection']}><ConfigurationPage /></MemoryRouter></I18nProvider>)

  expect(await screen.findByText('Deteksi & Model')).toBeInTheDocument()
  await userEvent.click(screen.getByText('Advanced'))
  expect(screen.getByText('Wajah attendance')).toBeInTheDocument()
  await userEvent.clear(screen.getByLabelText('Jumlah frame wajah bagus (K)'))
  await userEvent.type(screen.getByLabelText('Jumlah frame wajah bagus (K)'), '5')
  await userEvent.click(screen.getByRole('button', { name: 'Simpan setelan global' }))
  await waitFor(() => {
    const put = calls.find((c) => c.url.endsWith('/detector-settings') && c.init?.method === 'PUT')
    expect(put).toBeTruthy()
    const body = JSON.parse(String(put!.init!.body))
    expect(body.face_min_frames).toBe(5)
    expect(body.face_min_width_px).toBe(80)
  })
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

test('tabel memuat semua kamera dengan Status AI dari zona aktif, tanpa chip analyzer', async () => {
  const cams = [camera, { ...camera, id: 2, name: 'CAM-02' }, { ...camera, id: 3, name: 'CAM-03', enabled: false }]
  const zones = [
    { id: 9, camera_id: 1, name: 'Z', type: 'behavior', polygon: [], behaviors: [], trigger_seconds: 0, active: true },
    { id: 10, camera_id: 1, name: 'G', type: 'attendance', polygon: [], behaviors: [], trigger_seconds: 0, active: true },
    { id: 11, camera_id: 2, name: 'Off', type: 'behavior', polygon: [], behaviors: [], trigger_seconds: 0, active: false },
  ]
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const body = url.includes('/detector-settings') ? settings
      : url.includes('/zones') ? zones
      : url.includes('/cameras') ? cams
      : { id: 1, username: 'admin', role: 'admin' }
    return { ok: true, status: 200, json: async () => body }
  }))
  render(<I18nProvider><MemoryRouter initialEntries={['/configuration?tab=detection']}><ConfigurationPage /></MemoryRouter></I18nProvider>)

  expect(await screen.findByTestId('ai-status-1')).toHaveTextContent('Aktif · 2 zona')
  expect(screen.getByTestId('ai-status-2')).toHaveTextContent('Tidak jalan (tanpa zona aktif)')
  expect(screen.getByTestId('ai-status-3')).toHaveTextContent('Kamera nonaktif')
  expect(document.querySelectorAll('.det-chip')).toHaveLength(0)
  expect(screen.getByText('InsightFace buffalo_l')).toBeInTheDocument()
  expect(screen.getByText('lepas track setelah 3 s')).toBeInTheDocument()
  expect((document.querySelector('#fps-1') as HTMLInputElement).placeholder).toBe('5')
})

test('reset override tidak lagi mengirim analyzers', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    const body = url.includes('/detector-settings') ? settings : url.includes('/zones') ? [zone]
      : url.includes('/cameras') ? [camera] : { id: 1, username: 'admin', role: 'admin' }
    return { ok: true, status: 200, json: async () => body }
  }))
  render(<I18nProvider><MemoryRouter initialEntries={['/configuration?tab=detection']}><ConfigurationPage /></MemoryRouter></I18nProvider>)
  await userEvent.click(await screen.findByRole('button', { name: 'Reset override' }))
  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/cameras/1') && c.init?.method === 'PATCH')
    expect(JSON.parse(String(patch!.init!.body))).toEqual({ ai_fps: null, confidence: null, motion_enabled: null })
  })
})
