import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import LiveViewPage from '../features/live/LiveViewPage'

const CAMS = [
  { id: 1, name: 'CAM-01', location: null, host: '192.168.1.101', rtsp_main: null, rtsp_sub: null, node_id: 1, enabled: true, status: 'online', probe_main: null, probe_sub: null },
  { id: 2, name: 'CAM-02', location: null, host: '192.168.1.102', rtsp_main: null, rtsp_sub: null, node_id: 1, enabled: true, status: 'offline', probe_main: null, probe_sub: null },
]

function stubFetch() {
  return vi.fn(async (url: string) => {
    const u = String(url)
    if (u.endsWith('/cameras')) return { ok: true, status: 200, json: () => Promise.resolve(CAMS) }
    if (u.endsWith('/cameras/1/live')) {
      return {
        ok: true,
        status: 200,
        json: () => Promise.resolve({ camera_id: 1, streams: { sub: 'go2rtc/1?video=sub' }, webrtc: 'wss://x/api/ws?src=cam_1', snapshot: 'go2rtc/api/frame.jpeg?src=cam_1' }),
      }
    }
    if (u.endsWith('/cameras/2/live')) return { ok: false, status: 503, json: () => Promise.resolve(null) }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
}

function renderPage() {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/live']}>
        <LiveViewPage />
      </MemoryRouter>
    </I18nProvider>,
  )
}

beforeEach(() => localStorage.clear())

test('jumlah kolom: default 3, pilihan persist, nilai ngawur di localStorage jatuh ke 3', async () => {
  vi.stubGlobal('fetch', stubFetch())

  // nilai ngawur (bukan 2/3/4) → default 3, jangan sampai jadi 0 kolom
  localStorage.setItem('isentinel_live_cols', '99')
  const { unmount } = renderPage()
  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  expect(screen.getByTestId('live-cols-3')).toHaveAttribute('aria-pressed', 'true')
  expect(document.querySelector('.lv-grid')).toHaveStyle({ '--lv-cols': '3' })
  unmount()

  // pilih 2 → tersimpan
  renderPage()
  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  await userEvent.click(screen.getByTestId('live-cols-2'))
  expect(localStorage.getItem('isentinel_live_cols')).toBe('2')
  expect(screen.getByTestId('live-cols-2')).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByTestId('live-cols-3')).toHaveAttribute('aria-pressed', 'false')
  expect(document.querySelector('.lv-grid')).toHaveStyle({ '--lv-cols': '2' })
})

test('renders camera tiles with snapshot URLs from /live', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()

  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  expect(screen.getByText('CAM-02')).toBeInTheDocument()

  const img1 = screen.getByAltText('CAM-01') as HTMLImageElement
  expect(img1.src).toContain('go2rtc/api/frame.jpeg?src=cam_1')

  // kamera /live gagal → tile tanpa img snapshot
  expect(screen.queryByAltText('CAM-02')).not.toBeInTheDocument()
})

test('click tile focuses it (moves to big slot)', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()

  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  const tile1 = screen.getByTestId('cam-tile-1')
  const user = userEvent.setup()
  await user.click(tile1)

  // fokus: tile CAM-01 ada dua render (besar + strip)? Tidak — fokus mengeluarkannya dari grid
  const tiles1 = screen.getAllByTestId('cam-tile-1')
  expect(tiles1.length).toBe(1)
  expect(tiles1[0].dataset.big ?? '').toBe('big')
})
