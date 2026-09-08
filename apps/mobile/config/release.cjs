const targets = require('../release/store-targets.json');

function newerVersion(candidate, previous) {
  const a = candidate.split('.').map(Number);
  const b = previous.split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    if (a[i] !== b[i]) return a[i] > b[i];
  }
  return false;
}

function buildIdentity(env) {
  const variant = env.APP_VARIANT || 'preview';
  if (!['development', 'preview', 'production'].includes(variant)) throw new Error('Unknown APP_VARIANT');
  const production = variant === 'production';
  const valueOr = (name, fallback) => env[name]?.trim() || String(fallback);
  const bundleIdentifier = production ? targets.ios.bundleIdentifier : 'com.birthandbabyuniversity.wrapper.preview';
  const androidPackage = production ? targets.android.packageName : 'com.birthandbabyuniversity.wrapper.preview';
  const appleTeamId = production ? targets.ios.appleTeamId : undefined;
  const version = production ? valueOr('BBU_APP_VERSION', targets.nextRelease.version) : '0.1.0';
  const buildNumber = production ? valueOr('BBU_IOS_BUILD_NUMBER', targets.nextRelease.iosBuildNumber) : '1';
  const versionCodeString = production ? valueOr('BBU_ANDROID_VERSION_CODE', targets.nextRelease.androidVersionCode) : '1';
  const versionCode = Number(versionCodeString);
  if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error('BBU_APP_VERSION must use major.minor.patch');
  if (!/^[1-9]\d*$/.test(buildNumber) || !Number.isSafeInteger(Number(buildNumber))) throw new Error('BBU_IOS_BUILD_NUMBER must be a positive integer');
  if (!/^[1-9]\d*$/.test(versionCodeString) || !Number.isSafeInteger(versionCode) || versionCode > 2100000000) throw new Error('Invalid BBU_ANDROID_VERSION_CODE');
  if (!/^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$/.test(bundleIdentifier)) throw new Error('Invalid BBU_IOS_BUNDLE_ID');
  if (!/^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$/.test(androidPackage)) throw new Error('Invalid BBU_ANDROID_PACKAGE');
  if (production) {
    // These are updates to verified listings. Environment overrides cannot redirect the release.
    for (const [key, expected] of Object.entries({ BBU_IOS_BUNDLE_ID: bundleIdentifier, BBU_ANDROID_PACKAGE: androidPackage, BBU_APPLE_TEAM_ID: appleTeamId })) {
      if (env[key]?.trim() && env[key].trim() !== expected) throw new Error(`${key} must match the existing listing: ${expected}`);
    }
    if (!newerVersion(version, targets.ios.observedVersion) || !newerVersion(version, targets.android.observedVersion)) throw new Error('BBU_APP_VERSION must be newer than the verified store versions');
    if (Number(buildNumber) <= Number(targets.ios.observedBuildNumber)) throw new Error('BBU_IOS_BUILD_NUMBER must exceed the latest verified iOS build');
    if (versionCode <= targets.android.observedVersionCode) throw new Error('BBU_ANDROID_VERSION_CODE must exceed every verified Android upload');
  }
  if (env.EAS_PROJECT_ID && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(env.EAS_PROJECT_ID)) throw new Error('Invalid EAS_PROJECT_ID');
  return { variant, production, bundleIdentifier, androidPackage, appleTeamId, version, buildNumber, versionCode };
}

module.exports = { buildIdentity };
