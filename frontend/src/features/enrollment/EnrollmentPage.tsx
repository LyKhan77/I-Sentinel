import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Tab, TabList, TabPanel, TabPanels, Tabs } from '@carbon/react'
import { useT } from '../../app/i18n'
import { getMe, type Me } from '../../api/client'
import EmployeesTab from './EmployeesTab'
import ShiftsTab from './ShiftsTab'

const TABS = ['employees', 'shifts'] as const
type EnrollmentTab = (typeof TABS)[number]

export default function EnrollmentPage() {
  const { t } = useT()
  const [params, setParams] = useSearchParams()
  const [me, setMe] = useState<Me | null>(null)
  // ponytail: nilai `tab` di luar daftar → employees; hanya panel terpilih yang di-mount
  const raw = params.get('tab')
  const tab: EnrollmentTab = TABS.includes(raw as EnrollmentTab) ? (raw as EnrollmentTab) : 'employees'
  const isAdmin = me?.role === 'admin'

  useEffect(() => {
    getMe().then(setMe).catch(() => setMe(null))
  }, [])

  return (
    <div className="app-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('en.title')}</h1>
          <p className="app-page__sub">{t('en.sub')}</p>
        </div>
      </div>
      <Tabs
        selectedIndex={TABS.indexOf(tab)}
        onChange={({ selectedIndex }) => {
          const next = TABS[selectedIndex]
          if (next !== tab) setParams({ tab: next })
        }}
      >
        <TabList aria-label={t('en.title')}>
          <Tab>{t('en.tab.employees')}</Tab>
          <Tab>{t('en.tab.shifts')}</Tab>
        </TabList>
        <TabPanels>
          <TabPanel>{tab === 'employees' && <EmployeesTab isAdmin={isAdmin} />}</TabPanel>
          <TabPanel>{tab === 'shifts' && <ShiftsTab isAdmin={isAdmin} />}</TabPanel>
        </TabPanels>
      </Tabs>
    </div>
  )
}
