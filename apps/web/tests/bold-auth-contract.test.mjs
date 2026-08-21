import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { existsSync, readFileSync, statSync } from 'node:fs'

const profile = readFileSync(new URL('../services/branding/brandProfile.ts', import.meta.url), 'utf8')
const logo = readFileSync(new URL('../components/Brand/BrandLogo.tsx', import.meta.url), 'utf8')
const authPanel = readFileSync(new URL('../components/Auth/AuthBrandingPanel.tsx', import.meta.url), 'utf8')
const login = readFileSync(new URL('../app/auth/login/login.tsx', import.meta.url), 'utf8')
const globalStyles = readFileSync(new URL('../styles/globals.css', import.meta.url), 'utf8')
const logoEndpoint = readFileSync(new URL('../app/api/branding/logo/route.ts', import.meta.url), 'utf8')

describe('host-scoped BOLD and BBU auth branding contract', () => {
  test('uses the documented circle-only official BOLD derivative without stretching or crop', () => {
    const derivedAsset = new URL('../public/project-bold-emblem.png', import.meta.url)
    assert.equal(existsSync(derivedAsset), true)
    assert.ok(statSync(derivedAsset).size > 1000)
    assert.match(profile, /bold-favicon\.png\?v=3\.4\.0/)
    assert.match(profile, /x=111,y=111,w=290,h=290/)
    assert.match(profile, /logoPath: '\/api\/branding\/logo'/)
    assert.match(logoEndpoint, /project-bold-emblem\.png/)
    assert.match(logo, /src=\{brand\.logoPath\}/)
    assert.match(logo, /alt=\{brand\.logoAlt\}/)
    assert.match(authPanel, /<BrandLogo compact className="w-full h-full p-5" \/>/)
    assert.match(globalStyles, /html\[data-lh-brand='bold'\] \.lh-brand-auth-mark \.lh-brand-logo/)
    assert.match(globalStyles, /object-fit: contain/)
    assert.match(globalStyles, /object-position: center/)
  })

  test('keeps the BBU auth button utilities and isolates BOLD overrides', () => {
    assert.match(login, /bg-\[#113d5d\].*hover:bg-\[#0d3350\].*shadow-\[#113d5d\]\/20/)
    assert.match(login, /bg-indigo-600.*hover:bg-indigo-700/)
    assert.match(globalStyles, /html\[data-lh-brand='bold'\] \.lh-brand-primary-button/)
    assert.match(globalStyles, /html\[data-lh-brand='bold'\] \.lh-brand-input/)
    assert.match(globalStyles, /html\[data-lh-brand='bold'\] :focus-visible/)
    assert.doesNotMatch(globalStyles, /^\.lh-auth-shell\s*\{/m)
    assert.doesNotMatch(globalStyles, /^\.lh-brand-logo\s*\{/m)
    assert.doesNotMatch(globalStyles, /^\.lh-brand-primary-button\s*\{/m)
  })
})
