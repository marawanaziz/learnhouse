const { withAppBuildGradle, withXcodeProject } = require('expo/config-plugins');

// Gradle reads secrets from the build process, never from generated source files.
module.exports = function withLocalSigning(config) {
  if (process.env.APP_VARIANT !== 'production') return config;
  config = withAppBuildGradle(config, (result) => {
    const marker = '// BBU local production signing';
    if (!result.modResults.contents.includes(marker)) {
      result.modResults.contents += `
${marker}
android {
    signingConfigs {
        bbuRelease {
            def uploadStore = System.getenv('BBU_UPLOAD_STORE')
            if (uploadStore) storeFile file(uploadStore)
            storePassword System.getenv('BBU_UPLOAD_STORE_PASSWORD')
            keyAlias System.getenv('BBU_UPLOAD_ALIAS')
            keyPassword System.getenv('BBU_UPLOAD_KEY_PASSWORD')
        }
    }
    buildTypes.release.signingConfig signingConfigs.bbuRelease
}
`;
    }
    return result;
  });
  return withXcodeProject(config, (result) => {
    if (!process.env.BBU_IOS_PROFILE_UUID) return result;
    const configurations = result.modResults.pbxXCBuildConfigurationSection();
    for (const entry of Object.values(configurations)) {
      const settings = entry.buildSettings;
      if (!settings || String(settings.PRODUCT_BUNDLE_IDENTIFIER).replace(/"/g, '') !== config.ios.bundleIdentifier) continue;
      settings.CODE_SIGN_STYLE = 'Manual';
      settings.CODE_SIGN_IDENTITY = '"Apple Distribution"';
      settings.DEVELOPMENT_TEAM = config.ios.appleTeamId;
      settings.PROVISIONING_PROFILE_SPECIFIER = '"' + process.env.BBU_IOS_PROFILE_UUID + '"';
    }
    return result;
  });
};
