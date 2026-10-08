import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { I18nProvider } from '../app/i18n'
import ZonesPage from '../features/config/ZonesPage'
import type { Mock } from 'vitest'
import type { Zone } from '../api/zones'

const CAMS = [{ id: 1, name: 'CAM-01' }]

const zoneFix = (over: Partial<Zone> = {}): Zone => ({
  id: 10, camera_id: 1, name: 'Zona 1', type: 'behavior', direction: null,
  polygon: [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9]], schedule: null, severity: 'critical',
  rate_limit_min: 5, trigger_seconds: 0,
  behaviors: [{ kind: 'intrusion', trigger_seconds: 0, face_id: false }],
  snapshot: true, clip: true, telegram: false, active: true, ...over,
})

function stubFetch(zones: Zone[]) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    if (u.endsWith('/cameras')) return { ok: true, status: 200, json: () => Promise.resolve(CAMS) }
    if (u.endsWith('/cameras/1/live')) {
      return {
        ok: true, status: 200,
        json: () => Promise.resolve({ camera_id: 1, streams: { sub: 'cam_1' }, snapshot: 'http://x/frame' }),
      }
    }
    if (u.endsWith('/shifts')) return { ok: true, status: 200, json: () => Promise.resolve([]) }
    if (u.includes('/zones') && (init?.method ?? 'GET') === 'GET') {
      return { ok: true, status: 200, json: () => Promise.resolve(zones) }
    }
    if (u.includes('/zones/') && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body))
      return { ok: true, status: 200, json: () => Promise.resolve({ ...zones[0], ...body }) }
    }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  })
}

async function selectZone(zones: Zone[]) {
  const fetchMock = stubFetch(zones)
  vi.stubGlobal('fetch', fetchMock)
  render(<I18nProvider><ZonesPage /></I18nProvider>)
  fireEvent.click(await screen.findByTestId('zone-item-10'))
  return fetchMock
}

function patchBody(fetchMock: Mock) {
  const patch = fetchMock.mock.calls.find(
    (call) => String(call[0]).endsWith('/zones/10') &&
      (call[1] as RequestInit | undefined)?.method === 'PATCH')
  expect(patch).toBeTruthy()
  return JSON.parse(String(patch![1]!.body))
}

test('intrusion face_id toggle defaults off and saves face_id true', async () => {
  const f = await selectZone([zoneFix()])
  const toggle = document.getElementById('zone-face-id-intrusion')!
  expect(toggle).toHaveAttribute('aria-checked', 'false')
  fireEvent.click(toggle)
  fireEvent.click(screen.getByTestId('zone-save'))
  await waitFor(() => expect(patchBody(f).behaviors).toEqual([
    { kind: 'intrusion', trigger_seconds: 0, face_id: true },
  ]))
})

test('face_id toggle is not rendered for loitering', async () => {
  await selectZone([zoneFix({
    behaviors: [{ kind: 'loitering', trigger_seconds: 30, face_id: true }],
  })])
  expect(document.getElementById('zone-face-id-loitering')).toBeNull()
})
