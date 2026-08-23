import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { existsSync, readFileSync, statSync } from 'node:fs'

const profile = readFileSync(new URL('../services/branding/brandProfile.ts', import.meta.url), 'utf8')
const logo = readFileSync(new URL('../components/Brand/BrandLogo.tsx', import.meta.url), 'utf8')
const authPanel = readFileSync(new URL('../components/Auth/AuthBrandingPanel.tsx', import.meta.url), 'utf8')
const login = readFileSync(new URL('../app/auth/login/login.tsx', import.meta.url), 'utf8')
const globalStyles = readFileSync(new URL('../styles/globals.css', import.meta.url), 'utf8')
const logoEndpoint = readFileSync(new URL('../app/api/branding/logo/route.ts', import.meta.url), 'utf8')
const fullLogoEndpoint = readFileSync(new URL('../app/api/branding/full-logo/route.ts', import.meta.url), 'utf8')
const iconEndpoint = readFileSync(new URL('../app/api/branding/icon/route.ts', import.meta.url), 'utf8')

function pngInfo(relativePath) {
  const bytes = readFileSync(new URL(relativePath, import.meta.url))
  assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10])
  return {
    width: bytes.readUInt32BE(16),
    height: bytes.readUInt32BE(20),
    colorType: bytes[25],
  }
}

describe('host-scoped BOLD and BBU auth branding contract', () => {
  test('uses bundled transparent full, emblem, and icon derivatives from the supplied source', () => {
    const full = new URL('../public/project-bold-logo.png', import.meta.url)
    const emblem = new URL('../public/project-bold-emblem.png', import.meta.url)
    const icon = new URL('../public/project-bold-icon.png', import.meta.url)
    for (const asset of [full, emblem, icon]) {
      assert.equal(existsSync(asset), true)
      assert.ok(statSync(asset).size > 1000)
    }
    assert.deepEqual(pngInfo('../public/project-bold-logo.png'), { width: 693, height: 952, colorType: 6 })
    assert.deepEqual(pngInfo('../public/project-bold-emblem.png'), { width: 484, height: 480, colorType: 6 })
    assert.deepEqual(pngInfo('../public/project-bold-icon.png'), { width: 192, height: 192, colorType: 6 })
    assert.match(profile, /logoPath: '\/api\/branding\/logo'/)
    assert.match(profile, /fullLogoPath: '\/api\/branding\/full-logo'/)
    assert.match(logoEndpoint, /project-bold-emblem\.png/)
    assert.match(fullLogoEndpoint, /project-bold-logo\.png/)
    assert.match(iconEndpoint, /project-bold-icon\.png/)
    assert.match(logo, /const logoPath = compact \? brand\.logoPath : brand\.fullLogoPath/)
    assert.match(logo, /src=\{logoPath\}/)
    assert.match(logo, /brand\.fullLogoPath/)
    assert.match(logo, /alt=\{brand\.logoAlt\}/)
    assert.match(authPanel, /<BrandLogo className="w-full h-full p-5" \/>/)
    assert.match(authPanel, /effectiveTextColor/)
    assert.match(globalStyles, /html\[data-lh-brand='bold'\] \.lh-brand-auth-mark \.lh-brand-logo/)
    assert.match(globalStyles, /lh-brand-logo--full/)
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
