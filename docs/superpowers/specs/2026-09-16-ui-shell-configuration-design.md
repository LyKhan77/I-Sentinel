# UI Shell and Configuration Redesign

**Status:** Approved design brief; awaiting written-spec review

## Goal

Reduce sidebar ambiguity and configuration context switching by consolidating the four existing administrative settings views into one tabbed Configuration workbench. Preserve every existing functional operation, move logout into the signed-in account card, prevent rail navigation from expanding the sidebar, and make the zone editor usable on narrow screens.

## Scope

- Replace the four admin sidebar destinations with one **Configuration** entry.
- Canonical settings URL: `/configuration?tab=cameras|zones|gates|storage`.
- Render four functional tabs only: Cameras, Zones, Attendance Gates, Retention & Storage.
- Move the existing logout action into the sidebar account card.
- Keep desktop rail state stable when an item receives pointer or keyboard focus.
- Stack the zone canvas and detail editor at narrow viewport widths.

## Non-goals

- No Detection & Model, Notifications, or Users tab: the mockup includes these, but no real implementation/API exists.
- No new backend API, persistence model, dependency, role, or visual language.
- No compatibility redirects or aliases for `/config/*`; all internal callers move to the canonical Configuration URL.
- No confirmation dialog for logout.

## Information Architecture

| Group | Entries | Visibility |
| --- | --- | --- |
| Monitoring | Dashboard, Live View, Events | All authenticated users |
| Management | Attendance, Enrollment | All authenticated users |
| System | Configuration | Administrators only |
| Account | Avatar, username, role, logout | Signed-in users |

The rail displays one icon per destination. Configuration is the sole settings icon; settings subareas are text labels inside the Configuration tab strip.

## Shell Interaction

`AppShell` retains its persisted desktop `collapsed` state. Only `HeaderMenuButton` toggles it.

Carbon `SideNav` must disable both hover/click rail listeners and focus listeners. Its default rail focus handler toggles an internal `expandedViaHoverState`, so focus from a pointer click or keyboard tab can visually expand the rail even when the application controls `expanded`. Rail links remain focusable and must retain Carbon's visible focus treatment; they only navigate.

The account card owns the existing `logout()` then `navigate('/login')` action. In expanded mode the control has an icon and visible localized label. In rail mode its text is visually hidden but the control retains an accessible localized name and tooltip. The header no longer renders a logout action.

## Configuration Workbench

`ConfigurationPage` owns the shared page title and subtitle, the Carbon composable tab strip, and query-state validation.

- The `tab` query parameter determines selection.
- Missing or invalid `tab` resolves to `cameras` without rendering an invalid panel.
- Changing a tab updates the query parameter with router navigation, allowing refresh and browser back/forward.
- Only the selected panel mounts, preventing inactive Cameras, Zones, Gates, and Storage panels from fetching their APIs.
- Existing page implementations become panel components: no duplicated `.app-page` wrapper or repeated h1/subtitle.
- The Gate action that opens the zone editor navigates to `/configuration?tab=zones`.

Every tab preserves its current loading, empty, error, confirmation, admin-gated action, and API behavior. The workbench does not introduce empty future tabs.

## Responsive Zone Editor

On desktop, Zones keeps its existing canvas/detail two-column layout. At the narrow-screen breakpoint, the layout becomes one column: camera selector and canvas/list first, detail editor second. The desktop left divider becomes a top divider, ensuring the canvas has usable width.

## Accessibility

- Preserve `SkipToContent`, keyboard navigation, visible Carbon focus indicators, and semantic tab roles.
- The Configuration tab list has an accessible label.
- The rail logout control and header menu control retain localized accessible names.
- The active Configuration sidebar entry uses existing `NavLink` semantics; the selected configuration subsection is conveyed by the tab's selected state, not color alone.
- Responsive rearrangement keeps DOM/task order: canvas before editor details.

## Files Expected to Change

- `frontend/src/app/AppShell.tsx` — one Configuration nav item, rail focus fix, account logout action.
- `frontend/src/app/theme.scss` — account action/rail styling and narrow-screen zone layout.
- `frontend/src/main.tsx` — canonical Configuration route; remove four legacy routes/imports.
- `frontend/src/features/config/ConfigurationPage.tsx` — new workbench, query tab state, shared title, tabs.
- `frontend/src/features/config/CamerasPage.tsx`
- `frontend/src/features/config/ZonesPage.tsx`
- `frontend/src/features/config/GatesPage.tsx`
- `frontend/src/features/config/StoragePage.tsx` — convert page chrome to reusable panel content; preserve behavior.
- `frontend/src/app/i18n.tsx` — labels only if the existing keys do not cover tabs/account action.
- `frontend/src/__tests__/shell.test.tsx` and existing configuration tests — behavioural regression coverage.

## Verification

1. Add focused tests for: rail link pointer/keyboard activation preserves collapsed state; header control toggles it; Configuration resolves tab query state; Gate opens the Zones tab.
2. Run the focused frontend tests relevant to shell and configuration.
3. Deploy the changed frontend to the development server.
4. Use Playwright directly against the server identified by `temp/data/server-info.txt`, never the unauthenticated local Vite preview, to verify:
   - expanded and rail sidebar states;
   - desktop pointer and keyboard rail navigation;
   - Configuration tab selection, invalid/missing query fallback, refresh, back/forward;
   - all four panels and Gate → Zones transition;
   - logout in expanded and rail account card modes;
   - narrow-screen zone editor stack.
5. Save screenshots for the server interaction evidence.
