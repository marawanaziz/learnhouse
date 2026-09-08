# Birth & Baby University mobile wrapper

A thin Expo / React Native WebView for https://learn.birthandbabyuniversity.com/. The existing website supplies every learning screen, its bottom navigation, and the profile menu. There is no second implementation of courses, library, communities, authentication, or checkout.

## What is prepared

- iOS and Android source projects, generated with Expo Prebuild.
- Existing BBU artwork for the app icon and launch screen.
- Persistent WebView cookies and storage; the website continues to own login and logout.
- Android hardware back, iOS swipe navigation, inline/fullscreen video configuration, safe areas, and keyboard avoidance.
- External HTTPS links in the system browser; phone and email links in their device apps. Exact-origin checks keep university pages inside the wrapper.
- Offline notice, loading timeout, and explicit recovery after a failed load or terminated WebView. Recovery never automatically resubmits a form.
- Preview APK / iOS internal distribution, iOS simulator, and production AAB / iOS store build profiles.

## Run locally

Use Node 22.13 or newer and Python 3. Run commands from `apps/mobile`:

```sh
npm ci
npm run check
npm start
```

Scan the development QR with an Expo Go version supporting SDK 57. Expo Go is only a development smoke test; it does not verify the final splash screen, permissions, signing, or a production WebView session.

With native tooling installed:

```sh
npm run ios
npm run android
```

This uses Expo SDK 57 / React Native 0.86. Supported OS baselines are iOS 16.4+ and Android 7+. Native iOS builds require Xcode 26.4+; Android uses SDK 36. Confirm these baselines against the previous app before release.

`npm run prebuild` generates preview iOS and Android projects. Use `APP_VARIANT=production npx expo prebuild --clean --no-install` to generate the projects for the existing store apps. These folders are intentionally ignored: app config and dependencies are the source of truth. Do not hand-edit generated projects.

## Make installable preview builds

Sign into the client-owned Expo account and link its EAS project:

```sh
npx eas-cli@latest login
npx eas-cli@latest init
```

Because the app uses dynamic config, record the returned project UUID as `EAS_PROJECT_ID` and account/organization as `EXPO_OWNER` in `.env.local` (copy `.env.example`). Also configure those variables in the EAS preview and production environments. Do not store signing keys or account passwords in source control.

```sh
npm run build:preview:android
npm run build:preview:ios
```

The Android preview is an installable APK. iOS internal distribution requires an Apple Developer membership and registering the test device with `npx eas-cli@latest device:create`; EAS prepares an ad hoc provisioning profile. An iOS simulator build can instead use `npx eas-cli@latest build --platform ios --profile simulator`.

The preview is named **BBU Preview** and uses `com.birthandbabyuniversity.wrapper.preview` on both platforms. It installs separately from the client's existing app.

Run EAS commands from `apps/mobile`. The repository-root `.easignore` uploads only this self-contained app, excluding the website, API, local environment files, generated native projects, and dependency/build folders. EAS regenerates the native projects for the selected build profile.

## Update the existing store listings

Production is pinned to the live console records in `release/store-targets.json`, verified September 8, 2026:

| Setting | Verified value |
| --- | --- |
| iOS Bundle ID | `com.birthandbabyuniversity.learn` |
| App Store Connect app ID | `6739436162` |
| Apple team | `2V6MAB58ZP` — Birth and Baby University, Llc |
| Android package | `com.birthandbabyuniversity.learn` |
| Play Console app ID | `4972007289590886738` |
| Current releases | iOS `2.4.1 (20)`; Android `2.4.1 (19)` |
| Prepared update | Version `2.5.0`; iOS build `21`; Android version code `20` |

Environment variables cannot redirect production to another app or Apple team. Optional `BBU_APP_VERSION`, `BBU_IOS_BUILD_NUMBER`, and `BBU_ANDROID_VERSION_CODE` overrides must exceed the recorded store versions. Recheck console history immediately before the next build if another developer has uploaded anything since this verification.

Production uses **local signing credentials** so a new EAS project cannot accidentally generate an unrelated Android upload key. Copy `credentials.example.json` to ignored `credentials.json`, place signing files in ignored `signing/`, and replace the local placeholders. Keep both out of Git. EAS receives the credentials through its dedicated signing process; `.easignore` excludes them from the source archive.

Production build commands also set `EXPO_NO_CAPABILITY_SYNC=1`. The old App ID already has capabilities enabled (including Associated Domains); the wrapper must not disable those services on Apple's portal while the old app remains live. This uses Expo's documented capability-sync switch rather than modifying the existing registration.

- Android: obtain the existing upload keystore, alias, keystore password, and key password. The upload certificate must have SHA-256 `BC:85:76:47:FD:46:48:04:67:D9:83:D8:D2:AC:FE:37:AB:82:72:97:B1:51:3E:CF:27:23:97:72:07:34:D8:DF`. This differs from Google's app-signing certificate. No key reset has been requested.
- iOS: supply a `.p12` containing a distribution certificate and its private key, plus an App Store provisioning profile for the exact Bundle ID and Apple team. The portal currently has a Circle-created iOS Distribution certificate expiring December 21, 2026; its private key is not on this Mac. A new distribution certificate within the same team can also sign an update; the original private key is not mandatory on iOS.
- `npm run signing:check` verifies Android's certificate fingerprint and the iOS private-key/certificate/profile match, team, app ID, profile type, and expiry. It reads credentials locally and does not upload or change them. It needs `keytool` for Android and macOS `security` plus `openssl` for iOS.

```sh
APP_VARIANT=production npx expo config --type public
npm run signing:check
npm run build:production
```

Use the same Apple team and existing Bundle ID. On Android, use the existing upload keystore registered with Play App Signing (or the original app-signing key if Play App Signing was never enabled). Do not generate a replacement key blindly; a lost upload key must follow Play's reset process. Preview signing credentials are separate from production credentials.

Platforms can also be built separately with `npm run build:production:ios` and `npm run build:production:android`.

## Upload without review or release

The owner permits build uploads, but **does not authorize review submission or release**. Do not create a new listing.

`eas.json` contains an explicit `upload-only` profile. Apple is pinned to app `6739436162` and team `2V6MAB58ZP`. Android targets the internal track with `releaseStatus: draft` and `changesNotSentForReview: true`. Building never automatically uploads.

After validating the exact signed production artifacts, use a specific EAS build ID (never select an unverified latest/preview build):

```sh
APP_VARIANT=production npx eas-cli@latest submit --platform ios --profile upload-only --id IOS_BUILD_ID
APP_VARIANT=production npx eas-cli@latest submit --platform android --profile upload-only --id ANDROID_BUILD_ID
```

Keep `APP_VARIANT=production` on these commands so the uploader reads the existing app's package instead of the preview package. Despite the CLI command name, the Apple operation uploads a binary for TestFlight processing; App Review is a separate action. On Google, the configured operation leaves a draft without sending changes for review. API upload credentials are separate from signing credentials. Existing App Store Connect API access and a Play service account can be used if supplied; Google uploads can also be performed manually through the existing app's draft release UI.

Stop after verifying the uploaded iOS build appears in TestFlight and the Android artifact appears in the existing app without an in-review or published release. Do not add external TestFlight groups, click Submit for Review / Send for Review / Start rollout / Publish, or enable automatic release. The owner handles those actions.

## Device acceptance before submission

These checks must be performed in signed preview/release builds on an iPhone and an Android phone:

1. Cold launch, email/password login, force-close/reopen session persistence, logout, password reset, and account/profile actions.
2. Courses, Library, Communities, Access More Courses, and profile dropdown use the existing destinations. Check small phones, notches, Android back, iOS swipe, keyboard, rotation, and tablet layout.
3. Open a real enrolled lesson. Play, pause, seek, enter/exit fullscreen, background/foreground the app, and confirm progress is saved. Check each video provider the client uses.
4. Open actual course PDFs and library downloads on both platforms, including private files. PDF iframe rendering and attachment handling differ between WKWebView and Android WebView; native document viewing/download support has not been added or certified. Resolve any failed document flow before release. External browsers have separate cookies and may require login again.
5. Exercise image/file selection for a profile or community post, including denied permissions. Permission descriptions cover iOS photo/video attachments; no separate recording feature is implemented.
6. Launch with airplane mode, lose connectivity mid-session, reconnect and tap Try again. Verify recovery returns to learning without a duplicate form submission.
7. Test external links and return to the app. Existing store/checkout destinations are preserved. Purchase-policy decisions are outside this preparation task at the owner's instruction.
8. Verify the final icon, splash, app name, and existing app identity. Test an update over an installed old release when a correctly signed testing path is available. Old Circle sessions are not migrated; confirm the user can sign into the website account after updating.

Social OAuth return flows, push notifications, offline course downloads, native purchases, and verified universal/app links are not implemented. The current website email/password flow stays inside the WebView. Ordinary OS browser sessions are not imported into the app.

## Validation performed on September 8, 2026

- TypeScript and navigation/release configuration regression tests are run with `npm run check`. Signing checks have separate regression coverage for wrong app/team/key, expired profiles, and non-store profiles.
- Expo dependency compatibility passed. Expo Doctor passed 21/21 checks before native generation; with generated native folders it passes 20/21, with the remaining check reporting missing CocoaPods on this Mac.
- Release JavaScript/Hermes bundles exported for iOS and Android.
- Native iOS and Android projects generated and configuration inspected.
- Production Expo config now resolves to the verified existing app IDs, Apple team, and incremented build numbers. EAS archive filtering verified to include the mobile source and exclude server code, secrets, dependencies, and generated builds.
- Native compilation, signing, install, and device acceptance are pending: this Mac has Command Line Tools but no full Xcode or Android SDK, and EAS is not signed in.
- npm audit reports a moderate transitive `uuid` advisory through Expo's Xcode configuration tooling. Its suggested automatic changes downgrade Expo packages across SDK versions, so no incompatible downgrade was applied. Recheck with the next SDK-compatible tooling updates.

Console observations for the owner's later release: Apple shows a pending updated developer agreement; existing app metadata still contains Circle-specific support and review instructions. No agreements, metadata, account permissions, signing keys, or store releases have been changed by this preparation.

## References

- [Expo SDK 57](https://docs.expo.dev/versions/v57.0.0/)
- [SDK-compatible WebView](https://docs.expo.dev/versions/v57.0.0/sdk/webview/)
- [WebView API](https://github.com/react-native-webview/react-native-webview/blob/master/docs/Reference.md)
- [EAS monorepos](https://docs.expo.dev/build-reference/build-with-monorepos/)
- [EAS build variants](https://docs.expo.dev/build-reference/variants/)
- [EAS ignore files](https://docs.expo.dev/build-reference/easignore/)
