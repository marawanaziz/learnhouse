# Existing-listing update preparation — September 8, 2026

The owner permits build uploads, but no review submission or release. Only the two existing listings may be used.

| Requirement | Current evidence |
| --- | --- |
| Existing iOS listing | App Store Connect app `6739436162`, Bundle ID `com.birthandbabyuniversity.learn`, team and App ID prefix `2V6MAB58ZP` inspected in Firefox |
| Existing Android listing | Play Console app `4972007289590886738`, package `com.birthandbabyuniversity.learn`; Play App Signing enabled |
| Next update | `2.5.0`, iOS build `21` after observed `20`, Android version code `20` after observed `19` |
| Native configuration | Production iOS and Android projects generated and inspected; identifiers, team, version and build numbers match |
| Code validation | TypeScript and dependency compatibility passed; 15 JavaScript tests and 4 signing-validation tests passed; production Hermes bundles exported for both platforms |
| Upload configuration | Official EAS schema accepted both profiles; Apple targets existing app ID, Google uses an internal draft with changes not sent for review |
| Android signing | Expected upload SHA-256 recorded in `store-targets.json`; no production upload keystore found in this workspace |
| iOS signing | Existing distribution certificate visible in Apple portal, expiring December 21, 2026; no valid code-signing identity in local Keychain and no local `.p12` / provisioning profile |
| Build service | EAS CLI and Firefox Expo session both signed out; account to use is awaiting the owner's reply |
| Signed native binaries | Not built yet; local signing preflight stops because `credentials.json` is absent |
| Device acceptance | Pending native builds; website/browser checks and JavaScript exports do not prove native login, video, PDFs, gestures, or update installation |
| Store uploads/review/release | None performed; no new listings or versions created, no review submitted, no releases published |

The owner has been asked where Circle's Android upload keystore is kept and which Expo/EAS account should own the builds. iOS may reuse the existing certificate/private key or use a new distribution certificate in the same Apple team; an Android upload-key replacement must not be improvised.

Before uploading, verify the actual signed artifacts against the pinned app identity and signing records, recheck that build numbers remain unused, and finish native device acceptance. Keep uploads separate from review submission. See `README.md` for the exact commands and remaining checks.

Apple also displays a pending developer agreement and the listing contains old Circle support/reviewer instructions. These were observed only; neither agreements nor metadata nor app capabilities have been changed.
