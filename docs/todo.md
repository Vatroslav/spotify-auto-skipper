# TODO — nalazi code reviewa (2026-07-02)

Cijeli repo pregledan (backend, frontend JS, Docker/deploy). Stavke poredane po prioritetu.
Svaka stavka je samostalna — sadrži file, problem i smjer popravka.

## Visoki prioritet

- [x] **Jinja2 pin isključuje sigurnosni patch** — `cloud/requirements.txt:5` — DONE (v3.15.2, PR #63)
  `jinja2>=3.1.0,<3.1.6` pinira na 3.1.5, a upravo 3.1.6 fixa CVE-2025-27516 (sandbox escape kroz `|attr` filter). Cap izgleda kao tipfeler. Fix: promijeniti u `jinja2>=3.1.6,<3.2`. Nakon izmjene rebuildati i provjeriti da se templati normalno renderiraju. Deployano i verificirano zdravo (jinja2 3.1.6 u buildu).

- [x] **`ALLOWED_SPOTIFY_USER` prazan = svatko se može ulogirati** — DONE (v3.16.0)
  Prazan `ALLOWED_SPOTIFY_USER` sada je fail-closed: login se odbija osim ako je eksplicitno postavljeno `ALLOW_ANY_SPOTIFY_USER=true`. Startup (lifespan u `main.py`) logira jasan warning o trenutnom auth stanju. `.env.example` dokumentira oba vara. PREOSTALO: postaviti `ALLOWED_SPOTIFY_USER` na Vatrin Spotify user ID u `.env` na VPS-u PRIJE deploya (inače fail-closed zaključa vlasnika pri sljedećem re-loginu).

- [x] **Worker može umrijeti od NameError** — `cloud/app/worker.py` — DONE (v3.16.1)
  Završni `await app_state.interruptible_sleep(poll_interval)` je unutar `while` petlje ali izvan `try/except`. Ako na prvoj iteraciji `load_settings()` baci iznimku prije dodjele `poll_interval`, generic handler je uhvati, ali sleep na kraju petlje onda digne NameError koji ubije task. Fix: `poll_interval` inicijaliziran prije petlje iz settingsa učitanih pri startupu.

- [x] **Rediscovery ignorira track_id aliase** — `cloud/app/rediscovery.py:84` — DONE (v3.16.2, PR #66)
  Pozivao `get_last_play_date(artist, name)` bez `track_id`, iako ga ima (`track["id"]` iz playlist items). Aliasi keyani po track_id (moderni, iz Loved Sync / mapping-fails) se nisu primjenjivali, pa su pjesme s poznatim Spotify↔Last.fm mapping problemima ispadale "nikad slušane" i pogrešno ulazile u Rediscovery playlistu. Fix: `track["id"]` proslijeđen kao treći argument (kao u `worker.py:195`).

- [x] **Tihi parcijalni fetch kod Spotify paginacije** — DONE (v3.16.3, PR #67)
  Nova iznimka `SpotifyAPIError` baca se na ne-200 / mrežni fail nakon iscrpljenih retryja (tranzijentni network/429/401 već retrya `_request`), pa se greška u paginaciji više ne može tiho progutati. `get_playlist_tracks`/`get_all_saved_tracks`/`get_user_playlists` sada raise-aju umjesto da vraćaju parcijalne podatke. Calleri razlikuju "kraj liste" od "greške": Rediscovery job faila čisto (već ima try/except oko Phase 1), `compute_diff` (Loved Sync) vrati `{ok: False}` → 502, `list_playlists` vrati 502 umjesto parcijalnog dropdowna.

## Srednji prioritet

- [x] **`escapeHtml` ne escapa navodnike, a koristi se u HTML atributima** — `cloud/app/static/js/app.js:1362` — DONE (v3.16.4, PR #68)
  Trik s `textContent`/`innerHTML` nije escapao `"`/`'`, pa je naziv s navodnikom razbijao atribut (`value="..."`, `href="..."`). Fix: `escapeHtml` zamijenjen regex replace-mapom (`& < > " '`), identično onoj u `loved_sync.js`, uz null-guard za staro ponašanje.

- [x] **`is_track_liked` na svakom dashboard pollu** — `cloud/app/routers/playback.py` (`get_playback`) — DONE (v3.16.5, PR #69)
  Poll je radio pravi Spotify `/me/tracks/contains` poziv svakih 5 s (720 req/h po otvorenom tabu). Fix: liked status keširan po track_id-u u `app_state.liked_status_cache` (single-entry — drži samo trenutnu pjesmu, ne akumulira stale id-eve). Poll gađa Spotify samo na miss (nova pjesma); `toggle_like` upisuje novo stanje u cache pa se toggle odmah reflektira umjesto da se dugme vrati na staru vrijednost. Worker netaknut (već zove `is_track_liked` najviše jednom po pjesmi). Tradeoff: like/unlike s drugog Spotify klijenta ne vidi se na dashboardu dok se pjesma ne promijeni.

- [x] **Unhealthy container se ne restarta sam** — `cloud/app/worker.py`, `cloud/app/main.py` — DONE (v3.16.6)
  Rješenje: in-process supervizor (`worker_supervisor`, spawnan u lifespanu) koji restarta worker task **samo na crash** (`task.exception() is not None`), preko postojećeg `restart_worker_if_dead()`, uz eksponencijalni backoff. Uredan reauth/credential return ostaje netaknut (čeka korisnika na `/auth/login`). Svjesno BEZ container autoheala/self-exita: naivni autoheal bi restart-loopao na reauth-503; zaglavljeni-proces rep ostaje signal-only preko Docker HEALTHCHECK-a (odluka zapisana u CLAUDE.md, Health Monitoring).

- [x] **`restart_playlist` ne provjerava uspjeh PUT-ova** — `cloud/app/spotify_api.py` (`restart_playlist`) — DONE (v3.16.7, PR #71)
  Svaki PUT (skok na dummy, shuffle on, skok natrag) sada provjerava status; na grešku logira warning i vraća False. Prvi PUT (skok na dummy playlistu) aborta rano ako padne — playback netaknut. Ako je skok na dummy uspio, skok natrag na originalni kontekst se **uvijek** pokuša (i kad shuffle padne) da korisnik ne ostane zaglavljen na dummy playlisti. Worker call-site (`worker.py`) sada površi neuspjeh u user-facing log ("Playlist restart failed — check the dummy playlist ID in settings.").

- [ ] **Alias potpuno gazi originalni naziv umjesto da uzme noviji rezultat** — `cloud/app/lastfm_api.py:120` (`get_last_play_date`)
  Kad postoji alias, radi se `return await _lookup_scrobbles(artist, alias)` i originalni Spotify naziv se više uopće ne provjerava. Zato jedan loš alias tiho pokvari podatke: ako alias ne postoji na Last.fm-u, pjesma ispadne "nikad slušana" (jače od izostanka aliasa), a ako alias postoji ali je pod njim zadnja scrobbla starija, app radi na zastarjelom datumu i ne skipa pjesmu koju bi trebao. Oba slučaja potvrđena na produ 2026-08-04: 1 slomljen alias (zalijepljen "Love this track " prefiks s Last.fm stranice) + 3 koja su pokazivala na scrobblu iz 2022. dok je originalni naziv imao 2026. Podaci su počišćeni ručno (`track_aliases` 60 → 40), ali logika i dalje dopušta isti scenarij.
  Fix: pozvati oba naziva i uzeti noviji (`max`), uz čuvanje semantike `LASTFM_ERROR` — greška na jednom pozivu ne smije se pretvoriti u "nema scrobble". Cijena: jedan dodatni Last.fm poziv po pjesmi koja ima alias. Napomena: lookup je case-insensitive, pa alias koji se od Spotify naziva razlikuje samo u velikim slovima nema efekta — razmisliti i o tome da UI odbije spremiti takav alias umjesto da stvori mrtav redak.

## Nizak prioritet / čišćenje

- [ ] **`.env.example` kaže "min 16 chars" za SECRET_KEY, kod traži 32** — `cloud/.env.example:11` vs `cloud/app/config.py` (`get_secret_key`). Uskladiti komentar na 32.
- [ ] **`ruff` u production requirements** — `cloud/requirements.txt:10`. Maknuti iz requirements.txt (dev alat, instalira se u Docker image); po potrebi dodati `requirements-dev.txt`.
- [ ] **Mrtav kod**: `compute_metrics_all` (`cloud/app/insights.py:175`), `get_all_track_events` + `get_all_track_events_by_date` (`cloud/app/database.py`), `app_state.recent_skip_days` (`cloud/app/state.py:18` — worker koristi lokalnu varijablu), provjera `asyncio.current_task().cancelled()` (`cloud/app/rediscovery.py:74` — uvijek False dok task radi). Obrisati.
- [ ] **Null-check za Spotify client** — `cloud/app/routers/settings.py` (`resolve_playlist`) i `cloud/app/routers/artists.py` (`search_artists`) ne provjeravaju `app_state.spotify_client is None` → 500 umjesto urednog 503 prije prvog OAutha. Dodati check kao u rediscovery routeru.
- [ ] **(opcionalno) SQLite konekcija po upitu** — `cloud/app/database.py` (`get_db`): svaki upit otvara novu konekciju + pragme. Radi i nije hitno za single-user app; ako se dira, prijeći na jednu perzistentnu konekciju ili mali pool.

## Napomene za izvođenje

- Redoslijed rada: odozgo prema dolje; svaki fix zasebno testirati.
- Feature branch + deploy branch da testiraš prije mergea na main — vidi CLAUDE.md (Versioning) i memory feedback.
- Bump je intent-based, u istom commitu: feat → minor, fix/perf → patch; docs/chore/tooling bez runtime učinka → bez bumpa. Vidi CLAUDE.md (Versioning).
