import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import {
  BOLD_ASSET_SOURCES,
  BRAND_PROFILES,
  BRAND_HOSTS,
  brandKeyFromHostname,
  getBrandProfile,
  getBrandProfileForHostname,
  normalizeHostname,
} from '../services/branding/brandProfile.ts'

describe('Project BOLD host brand contract', () => {
  test('selects BOLD only for the exact allowlisted hostname', () => {
    assert.equal(brandKeyFromHostname(BRAND_HOSTS.bold), 'bold')
    assert.equal(brandKeyFromHostname('LEARN.BOLDMOVEMENT.ORG:443'), 'bold')
    assert.equal(brandKeyFromHostname('boldmovement.org'), 'bbu')
    assert.equal(brandKeyFromHostname('learn.boldmovement.org.attacker.example'), 'bbu')
    assert.equal(brandKeyFromHostname(BRAND_HOSTS.bbu), 'bbu')
  })

  test('falls back safely for unknown and malformed host input', () => {
    assert.equal(normalizeHostname('learn.boldmovement.org, attacker.example'), '')
    assert.equal(brandKeyFromHostname(''), 'bbu')
    assert.equal(brandKeyFromHostname('https://learn.boldmovement.org'), 'bbu')
    assert.equal(getBrandProfileForHostname('unregistered.example').key, 'bbu')
  })

  test('brand profiles do not alter the underlying organization contract', () => {
    assert.equal(getBrandProfile('bold').displayName, 'Project BOLD')
    assert.match(getBrandProfile('bold').partnershipLine, /Birth & Baby University/)
    assert.equal(getBrandProfile('bbu').displayName, 'Birth & Baby University')
  })

  test('keeps the official BOLD assets, tokens, and type contract explicit', () => {
    const bold = BRAND_PROFILES.bold
    assert.equal(bold.logoPath, '/api/branding/logo')
    assert.equal(bold.faviconPath, '/api/branding/icon')
    assert.equal(bold.colors.primary, '#0E335D')
    assert.equal(bold.colors.accent, '#CD2E3A')
    assert.equal(bold.colors.paper, '#FAF6EE')
    assert.equal(bold.colors.ink, '#16324C')
    assert.equal(bold.fonts.body, 'Inter')
    assert.equal(bold.fonts.heading, 'Fraunces')
    assert.match(BOLD_ASSET_SOURCES.logo, /bold-favicon\.png/)
    assert.match(BOLD_ASSET_SOURCES.favicon, /bold-favicon\.png/)
  })
})
