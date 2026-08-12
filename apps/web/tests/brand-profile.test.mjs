import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import {
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
})
