// Playlist Genres — frontend logic

(function () {
    const select = document.getElementById('playlist-select');
    const analyzeBtn = document.getElementById('analyze-btn');
    const loading = document.getElementById('loading');
    const progressMessage = document.getElementById('progress-message');
    const progressBar = document.getElementById('progress-bar');
    const progressDetail = document.getElementById('progress-detail');
    const cancelBtn = document.getElementById('cancel-btn');
    const results = document.getElementById('results');
    const errorBanner = document.getElementById('error-banner');
    const errorText = document.getElementById('error-text');

    const statTracks = document.getElementById('stat-tracks');
    const statArtists = document.getElementById('stat-artists');
    const statGenres = document.getElementById('stat-genres');
    const coverageNote = document.getElementById('coverage-note');

    const genreList = document.getElementById('genre-list');
    const genreEmpty = document.getElementById('genre-empty');
    const sortChips = document.querySelectorAll('.chip[data-sort]');
    const sourceChips = document.querySelectorAll('.chip[data-source]');
    const sourceHelp = document.getElementById('source-help');

    const SOURCE_HELP = {
        spotify: 'Fast. Spotify\'s own classification — broad labels, and some artists are unclassified.',
        lastfm: 'Slow on the first run (one lookup per artist, then cached for 30 days). Crowd-sourced tags — far more granular subgenres.'
    };
    const SOURCE_LABEL = {spotify: 'Spotify', lastfm: 'Last.fm'};

    let lastData = null;
    let sortKey = 'tracks';
    let source = 'spotify';
    let pollTimer = null;

    function plural(n, word) {
        return n + ' ' + word + (n === 1 ? '' : 's');
    }

    function showError(msg) {
        errorText.textContent = msg;
        errorBanner.classList.remove('hidden');
    }

    function hideError() {
        errorBanner.classList.add('hidden');
    }

    sourceHelp.textContent = SOURCE_HELP[source];

    // ── Load playlists ──────────────────────────────────
    (async function loadPlaylists() {
        try {
            const r = await fetch('/api/genres/playlists');
            if (!r.ok) throw new Error('failed');
            const data = await r.json();
            const playlists = data.playlists || [];

            select.innerHTML = '<option value="">Select a playlist...</option>';
            for (const p of playlists) {
                const opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = p.name + ' (' + p.track_count + ' tracks)';
                select.appendChild(opt);
            }
        } catch (e) {
            select.innerHTML = '<option value="">Error loading playlists</option>';
            showError('Could not load your playlists.');
        }
    })();

    select.addEventListener('change', function () {
        analyzeBtn.disabled = !select.value;
    });

    // ── Source switch ───────────────────────────────────
    sourceChips.forEach(function (chip) {
        chip.addEventListener('click', function () {
            source = chip.dataset.source;
            sourceChips.forEach(function (c) { c.classList.toggle('active', c === chip); });
            sourceHelp.textContent = SOURCE_HELP[source];
        });
    });

    // ── Start job ───────────────────────────────────────
    analyzeBtn.addEventListener('click', async function () {
        if (!select.value) return;

        hideError();
        analyzeBtn.disabled = true;
        results.classList.add('hidden');
        progressBar.style.width = '0%';
        progressMessage.textContent = 'Starting...';
        progressDetail.textContent = '';
        cancelBtn.disabled = false;
        loading.classList.remove('hidden');

        try {
            const r = await fetch('/api/genres/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({playlist_id: select.value, source: source}),
            });
            if (!r.ok) {
                const err = await r.json().catch(function () { return {}; });
                showError('Could not start: ' + (err.detail || r.status));
                loading.classList.add('hidden');
                analyzeBtn.disabled = !select.value;
                return;
            }
        } catch (e) {
            showError('Network error.');
            loading.classList.add('hidden');
            analyzeBtn.disabled = !select.value;
            return;
        }

        startPolling();
    });

    cancelBtn.addEventListener('click', async function () {
        cancelBtn.disabled = true;
        try {
            await fetch('/api/genres/cancel', {method: 'POST'});
        } catch (e) {
            // the poll will settle the UI either way
        }
    });

    // ── Poll ────────────────────────────────────────────
    function startPolling() {
        if (pollTimer) clearInterval(pollTimer);
        // 1s: the Spotify source often finishes in a couple of ticks
        pollTimer = setInterval(poll, 1000);
        poll();
    }

    function stopPolling() {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = null;
    }

    async function poll() {
        let data;
        try {
            const r = await fetch('/api/genres/status');
            if (!r.ok) return;
            data = await r.json();
        } catch (e) {
            return;  // transient — keep polling
        }

        const progress = data.progress || {};
        progressMessage.textContent = progress.message || 'Working...';
        if (progress.total > 0) {
            const pct = Math.round((progress.current / progress.total) * 100);
            progressBar.style.width = pct + '%';
            progressDetail.textContent = progress.current + ' / ' + progress.total + ' artists';
        } else {
            progressDetail.textContent = '';
        }

        if (data.status === 'completed') {
            stopPolling();
            loading.classList.add('hidden');
            analyzeBtn.disabled = !select.value;
            lastData = data.result;
            if (lastData) {
                render();
                results.classList.remove('hidden');
            }
        } else if (data.status === 'failed') {
            stopPolling();
            loading.classList.add('hidden');
            analyzeBtn.disabled = !select.value;
            showError(progress.message || 'Analysis failed.');
        } else if (data.status === 'idle') {
            stopPolling();
            loading.classList.add('hidden');
            analyzeBtn.disabled = !select.value;
        }
    }

    // ── Sort toggle ─────────────────────────────────────
    sortChips.forEach(function (chip) {
        chip.addEventListener('click', function () {
            sortKey = chip.dataset.sort;
            sortChips.forEach(function (c) { c.classList.toggle('active', c === chip); });
            if (lastData) render();
        });
    });

    // ── Render ──────────────────────────────────────────
    function render() {
        const data = lastData;

        statTracks.textContent = data.total_tracks;
        statArtists.textContent = data.artist_count;
        statGenres.textContent = data.genres.length;

        const notes = ['Source: ' + (SOURCE_LABEL[data.source] || data.source) + '.'];
        if (data.artists_without_genres) {
            notes.push(
                data.artists_without_genres + ' of ' + data.artist_count +
                (data.artist_count === 1 ? ' artist has' : ' artists have') +
                ' no genre listed (' + plural(data.tracks_without_genres, 'track') + ' uncounted).'
            );
        }
        if (data.lookup_failures) {
            notes.push(plural(data.lookup_failures, 'artist') + ' could not be looked up on Last.fm.');
        }
        if (data.tracks_without_artist) {
            notes.push(
                'Skipped ' + plural(data.tracks_without_artist, 'track') +
                ' with no artist (local files or podcast episodes).'
            );
        }
        coverageNote.textContent = notes.join(' ');

        const rows = data.genres.slice().sort(function (a, b) {
            if (sortKey === 'artists') {
                return b.artists - a.artists || b.tracks - a.tracks || a.genre.localeCompare(b.genre);
            }
            return b.tracks - a.tracks || b.artists - a.artists || a.genre.localeCompare(b.genre);
        });

        genreList.innerHTML = '';
        if (!rows.length) {
            genreEmpty.classList.remove('hidden');
            return;
        }
        genreEmpty.classList.add('hidden');

        const max = rows[0][sortKey] || 1;

        for (const row of rows) {
            const item = document.createElement('div');
            item.className = 'genre-row';

            const head = document.createElement('div');
            head.className = 'genre-row-head';

            const name = document.createElement('span');
            name.className = 'genre-name';
            name.textContent = row.genre;

            const count = document.createElement('span');
            count.className = 'genre-count';
            count.textContent = sortKey === 'artists'
                ? plural(row.artists, 'artist')
                : plural(row.tracks, 'track');

            head.appendChild(name);
            head.appendChild(count);

            const track = document.createElement('div');
            track.className = 'genre-bar-track';
            const fill = document.createElement('div');
            fill.className = 'genre-bar-fill';
            fill.style.width = Math.max(2, Math.round((row[sortKey] / max) * 100)) + '%';
            track.appendChild(fill);

            const meta = document.createElement('div');
            meta.className = 'genre-meta';
            const other = sortKey === 'artists'
                ? plural(row.tracks, 'track')
                : plural(row.artists, 'artist');
            meta.textContent = other + ' — ' + row.top_artists.join(', ');

            item.appendChild(head);
            item.appendChild(track);
            item.appendChild(meta);
            genreList.appendChild(item);
        }
    }

    // ── Reattach to a job already running (e.g. after a reload) ──
    (async function resume() {
        try {
            const r = await fetch('/api/genres/status');
            if (!r.ok) return;
            const data = await r.json();
            if (data.status === 'running') {
                analyzeBtn.disabled = true;
                loading.classList.remove('hidden');
                startPolling();
            }
        } catch (e) {
            // ignore
        }
    })();
})();
