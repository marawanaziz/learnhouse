import test from 'node:test'
import assert from 'node:assert/strict'
import { buildResetCompatibilityPath } from '../services/auth/reset-compatibility.ts'

test('redirects the legacy route to /reset and safely preserves required parameters', () => {
  assert.equal(
    buildResetCompatibilityPath({
      email: 'user+tag@example.com',
      resetCode: 'ABC123',
      unrelated: 'must-not-forward',
    }),
    '/reset?email=user%2Btag%40example.com&resetCode=ABC123',
  )
})

test('does not log or forward reset values outside the redirect query', () => {
  const result = buildResetCompatibilityPath({ email: ['user@example.com'], resetCode: [] })
  assert.equal(result, '/reset?email=user%40example.com')
  assert.equal(result.includes('unrelated'), false)
})
