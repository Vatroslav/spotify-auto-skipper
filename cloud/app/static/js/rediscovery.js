// Rediscovery — full frontend logic

(async function () {
    const select = document.getElementById('playlist-select');
    const thresholdInput = document.getElementById('threshold-days');
    const nameInput = document.getElementById('playlist-name');
    const namePreview = document.getElementById('name-preview');
    const startBtn = document.getElementById('start-btn');
    const configSection = document.getElementById('config-section');
    const progressSection = document.getElementById('progress-section');
    const progressMessage = document.getElementById('progress-message');
    const progressBar = document.getElementById('progress-bar');
    const progressDetail = document.getElementById('progress-detail');
    const cancelBtn = document.getElementById('cancel-btn');
    const resultSection = document.getElementById('result-section');
    const resultMessage = document.getElementById('result-message');
    const resultLinks = document.getElementById('result-links');
    const resetBtn = document.getElementById('reset-btn');

    let pollInterval = null;

    // ── Load playlists ──────────────────────────────────
    try {
        const r = await fetch('/api/rediscovery/playlists');
        if (!r.ok) throw new Error('Failed to load playlists');
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
    }

    // ── Thresholds + default name ───────────────────────
    // "100, 500 1000" → [100, 500, 1000]; null if any part is invalid.
    function thresholdsDays() {
        const parts = thresholdInput.value.split(/[\s,;]+/).filter(Boolean);
        if (parts.length === 0) return null;
        const days = [];
        for (const part of parts) {
            if (!/^\d+$/.test(part)) return null;
            const n = parseInt(part, 10);
            if (n < 1 || n > 36500) return null;
            if (!days.includes(n)) days.push(n);
        }
        if (days.length > 5) return null;
        return days.sort(function (a, b) { return a - b; });
    }

    // Each created playlist gets its bucket appended, e.g. "(500-999 days)".
    function defaultName() {
        const selected = select.options[select.selectedIndex];
        const source = select.value ? selected.textContent.replace(/ \(\d+ tracks\)$/, '') : '...';
        return 'Rediscovery - ' + source;
    }

    // Same labels as _build_buckets in rediscovery.py.
    function bucketLabels(days) {
        return days.map(function (d, i) {
            return i + 1 < days.length ? d + '-' + (days[i + 1] - 1) + ' days' : d + '+ days';
        });
    }

    function refreshForm() {
        nameInput.placeholder = defaultName();
        const days = thresholdsDays();
        startBtn.disabled = !select.value || days === null;

        namePreview.innerHTML = '';
        if (days === null) return;
        const base = nameInput.value.trim() || defaultName();
        const intro = document.createElement('div');
        intro.textContent = days.length > 1
            ? 'Creates up to ' + days.length + ' playlists (one per threshold that has songs):'
            : 'Creates:';
        namePreview.appendChild(intro);
        for (const label of bucketLabels(days)) {
            const line = document.createElement('div');
            line.textContent = base + ' (' + label + ')';
            namePreview.appendChild(line);
        }
    }

    select.addEventListener('change', refreshForm);
    thresholdInput.addEventListener('input', refreshForm);
    nameInput.addEventListener('input', refreshForm);
    refreshForm();

    // ── Start job ───────────────────────────────────────
    startBtn.addEventListener('click', async function () {
        const playlistId = select.value;
        const days = thresholdsDays();
        if (!playlistId || days === null) return;

        const playlistName = nameInput.value.trim() || defaultName();

        startBtn.disabled = true;
        try {
            const r = await fetch('/api/rediscovery/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({playlist_id: playlistId, playlist_name: playlistName, thresholds_days: days}),
            });
            if (!r.ok) {
                const err = await r.json().catch(function () { return {}; });
                alert(err.detail || 'Failed to start job');
                startBtn.disabled = false;
                return;
            }
        } catch (e) {
            alert('Network error');
            startBtn.disabled = false;
            return;
        }

        // Switch to progress view
        configSection.classList.add('hidden');
        progressSection.classList.remove('hidden');
        resultSection.classList.add('hidden');

        startPolling();
    });

    // ── Cancel job ──────────────────────────────────────
    cancelBtn.addEventListener('click', async function () {
        cancelBtn.disabled = true;
        try {
            await fetch('/api/rediscovery/cancel', {method: 'POST'});
        } catch (e) {
            // ignore
        }
    });

    // ── Reset ───────────────────────────────────────────
    resetBtn.addEventListener('click', function () {
        resultSection.classList.add('hidden');
        configSection.classList.remove('hidden');
        refreshForm();
        progressBar.style.width = '0%';
    });

    // ── Poll status ─────────────────────────────────────
    function startPolling() {
        if (pollInterval) clearInterval(pollInterval);
        // Cancel disables itself; re-arm it for this run, or a second run
        // after a cancelled one could not be cancelled.
        cancelBtn.disabled = false;
        pollInterval = setInterval(pollStatus, 2000);
        pollStatus();
    }

    async function pollStatus() {
        try {
            const r = await fetch('/api/rediscovery/status');
            if (!r.ok) return;
            const data = await r.json();
            const progress = data.progress || {};

            progressMessage.textContent = progress.message || 'Working...';

            // Update progress bar
            if (progress.total > 0) {
                const pct = Math.round((progress.current / progress.total) * 100);
                progressBar.style.width = pct + '%';
                progressDetail.textContent = progress.current + ' / ' + progress.total;
            }

            // Job finished
            if (data.status === 'completed' || data.status === 'failed') {
                clearInterval(pollInterval);
                pollInterval = null;

                progressSection.classList.add('hidden');
                resultSection.classList.remove('hidden');
                resultMessage.textContent = progress.message || 'Done.';

                resultLinks.innerHTML = '';
                for (const p of data.playlists || []) {
                    const a = document.createElement('a');
                    a.href = p.url;
                    a.target = '_blank';
                    a.className = 'btn btn-accent btn-full mt-8';
                    a.textContent = 'Open ' + p.label + ' (' + p.count + ' tracks)';
                    resultLinks.appendChild(a);
                }
            }

            // Job cancelled/idle
            if (data.status === 'idle') {
                clearInterval(pollInterval);
                pollInterval = null;
                progressSection.classList.add('hidden');
                configSection.classList.remove('hidden');
                refreshForm();
            }
        } catch (e) {
            // Network error, keep polling
        }
    }

    // ── Check if a job is already running on page load ──
    try {
        const r = await fetch('/api/rediscovery/status');
        if (r.ok) {
            const data = await r.json();
            if (data.status === 'running') {
                configSection.classList.add('hidden');
                progressSection.classList.remove('hidden');
                startPolling();
            }
        }
    } catch (e) {
        // ignore
    }
})();
