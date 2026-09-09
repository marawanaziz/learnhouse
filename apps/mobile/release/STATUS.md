# Existing-listing update preparation — September 9, 2026

The owner permits build uploads, but no review submission or release. Only the two existing listings may be used.

| Requirement | Current evidence |
| --- | --- |
| Existing iOS listing | App Store Connect app `6739436162`, Bundle ID `com.birthandbabyuniversity.learn`, team and App ID prefix `2V6MAB58ZP` inspected in Firefox |
| Existing Android listing | Play Console app `4972007289590886738`, package `com.birthandbabyuniversity.learn`; Play App Signing enabled |
| Next update | `2.5.0`, iOS build `21` after observed `20`, Android version code `20` after observed `19` |
| Native configuration | Production iOS and Android projects generated and inspected; identifiers, team, version and build numbers match |
| Code validation | SDK 55.0.31 / React Native 0.83.10; TypeScript, 19 tests, dependency compatibility and 20/20 Expo Doctor checks pass. Both production Hermes bundles exported; native projects regenerated and inspected |
| Upload configuration | Uploads will use Xcode Organizer/Transporter and the existing Play Console draft; EAS is not used. Review and release remain unauthorized |
| Android signing | New upload keystore and public PEM generated; private key and passwords validated. Google upload-key reset requested September 9 and confirmed pending. Old active fingerprint remains pinned until activation is verified |
| iOS signing | New Apple Distribution certificate `5QG57AVD4Z` and App Store profile `GTF9824HGC` issued; local encrypted `.p12` and profile validated for the existing app/team, expiring September 9, 2027. Original credentials not revoked |
| Build tools | Owner selected local builds with SDK 55; Java 17, CocoaPods and Android SDK/NDK/CMake installed. Xcode 26.3 installed with first launch complete and iOS 26.2 SDK verified; no EAS login needed |
| Signed native binaries | Not built yet; iOS signing preflight passes. Android preflight intentionally stops until Google activates the new upload certificate and its fingerprint is repinned |
| Device acceptance | Pending native builds; website/browser checks and JavaScript exports do not prove native login, video, PDFs, gestures, or update installation |
| Store uploads/review/release | None performed; no new listings or versions created, no review submitted, no releases published |

The owner confirmed the original developers' credentials are unavailable and explicitly authorized creating Apple credentials and requesting Google's upload-key reset. Those steps are complete; Google activation remains pending. The owner declined cloud builds and chose SDK 55 for local builds on macOS 15.7.3. Local credentials are in ignored `credentials.json` and `signing/`, with a protected same-computer backup at `~/.local/share/bbu-signing/2026-09-09/`. The new Android upload SHA-256 is `8F:76:72:C1:08:55:44:3A:51:42:28:1D:49:DA:62:95:D3:0D:1C:5A:E6:70:8F:CE:47:AB:DD:FF:7B:64:67:B4`; do not replace the active pin until Play confirms activation. Google showed no activation date/time when the request was filed.

Before uploading, verify the actual signed artifacts against the pinned app identity and signing records, recheck that build numbers remain unused, and finish native device acceptance. Keep uploads separate from review submission. See `README.md` for the exact commands and remaining checks.

Apple also displays a pending developer agreement and the listing contains old Circle support/reviewer instructions. These were observed only; neither the Developer Program agreement nor metadata nor app capabilities have been changed. The local Xcode software license was accepted for the authorized installation.

SDK 55 migration: TypeScript, 19 tests, compatible dependencies, production Hermes exports for both platforms and native prebuild passed. Expo Doctor passes 20/20 checks using the local tool environment. Local build helpers replace EAS build scripts. Xcode installation is complete. Native app compilation remains pending; no native binary is claimed ready.

Gradle native project configuration (`:app:tasks --all`) passed. Native macOS Keychain import of the distribution certificate passed after re-exporting the same key/certificate in compatible PKCS12 format. Xcode 26.3 code signature and first-launch completion passed; iOS SDK 26.2 is available. The iOS 26.2 ARM64 platform/runtime package is downloading because the first archive attempt reported its device destination unavailable; SDK presence alone did not establish build readiness.

The ARM64 Homebrew bootstrap was version 4.4.13 and skipped newer formula `post_install_steps`, leaving Ruby/OpenSSL without the CA bundle. Updated Homebrew itself to 6.0.22 and reran the native ca-certificates/openssl postinstall steps. The bundle and default OpenSSL link now exist, and a fresh Ruby HTTPS request to the CocoaPods CDN passed with certificate verification enabled. No app-specific CA override or disabled TLS verification was introduced.

CocoaPods completed successfully after the Homebrew correction. The first Android preview APK build is running; its Gradle workers were verified downloading native dependencies. The first iOS archive stopped at destination selection before compilation, pending iOS platform installation.
