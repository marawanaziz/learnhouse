const { buildIdentity } = require('./config/release.cjs');

module.exports = () => {
  const identity = buildIdentity(process.env);
  return {
    name: identity.production ? 'Birth & Baby University' : 'BBU Preview',
    slug: 'birth-and-baby-university',
    ...(process.env.EXPO_OWNER ? { owner: process.env.EXPO_OWNER } : {}),
    version: identity.version,
    orientation: 'default',
    platforms: ['ios', 'android'],
    icon: './assets/bbu-icon.png',
    userInterfaceStyle: 'light',
    ios: {
      bundleIdentifier: identity.bundleIdentifier,
      ...(identity.appleTeamId ? { appleTeamId: identity.appleTeamId } : {}),
      buildNumber: identity.buildNumber,
      supportsTablet: true,
      infoPlist: {
        ITSAppUsesNonExemptEncryption: false,
        NSCameraUsageDescription: 'Take a photo or video when you choose to attach one to your profile or community post.',
        NSMicrophoneUsageDescription: 'Include sound when you choose to record a video attachment.',
        NSPhotoLibraryUsageDescription: 'Choose a photo or video to attach to your profile or community post.',
      },
    },
    android: {
      package: identity.androidPackage,
      versionCode: identity.versionCode,
      softwareKeyboardLayoutMode: 'resize',
      blockedPermissions: ['android.permission.RECORD_AUDIO', 'android.permission.SYSTEM_ALERT_WINDOW'],
    },
    plugins: [
      ['expo-splash-screen', { backgroundColor: '#ffffff', image: './assets/bbu-icon.png', imageWidth: 180 }],
      'expo-web-browser',
    ],
    extra: {
      variant: identity.variant,
      ...(process.env.EAS_PROJECT_ID ? { eas: { projectId: process.env.EAS_PROJECT_ID } } : {}),
    },
  };
};
