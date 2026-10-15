import { act, renderHook, waitFor } from '@testing-library/react'
import { useLiveCameras } from '../features/live/useLiveCameras'

const cam = (id: number, enabled = true) => ({
  id, name: `CAM-${id}`, location: null, host: `10.0.0.${id}`, rtsp_main: null, rtsp_sub: null, node_id: 1,
  enabled, status: 'online', probe_main: null, probe_sub: null,
})

// 1, 2, 3, 5 aktif; 4 nonaktif
const CAMS = [cam(1), cam(2), cam(3), cam(4, false), cam(5)]

function stub() {
  const calls: string[] = []
  const f = vi.fn(async (url: string) => {
    const u = String(url)
    calls.push(u)
    const live = /\/cameras\/(\d+)\/live$/.exec(u)
    if (u.endsWith('/cameras')) return { ok: true, status: 200, json: () => Promise.resolve(CAMS) }
    if (live) return { ok: true, status: 200, json: () => Promise.resolve({ camera_id: Number(live[1]) }) }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
  const liveIds = () => calls.filter((u) => /\/live$/.test(u)).map((u) => Number(/cameras\/(\d+)\/live/.exec(u)![1]))
  return { f, liveIds, reset: () => { calls.length = 0 } }
}

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

const loaded = (r: { current: ReturnType<typeof useLiveCameras> }) => waitFor(() => expect(r.current.loading).toBe(false))
const keys = (r: { current: ReturnType<typeof useLiveCameras> }) => Object.keys(r.current.lives).map(Number).sort((a, b) => a - b)

test('wanted=[1,2]: /live hanya untuk kamera yang tampil', async () => {
  const s = stub()
  vi.stubGlobal('fetch', s.f)
  const { result } = renderHook(() => useLiveCameras([1, 2]))
  await loaded(result)
  await waitFor(() => expect(keys(result)).toEqual([1, 2]))
  expect(s.liveIds().sort()).toEqual([1, 2])
})

test('kamera nonaktif dan ID tak dikenal di wanted tidak pernah diambil', async () => {
  const s = stub()
  vi.stubGlobal('fetch', s.f)
  const { result } = renderHook(() => useLiveCameras([4, 99, 2]))
  await loaded(result)
  await waitFor(() => expect(keys(result)).toEqual([2]))
  expect(s.liveIds()).toEqual([2])
})

test('wanted=null: semua kamera aktif (tanpa yang nonaktif), seperti perilaku lama', async () => {
  const s = stub()
  vi.stubGlobal('fetch', s.f)
  const { result } = renderHook(() => useLiveCameras(null))
  await loaded(result)
  await waitFor(() => expect(keys(result)).toEqual([1, 2, 3, 5]))
  expect(s.liveIds().sort()).toEqual([1, 2, 3, 5])
})

test('himpunan berubah: hanya ID baru yang diambil segera, ID lama tidak diambil ulang', async () => {
  const s = stub()
  vi.stubGlobal('fetch', s.f)
  const { result, rerender } = renderHook(({ w }: { w: number[] | null }) => useLiveCameras(w), { initialProps: { w: [1, 2] as number[] | null } })
  await loaded(result)
  await waitFor(() => expect(keys(result)).toEqual([1, 2]))
  s.reset()
  rerender({ w: [1, 2, 3] })
  await waitFor(() => expect(keys(result)).toEqual([1, 2, 3]))
  expect(s.liveIds()).toEqual([3])
  s.reset()
  rerender({ w: [2] }) // dikurangi: tidak ada permintaan, info yang tak tampil dibuang
  await waitFor(() => expect(keys(result)).toEqual([2]))
  expect(s.liveIds()).toEqual([])
})

test('refresh 30 detik hanya untuk himpunan saat ini', async () => {
  vi.useFakeTimers()
  const s = stub()
  vi.stubGlobal('fetch', s.f)
  renderHook(() => useLiveCameras([1, 2]))
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
  s.reset()
  await act(async () => { await vi.advanceTimersByTimeAsync(30000) })
  expect(s.liveIds().sort()).toEqual([1, 2])
})
