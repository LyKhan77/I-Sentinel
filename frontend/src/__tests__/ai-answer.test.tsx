import { render } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import AiAnswer from '../features/events/AiAnswer'

const html = (text: string) => render(<AiAnswer text={text} />).container

test('timeline lines become time rows; summary and conclusion are separate', () => {
  const c = html('Seorang pria berdiri lalu pergi.\n0:03 — Pria berdiri memegang ponsel\n0:09 - Pria berjalan ke arah kamera\nKesimpulan: Ia keluar bingkai.')
  const rows = c.querySelectorAll('.ev-ai-time')
  expect(Array.from(rows).map(r => r.textContent)).toEqual(['0:03', '0:09'])
  expect(c.querySelectorAll('.ev-ai-timeline li')).toHaveLength(2)
  expect(c.querySelector('.ev-ai-timeline li')?.textContent).toContain('Pria berdiri memegang ponsel')
  expect(c.querySelector('.ev-ai-summary')?.textContent).toBe('Seorang pria berdiri lalu pergi.')
  expect(c.querySelector('.ev-ai-conclusion strong')?.textContent).toBe('Kesimpulan:')
  expect(c.querySelector('.ev-ai-conclusion')?.textContent).toContain('Ia keluar bingkai.')
})

test('bold, numbered and dashed items render without literal markdown', () => {
  const c = html('1. **Aktivitas:** berdiri di lorong\n2. **Hasil:** keluar bingkai\n- memegang ponsel')
  expect(c.textContent).not.toContain('**')
  expect(c.querySelectorAll('strong')).toHaveLength(2)
  expect(c.querySelectorAll('li')).toHaveLength(3)
  expect(c.querySelector('strong')?.textContent).toBe('Aktivitas:')
})

test('relative seconds label and markdown time are accepted', () => {
  const c = html('- **0:12** — Pria muncul\ndetik 3,3 — Pria berdiri')
  expect(Array.from(c.querySelectorAll('.ev-ai-time')).map(r => r.textContent)).toEqual(['0:12', 'detik 3,3'])
})

test('markup in model text stays text and never becomes elements', () => {
  const c = html('<img src=x onerror=alert(1)>\n<script>alert(1)</script>')
  expect(c.querySelector('img, script')).toBeNull()
  expect(c.textContent).toContain('<img src=x onerror=alert(1)>')
})

test('plain lines become separate paragraphs and blank input renders nothing', () => {
  const c = html('Satu.\n\nDua.')
  expect(Array.from(c.querySelectorAll('p')).map(p => p.textContent)).toEqual(['Satu.', 'Dua.'])
  expect(html('  \n ').textContent).toBe('')
})
