import type { Mock } from 'vitest'
import { act } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import AskAiPanel from '../features/events/AskAiPanel'
import EventsPage from '../features/events/EventsPage'
import type { AiStatus, AiRow } from '../api/ai'
import type { EventOut } from '../api/events'

const EVENT: EventOut = { id: 1, event_id: 'ev-1', type: 'idle_zone', camera_id: 1, zone_id: 1, severity: 'warning',
  ts_event: '2026-10-02T08:00:00Z', payload: null, snapshot_path: 'synthetic.jpg', clip_path: null }
const STATUS: AiStatus = { enabled: true, presets: { idle_zone: ['what_happened', 'false_alarm', 'report', 'person_in_zone', 'last_person', 'fallen'] }, caption_prompts: {} }
const CAPTION: AiRow = { id: 1, kind: 'caption', preset: null, question: null, answer: 'Area terlihat kosong.', status: 'ok', error: null,
  model: 'test-model', channel: 'auto', actor: null, created_at: EVENT.ts_event }

function stub(opts: { caption?: AiRow | null; answer?: string; status?: number; code?: string; enabled?: boolean; type?: string } = {}) {
  const f = vi.fn(async (url: string, _init?: RequestInit) => {
    const u = String(url)
    const data = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body })
    if (u.endsWith('/ai/status')) return data({ ...STATUS, enabled: opts.enabled ?? true })
    if (u.endsWith('/ask')) return opts.status ? data({ detail: opts.code }, opts.status)
      : data({ answer: opts.answer ?? 'Satu orang bergerak.', frames_used: 6, cached: false, latency_ms: 123, model: 'test-model' })
    if (u.endsWith('/ai')) return data({ caption: opts.caption === undefined ? CAPTION : opts.caption, history: [] })
    if (u.includes('/events?')) return data([{ ...EVENT, type: opts.type ?? EVENT.type }])
    if (u.endsWith('/cameras')) return data([{ id: 1, name: 'CAM-01' }])
    if (u.endsWith('/zones')) return data([{ id: 1, name: 'Area' }])
    return data(null, 404)
  })
  vi.stubGlobal('fetch', f)
  return f
}
function panel(event = EVENT, status = STATUS, open = true) {
  const view = render(<I18nProvider><AskAiPanel event={event} status={status} tick={0} /></I18nProvider>)
  // bagian Tanya AI tertutup secara default; tes lama berinteraksi dengannya, jadi dibuka di sini
  if (open) fireEvent.click(screen.getByRole('button', { name: 'Tanya AI' }))
  return view
}
const posts = (f: Mock) => f.mock.calls.filter(([u, init]) => String(u).endsWith('/ask') && init?.method === 'POST')

 test('caption ok memakai lencana Dibuat AI', async () => {
  stub(); panel()
  expect(await screen.findByText('Area terlihat kosong.')).toBeInTheDocument()
  expect(screen.getByText('Dibuat AI')).toBeInTheDocument()
})

test.each([['pending', 'Menunggu caption…'], ['failed', 'Caption gagal dibuat.']] as const)('caption %s menampilkan status', async (status, text) => {
  stub({ caption: { ...CAPTION, status, answer: null, error: status === 'failed' ? 'timeout' : null } }); panel()
  expect(await screen.findByText(text)).toBeInTheDocument()
})

test('enam chip sesuai tipe; preset dikirim, jawaban dan frame tampil', async () => {
  const f = stub(); const { container } = panel()
  await screen.findByText('Area terlihat kosong.')
  expect(container.querySelectorAll('.ev-ai__presets button')).toHaveLength(6)
  fireEvent.click(screen.getByRole('button', { name: 'Apa yang terjadi?' }))
  expect(await screen.findByText('Satu orang bergerak.')).toBeInTheDocument()
  expect(screen.getByText('Frame yang dipakai: 6')).toBeInTheDocument()
  expect(JSON.parse(String(posts(f)[0][1]!.body))).toEqual({ preset: 'what_happened', history: [] })
})

test('pertanyaan berikutnya mengirim riwayat browser maksimal enam giliran', async () => {
  const f = stub(); panel()
  for (let i = 0; i < 8; i++) {
    fireEvent.change(screen.getByLabelText('Pertanyaan untuk AI'), { target: { value: `q${i}` } })
    fireEvent.click(screen.getByRole('button', { name: 'Kirim pertanyaan' }))
    await waitFor(() => expect(posts(f)).toHaveLength(i + 1))
    await waitFor(() => expect(screen.getByLabelText('Pertanyaan untuk AI')).toHaveValue(''))
  }
  const second = JSON.parse(String(posts(f)[1][1]!.body))
  expect(second.history).toEqual([{ q: 'q0', a: 'Satu orang bergerak.' }])
  const last = JSON.parse(String(posts(f)[7][1]!.body))
  expect(last.history).toHaveLength(6)
  expect(last.history[0].q).toBe('q1')
})

test.each([[429, 'rate_limited', 'Batas pertanyaan tercapai. Coba lagi dalam satu menit.'],
  [503, 'busy', 'AI sibuk. Coba lagi sebentar.'], [503, 'disabled', 'AI sedang nonaktif.'],
  [409, 'media_expired', 'Media event sudah kedaluwarsa.']] as const)('galat %s/%s ramah', async (status, code, text) => {
  stub({ status, code }); panel()
  fireEvent.click(screen.getByRole('button', { name: 'Apa yang terjadi?' }))
  expect(await screen.findByText(text)).toBeInTheDocument()
})

test('media habis menonaktifkan input dan chip', async () => {
  stub(); const { container } = panel({ ...EVENT, snapshot_path: null, clip_path: null })
  expect(screen.getByLabelText('Pertanyaan untuk AI')).toBeDisabled()
  for (const button of container.querySelectorAll('.ev-ai__presets button')) expect(button).toBeDisabled()
})

test('test_answer_markup_rendered_as_text', async () => {
  const answer = '<img src=x onerror=alert(1)>'
  stub({ answer }); const { container } = panel()
  fireEvent.click(screen.getByRole('button', { name: 'Apa yang terjadi?' }))
  expect(await screen.findByText(answer)).toBeInTheDocument()
  expect(container.querySelector('img[src="x"]')).toBeNull()
})

class FakeWs {
  static instance: FakeWs
  onmessage: ((ev: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  constructor() { FakeWs.instance = this }
  close() {}
}
function page() { return render(<I18nProvider><MemoryRouter initialEntries={['/events?event=1']}><EventsPage /></MemoryRouter></I18nProvider>) }

test.each([[false, 'idle_zone'], [true, 'attendance'], [true, 'system']] as const)('EventsPage sembunyi panel enabled=%s tipe=%s', async (enabled, type) => {
  const f = stub({ enabled, type }); page()
  await waitFor(() => expect(f.mock.calls.some(([u]) => String(u).endsWith('/ai/status'))).toBe(true))
  await screen.findByTestId('event-detail')
  expect(screen.queryByText('Tanya AI')).not.toBeInTheDocument()
})

test('WS kind ai memicu refetch caption', async () => {
  const f = stub(); vi.stubGlobal('WebSocket', FakeWs); page()
  await screen.findByText('Area terlihat kosong.')
  const before = f.mock.calls.filter(([u]) => String(u).endsWith('/events/1/ai')).length
  act(() => FakeWs.instance.onmessage?.({ data: JSON.stringify({ kind: 'ai', event_id: 1, status: 'ok' }) }))
  await waitFor(() => expect(f.mock.calls.filter(([u]) => String(u).endsWith('/events/1/ai')).length).toBeGreaterThan(before))
})

test('ganti event mereset percakapan browser', async () => {
  const f = stub()
  const view = panel()
  fireEvent.change(screen.getByLabelText('Pertanyaan untuk AI'), { target: { value: 'q lama' } })
  fireEvent.click(screen.getByRole('button', { name: 'Kirim pertanyaan' }))
  await screen.findByText('Satu orang bergerak.')
  view.rerender(<I18nProvider><AskAiPanel event={{ ...EVENT, id: 2 }} status={STATUS} tick={0} /></I18nProvider>)
  expect(screen.queryByText('q lama')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Pertanyaan untuk AI')).not.toBeInTheDocument() // event baru: bagian Tanya AI tertutup lagi
  fireEvent.click(screen.getByRole('button', { name: 'Tanya AI' }))
  fireEvent.change(screen.getByLabelText('Pertanyaan untuk AI'), { target: { value: 'q baru' } })
  fireEvent.click(screen.getByRole('button', { name: 'Kirim pertanyaan' }))
  await waitFor(() => expect(posts(f)).toHaveLength(2))
  expect(JSON.parse(String(posts(f)[1][1]!.body)).history).toEqual([])
})

test('event hanya-klip: input nonaktif dengan pesan snapshot, bukan media kedaluwarsa', async () => {
  stub(); const { container } = panel({ ...EVENT, snapshot_path: null, clip_path: 'clip.mp4' })
  await screen.findByText('Area terlihat kosong.')
  expect(screen.getByLabelText('Pertanyaan untuk AI')).toBeDisabled()
  for (const button of container.querySelectorAll('.ev-ai__presets button')) expect(button).toBeDisabled()
  expect(screen.getByText('Snapshot event tidak tersedia; Tanya AI membutuhkan snapshot.')).toBeInTheDocument()
  expect(screen.queryByText('Media event sudah kedaluwarsa.')).not.toBeInTheDocument()
})

test('409 snapshot_unavailable dari server memakai pesan snapshot', async () => {
  stub({ status: 409, code: 'snapshot_unavailable' }); panel()
  fireEvent.click(screen.getByRole('button', { name: 'Apa yang terjadi?' }))
  expect(await screen.findByText('Snapshot event tidak tersedia; Tanya AI membutuhkan snapshot.')).toBeInTheDocument()
  expect(screen.queryByText('Media event sudah kedaluwarsa.')).not.toBeInTheDocument()
})

test('caption pending dipantau lewat polling sampai selesai, tanpa pesan WS', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  try {
    let reads = 0
    const f = vi.fn(async (url: string) => {
      const u = String(url)
      const data = (body: unknown) => ({ ok: true, status: 200, json: async () => body })
      if (u.endsWith('/ai')) {
        reads += 1
        return data({ caption: reads === 1 ? { ...CAPTION, status: 'pending', answer: null } : CAPTION, history: [] })
      }
      return { ok: false, status: 404, json: async () => null }
    })
    vi.stubGlobal('fetch', f)
    panel()
    expect(await screen.findByText('Menunggu caption…')).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(await screen.findByText('Area terlihat kosong.')).toBeInTheDocument()
    const afterDone = reads
    await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
    expect(reads).toBe(afterDone)
  } finally {
    vi.useRealTimers()
  }
})

test('Tanya AI tertutup secara default dan terbuka lewat tombol', async () => {
  stub(); const { container } = panel(EVENT, STATUS, false)
  await screen.findByText('Area terlihat kosong.')
  const toggle = screen.getByRole('button', { name: 'Tanya AI' })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  expect(screen.queryByLabelText('Pertanyaan untuk AI')).not.toBeInTheDocument()
  expect(container.querySelectorAll('.ev-ai__presets button')).toHaveLength(0)
  fireEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByLabelText('Pertanyaan untuk AI')).toBeInTheDocument()
  expect(container.querySelectorAll('.ev-ai__presets button')).toHaveLength(6)
})

test('caption ok disorot sedangkan caption belum ada hanya satu baris redup', async () => {
  stub(); const first = panel(EVENT, STATUS, false)
  await screen.findByText('Area terlihat kosong.')
  expect(first.container.querySelector('.ev-ai__caption--ok')).toHaveTextContent('Area terlihat kosong.')
  expect(first.container.querySelector('.ev-ai__caption--ok')).toHaveTextContent('Dibuat AI')
  first.unmount()
  stub({ caption: null }); const second = panel(EVENT, STATUS, false)
  await screen.findByText('Belum ada caption otomatis.')
  expect(second.container.querySelector('.ev-ai__caption--ok')).toBeNull()
  expect(second.container.querySelector('.ev-ai__caption--muted')).not.toBeNull()
})

test('jawaban kronologi tampil sebagai linimasa rapi', async () => {
  stub({ answer: 'Pria berdiri lalu pergi.\n0:03 — Berdiri memegang ponsel\n0:09 — Berjalan ke kamera\nKesimpulan: Keluar bingkai.' })
  const { container } = panel()
  fireEvent.click(screen.getByRole('button', { name: 'Apa yang terjadi?' }))
  await screen.findByText('Berjalan ke kamera')
  expect(Array.from(container.querySelectorAll('.ev-ai__turn .ev-ai-time')).map(e => e.textContent)).toEqual(['0:03', '0:09'])
  expect(container.querySelector('.ev-ai__turn .ev-ai-conclusion')).not.toBeNull()
})

test('EventsPage menaruh blok AI di bawah meta grid', async () => {
  stub(); const { container } = page()
  await screen.findByText('Area terlihat kosong.')
  const grid = container.querySelector('.ev-meta-grid')!
  const ai = container.querySelector('.ev-ai')!
  expect(grid.compareDocumentPosition(ai) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})
