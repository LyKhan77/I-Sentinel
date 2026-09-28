import { act, render, screen } from '@testing-library/react'
import { END_PAUSE_MS, SCROLL_START, stepScroll, useIdle, type ScrollState } from '../features/live/useAutoScroll'

function run(s: ScrollState, steps: number, dt: number, max: number, px: number) {
  for (let i = 0; i < steps; i++) s = stepScroll(s, dt, max, px)
  return s
}

test('turun dengan kecepatan tetap, posisi pecahan diakumulasi', () => {
  // 20 px/s, frame 16 ms → 0,32 px per frame; 100 frame = 32 px (tidak hilang karena pembulatan)
  expect(run(SCROLL_START, 100, 16, 1000, 20).pos).toBeCloseTo(32, 5)
})

test('dasar: berhenti 5 detik, kembali ke atas, jeda 5 detik, lalu turun lagi', () => {
  // deviasi plan: 30 langkah (plan) menggerus jeda dasar 500 ms; 25 langkah × 4 px = tepat 100 px
  let s = run(SCROLL_START, 25, 100, 100, 40) // 2,5 s × 40 px/s = 100 → dasar tepat di langkah terakhir
  expect(s).toEqual({ phase: 'bottom', pos: 100, wait: END_PAUSE_MS })
  s = run(s, 49, 100, 100, 40)
  expect(s.phase).toBe('bottom')
  s = run(s, 1, 100, 100, 40)
  expect(s).toEqual({ phase: 'top', pos: 0, wait: END_PAUSE_MS })
  s = run(s, 50, 100, 100, 40)
  expect(s).toEqual({ phase: 'down', pos: 0, wait: 0 })
  expect(stepScroll(s, 100, 100, 40).pos).toBeCloseTo(4, 5)
})

test('konten muat satu layar → tidak menggulir; jeda frame panjang dibatasi', () => {
  expect(stepScroll({ phase: 'down', pos: 50, wait: 0 }, 16, 0, 40)).toEqual(SCROLL_START)
  // tab sempat tidak aktif 5 s: satu frame tidak melompat 200 px
  expect(stepScroll(SCROLL_START, 5000, 1000, 40).pos).toBeCloseTo(4, 5)
})

function IdleProbe({ ms }: { ms: number }) {
  return <span data-testid="idle">{String(useIdle(ms))}</span>
}

test('useIdle: aktif saat mouse bergerak, idle setelah ms tanpa aktivitas', () => {
  vi.useFakeTimers()
  try {
    render(<IdleProbe ms={4000} />)
    expect(screen.getByTestId('idle')).toHaveTextContent('false')
    act(() => { vi.advanceTimersByTime(4000) })
    expect(screen.getByTestId('idle')).toHaveTextContent('true')
    act(() => { window.dispatchEvent(new MouseEvent('mousemove')) })
    expect(screen.getByTestId('idle')).toHaveTextContent('false')
    act(() => { vi.advanceTimersByTime(3999) })
    expect(screen.getByTestId('idle')).toHaveTextContent('false')
    act(() => { vi.advanceTimersByTime(1) })
    expect(screen.getByTestId('idle')).toHaveTextContent('true')
  } finally {
    vi.useRealTimers()
  }
})
