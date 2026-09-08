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

Use Node 22.13 or newer. Run commands from `apps/mobile`:

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

`npm run prebuild` generates `ios/BBUPreview.xcodeproj` and `android/`. These folders are intentionally ignored: app config and dependencies are the source of truth. After changing native settings, regenerate with `npx expo prebuild --clean --no-install`. Do not hand-edit generated projects.

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

Production config deliberately requires these values instead of guessing the identity of the client's old apps:

| Variable | Source |
| --- | --- |
| `BBU_IOS_BUNDLE_ID` | Exact Bundle ID in the existing App Store Connect app |
| `BBU_ANDROID_PACKAGE` | Exact package name in the existing Play Console app |
| `BBU_APP_VERSION` | Next public version in `major.minor.patch` format |
| `BBU_IOS_BUILD_NUMBER` | A new iOS build number, higher than the previous build |
| `BBU_ANDROID_VERSION_CODE` | An integer higher than every previous uploaded Android build |

Add them to the EAS **production** environment as plain-text configuration values and to `.env.local` for local inspection. These identifiers are not credentials. The guard verifies presence and syntax; it cannot compare against private store history.

```sh
APP_VARIANT=production npx expo config --type public
npm run build:production
```

Use the same Apple team and existing Bundle ID. On Android, use the existing upload keystore registered with Play App Signing (or the original app-signing key if Play App Signing was never enabled). Do not generate a replacement key blindly; a lost upload key must follow Play's reset process. Preview signing credentials are separate from production credentials.

Upload the resulting builds to TestFlight and the existing Play app's internal testing track first. Create a new version/release **inside the existing listings**. Building does not submit or release anything; no automatic submission is configured.

## Device acceptance before submission

These checks must be performed in signed preview/release builds on an iPhone and an Android phone:

1. Cold launch, email/password login, force-close/reopen session persistence, logout, password reset, and account/profile actions.
2. Courses, Library, Communities, Access More Courses, and profile dropdown use the existing destinations. Check small phones, notches, Android back, iOS swipe, keyboard, rotation, and tablet layout.
3. Open a real enrolled lesson. Play, pause, seek, enter/exit fullscreen, background/foreground the app, and confirm progress is saved. Check each video provider the client uses.
4. Open actual course PDFs and library downloads on both platforms, including private files. PDF iframe rendering and attachment handling differ between WKWebView and Android WebView; native document viewing/download support has not been added or certified. Resolve any failed document flow before release. External browsers have separate cookies and may require login again.
5. Exercise image/file selection for a profile or community post, including denied permissions. Permission descriptions cover iOS photo/video attachments; no separate recording feature is implemented.
6. Launch with airplane mode, lose connectivity mid-session, reconnect and tap Try again. Verify recovery returns to learning without a duplicate form submission.
7. Test external links and return to the app. Existing store/checkout destinations are preserved. Confirm the client's intended digital-course purchase flow meets the current store rules before submission; wrapper preparation does not settle billing eligibility.
8. Verify the final icon, splash, app name, privacy policy, account deletion path, review account, privacy/data-safety declarations, age rating, screenshots, and existing app identity. Evaluate Apple's minimum-functionality requirement for this thin wrapper before submitting.

Social OAuth return flows, push notifications, offline course downloads, native purchases, and verified universal/app links are not implemented. The current website email/password flow stays inside the WebView. Ordinary OS browser sessions are not imported into the app.

## Validation performed on September 8, 2026

- TypeScript check and 10 navigation/release configuration regression tests passed.
- Expo dependency compatibility passed. Expo Doctor passed 21/21 checks before native generation; with generated native folders it passes 20/21, with the remaining check reporting missing CocoaPods on this Mac.
- Release JavaScript/Hermes bundles exported for iOS and Android.
- Native iOS and Android projects generated and configuration inspected.
- Production Expo config verified with fixture identifiers; the client's actual store identifiers are still required. EAS archive filtering verified to include the mobile source and exclude server code, secrets, dependencies, and generated builds.
- Native compilation, signing, install, and device acceptance are pending: this Mac has Command Line Tools but no full Xcode or Android SDK, and EAS is not signed in.
- npm audit reports a moderate transitive `uuid` advisory through Expo's Xcode configuration tooling. Its suggested automatic changes downgrade Expo packages across SDK versions, so no incompatible downgrade was applied. Recheck with the next SDK-compatible tooling updates.

## References

- [Expo SDK 57](https://docs.expo.dev/versions/v57.0.0/)
- [SDK-compatible WebView](https://docs.expo.dev/versions/v57.0.0/sdk/webview/)
- [WebView API](https://github.com/react-native-webview/react-native-webview/blob/master/docs/Reference.md)
- [EAS monorepos](https://docs.expo.dev/build-reference/build-with-monorepos/)
- [EAS build variants](https://docs.expo.dev/build-reference/variants/)
- [EAS ignore files](https://docs.expo.dev/build-reference/easignore/)
