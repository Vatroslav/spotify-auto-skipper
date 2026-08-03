// Playlist Genres — frontend logic

(function () {
    const select = document.getElementById('playlist-select');
    const analyzeBtn = document.getElementById('analyze-btn');
    const loading = document.getElementById('loading');
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

    let lastData = null;
    let sortKey = 'tracks';

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

    // ── Analyze ─────────────────────────────────────────
    analyzeBtn.addEventListener('click', async function () {
        if (!select.value) return;

        hideError();
        analyzeBtn.disabled = true;
        results.classList.add('hidden');
        loading.classList.remove('hidden');

        try {
            const r = await fetch('/api/genres/stats?playlist_id=' + encodeURIComponent(select.value));
            if (!r.ok) {
                const err = await r.json().catch(function () { return {}; });
                showError('Analysis failed: ' + (err.detail || r.status));
                return;
            }
            lastData = await r.json();
            render();
            results.classList.remove('hidden');
        } catch (e) {
            showError('Network error.');
        } finally {
            loading.classList.add('hidden');
            analyzeBtn.disabled = !select.value;
        }
    });

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

        const notes = [];
        if (data.artists_without_genres) {
            notes.push(
                data.artists_without_genres + ' of ' + data.artist_count +
                (data.artist_count === 1 ? ' artist has' : ' artists have') +
                ' no genre listed on Spotify (' + plural(data.tracks_without_genres, 'track') + ' uncounted).'
            );
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
})();
