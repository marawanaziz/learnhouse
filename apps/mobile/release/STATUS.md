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
| Android production artifact | Not built yet; production signing preflight intentionally remains gated until Google's upload-key activation is confirmed |
| Device acceptance | Pending. No authorized Android device was connected; the APK and IPA have not undergone native login, video, PDF, gesture or update-installation acceptance |
| Store actions | No build uploads, new listings, review submissions or releases performed |

## Signing and Google activation

Apple Distribution certificate `5QG57AVD4Z` and App Store profile `GTF9824HGC` were created with the owner's authorization. The profile UUID is `1794097b-c642-4ba7-96e3-7e3d88058b61`; the certificate expires September 9, 2027. The private key, profile and app/team checks passed, as did native Keychain import and local macOS code-signing trust verification. The final IPA uses this exact certificate and profile. Original developer credentials were not revoked.

Google's notification confirms the new Android upload key becomes valid **September 11, 2026 at 07:01 UTC / 03:01 America/New_York**. Until then, Google prohibits new APK/AAB uploads. The console already displays the new SHA-256 fingerprint, but the request is still pending:

`8F:76:72:C1:08:55:44:3A:51:42:28:1D:49:DA:62:95:D3:0D:1C:5A:E6:70:8F:CE:47:AB:DD:FF:7B:64:67:B4`

The previous upload fingerprint remains pinned in `store-targets.json`. Recheck activation in Play Console before updating that pin and building/uploading production Android. Google's actual app-signing key was not changed.

Credentials remain in ignored `credentials.json` and `signing/`, with a protected same-computer backup at `~/.local/share/bbu-signing/2026-09-09/`. They were not committed or sent to a cloud build service. The iOS build uses a temporary signing keychain, then restores the user's original search list and deletes the temporary keychain.

## Toolchain corrections verified

- Updated ARM64 Homebrew from 4.4.13 to 6.0.22 because the old version skipped newer formula post-install steps, leaving Ruby/OpenSSL without its CA bundle. Native ca-certificates/OpenSSL post-install steps now complete; a fresh verified HTTPS request and CocoaPods install passed.
- Installed the matching platform package through Xcode Settings > Components. A simulator pinned to the SDK's version did not provide the matching build support. The unused runtime and Xcode installer archive were removed. Fresh destination validation confirms Any iOS Device and simulator destinations are available. [Apple explains the platform-support requirement](https://developer.apple.com/forums/thread/817687).
- Scoped the iOS export subprocess to prefer macOS tools in PATH. Apple's rsync had launched Homebrew's incompatible GNU rsync peer. An isolated copy test reproduced the failure and passed with the corrected environment; a fresh full archive and IPA export then succeeded. Other tools' global settings were not changed.

Artifact checksums and verification details are in ignored `artifacts/android-preview-verification.json` and `artifacts/ios-production/verification.json`. Build/setup logs are in `~/Library/Caches/bbu-toolchain/`.

## Remaining release checks

Complete native device acceptance, recheck unused version/build numbers, and confirm Google activation before the production Android build. Uploads should use Xcode Organizer/Transporter and the existing Play Console draft. Do not submit for review, add external TestFlight groups, start rollout, publish or enable automatic release.

Xcode export completed with three symbol-processing warnings in its distribution log; native framework crash-symbol coverage has not been validated. This did not prevent IPA export or signature verification. Store-side validation remains pending.

Apple displays a pending Developer Program agreement and old Circle-specific support/reviewer instructions. Those were observed only; the agreement, metadata and app capabilities were not changed. The local Xcode software license was accepted for the authorized installation.
