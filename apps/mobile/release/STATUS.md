# Existing-listing update preparation — September 9, 2026

Local SDK 55 setup is complete on the owner's macOS 15.7.3. The owner permits build uploads, but no review submission or release. Only the two existing listings may be used.

| Requirement | Current evidence |
| --- | --- |
| Existing iOS listing | App Store Connect app `6739436162`, Bundle ID `com.birthandbabyuniversity.learn`, Apple team `2V6MAB58ZP` |
| Existing Android listing | Play Console app `4972007289590886738`, package `com.birthandbabyuniversity.learn`; Play App Signing enabled |
| Prepared production update | Version `2.5.0`, iOS build `21` after observed `20`, Android version code `20` after observed `19` |
| Code validation | Expo 55.0.31 / React Native 0.83.10 / React 19.2.0; TypeScript, 19 tests, dependency compatibility and 20/20 Expo Doctor checks passed. Both production Hermes bundles exported |
| Local tools | Xcode 26.3 (17C529), matching iOS 26.2 platform support with iOS 26.3.1 Simulator, CocoaPods, Java 17, Android SDK 36, build-tools 36.0.0, NDK 27.1.12297006 and CMake 3.22.1 installed. No macOS upgrade or cloud-build login used |
| iOS production artifact | `artifacts/ios-production/BirthBabyUniversity.ipa` (7.9 MB). Archive and export succeeded; deep/strict signature, exact distribution certificate, App Store profile, existing bundle/team, version 2.5.0/build 21, iOS 15.1 minimum and embedded JavaScript verified |
| Android preview artifact | `artifacts/android-preview.apk` (60 MB). Gradle build succeeded (330 tasks); APK v2 signature, `com.birthandbabyuniversity.wrapper.preview`, BBU Preview, minimum SDK 24, target SDK 36 and embedded JavaScript verified. Signed with the preview debug key, not the production upload key |
| Android production artifact | `artifacts/android-production-pending-key-activation.aab` (44,508,421 bytes), v2.5.0/code 20, existing package, SDK 24–36, embedded JavaScript, JAR signature and Google-confirmed replacement certificate verified. Bundletool validation passed. Upload remains blocked until key activation |
| Device acceptance | iPhone and iPad Release simulator preview: reviewer login, enrolled course access and real lesson video playback passed. Android device acceptance and full PDF/permissions/offline/session/update-installation checks remain pending. iPad portrait header is cramped; landscape screenshots render correctly |
| Store actions | Apple IPA validated, uploaded and processed VALID; build 21 attached to existing app version 2.5.0 with manual release. Description, reviewer login/instructions and five branded screenshots uploaded. Google production draft 8 and reviewer instructions saved; AAB upload blocked. No new listings, review submissions or releases |

## Signing and Google activation

Apple Distribution certificate `5QG57AVD4Z` and App Store profile `GTF9824HGC` were created with the owner's authorization. The profile UUID is `1794097b-c642-4ba7-96e3-7e3d88058b61`; the certificate expires September 9, 2027. The private key, profile and app/team checks passed, as did native Keychain import and local macOS code-signing trust verification. The final IPA uses this exact certificate and profile. Original developer credentials were not revoked.

Google's notification confirms the new Android upload key becomes valid **September 11, 2026 at 07:01 UTC / 03:01 America/New_York**. Until then, Google prohibits new APK/AAB uploads. The console already displays the new SHA-256 fingerprint, but the request is still pending:

`8F:76:72:C1:08:55:44:3A:51:42:28:1D:49:DA:62:95:D3:0D:1C:5A:E6:70:8F:CE:47:AB:DD:FF:7B:64:67:B4`

The previous upload fingerprint remains pinned in `store-targets.json`. Recheck activation in Play Console before updating that pin and uploading production Android. A protected local preparation helper verified the pending replacement certificate and built the AAB without changing the active-key pin; the ordinary production preflight remains gated. Google's actual app-signing key was not changed.

Credentials remain in ignored `credentials.json` and `signing/`, with a protected same-computer backup at `~/.local/share/bbu-signing/2026-09-09/`. They were not committed or sent to a cloud build service. The iOS build uses a temporary signing keychain, then restores the user's original search list and deletes the temporary keychain.

## Toolchain corrections verified

- Updated ARM64 Homebrew from 4.4.13 to 6.0.22 because the old version skipped newer formula post-install steps, leaving Ruby/OpenSSL without its CA bundle. Native ca-certificates/OpenSSL post-install steps now complete; a fresh verified HTTPS request and CocoaPods install passed.
- Installed the matching platform package through Xcode Settings > Components. A simulator pinned to the SDK's version did not provide the matching build support. The unused runtime and Xcode installer archive were removed. Fresh destination validation confirms Any iOS Device and simulator destinations are available. [Apple explains the platform-support requirement](https://developer.apple.com/forums/thread/817687).
- Scoped the iOS export subprocess to prefer macOS tools in PATH. Apple's rsync had launched Homebrew's incompatible GNU rsync peer. An isolated copy test reproduced the failure and passed with the corrected environment; a fresh full archive and IPA export then succeeded. Other tools' global settings were not changed.

Artifact checksums and verification details are in ignored `artifacts/android-preview-verification.json` and `artifacts/ios-production/verification.json`. Build/setup logs are in `~/Library/Caches/bbu-toolchain/`.

## Remaining release checks

Complete remaining native acceptance and confirm Google activation before the Android upload to the existing Play Console draft. Do not submit for review, add external TestFlight groups, start rollout, publish or enable automatic release.

Xcode export completed with three symbol-processing warnings in its distribution log; native framework crash-symbol coverage has not been validated. This did not prevent IPA export or signature verification. Apple authenticated IPA validation and store processing both succeeded; framework crash-symbol coverage remains unverified.

Apple displays a pending Developer Program agreement. Circle-specific Apple support/reviewer instructions have been replaced; the agreement and app capabilities were not changed. The local Xcode software license was accepted for the authorized installation.

## Store preparation and screenshot artwork

Apple version 2.5.0 is **READY_FOR_REVIEW** with manual release. Its draft review package has `submittedDate: null`; the final Submit for Review button was left untouched. Apple’s readiness state confirms console preparation, not completion of the remaining acceptance/privacy checks below.

- Apple build UUID: `4bded461-033f-4380-b759-f6dbbb0f8b7f`; version ID: `0aaa0ce2-4d6c-4809-8ca0-c919d4d2a257`. IPA SHA-256: `e44931306da9991c8cb3fba0ebcfb231b10f59203a6d5233dd401f8edc07e805`.
- Google draft release 8, production track `4697487997690425627`, has saved 2.5.0 notes but no bundle attached. AAB SHA-256: `33ed27bb1a32fe7e80ce54548b7a8918e055a2c2fe8011d1a643af50f8f5d211`.
- Three iPhone 1320×2868 and two landscape iPad 2752×2064 branded PNGs are in ignored `artifacts/store-preparation/branded/`, with a gallery, ZIP, editable SVG layouts and verification manifest. Real simulator screenshot assets are embedded unchanged; the OS status area is clipped above the app header. BBU logo, navy/pale blue backgrounds and benefit headlines are included. All five Apple asset states are COMPLETE. Live 2.4.1 screenshots were preserved.
- A dedicated learner reviewer account with three enrolled courses was created and verified. Credentials are saved in the store review fields and protected local preparation records; never commit them.
- The draft Apple privacy URL now points to the public BBU privacy policy. The public policy is generic WordPress text; privacy/data-safety disclosures have not been fully reconciled with the new learning platform.
- Google shows an overdue foreground-service declaration inherited from existing artifacts. The new verified AAB manifest contains no foreground-service permission; recheck the console requirement after uploading it.
- Google sign-in details were updated and saved to Publishing overview, without sending them for review. Google listing artwork/metadata and remaining declarations must be rechecked when the bundle can be attached.
