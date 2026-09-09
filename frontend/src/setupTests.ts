import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

// jsdom tidak punya matchMedia; Carbon Header memakainya
window.matchMedia = window.matchMedia || ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addListener: () => {},
  removeListener: () => {},
  addEventListener: () => {},
  removeEventListener: () => {},
  dispatchEvent: () => false,
}))

// stub fetch: /auth/me → admin; test login tidak submit, jadi tidak menyentuh fetch
vi.stubGlobal(
  'fetch',
  vi.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ id: 1, username: 'admin', role: 'admin' }),
    }),
  ),
)
