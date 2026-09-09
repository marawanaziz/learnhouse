# Birth & Baby University mobile wrapper

A thin Expo / React Native WebView for https://learn.birthandbabyuniversity.com/. The existing website supplies every learning screen, its bottom navigation, and the profile menu. There is no second implementation of courses, library, communities, authentication, or checkout.

## What is prepared

- iOS and Android source projects, generated with Expo Prebuild.
- Existing BBU artwork for the app icon and launch screen.
- Persistent WebView cookies and storage; the website continues to own login and logout.
- Android hardware back, iOS swipe navigation, inline/fullscreen video configuration, safe areas, and keyboard avoidance.
- External HTTPS links in the system browser; phone and email links in their device apps. Exact-origin checks keep university pages inside the wrapper.
- Offline notice, loading timeout, and explicit recovery after a failed load or terminated WebView. Recovery never automatically resubmits a form.
- Local preview APK / iOS simulator builds and production AAB / iOS archive exports.

## Run locally

Use Node 22.13 or newer and Python 3. Run commands from `apps/mobile`:

```sh
npm ci
npm run check
npm start
```

Scan the development QR with an Expo Go version supporting SDK 55. Expo Go is only a development smoke test; it does not verify the final splash screen, permissions, signing, or a production WebView session.

With native tooling installed:

```sh
npm run ios
npm run android
```

This uses Expo SDK 55 / React Native 0.83. Supported OS baselines are iOS 15.1+ and Android 7+. Native iOS builds require Xcode 26.2+; Android uses SDK 36. Confirm these baselines against the previous app before release.

`npm run prebuild` generates preview iOS and Android projects. Use `APP_VARIANT=production npx expo prebuild --clean --no-install` to generate the projects for the existing store apps. These folders are intentionally ignored: app config and dependencies are the source of truth. Do not hand-edit generated projects.

## Build on the owner's Mac

Cloud builds are not used. No Expo/EAS login or AWS account is needed. Expo is the local app framework and prebuild CLI; Gradle and Xcode compile the native binaries.

Java 17, CocoaPods, Android SDK 36, build-tools 36.0.0, NDK 27.1.12297006 and CMake 3.22.1 are installed. Xcode 26.3 for Apple silicon is installed at `/Applications/Xcode.app` on macOS 15.7.3; its code signature, first-launch completion and included iOS 26.2 SDK are verified. Device platform support is checked separately from SDK presence with Xcode’s destination validation. The iOS 26.2 ARM64 platform/runtime package is being installed after Xcode reported the device archive destination unavailable. watchOS, tvOS, visionOS and predictive code completion are not needed for this wrapper. The helper selects Xcode through `DEVELOPER_DIR` without changing the Mac's global developer directory.

```sh
source scripts/local-tools.sh
npm run build:preview:android
npm run build:preview:ios
```

The Android preview is an APK signed with the generated debug key. The iOS preview is a simulator Release build. Both use the separate `com.birthandbabyuniversity.wrapper.preview` identifier and **BBU Preview** name. Physical iPhone preview installation additionally requires an appropriate development/ad hoc profile; the App Store profile is not a direct-install profile.

The local build helper regenerates the selected native platform for the selected variant. `plugins/with-local-signing.js` gives production Android its upload-key signing configuration and selects the iOS App Store profile for the app target only. Signing passwords stay in the build process environment or protected local credential files, never generated Gradle source. iOS uses a temporary signing keychain and restores the previous keychain search list afterward.

Production outputs are saved in `artifacts/`. iOS creates an archive and exports an IPA locally; Android creates an AAB. Building does not upload or submit anything.

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

Production uses **local signing credentials** pinned to the existing store apps. On September 9, 2026, the owner authorized replacement credentials; ignored `credentials.json` and `signing/` are now populated on this Mac. Keep both out of Git. A protected local backup is at `~/.local/share/bbu-signing/2026-09-09/`; it is not an off-device backup. The local build helper reads these files on this Mac; they are not uploaded to a build service.

The local build helper also sets `EXPO_NO_CAPABILITY_SYNC=1` and never requests portal capability synchronization. The old App ID already has capabilities enabled (including Associated Domains); the wrapper must not disable those services on Apple's portal while the old app remains live. This uses Expo's documented capability-sync switch rather than modifying the existing registration.

- Android: a new RSA-2048 upload keystore was generated and its public PEM submitted through the existing app's **Request upload key reset** flow on September 9, 2026. Google currently shows the request as **pending**, with no activation time displayed. New upload SHA-256: `8F:76:72:C1:08:55:44:3A:51:42:28:1D:49:DA:62:95:D3:0D:1C:5A:E6:70:8F:CE:47:AB:DD:FF:7B:64:67:B4`. Both passwords and private-key access were validated. The old active fingerprint remains pinned in `release/store-targets.json`, so the Android production preflight intentionally stops until Google's activation is verified. After activation, confirm the new fingerprint in Play Console, record that evidence, and update the pin. Google's actual app-signing key was not changed.
- iOS: new Apple Distribution certificate `5QG57AVD4Z` expires September 9, 2027. App Store profile `GTF9824HGC`, named `BBU App Store 2026-09-09`, targets the existing Bundle ID and team. The encrypted `.p12`, private-key match, profile certificate, profile type, expiry, and app/team identifiers all passed `python3 scripts/check-signing.py ios`. The original Circle certificate/profile were left intact.
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

After validating the signed artifacts, upload the iOS archive using Xcode Organizer/Transporter and the Android AAB using the existing app's Play Console draft release. Keep App Review and rollout as separate, unauthorized actions. The historical `eas.json` upload-only policy remains as a reference; do not run EAS commands for this task.

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
- At the initial September 8 check, native tooling was absent. The September 9 local setup installs it; see the migration status below.
- npm audit reports a moderate transitive `uuid` advisory through Expo's Xcode configuration tooling. Its suggested automatic changes downgrade Expo packages across SDK versions, so no incompatible downgrade was applied. Recheck with the next SDK-compatible tooling updates.

Console observations for the owner's later release: Apple shows a pending updated developer agreement; existing app metadata still contains Circle-specific support and review instructions. No Developer Program agreements, metadata, app capabilities, review submissions, or store releases were changed. The local Xcode software license was accepted as part of the authorized installation. The explicitly authorized signing credential setup on September 9 is documented above.

## References

- [Expo SDK 55](https://docs.expo.dev/versions/v55.0.0/)
- [SDK-compatible WebView](https://docs.expo.dev/versions/v55.0.0/sdk/webview/)
- [WebView API](https://github.com/react-native-webview/react-native-webview/blob/master/docs/Reference.md)
- [Expo local production builds](https://docs.expo.dev/guides/local-app-production/)
- [Android command-line builds](https://developer.android.com/build/building-cmdline)
- [Xcode system requirements](https://developer.apple.com/xcode/system-requirements)

## SDK 55 migration — September 9, 2026

- Expo 55.0.31 / React Native 0.83.10 / React 19.2.0, TypeScript 5.9, and SDK-compatible native modules are pinned in the lockfile.
- Metro runtime and React DOM are explicitly aligned with SDK 55 to prevent optional peer resolution from retaining SDK 57 or choosing a mismatched React DOM release.
- TypeScript, all 19 existing tests, dependency compatibility, both production Hermes exports, and native prebuild passed after the migration.
- Generated production identifiers, version/build numbers, iOS profile selection and Android upload-key signing configuration are inspected separately from device acceptance.
- The ten moderate npm audit entries all trace to the existing transitive `uuid` issue in Expo's Xcode tooling. No unsupported forced dependency upgrade was applied.
- Expo Doctor passed all 20 checks using `source scripts/local-tools.sh`. Java 17, Gradle 9.0.0 and adb execute successfully on this ARM64 Mac.
- Gradle `:app:tasks --all` completed successfully, including compilation of the SDK 55 native build plugins and project configuration.
- The Apple `.p12` was re-exported with macOS-compatible encryption and its actual Keychain import was verified; it contains the same certificate/private key.
- App compilation and device acceptance remain pending; successful JavaScript export and Gradle configuration are not a compiled native app.
