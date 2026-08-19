import test from 'node:test'
import assert from 'node:assert/strict'
import { buildOrgResetRequest } from '../services/auth/reset-request.ts'

test('organization reset requests keep the learner email out of the URL', () => {
  const email = 'greenthumbgranny76@gmail.com'
  const { url, body } = buildOrgResetRequest('https://learn.example/api/v1/', email, 1)

  assert.equal(url, 'https://learn.example/api/v1/users/reset_password/send_reset_code')
  assert.equal(url.includes(email), false)
  assert.deepEqual(body, { email, org_id: 1 })
})
