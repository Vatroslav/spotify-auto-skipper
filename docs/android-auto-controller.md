# Android Auto kontroler - implementacijski plan

Samostalan spec: sve što treba za implementaciju je ovdje, razgovor u kojem je nastao nije potreban.
Dizajn je finaliziran 2026-08-04 (Fable sesija); ovo je uputa za izvedbu, ne prostor za re-dizajn.
Ako nešto od dolje navedenog ne prođe provjeru u stvarnosti, stati i javiti Vatri - ne improvizirati zamjenu.

## Cilj

Pet ručnih gumba iz PWA (Check Now, Pause Skipping, Don't Skip This Song, Add to Liked
Songs, Remove from Playlist) dostupno s ekrana auta kroz Android Auto, bez vađenja mobitela.
Automatski skip već radi (server-side worker) - ovo je isključivo za ručne komande.

Rješenje: **sideload Android media app** (jedina kategorija koju AA "Unknown sources"
developer opcija pušta bez Play review-a). Browse tree nosi komande umjesto pjesama;
klik na stavku okida HTTP poziv na postojeće API endpointe.

## Utvrđene činjenice (provjereno u službenoj dokumentaciji, ne preispitivati)

1. **Media button routing (volan):** od Androida 8, sustav media button evente šalje
   zadnjoj MediaSession koja je *stvarno reproducirala audio*. Sesija koja nikad ne uđe
   u STATE_PLAYING ne preuzima volan niti media karticu. Spotify ostaje vlasnik oboje.
   (developer.android.com/media/legacy/media-buttons)
2. **Audio focus:** traži se tek pri reprodukciji. App koji ne svira ne prekida Spotify.
3. **Poruke korisniku:** `PlaybackStateCompat.STATE_ERROR` + `setErrorMessage()` - AA to
   prikazuje; službeni vodič "Handle errors" za AA media appove.
   (developer.android.com/training/cars/media/errors)
4. **Provjereno spikeom u stvarnom autu (2026-08-08):** kad klik na playable stavku ne
   pokrene playback, AA prikaže VLASTITU generičku poruku "Could not load your selection" -
   iako je komanda na serveru uredno izvršena. Uzrok: app je STATE_ERROR postavljao tek
   nakon HTTP round-tripa, a AA nakon klika čeka tranziciju stanja odmah. Posljedica za
   dizajn: STATE_ERROR se postavlja SINKRONO na klik (prije HTTP-a), poruka se ažurira po
   odgovoru; primarna potvrda ide kroz promjenu labela/subtitlea stavki
   (notifyChildrenChanged), koju AA garantirano renderira.
5. **Provjereno spikeom:** AA kešira popis appova - novoinstalirani sideload media app se
   ne pojavi u launcheru dok se Android Auto ne force-stopa (ili telefon ne restarta).

## Kardinalna pravila (kršenje ruši cijeli pristup)

- **Sesija NIKAD ne prijavljuje STATE_PLAYING ni STATE_BUFFERING.** Stanje je STATE_NONE,
  s kratkim izletima u STATE_ERROR radi poruka (vratiti na NONE nakon ~4 s).
- **App NIKAD ne traži audio focus** (v1; eventualna TTS potvrda je v2, izvan ovog plana).
- **Nikakvi side-effecti u `onLoadChildren`** - AA ga zna spontano ponovno zvati (refresh),
  što bi ponovilo akciju. Sve akcije idu isključivo kroz `onPlayFromMediaId`.

## Faze

Redoslijed je obavezan: backend token prvo (APK ga treba), pa spike, pa **go/no-go gate**,
pa puni app. Svaka backend faza na feature branchu, deploy na VPS za test prije mergea
(vidi CLAUDE.md Versioning + memory feedback o feature branchu).

### Faza 1 - backend: device token auth (feat → minor bump)

- **DB:** nova tablica `device_tokens` (id, token_hash, label, created_at, last_used_at).
  Shema OBAVEZNO po `.claude/skills/sqlite-migration/SKILL.md`.
- **deps.py:** nova dependency `require_auth_or_device_token` - prvo postojeći session
  check (PWA put netaknut), pa `Authorization: Bearer <token>`: SHA-256 hash tokena,
  usporedba `hmac.compare_digest` protiv `device_tokens`, na uspjeh update `last_used_at`.
  Neuspjele bearer pokušaje logirati (add_log, warning). Postojeći `require_auth` ostaje
  kakav jest za sve ostale routere.
- **Playback router** (`routers/playback.py`): jedina promjena dependencyja -
  `require_auth` → `require_auth_or_device_token`. Settings, logs, genres, auth i sve
  ostalo ostaje session-only (ukraden token ne može ništa osim komandi iz auta).
- **Token management endpointi** (session-only, npr. u settings router):
  `POST /api/device-tokens` (generira `secrets.token_urlsafe(32)`, sprema hash, vraća
  plaintext JEDNOM), `GET /api/device-tokens` (lista: label, created_at, last_used_at),
  `DELETE /api/device-tokens/{id}` (revoke).
- **PWA Settings UI:** sekcija "Android Auto device" - generate (prikaz tokena jednom:
  QR + copy), lista tokena s last_used, revoke. QR sadrži JSON
  `{"url": "<base_url>", "token": "<token>"}`. QR lib mora biti lokalni vendorani file
  (CSP je `script-src 'self'`) - npr. qrcode-generator (MIT), u `static/js/vendor/`.
- **Pydantic zamka:** kod dodavanja request modela poštovati CLAUDE.md pravilo o
  redoslijedu BaseModel klasa i validatora.

### Faza 2 - spike APK (novi direktorij `android/`)

Minimalni app koji odgovara na go/no-go pitanja. Sadržaj:

- Kotlin, jedan modul. **Compat stack**: `MediaBrowserServiceCompat` + `MediaSessionCompat`
  (androidx.media). NE Media3 - error mapping prema AA tamo ima otvorene rubove
  (androidx/media #1077); Media3 je budući migracijski put, ne polazna točka.
- minSdk 26, targetSdk zadnji stabilni. Dependencies: androidx.media, OkHttp,
  kotlinx-coroutines, androidx.security-crypto.
- Manifest: service s intent filterom `android.media.browse.MediaBrowserService`,
  meta-data `com.google.android.gms.car.application` → `automotive_app_desc.xml`
  s `<uses name="media"/>`. Prijedlog applicationId: `uk.autoskipper.controls`,
  label "Car Skipper" (dogovoreno s Vatrom 2026-08-04 - "Auto-Skipper" bi se brkao s PWA-om
  instaliranim na istom telefonu; ikona je brand oznaka s autom između strelica).
- `onGetRoot`: dopustiti samo Android Auto (`com.google.android.projection.gearhead`)
  i vlastiti package - browse akcije imaju server-side efekte, ne smiju biti
  okidive od bilo koje aplikacije na telefonu.
- Browse tree: 2 stavke - "Check Now" (`cmd:check_now` → `POST /api/playback/check-now`)
  i "Pause/Resume Skipping" (`cmd:toggle_pause` → `POST /api/playback/toggle-pause`,
  label iz `skipping_paused` u `GET /api/playback`).
- Klik → `onPlayFromMediaId` → coroutine → HTTP (timeout 5 s) → refresh
  `GET /api/playback` → rebuild liste → `notifyChildrenChanged(root)`. Za vrijeme
  izvršavanja ignorirati nove klikove (single-flight).
- Feedback: STATE_ERROR poruka na grešku ("Server unreachable", tekst greške sa servera),
  kratki "OK" STATE_ERROR na uspjeh Check Now; nakon ~4 s natrag na STATE_NONE.
- Telefonska aktivnost: polja server URL (default `https://autoskipper.uk`) + token
  (paste), "Test connection" (GET /api/playback), pohrana u EncryptedSharedPreferences.
  QR scan nije potreban u spikeu.

**Go/no-go kriteriji (test u stvarnom autu, svih pet mora proći):**

1. App vidljiv u AA launcheru (uz uključen developer mode + Unknown sources) i stavke se
   renderiraju.
2. Klik izvršava komandu (potvrda u PWA logu) i AA se ne raspadne bez playbacka.
3. STATE_ERROR poruka je vidljiva i čitljiva na ekranu auta.
4. Nakon korištenja SAS stavki volan (next/prev) i dalje upravlja Spotifyjem, media
   kartica ostaje Spotifyjeva, zvuk se nijednom ne prekida.
5. Label "Pause/Resume" se osvježi nakon toggle-a (notifyChildrenChanged radi u vožnji).

Padne li bilo koji kriterij: STOP, javiti Vatri nalaz. Ne krpati hackovima.

**Rezultat spikea (2026-08-08):** kriteriji 1 (vidljivost, uz force-stop AA) i 2
(izvršenje komande, potvrđeno u server logu) PROŠLI. Kriterij 3 pao na timingu feedbacka
(vidi Utvrđene činjenice #4) - fix definiran i ugrađuje se u puni app. Kriterije 4 (volan)
i 5 (refresh labela) Vatra svjesno testira na punom appu umjesto ponovnog spike kruga.

### Faza 3 - backend proširenja (feat → minor bump)

- `GET /api/playback`: dodati `trash_configured: bool`
  (`bool((settings.get("trash_playlist_id") or "").strip())`).
- `POST /api/playback/remove-from-playlist`: opcionalni `expected_track_id` u bodyju;
  ako je poslan i različit od trenutno svirane pjesme → 409 `{"ok": false, "error":
  "Track changed"}` prije ikakvog brisanja.
- Proxy endpointi za volan-fallback: `POST /api/playback/next` (postojeći
  `skip_current_track`), `POST /api/playback/previous`, `POST /api/playback/pause`,
  `POST /api/playback/resume` (Spotify `POST /me/player/previous`, `PUT /me/player/pause`,
  `PUT /me/player/play`). Nove Spotify pozive pisati po `.claude/skills/spotify-api/SKILL.md`.

**Napravljeno (2026-08-08, v3.22.0):** sve troje. `expected_track_id` je opcionalan pa PWA
poziv bez bodyja i dalje prolazi - provjereno lokalno: prazan body uz
`Content-Type: application/json` → 200, nesklad → 409 bez ijednog Spotify writea.
`pause_spotify_playback` sad vraća bool (prije je slao PUT bez provjere statusa).
Nije još deployano na VPS.

### Faza 4 - puni app

Browse tree (redoslijed = redoslijed u listi):

| # | Stavka | mediaId | Endpoint | Label logika |
|---|--------|---------|----------|--------------|
| 1 | Status header | `cmd:check_now` | check-now | "Now: {track} - {artist}"; bez pjesme "Nothing playing" |
| 2 | Check Now | `cmd:check_now` | check-now | fiksno |
| 3 | Pause Skipping | `cmd:toggle_pause` | toggle-pause | ↔ "Resume Skipping (paused)" po `skipping_paused` |
| 4 | Don't Skip This Song | `cmd:skip_one_pause` | skip-one-pause | nakon uspjeha "Won't skip: {track}" dok `skip_exempt_track_id` == trenutna pjesma |
| 5 | Liked | `cmd:toggle_like` | toggle-like | "Add to Liked Songs" ↔ "Remove from Liked Songs" po `is_liked` |
| 6 | Remove from Playlist | `cmd:remove` | remove-from-playlist | vidi dolje; stavka postoji SAMO ako `trash_configured` |

- Ikone po stavci iz app resursa (`android.resource://` URI u MediaDescription).
  Postojeći brand asset (favicon) kao baza - ne izmišljati novi dizajn (memory feedback).
- **Remove dvofazno:** prvi klik ne šalje ništa - lokalno "armira" (zapamti track_id iz
  zadnjeg /api/playback + timestamp), label postane "Tap again to remove: {track}".
  Disarm: nakon 10 s, na promjenu pjesme, ili nakon izvršenja. Drugi klik šalje
  `expected_track_id`; 409 prikazati kao STATE_ERROR "Track changed - not removed".
- **State sync:** refresh na onGetRoot/onSubscribe, nakon svake akcije, plus poll
  `GET /api/playback` svakih 30 s dok postoji aktivna subscription (AA disconnect je
  prestanak subscriptiona - polling tada stane, bez posebne detekcije auta).
- **Volan-fallback:** session callbackovi `onSkipToNext/onSkipToPrevious/onPause/onPlay`
  → proxy endpointi iz Faze 3. Deklarirati odgovarajuće ACTION flagove u PlaybackState.
  Ovo je osiguranje za slučaj da routing ikad zaluta na SAS - ne primarni mehanizam.
- **Feedback (revidirano po spike nalazu):** STATE_ERROR se postavlja sinkrono na klik
  ("Working..."), pa se poruka ažurira po HTTP odgovoru; nakon ~4 s natrag na STATE_NONE.
  Primarna potvrda uspjeha je promjena labela/subtitlea stavke kroz notifyChildrenChanged
  (npr. "Check Now" → subtitle "Sent ✓"). **Greške sa servera** mapirati doslovno u
  STATE_ERROR poruke: "Nothing is playing", "Currently playing track is not from a
  playlist", "Spotify client not ready", mrežni fail → "Server unreachable".
- Telefonska aktivnost: + QR scan tokena (zxing-embedded) uz postojeći paste.

**Napravljeno (2026-08-08, app 0.2.0):** cijela tablica, dvofazni Remove, poll na 30 s
vezan uz `onSubscribe`/`onUnsubscribe`, volan-fallback i sinkroni STATE_ERROR. Tri odstupanja
od teksta gore, sva svjesna:

1. **QR scan preskočen** na Vatrin zahtjev - paste tokena već radi, zxing se ne uvodi.
2. **Status header ima vlastiti mediaId** (`cmd:status`), ne `cmd:check_now`. Akcija je ista
   (klik pokreće check-now), ali dvije stavke s istim mediaId-em u istoj listi su nepotreban
   rizik u tuđem list adapteru. Ponašanje prema planu je nepromijenjeno.
3. **Status header ima i subtitle** "Skipping active"/"Skipping paused"; potvrda nakon klika
   na njega ide na red Check Now (jedini red bez vlastitog subtitlea bio bi header).

Neprovjereno do testa u autu: kriteriji 3 (čitljivost poruke), 4 (volan i dalje vodi Spotify)
i 5 (refresh labela u vožnji), plus renderira li AA `android.resource://` ikone i subtitleove.

### Faza 5 (v2, opcionalno, NE raditi bez eksplicitnog zahtjeva)

TTS glasovna potvrda s transient-duck audio focusom. Prije uvođenja provjeriti da TTS
reprodukcija ne pomiče media button routing.

### Faza 6 - prikaz teksta pjesme (napravljeno: backend v3.23.0, app 0.3.0)

Tražena na eksplicitni zahtjev, izvedena bez prethodnog spikea (svjesna odluka - rizik je
poznat i izoliran na jednu točku).

**Izvor teksta:** LRCLIB (`lrclib.net`) - besplatan, bez ključa, daje vremenski usklađen LRC.
Spotify **nema** javni lyrics endpoint; interni `color-lyrics` traži `sp_dc` cookie iz web
playera, nedokumentiran je i krši ToS, pa nije razmatran. Musixmatch free tier daje 30% teksta.

LRCLIB ne poznaje Spotify id-eve - pjesma se traži po (izvođač, naslov, album, trajanje). To je
slaba točka: promašaj vrati tuđe timingove, što na ekranu izgleda gore od izostanka teksta. Zato
`/api/get` prvo, pa `/api/search` bez albuma kao fallback, a rezultati searcha se filtriraju po
trajanju (±3 s) - prvi rezultat je često verzija s kompilacije i drugim timingovima.

**Bez ijednog dodatnog Spotify poziva.** Pozicija se ne dohvaća, nego ekstrapolira iz zadnjeg
workerovog snapshota (`progress_ms` + starost snapshota). Napredovanje je linearno pa je to
jednako dobro kao svjež dohvat sve dok nitko ne premota. `is_playing` je dodan u
`get_current_track` iz **istog** odgovora - bez toga bi tekst nastavio teći kroz pauzu.

**Keširanje:** `lyrics_cache` po `track_id`. Pogodak trajno (tekst objavljene pjesme se ne
mijenja), promašaj 7 dana (LRCLIB pune korisnici, pa "nema" vrijedi za danas).

**Poznati rizik, neriješiv bez testa u autu:** AA zna propustiti `notifyChildrenChanged` dok
korisnik ne izađe i vrati se u podmapu. Ublaženo prozorom od pet redaka umjesto dva - propušteno
osvježavanje tada ostavlja kontekst umjesto praznine. Ako padne, ručno listanje ostaje.

## Repo i versioning

- Android kod: **poddirektorij `android/`** u ovom repou (API kontrakt i app se mijenjaju
  zajedno; version guard hookovi ostaju scoped na `cloud/`).
- Backend izmjene: standardna pravila (conventional prefix, bump u istom commitu,
  feature branch + deploy za test prije mergea).
- Android verzija: `versionName`/`versionCode` u Gradleu, neovisno o `APP_VERSION`.
- APK build artefakt ne committati; po potrebi GitHub release na tag.

## Instalacija (Vatrin ritual, jednom po telefonu)

1. APK na telefon, dopustiti instalaciju iz nepoznatih izvora.
2. Android Auto app → Settings → 10x tap na verziju → developer mode → "Unknown sources" ON.
3. U SAS app: server URL + token (QR iz PWA Settings ili paste), Test connection.
4. Spojiti na auto - app je u AA launcheru.

## Poznati rizici (dokumentirano, prihvaćeno)

- Ponašanje media appa koji nikad ne svira je nedokumentirano - budući AA update to može
  slomiti. Fallback je uvijek PWA.
- Coolwalk/UI redizajni mogu promijeniti broj tapova do appa, ali ne API.
- Google gura Media3; compat stack je podržan, migracija je poznat posao ako postane prisilna.
