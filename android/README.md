# Car Skipper — Auto-Skipper kontroler za Android Auto

Faza 4 iz [docs/android-auto-controller.md](../docs/android-auto-controller.md): media app koji u
Android Autu prikazuje ručne Auto-Skipper komande i šalje ih na postojeći playback API. Automatski
skip i dalje radi server-side; ovo je samo za ono što se inače klikalo u PWA.

## Browse lista

| Stavka | Što radi |
|--------|----------|
| Status | "Now: {pjesma} - {izvođač}", podnaslov "Skipping active"/"Skipping paused". Klik = Check Now. |
| Check Now | `POST /api/playback/check-now` |
| Pause / Resume Skipping | `POST /api/playback/toggle-pause`, label po `skipping_paused` |
| Don't Skip This Song | `POST /api/playback/skip-one-pause`; label postaje "Won't skip: {pjesma}" dok izuzeće vrijedi |
| Add / Remove Liked Songs | `POST /api/playback/toggle-like`, label po `is_liked` |
| Remove from Playlist | dvofazno, vidi dolje. Stavke nema ako `trash_configured` nije true. |
| Lyrics | podmapa s tekstom pjesme, vidi dolje. Namjerno zadnja - komande iznad su već mišićna memorija. |

**Remove je dvofazan:** prvi klik ništa ne šalje - zapamti pjesmu i promijeni label u "Tap again to
remove: {pjesma}". Potvrda šalje `expected_track_id`, pa server odbije s 409 ako je pjesma u
međuvremenu otišla dalje. Armirano stanje pada nakon 10 s, na promjenu pjesme ili nakon izvršenja.

Stanje se osvježava na svakom otvaranju liste, nakon svake komande i pollom svakih 30 s dok netko
gleda listu. Prestanak subscriptiona (odspajanje od auta) gasi poll - nema zasebne detekcije auta.

## Feedback na ekranu auta

Prvi test u autu pokazao je da AA odmah nakon klika presuđuje je li se stavka "učitala": ako se
stanje ne promijeni prije HTTP odgovora, prikaže vlastito "Could not load your selection" iako je
komanda na serveru uredno izvršena. Zato:

- `STATE_ERROR` se postavlja **sinkrono** na klik ("Working…"), pa se poruka zamijeni rezultatom;
  nakon 4 s natrag na `STATE_NONE`.
- Trajna potvrda je promjena liste (`notifyChildrenChanged`): red dobije podnaslov "Sent ✓",
  "Done ✓", "Removed ✓" ili "Failed".
- Greške sa servera idu doslovno na ekran - API ih već formulira za ljude.

## Lyrics

Podmapa "Lyrics" prikazuje **pet redaka odjednom**, s trenutnim na vrhu. Podnaslov gornjeg retka
nosi način rada ("Following the song", "Holding…", "Paused", "No timings…") jer je to jedini redak
koji vozač pouzdano pročita.

Zašto pet, a ne dva: AA zna propustiti osvježavanje browse liste dok korisnik ne izađe i vrati se u
podmapu. S prozorom od pet redaka propušteno osvježavanje ostavi čovjeka na retku koji malo kasni;
s dva retka ostavi ga na zaslonu bez konteksta. Prozor se pri kraju pjesme povlači unatrag da ostane
pun umjesto da se skupi na jedan redak.

**Dva sata, namjerno razdvojena:**

- *Server* (`GET /api/lyrics`, poll 20 s dok je podmapa otvorena) - koja pjesma svira, gdje je,
  koje su riječi. Hvata promjenu pjesme, pauzu i premotavanje.
- *Telefon* (besplatan) - između pollova pozicija se ekstrapolira lokalno, a lista se relabelira
  **točno na početak sljedećeg retka**. Nijedan poll ne bi pogodio granicu retka, a poll svakih par
  sekundi kroz cijelu vožnju je ono što ovaj dizajn izbjegava.

Tekst se dohvaća jednom po pjesmi: klijent šalje `known_track_id`, server izostavi retke kad se
poklapa i vrati samo poziciju.

**Ručno listanje:** klik na redak čini ga vrhom prozora i gasi automatiku ("Holding…"); klik na
redak koji je već na vrhu vraća praćenje pjesme. Namjerno nema zasebnog "Next" gumba - bio bi meta
koju vozač mora tražiti na dnu liste.

Stanja bez teksta prikazuju jedan redak: "Instrumental — no words" (LRCLIB zna pjesmu i kaže da
nema teksta), "No lyrics found for this song", "Nothing playing".

## Tri pravila koja drže cijeli pristup

1. Sesija nikad ne prijavljuje `STATE_PLAYING` ni `STATE_BUFFERING` — zato sustav ne preusmjerava
   media tipke s volana na ovaj app i Spotify zadržava media karticu.
2. App nikad ne traži audio focus.
3. `onLoadChildren` nema side-effecte — Android Auto ga zove kad hoće, pa bi komanda odatle
   ponavljala samu sebe. Tamo se radi samo `GET`.

Volan-fallback (`onSkipToNext/onSkipToPrevious/onPause/onPlay` → `/api/playback/next|previous|pause|resume`)
je osiguranje za slučaj da routing ikad zaluta ovamo, ne primarni mehanizam. Deklarirani ACTION
flagovi ne preuzimaju tipke - to radi tek stvarna reprodukcija.

Compat stack je namjeran: `MediaBrowserServiceCompat` + `MediaSessionCompat` (androidx.media),
**ne** Media3 — mapiranje grešaka prema AA tamo ima otvorene rubove.

## Ikone

`tools/make_launcher_icon.py` crta launcher ikonu (brand strelice + auto), `tools/make_browse_icons.py`
ikone stavki u listi. Sve su jednobojne (brand zelena, crvena za armirani Remove) jer AA listu
renderira na svijetloj ili tamnoj podlozi ovisno o day/night modu auta - dvobojni glif izgubi
polovicu sebe u jednom od njih. Boje su iz postojećeg `cloud/app/static/icons/maskable-512.png`.

Regeneriranje (traži Pillow):

```bash
python android/tools/make_browse_icons.py
```

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
3. Otvoriti Car Skipper na telefonu: server URL (`https://autoskipper.uk`) + device token iz PWA
   Settingsa (Android Auto device), **Save**, pa **Test connection** — mora javiti "Connected: …".
4. Spojiti telefon na auto; app je u AA launcheru.

Verzija piše u zaglavlju setup ekrana ("Car Skipper 0.3.4"). Sideload preko postojeće instalacije
ne javi je li stvarno prošao, pa je to prva stvar za pogledati nakon instalacije.

Zaglavlje je **vlastiti view**, a app ima `NoActionBar` temu. Sa sistemskim action barom vrh
sadržaja se renderirao ispod trake - uvodni odlomak na setup ekranu Vatra nikad nije vidio
(nađeno 2026-08-21 na njegovom telefonu; Samsungov skin crta višu traku nego što layout računa).

AA kešira popis appova: nakon instalacije nove verzije app se ne pojavi dok se Android Auto ne
force-stopa (ili telefon ne restarta). Utvrđeno na spikeu.

### Što provjeriti u autu

1. Sve stavke se renderiraju, s ikonama.
2. Klik izvršava komandu (potvrda u PWA logu) i AA se ne raspadne bez playbacka.
3. Poruka na klik je vidljiva i čitljiva, bez generičkog "Could not load your selection".
4. Volan (next/prev) i dalje upravlja Spotifyjem, media kartica ostaje Spotifyjeva, zvuk se
   nijednom ne prekida.
5. Labeli se osvježe nakon komande (Pause↔Resume, "Won't skip", Liked, "Tap again to remove").

Padne li bilo koji: stop, javiti nalaz. Ne krpati hackovima.

### Što provjeriti u Lyrics grani

1. **Osvježava li se lista sama** dok pjesma ide — ovo je jedina prava nepoznanica cijelog featurea.
   AA zna propustiti `notifyChildrenChanged` dok korisnik ne izađe i vrati se u podmapu. Ako se ne
   osvježava sama, ostatak je svejedno upotrebljiv ručnim listanjem, ali auto-scroll pada.
2. Poklapa li se tekst s onim što se čuje (kasni li, žuri li, je li uopće ta pjesma).
3. Klik na redak zaustavi praćenje, klik na gornji redak ga vrati.
4. Pauza na Spotifyju zaustavi pomicanje, nastavak ga nastavi s pravog mjesta.
5. Promjena pjesme povuče novi tekst bez izlaska iz podmape.
6. Pjesma bez teksta i instrumental daju čitljivu poruku, ne prazan ekran.

Trajanje testa: dovoljno je nekoliko pjesama. Ako prva točka padne, ostale se svejedno provjere
ručnim listanjem — nalaz o tome što radi bez auto-scrolla određuje ima li smisla dorađivati.

## Verzioniranje

`versionName`/`versionCode` u `app/build.gradle.kts`, neovisno o `APP_VERSION` backenda (version
guard hookovi su scoped na `cloud/`). Trenutno **0.3.4**; traži backend v3.23.0 ili noviji
(`GET /api/lyrics`, uz raniji `trash_configured`, `expected_track_id` i transport proxyje).

## Testovi

`LyricsTiming` (koji redak je na ekranu i kad ide sljedeći) pokriven je unit testovima — jedini dio
kojeg se ne može provjeriti pokretanjem appa, jer se kriva granica vidi kao kašnjenje, ne kao kvar.
Ostatak repoa nema testove i ovo ih ne uvodi šire.

```bash
cd android && JAVA_HOME="/c/Program Files/Android/Android Studio/jbr" ./gradlew testDebugUnitTest
```
