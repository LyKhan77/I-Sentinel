import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { I18nProvider } from '../app/i18n'
import ConfigurationPage from '../features/config/ConfigurationPage'
import type { AiTestResult } from '../api/aiSettings'

const INITIAL = {
  enabled: true, api_url: 'https://llm.test/v1', model: 'env-model', max_tokens: 1000,
  timeout_caption_s: 60, timeout_ask_s: 120, ask_rate_per_min: 6, caption_min_interval_s: 60,
  extra_body: { chat_template_kwargs: { enable_thinking: false } }, key_configured: true,
  sources: { enabled: 'default', api_url: 'env', model: 'env', max_tokens: 'db', timeout_caption_s: 'default',
    timeout_ask_s: 'default', ask_rate_per_min: 'default', caption_min_interval_s: 'default', extra_body: 'default' },
  restart_only: { concurrency: 2, queue_max: 100 },
}
const RESULT: AiTestResult = { ok: true, vision_ok: true, latency_ms: 42, model: 'form-model', error: null }
type Call = { url: string; method: string; body?: Record<string, unknown> }

function stub(status = 200, result = RESULT, getStatus = 200) {
  const calls: Call[] = []
  let current = structuredClone(INITIAL)
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined
    calls.push({ url: String(url), method, body })
    let code = 200
    let data: unknown = []
    if (String(url).endsWith('/ai/settings/test')) {
      code = status
      data = result
    } else if (String(url).endsWith('/ai/settings')) {
      code = method === 'GET' ? getStatus : status
      if (method === 'PUT' && code === 200) {
        for (const [field, value] of Object.entries(body ?? {})) {
          if (field === 'api_key') current.key_configured = true
          else if (field === 'clear_api_key') current.key_configured = false
          else {
            current = { ...current, [field]: value === null ? INITIAL[field as keyof typeof INITIAL] : value }
          }
        }
      }
      data = structuredClone(current)
    } else if (String(url).endsWith('/storage/stats')) {
      data = { retention_days: 30, settings: { clip_days: 30, snapshot_days: 30, attendance_days: 90, disk_alert_percent: 85 },
        disk_alert: { threshold: 85, over: false }, storage_root: '/data/test',
        disk: { total: 1000, used: 100, free: 900, percent: 10 }, kinds: {}, last_sweep: null }
    }
    return { ok: code < 400, status: code, json: async () => data }
  }))
  return calls
}

function mount(role: 'admin' | 'viewer' = 'admin') {
  return render(<I18nProvider><MemoryRouter initialEntries={['/configuration?tab=ai']}><Routes>
    <Route element={<Outlet context={{ id: 1, username: role, role }} />}>
      <Route path="/configuration" element={<ConfigurationPage />} />
    </Route>
  </Routes></MemoryRouter></I18nProvider>)
}

async function form() {
  mount()
  return screen.findByLabelText('Model LLM')
}

beforeEach(() => localStorage.clear())

test('test_tab_hidden_for_viewer_without_api_calls', async () => {
  const calls = stub()
  const viewer = mount('viewer')
  expect(await screen.findByRole('tab', { name: 'Retensi & Storage' })).toBeInTheDocument()
  expect(screen.queryByRole('tab', { name: 'AI Integration' })).not.toBeInTheDocument()
  expect(calls.some(call => call.url.includes('/ai/settings'))).toBe(false)
  viewer.unmount()
  mount('admin')
  expect(await screen.findByRole('tab', { name: 'AI Integration', selected: true })).toBeInTheDocument()
})

test('test_renders_values_and_never_prefills_key', async () => {
  stub()
  expect(await form()).toHaveValue('env-model')
  expect(screen.getByLabelText('URL API LLM')).toHaveValue('https://llm.test/v1')
  expect(screen.getByLabelText('Kunci API')).toHaveValue('')
  expect(screen.getByText('Kunci tersimpan')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Hapus kunci' })).toBeInTheDocument()
  expect(screen.getAllByText('Env').length).toBeGreaterThan(0)
  await userEvent.click(screen.getByRole('button', { name: 'Lanjutan' }))
  expect(screen.getByLabelText('Maksimum token')).toHaveValue(1000)
  expect(screen.getByText(/Konkurensi: 2.*Antrean: 100.*butuh restart/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Simpan' })).toBeDisabled()
})

test('test_save_sends_only_changed_fields', async () => {
  const calls = stub()
  fireEvent.change(await form(), { target: { value: 'new-model' } })
  await userEvent.click(screen.getByRole('button', { name: 'Simpan' }))
  await screen.findByText('Pengaturan AI disimpan.')
  const saved = calls.filter(call => call.method === 'PUT')
  expect(saved).toHaveLength(1)
  expect(saved[0].body).toEqual({ model: 'new-model' })
  expect(saved[0].body).not.toHaveProperty('api_key')
  expect(screen.getByRole('button', { name: 'Simpan' })).toBeDisabled()
})

test('typed key is sent once and cleared after save', async () => {
  const calls = stub()
  await form()
  fireEvent.change(screen.getByLabelText('Kunci API'), { target: { value: 'sk-form' } })
  await userEvent.click(screen.getByRole('button', { name: 'Simpan' }))
  await screen.findByText('Pengaturan AI disimpan.')
  expect(calls.find(call => call.method === 'PUT')?.body).toEqual({ api_key: 'sk-form' })
  expect(screen.getByLabelText('Kunci API')).toHaveValue('')
  fireEvent.change(screen.getByLabelText('Model LLM'), { target: { value: 'next-model' } })
  await userEvent.click(screen.getByRole('button', { name: 'Simpan' }))
  await waitFor(() => expect(calls.filter(call => call.method === 'PUT')).toHaveLength(2))
  expect(calls.filter(call => call.method === 'PUT')[1].body).toEqual({ model: 'next-model' })
})

test('test_test_connection_shows_result', async () => {
  const calls = stub()
  fireEvent.change(await form(), { target: { value: 'form-model' } })
  await userEvent.click(screen.getByRole('button', { name: 'Tes koneksi' }))
  expect(await screen.findByText(/Teks: OK.*Vision: OK.*42 ms/)).toBeInTheDocument()
  expect(calls.find(call => call.method === 'POST')?.body).toEqual({ model: 'form-model' })
  expect(calls.some(call => call.method === 'PUT')).toBe(false)
})

test('connection failure shows sanitized server error', async () => {
  stub(200, { ...RESULT, ok: false, vision_ok: false, error: 'LLM timeout' })
  await form()
  await userEvent.click(screen.getByRole('button', { name: 'Tes koneksi' }))
  expect(await screen.findByText(/LLM timeout/)).toBeInTheDocument()
})

test.each([403, 422])('save error %s is translated and clears a submitted key', async status => {
  stub(status)
  fireEvent.change(await form(), { target: { value: 'form-model' } })
  fireEvent.change(screen.getByLabelText('Kunci API'), { target: { value: 'sk-form' } })
  await userEvent.click(screen.getByRole('button', { name: 'Simpan' }))
  expect(await screen.findByText(status === 403 ? 'Hanya admin yang dapat mengatur AI.' : 'Pengaturan AI tidak valid. Periksa nilai form.')).toBeInTheDocument()
  expect(screen.getByLabelText('Kunci API')).toHaveValue('')
})

test.each([403, 422])('connection error %s is translated', async status => {
  stub(status)
  await form()
  await userEvent.click(screen.getByRole('button', { name: 'Tes koneksi' }))
  expect(await screen.findByText(status === 403 ? 'Hanya admin yang dapat mengatur AI.' : 'Pengaturan AI tidak valid. Periksa nilai form.')).toBeInTheDocument()
})

test('invalid extra_body JSON is rejected before any write or probe', async () => {
  const calls = stub()
  await form()
  await userEvent.click(screen.getByRole('button', { name: 'Lanjutan' }))
  fireEvent.change(screen.getByLabelText('Extra body (JSON)'), { target: { value: '[1]' } })
  await userEvent.click(screen.getByRole('button', { name: 'Simpan' }))
  expect(await screen.findByText('Extra body harus berupa objek JSON yang valid.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Tes koneksi' }))
  expect(calls.every(call => call.method === 'GET')).toBe(true)
})

test('blank fields reset overrides with null and clear key is explicit', async () => {
  const calls = stub()
  fireEvent.change(await form(), { target: { value: '' } })
  await userEvent.click(screen.getByRole('button', { name: 'Hapus kunci' }))
  await userEvent.click(screen.getByRole('button', { name: 'Simpan' }))
  await screen.findByText('Pengaturan AI disimpan.')
  expect(calls.find(call => call.method === 'PUT')?.body).toEqual({ model: null, clear_api_key: true })
})

test('enabled and numeric overrides can reset to environment', async () => {
  const calls = stub()
  await form()
  await userEvent.click(screen.getByRole('button', { name: 'Reset ke env: Aktifkan AI' }))
  await userEvent.click(screen.getByRole('button', { name: 'Lanjutan' }))
  fireEvent.change(screen.getByLabelText('Maksimum token'), { target: { value: '' } })
  await userEvent.click(screen.getByRole('button', { name: 'Simpan' }))
  await screen.findByText('Pengaturan AI disimpan.')
  expect(calls.find(call => call.method === 'PUT')?.body).toEqual({ enabled: null, max_tokens: null })
})

test('load 403 shows admin-only error', async () => {
  stub(200, RESULT, 403)
  mount()
  expect(await screen.findByText('Hanya admin yang dapat mengatur AI.')).toBeInTheDocument()
})
