import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import ConfigurationPage from '../features/config/ConfigurationPage'

const camera = { id: 1, name: 'CAM-01', location: null, host: '1.2.3.4', rtsp_main: null, rtsp_sub: null, main_path: null, sub_path: null, node_id: 1, source_id: null, location_group_id: null, credential_override_id: null, source: null, location_group: null, credential_override: null, enabled: true, status: 'online', probe_main: null, probe_sub: null, ai_fps: null, confidence: null, analyzers: null, motion_enabled: null }
const settings = { default_ai_fps: 5, default_confidence: 0.4, motion_enabled: true, motion_threshold: 25, motion_min_area: 0.01, motion_force_interval_s: 2, updated_at: '2026-09-22T00:00:00Z' }

test('detection tab updates analyzer and global motion settings', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    const body = url.endsWith('/detector-settings') ? settings : url.endsWith('/cameras') ? [camera] : { id: 1, username: 'admin', role: 'admin' }
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
