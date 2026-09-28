import {
  defaultCols, loadPrefs, savePrefs, screenName, selectCameras, setCameras, type ScreenPrefs,
} from '../features/live/screenPrefs'

const CAMS = [{ id: 1 }, { id: 2 }, { id: 3 }]

beforeEach(() => localStorage.clear())

test('screenName: hanya huruf/angka/-/_ maks 32, selain itu default', () => {
  expect(screenName('A')).toBe('A')
  expect(screenName('tv-kiri_2')).toBe('tv-kiri_2')
  for (const bad of [null, undefined, '', 'a b', '<x>', 'x'.repeat(33)]) expect(screenName(bad)).toBe('default')
})

test('pengaturan per layar terpisah: layar A tidak menimpa layar B', () => {
  const a: ScreenPrefs = { cols: 4, cameras: { mode: 'some', ids: [2] }, scroll: { on: true, speed: 'fast' } }
  savePrefs('A', a)
  expect(loadPrefs('A')).toEqual(a)
  expect(loadPrefs('B')).toEqual({ cols: 3, cameras: { mode: 'all' }, scroll: { on: false, speed: 'medium' } })
})

test('nilai rusak jatuh ke default per field; legacy kolom hanya untuk layar default', () => {
  localStorage.setItem('isentinel_live_screen:A', '{"cols": 7, "cameras": {"mode":"some","ids":[1,"x",2.5]}, "scroll": {"on":"yes","speed":"toString"}}')
  expect(loadPrefs('A')).toEqual({ cols: 3, cameras: { mode: 'some', ids: [1] }, scroll: { on: false, speed: 'medium' } })
  localStorage.setItem('isentinel_live_screen:B', 'bukan json')
  expect(loadPrefs('B').cols).toBe(3)
  localStorage.setItem('isentinel_live_cols', '2')
  expect(loadPrefs('default').cols).toBe(2)
  expect(loadPrefs('C').cols).toBe(3)
})

test('localStorage melempar error → default, tanpa crash', () => {
  const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
  const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('full') })
  try {
    expect(loadPrefs('A').cameras).toEqual({ mode: 'all' })
    expect(() => savePrefs('A', loadPrefs('A'))).not.toThrow()
  } finally {
    get.mockRestore()
    set.mockRestore()
  }
})

test('defaultCols: portrait 2, landscape 3', () => {
  const orig = window.matchMedia
  window.matchMedia = ((q: string) => ({ matches: q.includes('portrait') })) as unknown as typeof window.matchMedia
  expect(defaultCols()).toBe(2)
  window.matchMedia = orig
  expect(defaultCols()).toBe(3)
})

test('selectCameras: all ikut kamera baru, ID yang hilang diabaikan', () => {
  expect(selectCameras([...CAMS, { id: 9 }], { mode: 'all' }).map((c) => c.id)).toEqual([1, 2, 3, 9])
  expect(selectCameras(CAMS, { mode: 'some', ids: [3, 42] }).map((c) => c.id)).toEqual([3])
})

test('setCameras: toggle, semua terpilih kembali jadi all, ID usang dibuang', () => {
  const s1 = setCameras({ mode: 'all' }, CAMS, [2], false)
  expect(s1).toEqual({ mode: 'some', ids: [1, 3] })
  expect(setCameras(s1, CAMS, [2], true)).toEqual({ mode: 'all' })
  expect(setCameras({ mode: 'some', ids: [1, 42] }, CAMS, [3], true)).toEqual({ mode: 'some', ids: [1, 3] })
  expect(setCameras({ mode: 'all' }, CAMS, [1, 2, 3], false)).toEqual({ mode: 'some', ids: [] })
})
