function buildIdentity(env) {
  const variant = env.APP_VARIANT || 'preview';
  if (!['development', 'preview', 'production'].includes(variant)) throw new Error('Unknown APP_VARIANT');
  const production = variant === 'production';
  const required = (name) => {
    const value = env[name]?.trim();
    if (!value) throw new Error(`Production requires ${name}; use the existing store app identity and a higher build number.`);
    return value;
  };
  const bundleIdentifier = production ? required('BBU_IOS_BUNDLE_ID') : 'com.birthandbabyuniversity.wrapper.preview';
  const androidPackage = production ? required('BBU_ANDROID_PACKAGE') : 'com.birthandbabyuniversity.wrapper.preview';
  const version = production ? required('BBU_APP_VERSION') : '0.1.0';
  const buildNumber = production ? required('BBU_IOS_BUILD_NUMBER') : '1';
  const versionCodeString = production ? required('BBU_ANDROID_VERSION_CODE') : '1';
  const versionCode = Number(versionCodeString);
  if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error('BBU_APP_VERSION must use major.minor.patch');
  if (!/^\d+(\.\d+){0,2}$/.test(buildNumber)) throw new Error('BBU_IOS_BUILD_NUMBER must be numeric');
  if (!/^[1-9]\d*$/.test(versionCodeString) || !Number.isSafeInteger(versionCode) || versionCode > 2100000000) throw new Error('Invalid BBU_ANDROID_VERSION_CODE');
  if (!/^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$/.test(bundleIdentifier)) throw new Error('Invalid BBU_IOS_BUNDLE_ID');
  if (!/^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$/.test(androidPackage)) throw new Error('Invalid BBU_ANDROID_PACKAGE');
  if (production && [bundleIdentifier, androidPackage].some((value) => /(^|\.)(preview|development|example)(\.|$)/i.test(value))) throw new Error('Production cannot use a placeholder identifier');
  if (env.EAS_PROJECT_ID && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(env.EAS_PROJECT_ID)) throw new Error('Invalid EAS_PROJECT_ID');
  return { variant, production, bundleIdentifier, androidPackage, version, buildNumber, versionCode };
}

module.exports = { buildIdentity };
