# UI Shell and Configuration Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the four functional administrative settings views into a query-addressable Configuration workbench, make sidebar rail navigation stable, move logout into the account card, and make the Zones editor usable on narrow screens.

**Architecture:** `ConfigurationPage` owns the page chrome, Carbon tab strip, and `tab` query state. The existing Cameras, Zones, Gates, and Storage implementations become panel components that retain their own API, loading, error, and mutation behavior but no longer own page wrappers. `AppShell` exposes one admin-only Configuration destination and owns no state transition except the header menu toggle.

**Tech Stack:** React 19, React Router 7, Carbon React 1.115, TypeScript 6, Sass, Vitest, Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-16-ui-shell-configuration-design.md`

## Global Constraints

- Work on branch `feat/ui-shell-configuration`; do not implement on `main`.
- Canonical configuration URL is `/configuration?tab=cameras|zones|gates|storage`.
- Render only the four implemented tabs; do not create Detection, Notifications, or Users placeholders.
- Do not add dependencies, API endpoints, aliases, redirects, or compatibility routes for `/config/*`.
- Preserve all existing panel loading, error, empty, confirmation, admin-gated action, and API behavior.
- Keep Carbon focus indicators; rail focus must not alter the persisted collapsed state.
- Use existing ID and EN i18n structure; every new key must exist in both dictionaries.
- Verify user-visible behavior only against the development server identified by `temp/data/server-info.txt`; local Vite is not evidence.
- Do not push the feature branch or change the server checkout without explicit user authorization.

---

### Task 1: Build the Configuration workbench

**Files:**
- Create: `frontend/src/features/config/ConfigurationPage.tsx`
- Modify: `frontend/src/features/config/CamerasPage.tsx`
- Modify: `frontend/src/features/config/ZonesPage.tsx`
- Modify: `frontend/src/features/config/GatesPage.tsx`
- Modify: `frontend/src/features/config/StoragePage.tsx`
- Modify: `frontend/src/app/AppShell.tsx:33-53`
- Modify: `frontend/src/main.tsx:5-16,66-76`
- Modify: `frontend/src/app/i18n.tsx:6-35,264-285`
- Create: `frontend/src/__tests__/configuration.test.tsx`
- Modify: `frontend/src/__tests__/cameras.test.tsx:1-77`
- Modify: `frontend/src/__tests__/zones.test.tsx`
- Modify: `frontend/src/__tests__/gates.test.tsx:1-94`
- Modify: `frontend/src/__tests__/storage.test.tsx`

**Interfaces:**
- Consumes: default panel exports from Cameras, Zones, Gates, and Storage; React Router `useSearchParams`; Carbon `Tabs`, `TabList`, `Tab`, `TabPanels`, and `TabPanel`.
- Produces: `ConfigurationPage` as the only settings route component at `/configuration`; `ConfigurationTab = 'cameras' | 'zones' | 'gates' | 'storage'` internal to `ConfigurationPage`.

- [ ] **Step 1: Write failing URL-tab and Gate-to-Zone tests**

Create `configuration.test.tsx` with a route-location probe and a single URL-aware fetch stub. Exercise a real `MemoryRouter` route rather than mocking tab state:

```tsx
function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.search}</output>
}

function renderConfiguration(entry: string) {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/configuration" element={<ConfigurationPage />} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>
    </I18nProvider>,
  )
}

test('selects the tab named by the URL and updates history on tab selection', async () => {
  const user = userEvent.setup()
  stubFetch()
  renderConfiguration('/configuration?tab=gates')

  expect(await screen.findByRole('tab', { name: 'Gate Absensi', selected: true })).toBeInTheDocument()
  await user.click(screen.getByRole('tab', { name: 'Retensi & Storage' }))
  expect(screen.getByTestId('location')).toHaveTextContent('?tab=storage')
})

test('Gate editor action selects the Zones tab in the same workbench', async () => {
  const user = userEvent.setup()
  stubFetch([gate(1, 'entry')])
  renderConfiguration('/configuration?tab=gates')

  await user.click(await screen.findByTestId('gate-draw-1'))
  expect(await screen.findByRole('tab', { name: 'Zona', selected: true })).toBeInTheDocument()
  expect(screen.getByTestId('location')).toHaveTextContent('?tab=zones')
})
```

The stub must return the existing test fixtures for `/api/v1/auth/me`, `/api/v1/cameras`, `/api/v1/zones` (including query strings), and `/api/v1/storage/stats`; any unknown request returns the existing `{ ok: false, status: 404, json }` response shape.

- [ ] **Step 2: Run the new test and confirm the missing workbench fails**

Run from `frontend/`:

```bash
npx vitest run src/__tests__/configuration.test.tsx
```

Expected: FAIL because `ConfigurationPage` and `/configuration` do not exist.

- [ ] **Step 3: Implement the single Configuration route and tab state**

Add `ConfigurationPage.tsx`. Keep the tab identifiers in one closed tuple and derive the selected index without duplicate React state:

```tsx
const TABS = ['cameras', 'zones', 'gates', 'storage'] as const
type ConfigurationTab = (typeof TABS)[number]

function selectedTab(value: string | null): ConfigurationTab {
  return TABS.includes(value as ConfigurationTab) ? (value as ConfigurationTab) : 'cameras'
}
```

Use `useSearchParams()` and Carbon's composable tab API. `onChange={({ selectedIndex }) => setSearchParams({ tab: TABS[selectedIndex] })}` is the sole tab-selection mutation. Render four `TabPanel` elements, but conditionally render each API-owning panel only when its tab is selected. Add one page heading using `nav.configuration` and a new bilingual `configuration.sub` key.

Convert each current settings page to a default panel export by removing only its outer `.app-page` wrapper and duplicated page heading/subtitle. Preserve its state, API requests, action controls, and all existing `data-testid` values. Update `GatesPage` so its draw action calls `navigate('/configuration?tab=zones')`.

In `main.tsx`, replace the four configuration imports/routes with the `ConfigurationPage` import and `{ path: 'configuration', element: <ConfigurationPage /> }`. Remove the legacy `/config/*` route definitions entirely.
In `AppShell`, replace the four individual configuration items with the sole admin-only `Settings` item `{ to: '/configuration?tab=cameras', key: 'nav.configuration', icon: Settings, adminOnly: true }`, and remove the `DataBase` import. This keeps every sidebar link valid at the end of Task 1.

Update existing settings tests only where their old route entry or page-title assertion is no longer valid; preserve their current behavioral assertions for rows, admin gates, zone editing, and storage sweep information.

- [ ] **Step 4: Run Configuration and panel regression tests**

Run from `frontend/`:

```bash
npx vitest run src/__tests__/configuration.test.tsx src/__tests__/cameras.test.tsx src/__tests__/zones.test.tsx src/__tests__/gates.test.tsx src/__tests__/storage.test.tsx
```

Expected: PASS. Confirm the Gate test still checks its conflict and admin controls, and the new test proves query selection plus the in-workbench Zone handoff.

- [ ] **Step 5: Commit the workbench**

```bash
git add frontend/src/features/config/ConfigurationPage.tsx frontend/src/features/config/CamerasPage.tsx frontend/src/features/config/ZonesPage.tsx frontend/src/features/config/GatesPage.tsx frontend/src/features/config/StoragePage.tsx frontend/src/app/AppShell.tsx frontend/src/main.tsx frontend/src/app/i18n.tsx frontend/src/__tests__/configuration.test.tsx frontend/src/__tests__/cameras.test.tsx frontend/src/__tests__/zones.test.tsx frontend/src/__tests__/gates.test.tsx frontend/src/__tests__/storage.test.tsx
git commit -m "feat: consolidate configuration workbench"
```

### Task 2: Simplify the sidebar and account action

**Files:**
- Modify: `frontend/src/app/AppShell.tsx:1-198`
- Modify: `frontend/src/app/theme.scss:43-117`
- Modify: `frontend/src/__tests__/shell.test.tsx:1-34`

**Interfaces:**
- Consumes: the canonical `/configuration?tab=cameras` sidebar link produced by Task 1; existing `logout(): Promise<void>` and `login.logout` translation key.
- Produces: a user-card logout button; rail state changed only by `HeaderMenuButton`.

- [ ] **Step 1: Write failing rail and account-action tests**

Extend `shell.test.tsx` with a collapsed desktop render. Set `localStorage.setItem('isentinel_sidenav_collapsed', '1')` before rendering and remove it in `afterEach`. Test the user-visible rail contract:

```tsx
test('a rail link navigates without expanding the persisted rail', async () => {
  localStorage.setItem('isentinel_sidenav_collapsed', '1')
  const user = userEvent.setup()
  renderShell('/dashboard')

  const nav = document.querySelector('nav.cds--side-nav--rail')!
  await user.click(screen.getByRole('link', { name: 'Dashboard' }))
  expect(nav).not.toHaveClass('cds--side-nav--expanded')
})

test('shows one Configuration link and puts logout in the account card', async () => {
  renderShell('/dashboard')
  await screen.findByRole('link', { name: 'Konfigurasi' })

  expect(screen.getAllByRole('link', { name: 'Konfigurasi' })).toHaveLength(1)
  expect(screen.getByRole('button', { name: 'Keluar' })).toBeInTheDocument()
  expect(screen.queryByRole('banner')?.querySelector('[aria-label="Keluar"]')).toBeNull()
})
```

`renderShell` remains the existing `I18nProvider` + `MemoryRouter` helper. The test must allow `getMe()` to settle, as current setup does.

- [ ] **Step 2: Run the shell regression and confirm it fails**

Run from `frontend/`:

```bash
npx vitest run src/__tests__/shell.test.tsx
```

Expected: FAIL because rail focus still activates Carbon's internal expanded state and logout remains in the header.

- [ ] **Step 3: Implement stable rail navigation and account logout**

On `SideNav`, keep `addMouseListeners={false}` and add `addFocusListeners={false}`. Do not add a link `onClick` state patch: Carbon's focus listener is the shared root cause and disabling it preserves both pointer and keyboard navigation.

Remove `HeaderGlobalAction` and its `Logout` icon from the header imports/markup. Put a semantic `button type="button"` in `.app-sidenav-user` using the existing async logout handler, the `Logout` icon, and `t('login.logout')`. Style it as a full-width account-card action; in rail mode visually hide its text without removing its accessible name or focusable target.

- [ ] **Step 4: Run shell and workbench regression tests**

Run from `frontend/`:

```bash
npx vitest run src/__tests__/shell.test.tsx src/__tests__/configuration.test.tsx
```

Expected: PASS. The assertion must cover one Configuration destination, account-card logout, and no rail expansion after a link click.

- [ ] **Step 5: Commit the shell cleanup**

```bash
git add frontend/src/app/AppShell.tsx frontend/src/app/theme.scss frontend/src/__tests__/shell.test.tsx
git commit -m "fix: stabilize sidebar rail navigation"
```

### Task 3: Stack the Zones editor on narrow screens

**Files:**
- Modify: `frontend/src/features/config/ZonesPage.tsx:105-296`
- Modify: `frontend/src/app/theme.scss:325-387`
- Modify: `frontend/src/__tests__/zones.test.tsx`

**Interfaces:**
- Consumes: `ZonesPage` as the active Zones panel inside `ConfigurationPage`.
- Produces: `.configuration-zones` layout and `.configuration-zones__details` panel classes whose desktop layout is two columns and narrow layout is one column.

- [ ] **Step 1: Extend the Zones test with a structural regression**

After the existing test reaches the rendered editor, assert that the semantic layout hooks exist without pinning incidental inline styles:

```tsx
expect(await screen.findByTestId('zone-draw-start')).toBeInTheDocument()
expect(document.querySelector('.configuration-zones')).toBeInTheDocument()
expect(document.querySelector('.configuration-zones__details')).toBeInTheDocument()
```

- [ ] **Step 2: Run the Zones test and confirm the layout hooks are absent**

Run from `frontend/`:

```bash
npx vitest run src/__tests__/zones.test.tsx
```

Expected: FAIL because the editor still uses anonymous inline grid and detail styles.

- [ ] **Step 3: Replace the anonymous split layout with responsive classes**

Replace the outer grid inline style with `className="configuration-zones"`; put the right detail pane in `className="configuration-zones__details"`. Move only layout declarations to `theme.scss`:

```scss
.configuration-zones {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(280px, 1fr);

  > * { min-inline-size: 0; }
}

.configuration-zones__details {
  border-inline-start: 1px solid var(--cds-border-subtle);
  padding-inline-start: 16px;
}

@media (max-width: 671px) {
  .configuration-zones { grid-template-columns: minmax(0, 1fr); }
  .configuration-zones__details {
    border-inline-start: 0;
    border-block-start: 1px solid var(--cds-border-subtle);
    margin-block-start: 16px;
    padding-block-start: 16px;
    padding-inline-start: 0;
  }
}
```

Keep the existing DOM order: editor/list first, detail pane second. Do not change zone geometry, form state, or API calls.

- [ ] **Step 4: Run the focused Zones regression**

Run from `frontend/`:

```bash
npx vitest run src/__tests__/zones.test.tsx
```

Expected: PASS, including the existing zone drawing and selected-detail behavior.

- [ ] **Step 5: Commit the responsive layout**

```bash
git add frontend/src/features/config/ZonesPage.tsx frontend/src/app/theme.scss frontend/src/__tests__/zones.test.tsx
git commit -m "fix: stack zone editor on narrow screens"
```

### Task 4: Prove the integrated change on the development server

**Files:**
- Modify: `CHANGELOG.md:6-20`
- Create: `docs/evidence/ui-shell-configuration-desktop.png`
- Create: `docs/evidence/ui-shell-configuration-mobile.png`

**Interfaces:**
- Consumes: the feature-branch commits from Tasks 1–3 and the server endpoint recorded in `temp/data/server-info.txt`.
- Produces: direct-server evidence for desktop and narrow viewport behavior plus an Unreleased changelog entry.

- [ ] **Step 1: Run the complete affected frontend suite and production build**

Run from `frontend/`:

```bash
npx vitest run src/__tests__/shell.test.tsx src/__tests__/configuration.test.tsx src/__tests__/cameras.test.tsx src/__tests__/zones.test.tsx src/__tests__/gates.test.tsx src/__tests__/storage.test.tsx && npm run build
```

Expected: all named tests pass and TypeScript/Vite build exits 0.

- [ ] **Step 2: Obtain authorization before publishing or switching the shared server checkout**

Do not push the branch or switch the server checkout yet. Ask the user for explicit authorization; server validation requires the server to run `feat/ui-shell-configuration` rather than its current branch.

- [ ] **Step 3: Verify the actual server surface after authorized deployment**

Use Playwright against the server URL in `temp/data/server-info.txt`, with the existing safe authenticated-browser procedure from `.cooper/context/isentinel-design.md`. Capture desktop and 390px-width screenshots. Verify:

1. Header toggles the desktop expanded/rail state.
2. Pointer click and keyboard activation of Dashboard, Live View, Events, and Configuration do not expand a rail that was collapsed.
3. Sidebar contains exactly one Configuration entry; its account card owns logout in expanded and rail modes.
4. `/configuration` defaults visually to Cameras; each valid `tab` selects its panel; invalid `tab` visibly falls back to Cameras; browser back/forward returns to the prior tab.
5. Gate's draw action changes to `?tab=zones` and opens the Zone panel.
6. At 390px, the Zone canvas/list appears before a full-width detail editor; no horizontal document scroll occurs.

- [ ] **Step 4: Record the shipped behavior**

Add one `CHANGELOG.md` Unreleased bullet following the existing one-line-per-commit convention. It must name all changed frontend paths, report the focused test/build result, link the two evidence screenshots, state that the configuration routes were consolidated, and state rollback as reverting the three feature commits. Do not include credentials or server secrets.

- [ ] **Step 5: Commit evidence and changelog**

```bash
git add CHANGELOG.md docs/evidence/ui-shell-configuration-desktop.png docs/evidence/ui-shell-configuration-mobile.png
git commit -m "docs: record configuration UI verification"
```

## Plan Self-Review

- **Spec coverage:** Task 1 covers the single query-addressable workbench, four real tabs, no placeholders, panel preservation, and Gate → Zones. Task 2 covers one sidebar Configuration entry, account logout, and the Carbon rail focus root cause. Task 3 covers the narrow Zone editor. Task 4 covers direct-server proof, evidence, changelog, and rollback statement.
- **Scope control:** no backend/API/dependency work, no legacy route aliases, no unimplemented mockup tabs, and no server publication without user authorization.
- **Type consistency:** only `ConfigurationTab` exists, with the four IDs shared by query parsing, Carbon selected index, and panel selection.
