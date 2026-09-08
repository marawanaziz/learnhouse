import test from 'node:test';
import assert from 'node:assert/strict';
import { buildIdentity } from '../config/release.cjs';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const targets = require('../release/store-targets.json');

const release = {
  APP_VARIANT: 'production', BBU_IOS_BUNDLE_ID: 'com.birthandbabyuniversity.learn',
  BBU_ANDROID_PACKAGE: 'com.birthandbabyuniversity.learn', BBU_APP_VERSION: '3.2.0',
  BBU_IOS_BUILD_NUMBER: '120', BBU_ANDROID_VERSION_CODE: '120',
};
test('default identity is visibly separate from a store release', () => {
  const result = buildIdentity({});
  assert.equal(result.production, false);
  assert.equal(result.androidPackage, 'com.birthandbabyuniversity.wrapper.preview');
});
test('production defaults to the two verified existing listings and their next build numbers', () => {
  const result = buildIdentity({ APP_VARIANT: 'production' });
  assert.equal(result.bundleIdentifier, 'com.birthandbabyuniversity.learn');
  assert.equal(result.androidPackage, 'com.birthandbabyuniversity.learn');
  assert.equal(result.appleTeamId, '2V6MAB58ZP');
  assert.equal(result.version, '2.5.0');
  assert.equal(result.buildNumber, '21');
  assert.equal(result.versionCode, 20);
  assert.ok(Number(result.buildNumber) > Number(targets.ios.observedBuildNumber));
  assert.ok(result.versionCode > targets.android.observedVersionCode);
});
test('environment variables cannot redirect production to a different app or Apple team', () => {
  for (const invalid of [
    { BBU_IOS_BUNDLE_ID: 'com.client.university' },
    { BBU_ANDROID_PACKAGE: 'com.birthandbabyuniversity.wrapper.preview' },
    { BBU_APPLE_TEAM_ID: 'OTHERTEAM12' },
  ]) assert.throws(() => buildIdentity({ ...release, ...invalid }), /existing listing/);
});
test('versions and build numbers already used by the stores are rejected', () => {
  for (const invalid of [
    { BBU_APP_VERSION: '2.4.1' }, { BBU_APP_VERSION: '2.3.99' },
    { BBU_IOS_BUILD_NUMBER: '20' }, { BBU_ANDROID_VERSION_CODE: '19' },
  ]) assert.throws(() => buildIdentity({ ...release, ...invalid }), /newer|exceed/);
});
test('release preserves the exact identities and build values supplied by the owner', () => {
  const result = buildIdentity(release);
  assert.equal(result.bundleIdentifier, release.BBU_IOS_BUNDLE_ID);
  assert.equal(result.androidPackage, release.BBU_ANDROID_PACKAGE);
  assert.equal(result.versionCode, 120);
  assert.equal(result.buildNumber, '120');
});
test('invalid release values fail before packaging', () => {
  for (const invalid of [
    { BBU_ANDROID_VERSION_CODE: '1.5' }, { BBU_ANDROID_VERSION_CODE: '0' },
    { BBU_ANDROID_VERSION_CODE: '2100000001' }, { BBU_APP_VERSION: 'next' },
    { BBU_IOS_BUILD_NUMBER: 'test' }, { BBU_IOS_BUNDLE_ID: 'com.example.app' },
    { BBU_ANDROID_PACKAGE: 'com.client.123' }, { APP_VARIANT: 'prod' },
    { EAS_PROJECT_ID: 'placeholder' },
  ]) assert.throws(() => buildIdentity({ ...release, ...invalid }));
});
