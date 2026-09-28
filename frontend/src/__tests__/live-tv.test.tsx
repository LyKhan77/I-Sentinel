import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import LiveTvPage from '../features/live/LiveTvPage'

const cam = (id: number) => ({ id, name: `CAM-0${id}`, location: null, host: `10.0.0.${id}`, rtsp_main: null,
  rtsp_sub: null, node_id: 1, enabled: true, status: 'offline', probe_main: null, probe_sub: null })

function stubFetch() {
  return vi.fn(async (url: string) => (String(url).endsWith('/cameras')
    ? { ok: true, status: 200, json: () => Promise.resolve([cam(1), cam(2)]) }
    : { ok: false, status: 503, json: () => Promise.resolve(null) }))
}

function renderTv(entry: string) {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/live/tv" element={<LiveTvPage />} />
          <Route path="/live" element={<div data-testid="normal-live" />} />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  )
}

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

test('layar B hanya menampilkan pilihannya; perubahan di layar A tidak menimpa B', async () => {
  localStorage.setItem('isentinel_live_screen:B', JSON.stringify({ cameras: { mode: 'some', ids: [2] } }))
  vi.stubGlobal('fetch', stubFetch())
  const { unmount } = renderTv('/live/tv?screen=B')
  expect(await screen.findByTestId('cam-tile-2')).toBeInTheDocument()
  expect(screen.queryByTestId('cam-tile-1')).not.toBeInTheDocument()
  expect(screen.getByTestId('live-tv-toolbar')).toHaveTextContent('Layar B')
  unmount()

  renderTv('/live/tv?screen=A')
  expect(await screen.findByTestId('cam-tile-1')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('live-tv-cols-4'))
  await userEvent.click(screen.getByTestId('live-tv-scroll'))
  expect(JSON.parse(localStorage.getItem('isentinel_live_screen:A')!)).toMatchObject({ cols: 4, scroll: { on: true } })
  expect(JSON.parse(localStorage.getItem('isentinel_live_screen:B')!)).toEqual({ cameras: { mode: 'some', ids: [2] } })
  expect(document.querySelector('.lv-grid--tv')).toHaveStyle({ '--lv-cols': '4' })
})

test('toolbar hilang setelah 4 detik tanpa aktivitas (kursor disembunyikan) dan muncul lagi saat mouse bergerak', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', stubFetch())
  try {
    renderTv('/live/tv?screen=A')
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(screen.getByTestId('live-tv-toolbar')).toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(4000) })
    expect(screen.queryByTestId('live-tv-toolbar')).not.toBeInTheDocument()
    expect(screen.getByTestId('live-tv')).toHaveClass('lv-tv--idle')
    act(() => { window.dispatchEvent(new MouseEvent('mousemove')) })
    expect(screen.getByTestId('live-tv-toolbar')).toBeInTheDocument()
  } finally {
    vi.useRealTimers()
  }
})

test('screen ngawur → layar default; tombol Keluar kembali ke /live', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderTv('/live/tv?screen=%3Cx%3E')
  expect(await screen.findByTestId('live-tv-toolbar')).toHaveTextContent('Layar default')
  await userEvent.click(screen.getByTestId('live-tv-exit'))
  expect(screen.getByTestId('normal-live')).toBeInTheDocument()
})
