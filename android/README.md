# Auto-Skipper Android Auto kontroler — spike

Faza 2 iz [docs/android-auto-controller.md](../docs/android-auto-controller.md): minimalan media app
koji u Android Autu prikazuje dvije komande i šalje ih na postojeći playback API. Svrha je
odgovoriti na go/no-go pitanja u stvarnom autu, ne biti gotov proizvod.

## Što app radi

- Browse tree ima točno dvije stavke: **Check Now** (`POST /api/playback/check-now`) i
  **Pause Skipping** / **Resume Skipping (paused)** (`POST /api/playback/toggle-pause`,
  label se čita iz `skipping_paused`).
- Klik ide isključivo kroz `onPlayFromMediaId` → HTTP (timeout 5 s) → `GET /api/playback` →
  `notifyChildrenChanged`. Dok komanda traje, novi klikovi se ignoriraju.
- Feedback je `STATE_ERROR` + `setErrorMessage` (i za greške i za kratku "OK" potvrdu), povratak
  na `STATE_NONE` nakon 4 s.
- Autentikacija je device token iz PWA (Settings → Android Auto device), spremljen u
  `EncryptedSharedPreferences`.
- Na telefonu se zove **Car Skipper**, a ne Auto-Skipper, da se ne brka s PWA-om instaliranim na
  istom telefonu. Ikona je brand oznaka (zelene skip strelice) s autom između njih; generira je
  `tools/make_launcher_icon.py` iz boja postojećeg `cloud/app/static/icons/maskable-512.png`.

Tri pravila koja drže cijeli pristup (detalji u planu):

1. Sesija nikad ne prijavljuje `STATE_PLAYING` ni `STATE_BUFFERING` — zato sustav ne preusmjerava
   media tipke s volana na ovaj app i Spotify zadržava media karticu.
2. App nikad ne traži audio focus.
3. `onLoadChildren` nema side-effecte — Android Auto ga zove kad hoće, pa bi komanda odatle
   ponavljala samu sebe. Tamo se radi samo `GET`.

Compat stack je namjeran: `MediaBrowserServiceCompat` + `MediaSessionCompat` (androidx.media),
**ne** Media3 — mapiranje grešaka prema AA tamo ima otvorene rubove.

## Build

Traži Android SDK (platform 36) i JDK 17+. Na Vatrinom PC-u JDK dolazi s Android Studiom i nije na
PATH-u, pa se zadaje eksplicitno:

```bash
cd android && JAVA_HOME="/c/Program Files/Android/Android Studio/jbr" ./gradlew assembleDebug
```

APK završi u `app/build/outputs/apk/debug/app-debug.apk`. `local.properties` (sdk.dir) i APK-ovi
se ne commitaju.

## Instalacija i test

1. Prebaciti APK na telefon i dopustiti instalaciju iz nepoznatih izvora.
2. Android Auto app → Settings → 10x tap na verziju → developer mode → **Unknown sources** ON.
3. Otvoriti Auto-Skipper na telefonu: server URL (`https://autoskipper.uk`) + device token iz PWA
   Settingsa, **Save**, pa **Test connection** — mora javiti "Connected: …".
4. Spojiti telefon na auto; app je u AA launcheru.

### Go/no-go kriteriji (svih pet mora proći)

1. App je vidljiv u AA launcheru i obje stavke se renderiraju.
2. Klik izvršava komandu (potvrda u PWA logu) i AA se ne raspadne bez playbacka.
3. `STATE_ERROR` poruka je vidljiva i čitljiva na ekranu auta.
4. Nakon korištenja stavki volan (next/prev) i dalje upravlja Spotifyjem, media kartica ostaje
   Spotifyjeva, zvuk se nijednom ne prekida.
5. Label Pause/Resume se osvježi nakon toggle-a.

Padne li bilo koji kriterij: stop, javiti nalaz. Ne krpati hackovima.

## Verzioniranje

`versionName`/`versionCode` u `app/build.gradle.kts`, neovisno o `APP_VERSION` backenda (version
guard hookovi su scoped na `cloud/`).
