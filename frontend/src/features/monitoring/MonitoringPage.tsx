import { Tab, TabList, TabPanel, TabPanels, Tabs } from '@carbon/react'
import { useSearchParams } from 'react-router-dom'
import { useT } from '../../app/i18n'
import CurrentTab from './CurrentTab'
import TrendTab from './TrendTab'

const TABS = ['current', 'trend'] as const
type MonTab = (typeof TABS)[number]

/** System › Monitoring: "Kondisi saat ini" (S1) dan "Tren" (S2). Hanya tab aktif yang di-mount → polling terpisah. */
export default function MonitoringPage() {
  const { t } = useT()
  const [params, setParams] = useSearchParams()
  const raw = params.get('tab')
  const tab: MonTab = TABS.includes(raw as MonTab) ? (raw as MonTab) : 'current'
  return (
    <div className="app-page mon-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('mon.title')}</h1>
          <p className="app-page__sub">{t('mon.subtitle')}</p>
        </div>
      </div>
      <Tabs selectedIndex={TABS.indexOf(tab)}
        onChange={({ selectedIndex }) => {
          const next = TABS[selectedIndex]
          if (next !== tab) setParams({ tab: next })
        }}>
        <TabList aria-label={t('mon.title')}>
          <Tab data-testid="mon-tab-current">{t('mon.tab.current')}</Tab>
          <Tab data-testid="mon-tab-trend">{t('mon.tab.trend')}</Tab>
        </TabList>
        <TabPanels>
          <TabPanel className="mon-tabpanel">{tab === 'current' && <CurrentTab />}</TabPanel>
          <TabPanel className="mon-tabpanel">{tab === 'trend' && <TrendTab />}</TabPanel>
        </TabPanels>
      </Tabs>
    </div>
  )
}
