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

- [ ] **Tihi parcijalni fetch kod Spotify paginacije** — `cloud/app/rediscovery.py:40-52`, `cloud/app/spotify_api.py` (`get_all_saved_tracks`, `get_user_playlists`)
  Kad neka stranica paginacije vrati grešku, `get_playlist_tracks` vrati `{items: [], total: 0}` pa petlja pukne i job nastavi s dijelom pjesama kao da je sve dohvaćeno; `get_all_saved_tracks`/`get_user_playlists` na grešku samo `break`-aju (Loved Sync diff onda računa s nepotpunom Liked listom). Fix: razlikovati "kraj liste" od "greška" (npr. vratiti None / raise na ne-200) i job failati ili retryati umjesto tihog nastavka.

## Srednji prioritet

- [ ] **`escapeHtml` ne escapa navodnike, a koristi se u HTML atributima** — `cloud/app/static/js/app.js:1362` (definicija), korišteno u `value="..."` (~linija 809, 971) i `href="..."` (~864)
  Trik s `textContent`/`innerHTML` ne escapa `"`, pa naziv pjesme s navodnikom razbija atribut (attribute injection; CSP blokira inline handlere pa nije praktični XSS, ali lomi UI). Fix: escapeHtml zamijeniti replace-mapom koja pokriva i `"` i `'`.

- [ ] **`is_track_liked` na svakom dashboard pollu** — `cloud/app/routers/playback.py` (`get_playback`), frontend polla svakih 5 s (`app.js` `setInterval(updatePlayback, 5000)`)
  Svaki poll radi pravi Spotify API poziv za liked status — 720 req/h po otvorenom tabu, za istu pjesmu iznova; nepotrebna izloženost 429. Fix: keširati liked status po track id-u u `app_state` i invalidirati kad se pjesma promijeni ili na toggle-like.

- [ ] **Unhealthy container se ne restarta sam** — `cloud/Dockerfile` (HEALTHCHECK), `cloud/docker-compose.yml`
  `restart: unless-stopped` reagira samo na exit procesa, ne na unhealthy status — kad worker umre, container ostane unhealthy ali živ. Odlučiti: ili autoheal (npr. willfarrell/autoheal companion), ili da app sama exita kad je worker mrtav dulje od N minuta, ili svjesno ostaviti kao signal-only (onda zapisati tu odluku u CLAUDE.md).

- [ ] **`restart_playlist` ne provjerava uspjeh PUT-ova** — `cloud/app/spotify_api.py` (`restart_playlist`)
  Prvi PUT (skok na dummy playlistu) se ne provjerava; ako je `dummy_playlist_id` nevažeći (default je Spotifyjev editorial playlist, koje API od 2024. ograničava novim appovima), "restart" tiho degradira. Fix: provjeriti status svakog PUT-a, na grešku vratiti False i logirati.

## Nizak prioritet / čišćenje

- [ ] **`.env.example` kaže "min 16 chars" za SECRET_KEY, kod traži 32** — `cloud/.env.example:11` vs `cloud/app/config.py` (`get_secret_key`). Uskladiti komentar na 32.
- [ ] **`ruff` u production requirements** — `cloud/requirements.txt:10`. Maknuti iz requirements.txt (dev alat, instalira se u Docker image); po potrebi dodati `requirements-dev.txt`.
- [ ] **Mrtav kod**: `compute_metrics_all` (`cloud/app/insights.py:175`), `get_all_track_events` + `get_all_track_events_by_date` (`cloud/app/database.py`), `app_state.recent_skip_days` (`cloud/app/state.py:18` — worker koristi lokalnu varijablu), provjera `asyncio.current_task().cancelled()` (`cloud/app/rediscovery.py:74` — uvijek False dok task radi). Obrisati.
- [ ] **Null-check za Spotify client** — `cloud/app/routers/settings.py` (`resolve_playlist`) i `cloud/app/routers/artists.py` (`search_artists`) ne provjeravaju `app_state.spotify_client is None` → 500 umjesto urednog 503 prije prvog OAutha. Dodati check kao u rediscovery routeru.
- [ ] **(opcionalno) SQLite konekcija po upitu** — `cloud/app/database.py` (`get_db`): svaki upit otvara novu konekciju + pragme. Radi i nije hitno za single-user app; ako se dira, prijeći na jednu perzistentnu konekciju ili mali pool.

## Napomene za izvođenje

- Redoslijed rada: odozgo prema dolje; svaki fix zasebno testirati.
- Feature branch + test snapshot verzija (`-1`, `-2`, ...) prije mergea na main — vidi CLAUDE.md (Versioning) i memory feedback.
- Svaki commit na main bumpa patch verziju u `cloud/app/__init__.py`, bez iznimki.
