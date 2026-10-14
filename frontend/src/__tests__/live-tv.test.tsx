import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation, useNavigationType } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import LiveTvPage from '../features/live/LiveTvPage'

const cam = (id: number) => ({ id, name: `CAM-0${id}`, location: null, host: `10.0.0.${id}`, rtsp_main: null,
  rtsp_sub: null, node_id: 1, enabled: true, status: 'offline', probe_main: null, probe_sub: null })

function stubFetch(cams = [cam(1), cam(2)]) {
  return vi.fn(async (url: string) => (String(url).endsWith('/cameras')
    ? { ok: true, status: 200, json: () => Promise.resolve(cams) }
    : { ok: false, status: 503, json: () => Promise.resolve(null) }))
}

// tiga kamera aktif (1, 2) + satu nonaktif (3) untuk uji filter URL
const TV_CAMS = [cam(1), cam(2), { ...cam(3), enabled: false }]

function tileIds() {
  return [...document.querySelectorAll('[data-testid^="cam-tile-"]')].map((el) => el.getAttribute('data-testid'))
}

// Probe lokasi: query URL dan jenis navigasi (REPLACE bila toolbar menulis ulang URL tanpa entri riwayat)
function LocationProbe() {
  const loc = useLocation()
  const nav = useNavigationType()
  return <div data-testid="loc" data-search={loc.search} data-nav={nav} />
}
const searchOf = () => new URLSearchParams(screen.getByTestId('loc').getAttribute('data-search') ?? '')
const navType = () => screen.getByTestId('loc').getAttribute('data-nav')

function renderTv(entry: string) {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[entry]}>
        <LocationProbe />
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

test('cameras=2,1 menampilkan tile 2 lalu 1 meski pengaturan tersimpan "semua"', async () => {
  localStorage.setItem('isentinel_live_screen:A', JSON.stringify({ cameras: { mode: 'all' } }))
  vi.stubGlobal('fetch', stubFetch(TV_CAMS))
  renderTv('/live/tv?screen=A&cameras=2,1')
  expect(await screen.findByTestId('cam-tile-2')).toBeInTheDocument()
  expect(tileIds()).toEqual(['cam-tile-2', 'cam-tile-1'])
})

test('ID tak dikenal, nonaktif, dan duplikat dilewati', async () => {
  vi.stubGlobal('fetch', stubFetch(TV_CAMS))
  renderTv('/live/tv?screen=A&cameras=3,9,2,2')
  expect(await screen.findByTestId('cam-tile-2')).toBeInTheDocument()
  expect(tileIds()).toEqual(['cam-tile-2'])
})

test('cameras ada tapi tidak ada yang cocok → pesan URL, bukan semua kamera', async () => {
  vi.stubGlobal('fetch', stubFetch(TV_CAMS))
  const { unmount } = renderTv('/live/tv?screen=A&cameras=9')
  expect(await screen.findByTestId('live-tv-url-empty')).toBeInTheDocument()
  expect(tileIds()).toEqual([])
  unmount()
  renderTv('/live/tv?screen=A&cameras=')
  expect(await screen.findByTestId('live-tv-url-empty')).toBeInTheDocument()
  expect(tileIds()).toEqual([])
})

test('toolbar tetap aktif saat URL berparameter (tidak ada kontrol terkunci)', async () => {
  vi.stubGlobal('fetch', stubFetch(TV_CAMS))
  renderTv('/live/tv?screen=A&cameras=1&cols=2&scroll=on&speed=fast')
  expect(await screen.findByTestId('cam-tile-1')).toBeInTheDocument()
  for (const id of ['live-tv-cols-3', 'live-tv-scroll', 'live-tv-speed-slow', 'live-picker-open', 'live-tv-sound', 'live-tv-exit']) {
    expect(screen.getByTestId(id)).toBeEnabled()
  }
  expect(screen.queryByTestId('live-tv-locked')).not.toBeInTheDocument()
})

test('membuka URL tidak mengubah URL dan tidak menulis localStorage', async () => {
  vi.stubGlobal('fetch', stubFetch(TV_CAMS))
  renderTv('/live/tv?screen=A&cameras=2,1&cols=2')
  expect(await screen.findByTestId('cam-tile-2')).toBeInTheDocument()
  expect(screen.getByTestId('loc')).toHaveAttribute('data-search', '?screen=A&cameras=2,1&cols=2')
  expect(navType()).toBe('POP')
  expect(localStorage.length).toBe(0)
})

test('klik kolom menulis ulang URL (REPLACE), screen dipertahankan, localStorage layar ikut', async () => {
  vi.stubGlobal('fetch', stubFetch(TV_CAMS))
  renderTv('/live/tv?screen=A&cameras=2,1&cols=2')
  expect(await screen.findByTestId('cam-tile-2')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('live-tv-cols-4'))
  const p = searchOf()
  expect(p.get('screen')).toBe('A')
  expect(p.get('cameras')).toBe('2,1')
  expect(p.get('cols')).toBe('4')
  expect(navType()).toBe('REPLACE')
  expect(screen.getByTestId('loc').getAttribute('data-search')).toContain('cameras=2,1') // koma terbaca, bukan %2C
  expect(JSON.parse(localStorage.getItem('isentinel_live_screen:A')!)).toMatchObject({ cols: 4 })
  expect(document.querySelector('.lv-grid--tv')).toHaveStyle({ '--lv-cols': '4' })
})

test('scroll dan speed menulis scroll=on/off dan speed=… ke URL', async () => {
  vi.stubGlobal('fetch', stubFetch(TV_CAMS))
  renderTv('/live/tv?screen=A&cameras=1&scroll=on&speed=fast')
  expect(await screen.findByTestId('cam-tile-1')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('live-tv-scroll'))
  expect(searchOf().get('scroll')).toBe('off')
  expect(searchOf().get('speed')).toBe('fast') // speed dari URL tidak tertimpa nilai tersimpan
  await userEvent.click(screen.getByTestId('live-tv-speed-slow'))
  expect(searchOf().get('speed')).toBe('slow')
  expect(searchOf().get('cameras')).toBe('1')
  expect(JSON.parse(localStorage.getItem('isentinel_live_screen:A')!)).toMatchObject({ scroll: { on: false, speed: 'slow' } })
})

test('pemilih: ID lama menjaga urutan, ID baru ditambahkan di akhir', async () => {
  vi.stubGlobal('fetch', stubFetch(TV_CAMS))
  renderTv('/live/tv?screen=A&cameras=2')
  expect(await screen.findByTestId('cam-tile-2')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('live-picker-open'))
  await userEvent.click(screen.getByLabelText('CAM-01'))
  expect(searchOf().get('cameras')).toBe('2,1')
  expect(tileIds()).toEqual(['cam-tile-2', 'cam-tile-1'])
})

test('pemilih: Semua menulis semua ID aktif (urutan lama dijaga), Kosongkan menulis cameras= dan memunculkan pesan URL', async () => {
  vi.stubGlobal('fetch', stubFetch(TV_CAMS))
  renderTv('/live/tv?screen=A&cameras=2')
  expect(await screen.findByTestId('cam-tile-2')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('live-picker-open'))
  await userEvent.click(screen.getByTestId('live-picker-all'))
  expect(searchOf().get('cameras')).toBe('2,1') // 2 sudah ada lebih dulu, 1 ditambahkan di akhir
  await userEvent.click(screen.getByTestId('live-picker-none'))
  expect(searchOf().get('cameras')).toBe('')
  expect(await screen.findByTestId('live-tv-url-empty')).toBeInTheDocument()
  expect(tileIds()).toEqual([])
})

test('URL tanpa parameter + satu edit menghasilkan URL lengkap dari pengaturan tersimpan', async () => {
  localStorage.setItem('isentinel_live_screen:A', JSON.stringify({ cols: 4 }))
  vi.stubGlobal('fetch', stubFetch(TV_CAMS))
  renderTv('/live/tv?screen=A')
  expect(await screen.findByTestId('cam-tile-1')).toBeInTheDocument()
  expect(screen.getByTestId('loc')).toHaveAttribute('data-search', '?screen=A')
  await userEvent.click(screen.getByTestId('live-tv-scroll'))
  const p = searchOf()
  expect(p.get('screen')).toBe('A')
  expect(p.get('cameras')).toBe('1,2')
  expect(p.get('cols')).toBe('4')
  expect(p.get('scroll')).toBe('on')
  expect(p.get('speed')).toBe('medium')
})

test('mode URL: label pemilih menghitung kamera dari URL, bukan dari pengaturan tersimpan', async () => {
  vi.stubGlobal('fetch', stubFetch(TV_CAMS))
  renderTv('/live/tv?screen=A&cameras=1')
  expect(await screen.findByTestId('cam-tile-1')).toBeInTheDocument()
  expect(tileIds()).toEqual(['cam-tile-1'])
  // 2 kamera aktif, 1 dipilih URL; pengaturan tersimpan "semua" tidak boleh membuatnya terbaca 2/2
  expect(screen.getByTestId('live-picker-open')).toHaveTextContent('Kamera (1/2)')
  // ID tak dikenal/nonaktif tidak ikut terhitung
  expect(localStorage.length).toBe(0)
})

test('tanpa cameras di URL: label pemilih tetap dari pengaturan tersimpan', async () => {
  localStorage.setItem('isentinel_live_screen:A', JSON.stringify({ cameras: { mode: 'some', ids: [2] } }))
  vi.stubGlobal('fetch', stubFetch(TV_CAMS))
  renderTv('/live/tv?screen=A')
  expect(await screen.findByTestId('cam-tile-2')).toBeInTheDocument()
  expect(screen.getByTestId('live-picker-open')).toHaveTextContent('Kamera (1/2)')
})
