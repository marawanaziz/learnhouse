import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const eas = require('../eas.json');
const targets = require('../release/store-targets.json');
const pkg = require('../package.json');

test('Apple uploads address the verified existing listing and team', () => {
  assert.equal(eas.submit['upload-only'].ios.ascAppId, targets.ios.appStoreId);
  assert.equal(eas.submit['upload-only'].ios.appleTeamId, targets.ios.appleTeamId);
});
test('Android upload stays a draft and is never sent for review', () => {
  assert.equal(eas.submit['upload-only'].android.track, 'internal');
  assert.equal(eas.submit['upload-only'].android.releaseStatus, 'draft');
  assert.equal(eas.submit['upload-only'].android.changesNotSentForReview, true);
});
test('production requires supplied signing credentials and never auto-uploads', () => {
  assert.equal(eas.build.production.credentialsSource, 'local');
  assert.equal(eas.build.production.distribution, 'store');
  assert.equal(eas.build.production.env.EXPO_NO_CAPABILITY_SYNC, '1');
  for (const script of Object.values(pkg.scripts)) assert.doesNotMatch(script, /--auto-submit/);
  for (const [name, script] of Object.entries(pkg.scripts)) {
    if (name.startsWith('build:production')) assert.match(script, /EXPO_NO_CAPABILITY_SYNC=1 npx/);
  }
});
