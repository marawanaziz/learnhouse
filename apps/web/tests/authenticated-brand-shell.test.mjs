import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { readFileSync } from 'node:fs'

const dashboardMenu = readFileSync(new URL('../components/Dashboard/Menus/DashLeftMenu.tsx', import.meta.url), 'utf8')
const accountSidebar = readFileSync(new URL('../components/Objects/Account/AccountSidebar.tsx', import.meta.url), 'utf8')
const globalStyles = readFileSync(new URL('../styles/globals.css', import.meta.url), 'utf8')

describe('host-scoped authenticated shell branding', () => {
  test('dashboard identity uses official BOLD BrandLogo while preserving BBU organization fallback', () => {
    assert.match(dashboardMenu, /useBrand/)
    assert.match(dashboardMenu, /brand\.key === 'bold'/)
    assert.match(dashboardMenu, /<BrandLogo compact/)
    assert.match(dashboardMenu, /brand\.displayName/)
    assert.match(dashboardMenu, /org\?\.logo_image/)
    assert.match(dashboardMenu, /lh-dashboard-sidebar/)
    assert.doesNotMatch(dashboardMenu, /bg-\[#0f0f10\]/)
  })

  test('account navigation uses semantic token classes instead of gray-only state classes', () => {
    assert.match(accountSidebar, /useBrand/)
    assert.match(accountSidebar, /data-brand=\{brand\.key\}/)
    assert.match(accountSidebar, /lh-account-nav-item--active/)
    assert.match(accountSidebar, /lh-account-nav-item--inactive/)
    assert.doesNotMatch(accountSidebar, /bg-gray-900|text-gray-700/)
  })

  test('BOLD overrides are host-scoped and cover active, inactive, hover, focus, and selection states', () => {
    assert.match(globalStyles, /html\[data-lh-brand='bold'\] \.lh-dashboard-sidebar/)
    assert.match(globalStyles, /html\[data-lh-brand='bold'\] \.lh-account-sidebar/)
    assert.match(globalStyles, /lh-brand-primary/)
    assert.match(globalStyles, /lh-brand-accent/)
    assert.match(globalStyles, /focus-visible/)
    assert.match(globalStyles, /::selection/)
    assert.match(globalStyles, /\.lh-account-nav-item--active/)
  })
})
