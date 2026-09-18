import { Tab, TabList, TabPanel, TabPanels, Tabs } from '@carbon/react'
import { useSearchParams } from 'react-router-dom'
import { useT, type TKey } from '../../app/i18n'
import CamerasPage from './CamerasPage'
import ZonesPage from './ZonesPage'
import GatesPage from './GatesPage'
import StoragePage from './StoragePage'
import NodesPanel from './NodesPanel'

const TABS = ['cameras', 'zones', 'gates', 'storage', 'nodes'] as const
type ConfigurationTab = (typeof TABS)[number]

const TAB_LABEL: Record<ConfigurationTab, TKey> = {
  cameras: 'cameras.title',
  zones: 'zones.title',
  gates: 'gates.title',
  storage: 'storage.title',
  nodes: 'configuration.tabNodes',
}

export default function ConfigurationPage() {
  const { t } = useT()
  const [params, setParams] = useSearchParams()
  // ponytail: nilai `tab` di luar daftar → cameras; hanya panel terpilih yang di-mount agar panel non-aktif tidak memanggil API
  const raw = params.get('tab')
  const tab: ConfigurationTab = TABS.includes(raw as ConfigurationTab) ? (raw as ConfigurationTab) : 'cameras'

  return (
    <div className="app-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('nav.configuration')}</h1>
          <p className="app-page__sub">{t('configuration.sub')}</p>
        </div>
      </div>

      <Tabs
        selectedIndex={TABS.indexOf(tab)}
        onChange={({ selectedIndex }) => {
          const next = TABS[selectedIndex]
          // ponytail: Carbon tetap memanggil onChange saat tab aktif diklik → jangan push entri history duplikat
          if (next !== tab) setParams({ tab: next })
        }}
      >
        <TabList aria-label={t('nav.configuration')}>
          {TABS.map((id) => (
            <Tab key={id}>{t(TAB_LABEL[id])}</Tab>
          ))}
        </TabList>
        <TabPanels>
          <TabPanel>{tab === 'cameras' && <CamerasPage />}</TabPanel>
          <TabPanel>{tab === 'zones' && <ZonesPage />}</TabPanel>
          <TabPanel>{tab === 'gates' && <GatesPage />}</TabPanel>
          <TabPanel>{tab === 'storage' && <StoragePage />}</TabPanel>
          <TabPanel>{tab === 'nodes' && <NodesPanel />}</TabPanel>
        </TabPanels>
      </Tabs>
    </div>
  )
}
