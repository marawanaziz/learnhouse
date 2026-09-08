import test from 'node:test';
import assert from 'node:assert/strict';
import { buildIdentity } from '../config/release.cjs';

const release = {
  APP_VARIANT: 'production', BBU_IOS_BUNDLE_ID: 'com.client.university',
  BBU_ANDROID_PACKAGE: 'com.client.university', BBU_APP_VERSION: '3.2.0',
  BBU_IOS_BUILD_NUMBER: '120', BBU_ANDROID_VERSION_CODE: '120',
};
test('default identity is visibly separate from a store release', () => {
  const result = buildIdentity({});
  assert.equal(result.production, false);
  assert.equal(result.androidPackage, 'com.birthandbabyuniversity.wrapper.preview');
});
test('production cannot silently fall back to guessed identifiers or build numbers', () => {
  for (const key of Object.keys(release).filter((key) => key !== 'APP_VARIANT')) {
    const env = { ...release };
    delete env[key];
    assert.throws(() => buildIdentity(env), new RegExp(key));
  }
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
