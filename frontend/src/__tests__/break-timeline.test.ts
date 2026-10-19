import { buildTimeline, badBreak } from '../features/config/breakTimeline'

const WORK = { start: '08:30', end: '17:30' }

test('tanpa istirahat: sumbu = jam kerja ±1 jam, bilah kerja tanpa segmen diam', () => {
  const tl = buildTimeline(WORK, [])
  expect([tl.fromLabel, tl.toLabel]).toEqual(['07:30', '18:30'])
  expect(tl.work.left).toBeCloseTo(9.09, 1)
  expect(tl.work.width).toBeCloseTo(81.82, 1)
  expect(tl.quiet).toEqual([])
  expect(tl.outside).toBe(false)
})

test('istirahat di dalam jam kerja digambar pada posisi menit yang benar', () => {
  const tl = buildTimeline(WORK, [{ start: '12:00', end: '13:00' }])
  expect(tl.quiet).toHaveLength(1)
  expect(tl.quiet[0].left).toBeCloseTo(40.91, 1)
  expect(tl.quiet[0].width).toBeCloseTo(9.09, 1)
  expect(tl.outside).toBe(false)
})

test('istirahat di luar jam kerja memperluas sumbu dan ditandai outside', () => {
  const tl = buildTimeline(WORK, [{ start: '19:00', end: '20:00' }])
  expect(tl.toLabel).toBe('20:00')
  expect(tl.quiet[0].left).toBeCloseTo(92, 1)
  expect(tl.quiet[0].width).toBeCloseTo(8, 1)
  expect(tl.outside).toBe(true)
})

test('gate (tanpa jam kerja): sumbu 24 jam penuh, bilah kerja membentang semuanya', () => {
  const tl = buildTimeline(null, [{ start: '12:00', end: '13:00' }])
  expect([tl.fromLabel, tl.toLabel]).toEqual(['00:00', '24:00'])
  expect(tl.work).toEqual({ left: 0, width: 100 })
  expect(tl.quiet[0].left).toBeCloseTo(50, 1)
  expect(tl.quiet[0].width).toBeCloseTo(4.17, 1)
  expect(tl.outside).toBe(false)
})

test('sumbu dibatasi 00:00–24:00 dan jam kerja tidak valid dianggap sehari penuh', () => {
  expect(buildTimeline({ start: '00:00', end: '23:59' }, [])).toMatchObject({ fromLabel: '00:00', toLabel: '24:00' })
  const tl = buildTimeline({ start: '17:00', end: '08:00' }, [])
  expect([tl.fromLabel, tl.toLabel]).toEqual(['00:00', '24:00'])
  expect(tl.work).toEqual({ left: 0, width: 100 })
})

test('istirahat tidak valid tidak digambar dan tidak mengubah sumbu', () => {
  const tl = buildTimeline(WORK, [{ start: '13:00', end: '12:00' }, { start: '', end: '13:00' }])
  expect(tl.quiet).toEqual([])
  expect([tl.fromLabel, tl.toLabel]).toEqual(['07:30', '18:30'])
})

test('badBreak mengikuti aturan server: HH:MM 00:00–23:59 dan mulai < selesai', () => {
  expect(badBreak({ start: '12:00', end: '13:00' })).toBe(false)
  for (const b of [{ start: '13:00', end: '12:00' }, { start: '12:00', end: '12:00' }, { start: '', end: '13:00' },
    { start: '12:00', end: '24:00' }, { start: '12:0', end: '13:00' }]) {
    expect(badBreak(b)).toBe(true)
  }
})
