import { Tab, TabList, TabPanel, TabPanels, Tabs } from '@carbon/react'
import type { ReactNode } from 'react'
import { useOutletContext, useSearchParams } from 'react-router-dom'
import { useT, type TKey } from '../../app/i18n'
import type { Me } from '../../api/client'
import CamerasPage from './CamerasPage'
import ZonesPage from './ZonesPage'
import StoragePage from './StoragePage'
import NodesPanel from './NodesPanel'
import DetectionPage from './DetectionPage'
import NotificationsPage from './NotificationsPage'
import UsersPage from './UsersPage'

const TABS = ['cameras', 'zones', 'detection', 'notifications', 'storage', 'nodes', 'users'] as const
type ConfigurationTab = (typeof TABS)[number]

const TAB_LABEL: Record<ConfigurationTab, TKey> = {
  cameras: 'cameras.title',
  zones: 'zones.title',
  storage: 'storage.title',
  detection: 'detection.title',
  notifications: 'notifications.title',
  nodes: 'configuration.tabNodes',
  users: 'users.title',
}

export default function ConfigurationPage() {
  const { t } = useT()
  const [params, setParams] = useSearchParams()
  const me = useOutletContext<Me | null | undefined>()
  // viewer (D6): hanya Storage yang dirancang read-only untuk non-admin — tab admin disembunyikan
  const restricted = me != null && me.role !== 'admin'
  const tabs: readonly ConfigurationTab[] = restricted ? ['storage'] : TABS
  // ponytail: nilai `tab` di luar daftar terlihat → tab terlihat pertama; hanya panel terpilih yang di-mount
  // agar panel non-aktif tidak memanggil API
  const raw = params.get('tab')
  const tab: ConfigurationTab = tabs.includes(raw as ConfigurationTab) ? (raw as ConfigurationTab) : tabs[0]
  // elemen panel dibuat per render, tetapi hanya yang aktif yang dipasang (lihat TabPanels di bawah)
  const panels: Record<ConfigurationTab, ReactNode> = {
    cameras: <CamerasPage />,
    zones: <ZonesPage />,
    detection: <DetectionPage />,
    notifications: <NotificationsPage />,
    storage: <StoragePage />,
    nodes: <NodesPanel />,
    users: <UsersPage meId={me?.id} />,
  }

  return (
    <div className="app-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('nav.configuration')}</h1>
          <p className="app-page__sub">{t('configuration.sub')}</p>
        </div>
      </div>

      {/* sesi belum termuat (`me` null di AppShell): jangan pasang tab/panel — viewer tak boleh sempat memanggil API admin;
          `me` undefined (tanpa shell, mis. uji) tetap menampilkan semua tab */}
      {me !== null && (
        <Tabs
          selectedIndex={tabs.indexOf(tab)}
          onChange={({ selectedIndex }) => {
            const next = tabs[selectedIndex]
            // ponytail: Carbon tetap memanggil onChange saat tab aktif diklik → jangan push entri history duplikat
            if (next !== tab) setParams({ tab: next })
          }}
        >
          <TabList aria-label={t('nav.configuration')}>
            {tabs.map((id) => (
              <Tab key={id}>{t(TAB_LABEL[id])}</Tab>
            ))}
          </TabList>
          <TabPanels>
            {tabs.map((id) => (
              <TabPanel key={id}>{tab === id ? panels[id] : null}</TabPanel>
            ))}
          </TabPanels>
        </Tabs>
      )}
    </div>
  )
}
