// Rediscovery — full frontend logic

(async function () {
    const select = document.getElementById('playlist-select');
    const thresholdInput = document.getElementById('threshold-days');
    const nameInput = document.getElementById('playlist-name');
    const startBtn = document.getElementById('start-btn');
    const configSection = document.getElementById('config-section');
    const progressSection = document.getElementById('progress-section');
    const progressMessage = document.getElementById('progress-message');
    const progressBar = document.getElementById('progress-bar');
    const progressDetail = document.getElementById('progress-detail');
    const cancelBtn = document.getElementById('cancel-btn');
    const resultSection = document.getElementById('result-section');
    const resultMessage = document.getElementById('result-message');
    const resultLink = document.getElementById('result-link');
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

    // ── Threshold + default name ────────────────────────
    function thresholdDays() {
        const days = parseInt(thresholdInput.value, 10);
        return days >= 1 && days <= 36500 ? days : null;
    }

    // The threshold goes into the default name so runs at different
    // thresholds on the same playlist don't end up with identical names.
    function defaultName() {
        const selected = select.options[select.selectedIndex];
        const source = select.value ? selected.textContent.replace(/ \(\d+ tracks\)$/, '') : '...';
        const days = thresholdDays();
        return 'Rediscovery' + (days ? ' ' + days + 'd+' : '') + ' - ' + source;
    }

    function refreshForm() {
        nameInput.placeholder = defaultName();
        startBtn.disabled = !select.value || thresholdDays() === null;
    }

    select.addEventListener('change', refreshForm);
    thresholdInput.addEventListener('input', refreshForm);
    refreshForm();

    // ── Start job ───────────────────────────────────────
    startBtn.addEventListener('click', async function () {
        const playlistId = select.value;
        const days = thresholdDays();
        if (!playlistId || days === null) return;

        const playlistName = nameInput.value.trim() || defaultName();

        startBtn.disabled = true;
        try {
            const r = await fetch('/api/rediscovery/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({playlist_id: playlistId, playlist_name: playlistName, threshold_days: days}),
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

                if (data.status === 'completed' && data.playlist_url) {
                    resultLink.href = data.playlist_url;
                    resultLink.classList.remove('hidden');
                } else {
                    resultLink.classList.add('hidden');
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
