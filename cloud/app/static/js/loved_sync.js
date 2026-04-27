// Loved Sync — frontend logic

(async function () {
    const errorBanner = document.getElementById('error-banner');
    const errorText = document.getElementById('error-text');
    const authCard = document.getElementById('auth-card');
    const content = document.getElementById('content');
    const lastfmUsername = document.getElementById('lastfm-username');
    const disconnectBtn = document.getElementById('disconnect-btn');
    const refreshBtn = document.getElementById('refresh-btn');
    const loading = document.getElementById('loading');

    const statSpotify = document.getElementById('stat-spotify');
    const statLastfm = document.getElementById('stat-lastfm');
    const statNeedsLove = document.getElementById('stat-needs-love');
    const statLovedOnly = document.getElementById('stat-loved-only');
    const statIgnored = document.getElementById('stat-ignored');

    const needsLoveCard = document.getElementById('needs-love-card');
    const needsLoveList = document.getElementById('needs-love-list');
    const loveAllBtn = document.getElementById('love-all-btn');
    const lovedOnlyCard = document.getElementById('loved-only-card');
    const lovedOnlyList = document.getElementById('loved-only-list');
    const allClean = document.getElementById('all-clean');

    function showError(msg) {
        errorText.textContent = msg;
        errorBanner.classList.remove('hidden');
    }

    function hideError() {
        errorBanner.classList.add('hidden');
    }

    function parseQueryError() {
        const params = new URLSearchParams(window.location.search);
        if (params.get('error')) {
            const detail = params.get('detail') || '';
            showError('Last.fm authorization failed: ' + params.get('error') + (detail ? ' - ' + detail : ''));
        }
        if (params.get('authorized') === '1') {
            history.replaceState({}, '', '/sync');
        }
    }
    parseQueryError();

    // ── Status check ────────────────────────────────────
    async function checkStatus() {
        const r = await fetch('/api/loved-sync/status');
        if (!r.ok) {
            showError('Could not load status.');
            return null;
        }
        return await r.json();
    }

    const status = await checkStatus();
    if (!status) return;

    if (!status.has_api_secret) {
        showError('LASTFM_API_SECRET env var is not set on the server. Required for write operations.');
        return;
    }

    if (!status.authorized) {
        authCard.classList.remove('hidden');
        return;
    }

    lastfmUsername.textContent = status.lastfm_username || '(unknown)';
    content.classList.remove('hidden');

    // ── Disconnect ──────────────────────────────────────
    disconnectBtn.addEventListener('click', async function () {
        if (!confirm('Disconnect Last.fm? You will need to reauthorize to use Loved Sync.')) return;
        await fetch('/lastfm/auth/logout', {method: 'POST'});
        location.reload();
    });

    // ── Refresh ─────────────────────────────────────────
    refreshBtn.addEventListener('click', loadDiff);

    // ── Render ──────────────────────────────────────────
    function normKey(s) {
        return (s || '').trim().toLowerCase();
    }

    function decStat(el) {
        const n = parseInt(el.textContent, 10);
        if (!isNaN(n)) el.textContent = Math.max(0, n - 1);
    }

    function incStat(el) {
        const n = parseInt(el.textContent, 10);
        el.textContent = (isNaN(n) ? 0 : n) + 1;
    }

    function refreshEmptyState() {
        if (!needsLoveList.children.length) needsLoveCard.classList.add('hidden');
        if (!lovedOnlyList.children.length) lovedOnlyCard.classList.add('hidden');
        if (!needsLoveList.children.length && !lovedOnlyList.children.length) {
            allClean.classList.remove('hidden');
        }
    }

    function findLovedRow(artist, name) {
        const aKey = normKey(artist);
        const nKey = normKey(name);
        return Array.from(lovedOnlyList.querySelectorAll('.sync-row')).find(
            r => r.dataset.artistKey === aKey && r.dataset.nameKey === nKey
        );
    }

    function renderRow(track, withButtons) {
        const row = document.createElement('div');
        row.className = 'sync-row';
        row.dataset.id = track.id || '';
        row.dataset.artistKey = normKey(track.artist);
        row.dataset.nameKey = normKey(track.name);

        const info = document.createElement('div');
        info.className = 'sync-row-info';
        const artist = document.createElement('div');
        artist.className = 'sync-row-artist';
        artist.textContent = track.artist;
        const name = document.createElement('div');
        name.className = 'sync-row-track';
        name.textContent = track.name;
        if (track.lastfm_name && track.lastfm_name !== track.name) {
            const alias = document.createElement('span');
            alias.className = 'sync-row-alias';
            alias.textContent = ' → ' + track.lastfm_name;
            name.appendChild(alias);
        }
        info.appendChild(artist);
        info.appendChild(name);
        row.appendChild(info);

        if (withButtons) {
            const actions = document.createElement('div');
            actions.className = 'sync-row-actions';

            const hasCandidates = (track.candidates || []).length > 0;
            if (hasCandidates) {
                const matchBtn = document.createElement('button');
                matchBtn.className = 'btn btn-sm';
                matchBtn.textContent = 'Match';
                matchBtn.addEventListener('click', () => toggleCandidates(row, track, matchBtn));
                actions.appendChild(matchBtn);
            }

            const loveBtn = document.createElement('button');
            loveBtn.className = 'btn btn-sm btn-accent';
            loveBtn.textContent = 'Love';
            loveBtn.addEventListener('click', () => loveTrack(track, row, loveBtn));

            const ignoreBtn = document.createElement('button');
            ignoreBtn.className = 'btn btn-sm';
            ignoreBtn.textContent = 'Ignore';
            ignoreBtn.addEventListener('click', () => ignoreTrack(track, row, ignoreBtn));

            actions.appendChild(loveBtn);
            actions.appendChild(ignoreBtn);
            row.appendChild(actions);
        }

        return row;
    }

    function toggleCandidates(row, track, btn) {
        const existing = row.nextElementSibling;
        if (existing && existing.classList.contains('sync-candidates')) {
            existing.remove();
            btn.classList.remove('btn-accent');
            return;
        }
        btn.classList.add('btn-accent');

        const panel = document.createElement('div');
        panel.className = 'sync-candidates';

        for (const cand of track.candidates) {
            const item = document.createElement('button');
            item.className = 'sync-candidate';
            item.innerHTML =
                '<div class="sync-candidate-info">' +
                '<div class="sync-candidate-artist">' + escapeHtml(cand.artist) + '</div>' +
                '<div class="sync-candidate-name">' + escapeHtml(cand.name) + '</div>' +
                '</div>' +
                '<span class="sync-candidate-score">' + Math.round(cand.score * 100) + '%</span>';
            item.addEventListener('click', () => createMatch(track, cand, row, panel));
            panel.appendChild(item);
        }

        const manual = document.createElement('button');
        manual.className = 'sync-candidate sync-candidate-manual';
        manual.textContent = 'None of these — enter Last.fm name manually';
        manual.addEventListener('click', () => {
            const lfName = prompt('Last.fm track name (artist will stay "' + track.artist + '"):', track.name);
            if (!lfName || !lfName.trim()) return;
            createMatch(track, {artist: track.artist, name: lfName.trim()}, row, panel);
        });
        panel.appendChild(manual);

        row.insertAdjacentElement('afterend', panel);
    }

    async function createMatch(track, candidate, row, panel) {
        try {
            const r = await fetch('/api/loved-sync/match', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    track_id: track.id,
                    artist: track.artist,
                    spotify_name: track.name,
                    lastfm_name: candidate.name,
                }),
            });
            if (!r.ok) {
                const err = await r.json().catch(() => ({}));
                showError('Match failed: ' + (err.detail || r.status));
                return;
            }
            // Optimistic update: drop both rows, fix counts, no full refresh.
            panel.remove();
            row.remove();
            decStat(statNeedsLove);
            const lovedRow = findLovedRow(candidate.artist, candidate.name);
            if (lovedRow) {
                lovedRow.remove();
                decStat(statLovedOnly);
            }
            refreshEmptyState();
        } catch (e) {
            showError('Network error.');
        }
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    async function loveTrack(track, row, btn) {
        btn.disabled = true;
        btn.textContent = '...';
        try {
            const r = await fetch('/api/loved-sync/love', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({artist: track.artist, track: track.lastfm_name || track.name}),
            });
            if (!r.ok) {
                const err = await r.json().catch(() => ({}));
                btn.textContent = 'Love';
                btn.disabled = false;
                showError('Love failed: ' + (err.detail || r.status));
                return false;
            }
            row.remove();
            decStat(statNeedsLove);
            refreshEmptyState();
            return true;
        } catch (e) {
            btn.textContent = 'Love';
            btn.disabled = false;
            showError('Network error.');
            return false;
        }
    }

    async function ignoreTrack(track, row, btn) {
        btn.disabled = true;
        try {
            const r = await fetch('/api/loved-sync/ignore', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({track_id: track.id}),
            });
            if (!r.ok) {
                btn.disabled = false;
                showError('Ignore failed.');
                return;
            }
            row.remove();
            decStat(statNeedsLove);
            incStat(statIgnored);
            refreshEmptyState();
        } catch (e) {
            btn.disabled = false;
            showError('Network error.');
        }
    }

    loveAllBtn.addEventListener('click', async function () {
        const rows = Array.from(needsLoveList.querySelectorAll('.sync-row'));
        if (!rows.length) return;
        if (!confirm('Love ' + rows.length + ' tracks on Last.fm?')) return;
        loveAllBtn.disabled = true;
        loveAllBtn.textContent = 'Loving... 0/' + rows.length;
        let done = 0, failed = 0;
        for (const row of rows) {
            const loveBtn = row.querySelector('.btn-accent');
            if (!loveBtn) continue;
            const artist = row.querySelector('.sync-row-artist').textContent;
            const trackEl = row.querySelector('.sync-row-track');
            const aliasEl = trackEl.querySelector('.sync-row-alias');
            const trackName = aliasEl ? aliasEl.textContent.replace(/^ → /, '') : trackEl.textContent;
            const ok = await loveTrack({artist: artist, name: trackName, lastfm_name: trackName}, row, loveBtn);
            if (ok) done++; else failed++;
            loveAllBtn.textContent = 'Loving... ' + (done + failed) + '/' + rows.length;
            // Small delay to be nice to Last.fm
            await new Promise(r => setTimeout(r, 200));
        }
        loveAllBtn.disabled = false;
        loveAllBtn.textContent = 'Love all';
        await loadDiff();
        if (failed) showError(failed + ' track(s) failed to love.');
    });

    // ── Load diff ───────────────────────────────────────
    async function loadDiff() {
        hideError();
        loading.classList.remove('hidden');
        needsLoveCard.classList.add('hidden');
        lovedOnlyCard.classList.add('hidden');
        allClean.classList.add('hidden');

        try {
            const r = await fetch('/api/loved-sync/diff');
            if (!r.ok) {
                const err = await r.json().catch(() => ({}));
                showError('Diff failed: ' + (err.detail || r.status));
                loading.classList.add('hidden');
                return;
            }
            const data = await r.json();

            statSpotify.textContent = data.spotify_total;
            statLastfm.textContent = data.lastfm_total;
            statNeedsLove.textContent = data.needs_love.length;
            statLovedOnly.textContent = data.loved_not_liked.length;
            statIgnored.textContent = data.ignored_count;

            needsLoveList.innerHTML = '';
            for (const t of data.needs_love) {
                needsLoveList.appendChild(renderRow(t, true));
            }
            lovedOnlyList.innerHTML = '';
            for (const t of data.loved_not_liked) {
                lovedOnlyList.appendChild(renderRow(t, false));
            }

            if (data.needs_love.length) needsLoveCard.classList.remove('hidden');
            if (data.loved_not_liked.length) lovedOnlyCard.classList.remove('hidden');
            if (!data.needs_love.length && !data.loved_not_liked.length) {
                allClean.classList.remove('hidden');
            }
        } catch (e) {
            showError('Network error loading diff.');
        } finally {
            loading.classList.add('hidden');
        }
    }

    await loadDiff();
})();
