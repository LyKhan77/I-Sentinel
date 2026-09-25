import { useEffect, useState } from 'react'
import { Button, InlineNotification, PasswordInput, RadioButton, RadioButtonGroup, TextInput } from '@carbon/react'
import { useT } from '../../app/i18n'
import {
  discoverTelegramChats, getTelegramSettings, putTelegramSettings, sendTelegramTest,
  type TelegramChat, type TelegramSettings,
} from '../../api/telegram'

// Satu grup petugas menerima alert (toggle Telegram per behavior di Zona Deteksi).
export default function NotificationsPage() {
  const { t } = useT()
  const [settings, setSettings] = useState<TelegramSettings | null>(null)
  const [token, setToken] = useState('')
  const [editingToken, setEditingToken] = useState(false)
  const [chats, setChats] = useState<TelegramChat[] | null>(null)
  const [chosen, setChosen] = useState<TelegramChat | null>(null)
  const [appUrl, setAppUrl] = useState('')
  const [message, setMessage] = useState<{ kind: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => {
    getTelegramSettings()
      .then((s) => {
        setSettings(s)
        setAppUrl(s.app_url ?? window.location.origin)
      })
      .catch(() => setMessage({ kind: 'error', text: t('notifications.loadError') }))
  }, [t])

  if (!settings) {
    return message ? (
      <InlineNotification kind={message.kind} lowContrast title={message.text} onCloseButtonClick={() => setMessage(null)} />
    ) : null
  }
  const showToken = !settings.has_token || editingToken

  const saveToken = async () => {
    setMessage(null)
    try {
      setSettings(await putTelegramSettings({ token: token.trim() }))
      setToken('')
      setEditingToken(false)
    } catch (e) {
      setMessage({ kind: 'error', text: t(e instanceof Error && e.message.endsWith(': 422') ? 'notifications.tokenRejected' : 'notifications.saveError') })
    }
  }

  const discover = async () => {
    setMessage(null)
    try {
      setChats(await discoverTelegramChats())
    } catch {
      setMessage({ kind: 'error', text: t('notifications.discoverError') })
    }
  }

  const saveChat = async () => {
    if (!chosen) return
    setMessage(null)
    try {
      setSettings(await putTelegramSettings({ chat_id: chosen.chat_id, chat_title: chosen.title, app_url: appUrl.trim() || null }))
      setChats(null)
      setChosen(null)
    } catch {
      setMessage({ kind: 'error', text: t('notifications.saveError') })
    }
  }

  const saveUrl = async () => {
    setMessage(null)
    try {
      setSettings(await putTelegramSettings({ app_url: appUrl.trim() || null }))
    } catch {
      setMessage({ kind: 'error', text: t('notifications.saveError') })
    }
  }

  const test = async () => {
    setMessage(null)
    try {
      const r = await sendTelegramTest()
      setMessage(r.status === 'sent'
        ? { kind: 'success', text: t('notifications.testSent') }
        : { kind: 'error', text: `${t('notifications.testFailed')}: ${r.error ?? ''}` })
    } catch {
      setMessage({ kind: 'error', text: t('notifications.testFailed') })
    }
  }

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 20, maxWidth: 560 }}>
      <p style={{ margin: 0 }}>{t('notifications.intro')}</p>

      <div>
        <h4>{t('notifications.step1')}</h4>
        {showToken ? (
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <PasswordInput id="tg-token" labelText={t('notifications.token')} helperText={t('notifications.tokenHint')}
              autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} />
            <Button size="md" disabled={!token.trim()} onClick={() => void saveToken()}>{t('notifications.saveToken')}</Button>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <span>{t('notifications.tokenSaved')}</span>
            <Button kind="ghost" size="sm" onClick={() => setEditingToken(true)}>{t('notifications.changeToken')}</Button>
          </div>
        )}
      </div>

      <div>
        <h4>{t('notifications.step2')}</h4>
        <p style={{ fontSize: 12 }}>{t('notifications.groupHint')}</p>
        {settings.chat_title && <p>{t('notifications.currentGroup')}: <strong>{settings.chat_title}</strong></p>}
        <Button kind="secondary" size="sm" disabled={!settings.has_token} onClick={() => void discover()}>
          {t('notifications.discover')}
        </Button>
        {chats && chats.length === 0 && <p style={{ fontSize: 12 }}>{t('notifications.noGroups')}</p>}
        {chats && chats.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <RadioButtonGroup legendText={t('notifications.chooseGroup')} name="tg-group" orientation="vertical"
              valueSelected={chosen?.chat_id} onChange={(v) => setChosen(chats.find((c) => c.chat_id === v) ?? null)}>
              {chats.map((c) => <RadioButton key={c.chat_id} id={`tg-${c.chat_id}`} labelText={c.title} value={c.chat_id} />)}
            </RadioButtonGroup>
            <Button size="sm" disabled={!chosen} onClick={() => void saveChat()} style={{ marginTop: 8 }}>
              {t('notifications.saveGroup')}
            </Button>
          </div>
        )}
      </div>

      <div>
        <h4>{t('notifications.step3')}</h4>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <TextInput id="tg-app-url" labelText={t('notifications.appUrl')} helperText={t('notifications.appUrlHint')}
            value={appUrl} onChange={(e) => setAppUrl(e.target.value)} />
          <Button kind="ghost" size="md" onClick={() => void saveUrl()}>{t('common.save')}</Button>
        </div>
      </div>

      <div>
        <Button kind="secondary" disabled={!settings.has_token || !settings.chat_id} onClick={() => void test()}>
          {t('notifications.test')}
        </Button>
        {settings.last_alert && (
          <p style={{ fontSize: 12, marginTop: 8 }}>
            {t('notifications.lastAlert')}: {settings.last_alert.status}
            {settings.last_alert.error ? ` — ${settings.last_alert.error}` : ''}
          </p>
        )}
      </div>

      {message && (
        <InlineNotification kind={message.kind} lowContrast title={message.text} onCloseButtonClick={() => setMessage(null)} />
      )}
    </section>
  )
}
