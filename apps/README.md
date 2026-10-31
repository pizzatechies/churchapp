# Ecclesia native apps

| App | Platforms | Folder | Built with |
|---|---|---|---|
| **Ecclesia Connect** (members) | Android, iOS | `mobile/` | [Capacitor](https://capacitorjs.com) 8 |
| **Ecclesia Admin** (church management & finance) | Windows, macOS, Linux | `desktop/` | [Electron](https://www.electronjs.org) 45 + electron-builder |

Both web apps are also installable straight from the browser (they are Progressive Web Apps): open the address on a phone or computer and choose *Install app* / *Add to Home Screen*.

## How the apps work

The native apps are thin, fast shells around your church's own Ecclesia server, so they are always up to date with the server and need no app-store update when the church changes something.

1. On first launch the app shows the Ecclesia splash (with the Pizza Technologies mark) and asks for the church's address, e.g. `members.yourchurch.org`.
2. It checks `https://<address>/healthz/` and only connects if that address really is the right Ecclesia app — Ecclesia Connect refuses an admin address and Ecclesia Admin refuses a members address — then asks the user to confirm the church's name.
   If the church's server is asleep (free hosting such as Render's free plan sleeps when idle), the app shows *Waking up your church's server* and keeps trying for up to two minutes.
3. The address is remembered. Next time the app opens straight into the church; *Profile → Switch church* (mobile) or *File → Change church server…* (desktop) changes it.
4. In the desktop app, links to other websites open in the computer's browser, never inside the app.

`launcher/` holds this connect screen and is shared by both apps.

To ship an app that is locked to one church (no address screen), set `ECCLESIA_CONNECT_URL` (mobile) or `ECCLESIA_ADMIN_URL` (desktop) when building, for example `ECCLESIA_CONNECT_URL=https://members.yourchurch.org npm run sync`. In GitHub Actions set it as a repository *variable* of the same name.

## Building with GitHub Actions (no Mac or Windows PC needed)

Two workflows in `.github/workflows/` build everything in the cloud:

| Workflow | Produces | Run it |
|---|---|---|
| **Desktop app** | `Ecclesia-Admin-<version>-win-x64.exe` (and arm64), `…-mac-universal.dmg`, `…-linux-x86_64.AppImage`, `…-linux-amd64.deb` | *Actions → Desktop app → Run workflow*, or push a tag `desktop-v1.0.0` to attach the installers to a GitHub release |
| **Mobile app** | Android debug APK; with signing secrets also a signed release APK and a Play Store `.aab`; an iOS simulator build that proves the iOS app compiles | *Actions → Mobile app → Run workflow*, or push a tag `mobile-v1.0.0` |

Download the results from the workflow run's *Artifacts* section.

## Building on your own computer

### Android (Windows, macOS or Linux)

Requirements: Node.js 22, JDK 21, Android Studio (or the Android SDK command-line tools with platform 36).

```bash
cd apps/mobile
```

```bash
npm install
```

```bash
npm run build:android
```

The APK is `android/app/build/outputs/apk/debug/app-debug.apk`; copy it to a phone to test. `npm run open:android` opens the project in Android Studio.

### iOS (macOS only)

Requirements: a Mac with Xcode 16+, Node.js 22, and an [Apple Developer account](https://developer.apple.com/programs/) (USD 99/year) to install on real iPhones or publish.

```bash
cd apps/mobile
```

```bash
npm install && npm run sync
```

```bash
npm run open:ios
```

In Xcode select the **App** target → *Signing & Capabilities*, choose your team, then *Product → Archive* and *Distribute App* to upload to App Store Connect / TestFlight.

### Desktop

Build on the platform you are targeting (Windows builds `.exe`, macOS builds `.dmg`, Linux builds `.AppImage` and `.deb`):

```bash
cd apps/desktop
```

```bash
npm install
```

```bash
npm start
```

```bash
npm run dist
```

Installers land in `apps/desktop/dist/`.

## Signing and publishing

Signing keys and store accounts belong to your organisation; none are stored in this repository.

### Google Play (Ecclesia Connect for Android)

1. Create an upload keystore once and keep it (and its passwords) safe — you need the same key for every update:

   ```bash
   keytool -genkeypair -v -keystore ecclesia-upload.jks -alias ecclesia -keyalg RSA -keysize 2048 -validity 10000
   ```

2. Add these repository secrets: `ANDROID_KEYSTORE_BASE64` (output of `base64 -w0 ecclesia-upload.jks`), `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` (`ecclesia`), `ANDROID_KEY_PASSWORD`. Locally, set `ECCLESIA_KEYSTORE_PATH`, `ECCLESIA_KEYSTORE_PASSWORD`, `ECCLESIA_KEY_ALIAS` and `ECCLESIA_KEY_PASSWORD` and run `npm run build:android:release`.
3. Run the *Mobile app* workflow and upload the `.aab` in the [Google Play Console](https://play.google.com/console) (one-time USD 25 developer fee).
4. For each new release raise `versionCode` and `versionName` in `mobile/android/app/build.gradle`.

### App Store (Ecclesia Connect for iOS)

Archive and upload from Xcode as above, fill in the listing in App Store Connect and submit for review. Raise the version and build number in Xcode for each release. Apple expects apps to offer more than a website, so mention in the review notes that members sign in to their own church's private space (groups, fellowships and sermons), and provide a demo church address and member login for the reviewer.

### Windows and macOS installers

Unsigned installers work, but Windows SmartScreen and macOS Gatekeeper warn users about them.

- **Windows:** buy a code-signing certificate and add `WIN_CSC_LINK` (base64 of the `.pfx`) and `WIN_CSC_KEY_PASSWORD` secrets.
- **macOS:** with an Apple Developer account, export a *Developer ID Application* certificate as `.p12` and add `CSC_LINK`, `CSC_KEY_PASSWORD`, plus `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD` and `APPLE_TEAM_ID` so the app is notarised.

Raise `version` in `desktop/package.json` for each release.

## Changing the icon or splash screen

- Mobile: replace the images in `mobile/resources/` (`icon-only.png` 1024×1024, `icon-foreground.png`/`icon-background.png` for Android adaptive icons, `splash.jpg`/`splash-dark.jpg` 2732×2732), then run `npm run assets` and commit the regenerated files under `android/` and `ios/`.
- Desktop: replace `desktop/build/icon.png` (1024×1024).
- Connect screen: `launcher/img/`.

## App identifiers

| | |
|---|---|
| Android package / iOS bundle ID | `com.pizzatechnologies.ecclesia.connect` |
| Desktop app ID | `com.pizzatechnologies.ecclesia.admin` |
| User-agent marker | `EcclesiaApp/1.0 (Connect)` and `EcclesiaApp/1.0 (Desktop)` — the server uses it to skip the web splash screen and show *Switch church* |
