import {
  defaultCols, loadPrefs, orderCameraIds, parseTvUrl, savePrefs, screenName, selectByIds, selectCameras,
  setCameras, withOverrides, type ScreenPrefs, tvSearch,
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

test('parseTvUrl: cameras berurutan, spasi dipangkas, duplikat dan token sampah dibuang', () => {
  expect(parseTvUrl(new URLSearchParams('cameras= 3, 1,1,x,0,-2,2.5,2')).cameras).toEqual([3, 1, 2])
})

test('parseTvUrl: cameras ada tetapi tanpa ID valid → [] (bukan undefined)', () => {
  expect(parseTvUrl(new URLSearchParams('cameras=')).cameras).toEqual([])
  expect(parseTvUrl(new URLSearchParams('cameras=a,b')).cameras).toEqual([])
  expect(parseTvUrl(new URLSearchParams('screen=A')).cameras).toBeUndefined()
})

test('parseTvUrl: cols hanya 2/3/4', () => {
  expect(parseTvUrl(new URLSearchParams('cols=4')).cols).toBe(4)
  expect(parseTvUrl(new URLSearchParams('cols=5')).cols).toBeUndefined()
  expect(parseTvUrl(new URLSearchParams('cols=abc')).cols).toBeUndefined()
})

test('parseTvUrl: scroll dan speed tidak peka huruf besar-kecil, nilai asing diabaikan', () => {
  expect(parseTvUrl(new URLSearchParams('scroll=ON')).scroll).toBe(true)
  expect(parseTvUrl(new URLSearchParams('scroll=Off')).scroll).toBe(false)
  expect(parseTvUrl(new URLSearchParams('scroll=yes')).scroll).toBeUndefined()
  expect(parseTvUrl(new URLSearchParams('speed=FAST')).speed).toBe('fast')
  expect(parseTvUrl(new URLSearchParams('speed=turbo')).speed).toBeUndefined()
})

test('selectByIds: urutan mengikuti ids, ID tak dikenal dilewati', () => {
  expect(selectByIds(CAMS, [3, 9, 1]).map((c) => c.id)).toEqual([3, 1])
})

test('withOverrides: hanya field yang ada di URL yang menimpa, localStorage tetap kosong', () => {
  const prefs: ScreenPrefs = { cols: 3, cameras: { mode: 'all' }, scroll: { on: false, speed: 'medium' } }
  const eff = withOverrides(prefs, { cols: 2 })
  expect(eff.cols).toBe(2)
  expect(eff.scroll).toEqual({ on: false, speed: 'medium' })
  expect(eff.cameras).toEqual({ mode: 'all' })
  expect(localStorage.length).toBe(0)
})

test('orderCameraIds: ID yang masih terpilih menjaga urutan lama, ID baru di akhir menurut urutan kamera', () => {
  const active = [{ id: 1 }, { id: 2 }, { id: 3 }]
  expect(orderCameraIds([3, 1], { mode: 'some', ids: [1, 2, 3] }, active)).toEqual([3, 1, 2])
  expect(orderCameraIds([3, 1], { mode: 'some', ids: [1] }, active)).toEqual([1])
  // mode 'all' (semua dicentang): urutan lama tetap, sisanya di akhir menurut urutan kamera
  expect(orderCameraIds([2], { mode: 'all' }, active)).toEqual([2, 1, 3])
  expect(orderCameraIds([], { mode: 'all' }, active)).toEqual([1, 2, 3])
  expect(orderCameraIds([2, 1], { mode: 'some', ids: [] }, active)).toEqual([])
  // ID yang tidak lagi ada di kamera aktif tidak ikut
  expect(orderCameraIds([9, 2], { mode: 'some', ids: [2, 9] }, active)).toEqual([2])
})

test('tvSearch: menulis cameras/cols/scroll/speed, koma terbaca, parameter lain dipertahankan, base tidak dimutasi', () => {
  const base = new URLSearchParams('screen=A&cameras=9&cols=2&foo=a%20b')
  const out = tvSearch(base, { cameras: [3, 1], cols: 3, scroll: true, speed: 'medium' })
  expect(out).toBe('screen=A&foo=a%20b&cameras=3,1&cols=3&scroll=on&speed=medium')
  expect(tvSearch(new URLSearchParams(), { cameras: [], cols: 4, scroll: false, speed: 'fast' }))
    .toBe('cameras=&cols=4&scroll=off&speed=fast')
  expect(base.toString()).toBe('screen=A&cameras=9&cols=2&foo=a+b')
})
