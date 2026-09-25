import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import NewCredentialForm from '../features/config/NewCredentialForm'

function renderForm(onCreated = vi.fn(), onCancel = vi.fn()) {
  render(
    <I18nProvider>
      <NewCredentialForm onCancel={onCancel} onCreated={onCreated} />
    </I18nProvider>,
  )
  return { onCreated, onCancel }
}

function stub(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => ({ ok: status < 400, status, json: () => Promise.resolve(body) }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

test('saves name, username and password, then hands the profile back', async () => {
  const created = { id: 5, name: 'ZKteco', username: 'admin', secret_ref: 'store:cred_5', enabled: true }
  const fetchMock = stub(200, created)
  const { onCreated } = renderForm()

  const save = screen.getByRole('button', { name: 'Simpan kredensial' })
  expect(save).toBeDisabled()
  await userEvent.type(screen.getByLabelText('Nama kredensial'), 'ZKteco')
  await userEvent.type(screen.getByLabelText('Username'), 'admin')
  expect(save).toBeDisabled() // password wajib
  await userEvent.type(screen.getByLabelText('Password', { selector: 'input' }), 'Rahasia#1')
  await userEvent.click(save)

  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created))
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
  expect(url).toMatch(/\/credential-profiles$/)
  expect(JSON.parse(String(init.body))).toEqual({ name: 'ZKteco', username: 'admin', password: 'Rahasia#1' })
})

test('duplicate name shows a specific message', async () => {
  stub(409, { detail: 'credential profile name already exists' })
  const { onCreated } = renderForm()
  await userEvent.type(screen.getByLabelText('Nama kredensial'), 'ZKteco')
  await userEvent.type(screen.getByLabelText('Password', { selector: 'input' }), 'x')
  await userEvent.click(screen.getByRole('button', { name: 'Simpan kredensial' }))
  expect(await screen.findByText('Nama kredensial sudah dipakai')).toBeInTheDocument()
  expect(onCreated).not.toHaveBeenCalled()
})
