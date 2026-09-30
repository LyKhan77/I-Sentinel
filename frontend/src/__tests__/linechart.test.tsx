import { fireEvent, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import LineChart, { type ChartSeries } from '../components/LineChart'

const MIN = 60_000
const FROM = Date.UTC(2026, 8, 30, 8, 0)
const TO = FROM + 60 * MIN
const pts = (minutes: number[], v = (i: number) => i) => minutes.map((m, i) => ({ t: FROM + m * MIN, v: v(i) }))

const base = (series: ChartSeries[], extra = {}) => render(
  <LineChart title="CPU" series={series} from={FROM} to={TO} bucketMs={MIN} yMin={0} yMax={100} unit=" %"
    locale="id" testId="chart" {...extra} />)

test('satu path per seri; loncatan > 1,5 bucket jadi celah (M baru)', () => {
  base([{ key: 'cpu', label: 'CPU', color: '#6929c4', points: pts([0, 1, 2, 10, 11]) }])
  const d = screen.getByTestId('lc-line-cpu').getAttribute('d')!
  expect(d.match(/M/g)).toHaveLength(2)  // 0-2 bersambung, 10-11 segmen baru
  expect(d.match(/L/g)).toHaveLength(3)
})

test('seri dashed memakai stroke-dasharray; arsir offline tergambar', () => {
  base([{ key: 'fps', label: 'fps', color: '#1192e8', points: pts([0, 1]) },
        { key: 'target', label: 'target', color: '#8d8d8d', points: pts([0, 1]), dashed: true }],
       { shaded: [{ from: FROM + 20 * MIN, to: FROM + 30 * MIN }] })
  expect(screen.getByTestId('lc-line-target')).toHaveAttribute('stroke-dasharray')
  expect(screen.getByTestId('lc-line-fps')).not.toHaveAttribute('stroke-dasharray')
  expect(screen.getAllByTestId('lc-offline')).toHaveLength(1)
})

test('refLine digambar sebagai garis horizontal putus-putus dan ikut tooltip', () => {
  base([{ key: 'fps', label: 'fps', color: '#1192e8', points: pts([0, 30]) }], { refLine: { v: 50, label: 'target' } })
  const ref = screen.getByTestId('lc-ref')
  expect(ref).toHaveAttribute('stroke-dasharray')
  expect(ref.getAttribute('y1')).toBe(ref.getAttribute('y2'))
  fireEvent.mouseMove(screen.getByRole('img'), { clientX: 300 })
  expect(screen.getByTestId('lc-tip')).toHaveTextContent('target: 50.0 %')
})

test('hover menampilkan tooltip nilai tiap seri; keluar menutup', () => {
  base([{ key: 'cpu', label: 'CPU', color: '#6929c4', points: pts([0, 30, 59], (i) => [10, 55, 90][i]) }])
  const svg = screen.getByRole('img')
  // lebar default 600, padding kiri 40 → x tengah ≈ menit 30
  fireEvent.mouseMove(svg, { clientX: 40 + (600 - 52) / 2 })
  expect(screen.getByTestId('lc-tip')).toHaveTextContent('CPU: 55.0 %')
  fireEvent.mouseLeave(svg)
  expect(screen.queryByTestId('lc-tip')).toBeNull()
})

test('aria-label merangkum nilai terakhir; tanpa data tetap render', () => {
  base([{ key: 'cpu', label: 'CPU', color: '#6929c4', points: pts([0, 1], (i) => [10, 42][i]) }])
  expect(screen.getByRole('img')).toHaveAttribute('aria-label', expect.stringContaining('CPU 42.0 %'))
  base([{ key: 'x', label: 'X', color: '#000', points: [] }])
  expect(screen.getAllByRole('img')).toHaveLength(2)
})
