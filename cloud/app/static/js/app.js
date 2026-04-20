/**
 * Dashboard interactivity — polling, button handlers, page logic.
 */

// ── Toast notification ──────────────────────────────────────────

function showToast(message, duration = 2000, type = "success") {
    let toast = document.getElementById("toast");
    if (!toast) {
        toast = document.createElement("div");
        toast.id = "toast";
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.className = "toast show " + (type === "error" ? "toast-error" : "");
    clearTimeout(toast._timeout);
    toast._timeout = setTimeout(() => toast.classList.remove("show"), duration);
}

// ── Dashboard (index.html) ──────────────────────────────────────

function initDashboard() {
    const trackName = document.getElementById("track-name");
    const artistName = document.getElementById("artist-name");
    const albumArt = document.getElementById("album-art");
    const nothingPlaying = document.getElementById("nothing-playing");
    const trackInfo = document.getElementById("track-info");
    const statusBadge = document.getElementById("status-badge");
    const pauseBtn = document.getElementById("pause-btn");
    const checkNowBtn = document.getElementById("check-now-btn");
    const skipOnePauseBtn = document.getElementById("skip-one-pause-btn");

    if (!trackName) return; // Not on dashboard

    let nextCheckAt = null; // epoch ms when next check fires

    async function updatePlayback() {
        try {
            const data = await API.get("/api/playback");
            if (data.track) {
                trackName.textContent = data.track.name;
                artistName.textContent = data.track.artist;
                trackInfo.classList.remove("hidden");
                nothingPlaying.classList.add("hidden");
                const lastCheck = document.getElementById("last-check");
                if (lastCheck) {
                    lastCheck.textContent = data.last_check_message || "";
                }
                if (albumArt && data.track.album_art) {
                    albumArt.src = data.track.album_art;
                    albumArt.classList.remove("hidden");
                } else if (albumArt) {
                    albumArt.classList.add("hidden");
                }
            } else {
                trackInfo.classList.add("hidden");
                nothingPlaying.classList.remove("hidden");
                if (albumArt) albumArt.classList.add("hidden");
            }

            // Last checked time + compute next check
            const lastCheckedEl = document.getElementById("last-checked-time");
            if (lastCheckedEl && data.last_checked) {
                const d = new Date(data.last_checked);
                lastCheckedEl.textContent = `Last checked at ${d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false})}`;
                if (data.poll_interval) {
                    nextCheckAt = d.getTime() + data.poll_interval * 1000;
                }
            }

            // Status badge
            if (!data.worker_running) {
                statusBadge.textContent = "Worker Offline";
                statusBadge.className = "status-badge offline";
            } else if (data.skipping_paused) {
                statusBadge.textContent = "Skipping Paused";
                statusBadge.className = "status-badge paused";
            } else if (data.idle_mode) {
                statusBadge.textContent = "Idle Mode";
                statusBadge.className = "status-badge paused";
            } else {
                statusBadge.textContent = "Skipping Active";
                statusBadge.className = "status-badge active";
            }

            // Pause button text
            if (pauseBtn) {
                pauseBtn.textContent = data.skipping_paused ? "Resume Skipping" : "Pause Skipping";
            }

            // "Don't Skip This Song" button
            if (skipOnePauseBtn) {
                if (data.track && data.skip_exempt_track_id === data.track.id) {
                    skipOnePauseBtn.textContent = "Skip Paused for This Song";
                    skipOnePauseBtn.disabled = true;
                } else {
                    skipOnePauseBtn.textContent = "Don't Skip This Song";
                    skipOnePauseBtn.disabled = false;
                }
            }
        } catch (e) {
            console.error("Failed to fetch playback:", e);
        }
    }

    // Pause/resume
    if (pauseBtn) {
        pauseBtn.addEventListener("click", async () => {
            await API.post("/api/playback/toggle-pause");
            updatePlayback();
        });
    }

    // Check now
    if (checkNowBtn) {
        checkNowBtn.addEventListener("click", async () => {
            checkNowBtn.disabled = true;
            checkNowBtn.textContent = "Checking...";
            await API.post("/api/playback/check-now");
            setTimeout(() => {
                checkNowBtn.disabled = false;
                checkNowBtn.textContent = "Check Now";
                updatePlayback();
            }, 3000);
        });
    }

    // Don't skip this song
    if (skipOnePauseBtn) {
        skipOnePauseBtn.addEventListener("click", async () => {
            try {
                const result = await API.post("/api/playback/skip-one-pause");
                showToast(`Won't skip: ${result.track_name}`);
                updatePlayback();
            } catch (e) {
                showToast(e.message || "Failed", 2000, "error");
            }
        });
    }

    // Countdown ticker (every second)
    const nextCheckEl = document.getElementById("next-check");
    setInterval(() => {
        if (!nextCheckEl || !nextCheckAt) return;
        const remaining = Math.max(0, Math.round((nextCheckAt - Date.now()) / 1000));
        const mins = Math.floor(remaining / 60);
        const secs = remaining % 60;
        nextCheckEl.textContent = `Next check in ${mins}:${secs.toString().padStart(2, "0")}`;
    }, 1000);

    // Poll every 5 seconds
    updatePlayback();
    setInterval(updatePlayback, 5000);
}


// ── Settings (settings.html) ────────────────────────────────────

function initSettings() {
    const form = document.getElementById("settings-form");
    if (!form) return;

    async function loadSettings() {
        const data = await API.get("/api/settings");
        // Populate numeric inputs
        document.querySelectorAll("[data-setting]").forEach(el => {
            const key = el.dataset.setting;
            if (key in data) {
                if (el.type === "checkbox") {
                    el.checked = data[key];
                } else {
                    el.value = data[key];
                }
            }
        });
    }

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const updates = {};
        document.querySelectorAll("[data-setting]").forEach(el => {
            const key = el.dataset.setting;
            if (el.type === "checkbox") {
                updates[key] = el.checked;
            } else if (el.type === "number") {
                updates[key] = parseInt(el.value, 10);
            } else {
                updates[key] = el.value;
            }
        });
        try {
            const result = await API.put("/api/settings", updates);
            if (result._warnings && result._warnings.length > 0) {
                showToast(result._warnings[0], 3000, "error");
            } else {
                showToast("Settings saved!");
            }
        } catch (err) {
            showToast(err.message || "Failed to save settings", 3000, "error");
        }
    });

    // Resolve playlist button
    const resolveBtn = document.getElementById("resolve-playlist-btn");
    const playlistInput = document.getElementById("dummy-playlist");
    const playlistStatus = document.getElementById("playlist-status");
    if (resolveBtn && playlistInput) {
        function formatPlaylistInfo(data) {
            let text = `\u2713 ${data.name}`;
            if (data.owner) text += ` \u2014 by ${data.owner}`;
            if (data.description) text += `\n${data.description}`;
            return text;
        }

        // Auto-resolve on load
        loadSettings().then(async () => {
            if (playlistInput.value) {
                const data = await API.get(`/api/settings/resolve-playlist?q=${encodeURIComponent(playlistInput.value)}`);
                if (data.name) {
                    playlistStatus.textContent = formatPlaylistInfo(data);
                    playlistStatus.className = "help-text text-success";
                    playlistInput.value = data.id;
                }
            }
        });

        resolveBtn.addEventListener("click", async () => {
            const q = playlistInput.value.trim();
            if (!q) return;
            resolveBtn.disabled = true;
            resolveBtn.textContent = "...";
            try {
                const data = await API.get(`/api/settings/resolve-playlist?q=${encodeURIComponent(q)}`);
                playlistStatus.textContent = formatPlaylistInfo(data);
                playlistStatus.className = "help-text text-success";
                playlistInput.value = data.id;
            } catch (err) {
                playlistStatus.textContent = `\u2717 ${err.message || "Not found"}`;
                playlistStatus.className = "help-text text-error";
            }
            resolveBtn.disabled = false;
            resolveBtn.textContent = "Resolve";
        });
        bindLogout();
        return; // loadSettings already called above
    }

    loadSettings();
    bindLogout();
}

function bindLogout() {
    const logoutBtn = document.getElementById("logout-btn");
    if (logoutBtn && !logoutBtn._bound) {
        logoutBtn._bound = true;
        logoutBtn.addEventListener("click", async () => {
            try {
                await API.post("/auth/logout");
            } catch { /* ignore */ }
            location.href = "/";
        });
    }
}


// ── Artists (artists.html) ──────────────────────────────────────

async function initArtists() {
    const list = document.getElementById("artist-list");
    const searchInput = document.getElementById("artist-search");
    const searchResults = document.getElementById("search-results");
    const toggleNeverSkip = document.getElementById("toggle-never-skip");
    if (!list) return;

    // Load and bind the enable toggle
    if (toggleNeverSkip) {
        const settings = await API.get("/api/settings");
        toggleNeverSkip.checked = settings.enable_never_skip_artists;
        toggleNeverSkip.addEventListener("change", async () => {
            try {
                await API.put("/api/settings", { enable_never_skip_artists: toggleNeverSkip.checked });
                showToast(toggleNeverSkip.checked ? "Never-skip enabled" : "Never-skip disabled");
            } catch (err) {
                showToast(err.message || "Failed to update setting", 3000, "error");
                toggleNeverSkip.checked = !toggleNeverSkip.checked;
            }
        });
    }

    async function loadArtists() {
        const data = await API.get("/api/artists");
        list.innerHTML = "";
        if (data.artists.length === 0) {
            list.innerHTML = '<p class="text-muted text-center mt-16">No never-skip artists configured.</p>';
            return;
        }
        data.artists.forEach(a => {
            const div = document.createElement("div");
            div.className = "artist-item";

            const info = document.createElement("div");
            info.className = "artist-info";

            if (a.image_url) {
                const img = document.createElement("img");
                img.className = "artist-img";
                img.alt = "";
                img.src = a.image_url;
                info.appendChild(img);
            } else {
                const placeholder = document.createElement("div");
                placeholder.className = "artist-img artist-img-placeholder";
                info.appendChild(placeholder);
            }

            const nameSpan = document.createElement("span");
            nameSpan.className = "artist-name-text";
            nameSpan.textContent = a.name;
            info.appendChild(nameSpan);

            const removeBtn = document.createElement("button");
            removeBtn.className = "artist-remove";
            removeBtn.title = "Remove";
            removeBtn.textContent = "\u00d7";
            removeBtn.addEventListener("click", async () => {
                await API.del(`/api/artists/${encodeURIComponent(a.id)}`);
                loadArtists();
            });

            div.appendChild(info);
            div.appendChild(removeBtn);
            list.appendChild(div);
        });
    }

    let searchTimeout = null;
    if (searchInput) {
        searchInput.addEventListener("input", () => {
            clearTimeout(searchTimeout);
            const q = searchInput.value.trim();
            if (q.length < 2) {
                searchResults.classList.add("hidden");
                return;
            }
            searchTimeout = setTimeout(async () => {
                const data = await API.get(`/api/artists/search?q=${encodeURIComponent(q)}`);
                searchResults.innerHTML = "";
                if (data.artists.length === 0) {
                    searchResults.classList.add("hidden");
                    return;
                }
                data.artists.forEach(a => {
                    const div = document.createElement("div");
                    div.className = "search-result-item";

                    if (a.image_url) {
                        const img = document.createElement("img");
                        img.className = "artist-img";
                        img.alt = "";
                        img.src = a.image_url;
                        div.appendChild(img);
                    } else {
                        const placeholder = document.createElement("div");
                        placeholder.className = "artist-img";
                        div.appendChild(placeholder);
                    }

                    const infoDiv = document.createElement("div");
                    infoDiv.className = "search-result-info";
                    const nameDiv = document.createElement("div");
                    nameDiv.className = "search-result-name";
                    nameDiv.textContent = a.name;
                    infoDiv.appendChild(nameDiv);
                    const metaDiv = document.createElement("div");
                    metaDiv.className = "search-result-meta";
                    metaDiv.textContent = a.followers > 0 ? `${(a.followers / 1000).toFixed(0)}K followers` : "";
                    infoDiv.appendChild(metaDiv);
                    div.appendChild(infoDiv);

                    div.addEventListener("click", async () => {
                        await API.post("/api/artists", { id: a.id, name: a.name, image_url: a.image_url || "" });
                        searchInput.value = "";
                        searchResults.classList.add("hidden");
                        loadArtists();
                    });
                    searchResults.appendChild(div);
                });
                searchResults.classList.remove("hidden");
            }, 300);
        });
    }

    loadArtists();
}


// ── Insights (insights.html) ────────────────────────────────────

function initInsights() {
    const metricsGrid = document.getElementById("metrics-grid");
    const insightsList = document.getElementById("insights-list");
    const dateText = document.getElementById("date-text");
    const prevBtn = document.getElementById("date-prev");
    const nextBtn = document.getElementById("date-next");
    if (!metricsGrid) return;

    const tz = encodeURIComponent(Intl.DateTimeFormat().resolvedOptions().timeZone);

    let dates = [];
    let currentIdx = -1;

    function updateButtons() {
        if (prevBtn) prevBtn.disabled = currentIdx <= 0;
        if (nextBtn) nextBtn.disabled = currentIdx >= dates.length - 1;
    }

    // ── Shared renderers ──────────────────────────────────────────

    function renderMetrics(container, m) {
        container.innerHTML = `
            <div class="metric-card"><div class="metric-value">${m.songs_played.toLocaleString()}</div><div class="metric-label">Songs</div></div>
            <div class="metric-card"><div class="metric-value">${m.songs_skipped.toLocaleString()}</div><div class="metric-label">Skipped</div></div>
            <div class="metric-card"><div class="metric-value">${m.songs_kept.toLocaleString()}</div><div class="metric-label">Kept</div></div>
            <div class="metric-card"><div class="metric-value">${m.skip_rate.toFixed(0)}%</div><div class="metric-label">Skip Rate</div></div>
            <div class="metric-card"><div class="metric-value">${m.unique_songs.toLocaleString()}</div><div class="metric-label">Unique Songs</div></div>
            <div class="metric-card"><div class="metric-value">${m.unique_artists.toLocaleString()}</div><div class="metric-label">Unique Artists</div></div>
        `;
    }

    function renderDetails(container, m) {
        const mostSkipped = m.most_skipped;
        const mostPlayed = m.most_played;
        const streak = m.longest_skip_streak;
        const avgDays = m.avg_skip_days;
        container.innerHTML = `
            <div class="detail-row">
                <span class="detail-label">Most skipped</span>
                <span class="detail-value">${mostSkipped ? `${escapeHtml(mostSkipped.song)} — ${escapeHtml(mostSkipped.artist)} (${mostSkipped.count}x)` : "—"}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Most played</span>
                <span class="detail-value">${mostPlayed ? `${escapeHtml(mostPlayed.song)} — ${escapeHtml(mostPlayed.artist)} (${mostPlayed.count}x)` : "—"}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Longest skip streak</span>
                <span class="detail-value">${streak > 0 ? `${streak} songs` : "—"}</span>
            </div>
            <div class="detail-row">
                <span class="detail-label">Avg skip age</span>
                <span class="detail-value">${avgDays !== null ? `${avgDays.toFixed(0)} days` : "—"}</span>
            </div>
        `;
    }

    function renderInsightsList(container, insights) {
        container.innerHTML = "";
        (insights || []).forEach(i => {
            const iconChar = i.icon === "warning" ? "\u26a0\ufe0f" : "\u2139\ufe0f";
            container.innerHTML += `
                <div class="insight-item">
                    <div class="insight-icon ${i.icon}">${iconChar}</div>
                    <div class="insight-content">
                        <div class="insight-title">${escapeHtml(i.title)}</div>
                        <div class="insight-detail">${escapeHtml(i.detail)}</div>
                    </div>
                </div>
            `;
        });
    }

    // ── Overall section ───────────────────────────────────────────

    async function loadOverall() {
        const overallMetrics = document.getElementById("overall-metrics-grid");
        const overallDetails = document.getElementById("overall-details-grid");
        const overallRecords = document.getElementById("overall-records-grid");
        const overallInsights = document.getElementById("overall-insights-list");
        if (!overallMetrics) return;

        const data = await API.get(`/api/insights/overall?tz=${tz}`);
        const m = data.metrics;

        if (!m) {
            overallMetrics.innerHTML = '<p class="text-muted text-center">No data yet.</p>';
            if (overallDetails) overallDetails.innerHTML = '<p class="text-muted text-center">—</p>';
            if (overallRecords) overallRecords.innerHTML = '<p class="text-muted text-center">—</p>';
            if (overallInsights) overallInsights.innerHTML = '<p class="text-muted text-center">—</p>';
            return;
        }

        renderMetrics(overallMetrics, m);
        if (overallDetails) renderDetails(overallDetails, m);

        // Records section
        if (overallRecords) {
            const oldest = m.oldest_scrobble;
            const busiest = m.busiest_day;
            const mostSkipsDay = m.most_skips_day;
            const highRate = m.highest_skip_rate_day;
            const longestStreak = m.longest_streak_day;

            overallRecords.innerHTML = `
                <div class="detail-row">
                    <span class="detail-label">Oldest last scrobble</span>
                    <span class="detail-value">${oldest ? `${escapeHtml(oldest.song)} — ${escapeHtml(oldest.artist)} (${oldest.days_ago} days)` : "—"}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Busiest day</span>
                    <span class="detail-value">${busiest && busiest.count > 0 ? `${busiest.date} (${busiest.count} songs)` : "—"}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Most skips in a day</span>
                    <span class="detail-value">${mostSkipsDay && mostSkipsDay.count > 0 ? `${mostSkipsDay.date} (${mostSkipsDay.count} skips)` : "—"}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Highest skip rate</span>
                    <span class="detail-value">${highRate && highRate.rate > 0 ? `${highRate.date} (${highRate.rate.toFixed(0)}%)` : "—"}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Longest streak</span>
                    <span class="detail-value">${longestStreak && longestStreak.streak > 0 ? `${longestStreak.date} (${longestStreak.streak} in a row)` : "—"}</span>
                </div>
            `;
        }

        if (overallInsights) renderInsightsList(overallInsights, data.insights);
    }

    // ── Daily section ─────────────────────────────────────────────

    async function loadDates() {
        const data = await API.get(`/api/insights/dates?tz=${tz}`);
        dates = data.dates || [];
        if (dates.length > 0) {
            currentIdx = dates.length - 1;
            loadDailyInsights(dates[currentIdx]);
        } else {
            dateText.textContent = "No data yet";
            metricsGrid.innerHTML = '<p class="text-muted text-center">No data yet.</p>';
            insightsList.innerHTML = '<p class="text-muted text-center">—</p>';
            const dg = document.getElementById("details-grid");
            if (dg) dg.innerHTML = '<p class="text-muted text-center">—</p>';
        }
        updateButtons();
    }

    async function loadDailyInsights(date) {
        dateText.textContent = date;
        const data = await API.get(`/api/insights?date=${date}&tz=${tz}`);
        const m = data.metrics;

        renderMetrics(metricsGrid, m);

        const detailsGrid = document.getElementById("details-grid");
        if (detailsGrid) renderDetails(detailsGrid, m);

        renderInsightsList(insightsList, data.insights);
    }

    if (prevBtn) prevBtn.addEventListener("click", () => {
        if (currentIdx > 0) { currentIdx--; loadDailyInsights(dates[currentIdx]); updateButtons(); }
    });
    if (nextBtn) nextBtn.addEventListener("click", () => {
        if (currentIdx < dates.length - 1) { currentIdx++; loadDailyInsights(dates[currentIdx]); updateButtons(); }
    });

    // ── Mapping issues ────────────────────────────────────────────

    async function loadMappingFails() {
        const container = document.getElementById("mapping-fails-list");
        if (!container) return;

        try {
            const data = await API.get("/api/insights/mapping-fails");
            const candidates = data.candidates || [];
            const windowDays = data.skip_window_days;

            if (candidates.length === 0) {
                container.innerHTML = `<p class="text-muted text-center">No mapping issues detected in the last ${windowDays} days.</p>`;
                return;
            }

            const fmtLastSeen = (ts) => {
                if (!ts) return "";
                const d = new Date(ts.endsWith("Z") ? ts : ts + "Z");
                const pad = (n) => String(n).padStart(2, "0");
                return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
            };

            const renderDefaultActions = (actions, artist, track) => {
                actions.innerHTML = `
                    <button class="btn btn-sm mapping-fail-alias">Add alias</button>
                    <button class="btn btn-sm mapping-fail-dismiss">Dismiss</button>
                `;
                actions.querySelector(".mapping-fail-alias").addEventListener("click", () => startAliasEdit(actions, artist, track));
                actions.querySelector(".mapping-fail-dismiss").addEventListener("click", () => doDismiss(actions, artist, track));
            };

            const doDismiss = async (actions, artist, track) => {
                actions.querySelectorAll("button").forEach(b => b.disabled = true);
                try {
                    await API.post("/api/insights/mapping-fails/dismiss", { artist, track });
                    showToast(`Dismissed "${track}"`);
                    loadMappingFails();
                } catch (e) {
                    actions.querySelectorAll("button").forEach(b => b.disabled = false);
                    showToast(`Dismiss failed: ${e.message}`, 3000, "error");
                }
            };

            const startAliasEdit = (actions, artist, spotifyName) => {
                actions.innerHTML = `
                    <input class="mapping-fail-alias-input" type="text" value="${escapeHtml(spotifyName)}">
                    <button class="btn btn-sm mapping-fail-alias-save">Save</button>
                    <button class="btn btn-sm mapping-fail-alias-cancel">Cancel</button>
                `;
                const input = actions.querySelector(".mapping-fail-alias-input");
                const saveBtn = actions.querySelector(".mapping-fail-alias-save");
                const cancelBtn = actions.querySelector(".mapping-fail-alias-cancel");

                input.focus();
                input.select();

                const save = async () => {
                    const trimmed = input.value.trim();
                    if (!trimmed) { input.focus(); return; }
                    input.disabled = true;
                    saveBtn.disabled = true;
                    cancelBtn.disabled = true;
                    try {
                        await API.post("/api/insights/track-aliases", {
                            artist,
                            spotify_name: spotifyName,
                            lastfm_name: trimmed,
                        });
                        await API.post("/api/insights/mapping-fails/dismiss", {
                            artist,
                            track: spotifyName,
                        });
                        showToast(`Alias saved: "${spotifyName}" → "${trimmed}"`);
                        loadMappingFails();
                    } catch (e) {
                        input.disabled = false;
                        saveBtn.disabled = false;
                        cancelBtn.disabled = false;
                        showToast(`Add alias failed: ${e.message}`, 3000, "error");
                    }
                };

                const cancel = () => renderDefaultActions(actions, artist, spotifyName);

                saveBtn.addEventListener("click", save);
                cancelBtn.addEventListener("click", cancel);
                input.addEventListener("keydown", (e) => {
                    if (e.key === "Enter") { e.preventDefault(); save(); }
                    else if (e.key === "Escape") { e.preventDefault(); cancel(); }
                });
            };

            container.innerHTML = candidates.map(c => {
                const breakdown = [];
                if (c.no_scrobble_count > 0) breakdown.push(`${c.no_scrobble_count} no-scrobble`);
                if (c.played_count > 0) breakdown.push(`${c.played_count} stale scrobble`);
                const lastSeen = fmtLastSeen(c.last_seen);
                return `
                    <div class="mapping-fail-row" data-artist="${escapeHtml(c.artist_name)}" data-track="${escapeHtml(c.track_name)}">
                        <div class="mapping-fail-title">${escapeHtml(c.track_name)} — ${escapeHtml(c.artist_name)}</div>
                        <div class="mapping-fail-meta">
                            <span class="text-muted">${lastSeen}</span>
                            <span class="text-muted">${c.total_count}x (${breakdown.join(", ")})</span>
                            <div class="mapping-fail-actions"></div>
                        </div>
                    </div>
                `;
            }).join("");

            container.querySelectorAll(".mapping-fail-row").forEach(row => {
                const actions = row.querySelector(".mapping-fail-actions");
                renderDefaultActions(actions, row.dataset.artist, row.dataset.track);
            });
        } catch (e) {
            container.innerHTML = `<p class="text-muted text-center">Failed to load: ${escapeHtml(e.message)}</p>`;
        }
    }

    loadOverall();
    loadDates();
    loadMappingFails();
}


// ── Logs (logs.html) ────────────────────────────────────────────

function initLogs() {
    const logsContainer = document.getElementById("logs-container");
    const datePicker = document.getElementById("log-date-picker");
    if (!logsContainer) return;

    let currentLevel = "all";
    const LOG_PAGE_SIZE = 200;
    let hasMore = false;
    let oldestLoadedId = null;
    let allLogs = [];
    let searchMode = false;
    const searchInput = document.getElementById("log-search");
    const searchBtn = document.getElementById("log-search-btn");

    function init() {
        loadLogs();
    }

    function utcToLocal(ts) {
        if (!ts) return "";
        const d = new Date(ts.endsWith("Z") ? ts : ts + "Z");
        return d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false});
    }

    function buildLogEntryHTML(log) {
        const ts = utcToLocal(log.timestamp);
        const levelClass = `log-level-${log.level}`;
        return `<div class="log-entry"><span class="log-time">${ts}</span><span class="${levelClass}">${escapeHtml(log.message)}</span></div>`;
    }

    function renderLoadMoreBtn() {
        // Remove existing button if any
        const existing = logsContainer.querySelector(".load-more-btn");
        if (existing) existing.remove();

        if (hasMore) {
            const btn = document.createElement("button");
            btn.className = "btn btn-sm load-more-btn";
            btn.textContent = "Load older logs";
            btn.style.cssText = "display:block;margin:8px auto";
            btn.addEventListener("click", loadOlder);
            logsContainer.prepend(btn);
        }
    }

    function groupIntoBlocks(logs) {
        const blocks = [];
        let current = null;
        for (const log of logs) {
            if (log.message.startsWith("Currently playing:")) {
                if (current) blocks.push(current);
                current = { entries: [log], outcome: null };
            } else if (current) {
                current.entries.push(log);
                const msg = log.message;
                if (msg.includes("\u2014 skipping") && !msg.includes("not skipping")) {
                    current.outcome = "skipped";
                } else if (msg.includes("not skipping") || msg.includes("never-skip")) {
                    current.outcome = "kept";
                }
            }
        }
        if (current) blocks.push(current);
        return blocks;
    }

    function buildQueryParams(extraLimit, beforeId) {
        const date = datePicker ? datePicker.value : "";
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        let params = `level=${currentLevel}&tz=${encodeURIComponent(tz)}`;
        if (date) params += `&date=${date}`;
        if (extraLimit) params += `&limit=${extraLimit}`;
        if (beforeId) params += `&before_id=${beforeId}`;
        return params;
    }

    function renderFilteredBlocks(blocks) {
        logsContainer.innerHTML = "";
        if (blocks.length === 0) {
            logsContainer.innerHTML = '<p class="text-muted text-center mt-16">No matching entries.</p>';
            return;
        }
        const html = blocks.map((block, i) => {
            let out = block.entries.map(buildLogEntryHTML).join("");
            if (i < blocks.length - 1) out += '<div class="log-separator"></div>';
            return out;
        }).join("");
        logsContainer.innerHTML = html;
    }

    function renderAll() {
        const isBlockFilter = currentLevel === "skipped" || currentLevel === "kept";

        if (allLogs.length === 0) {
            logsContainer.innerHTML = '<p class="text-muted text-center mt-16">No log entries.</p>';
            renderLoadMoreBtn();
            return;
        }

        if (isBlockFilter) {
            let blocks = groupIntoBlocks(allLogs);
            blocks = blocks.filter(b => b.outcome === currentLevel);
            renderFilteredBlocks(blocks);
        } else {
            logsContainer.innerHTML = allLogs.map(buildLogEntryHTML).join("");
        }
        renderLoadMoreBtn();
    }

    async function loadLogs() {
        const params = buildQueryParams(LOG_PAGE_SIZE, 0);
        const data = await API.get(`/api/logs?${params}`);

        if (!data.logs || data.logs.length === 0) {
            allLogs = [];
            hasMore = false;
            oldestLoadedId = null;
            renderAll();
            return;
        }

        hasMore = data.has_more || false;
        oldestLoadedId = data.logs[0].id;
        allLogs = data.logs;
        renderAll();
        logsContainer.scrollTop = logsContainer.scrollHeight;
    }

    async function loadOlder() {
        if (!oldestLoadedId) return;
        const params = buildQueryParams(LOG_PAGE_SIZE, oldestLoadedId);
        const data = await API.get(`/api/logs?${params}`);

        if (!data.logs || data.logs.length === 0) {
            hasMore = false;
            renderLoadMoreBtn();
            return;
        }

        hasMore = data.has_more || false;
        oldestLoadedId = data.logs[0].id;

        const prevHeight = logsContainer.scrollHeight;
        allLogs = [...data.logs, ...allLogs];
        renderAll();
        logsContainer.scrollTop = logsContainer.scrollHeight - prevHeight;
    }

    async function doSearch() {
        const query = (searchInput ? searchInput.value : "").trim();
        if (!query) {
            searchMode = false;
            loadLogs();
            return;
        }
        searchMode = true;
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        const date = datePicker ? datePicker.value : "";
        let params = `q=${encodeURIComponent(query)}&tz=${encodeURIComponent(tz)}`;
        if (date) params += `&date=${date}`;
        logsContainer.innerHTML = '<p class="text-muted text-center">Searching...</p>';
        const data = await API.get(`/api/logs/search?${params}`);
        hasMore = false;
        allLogs = data.logs || [];
        const blocks = groupIntoBlocks(allLogs);
        renderFilteredBlocks(blocks);
        logsContainer.scrollTop = logsContainer.scrollHeight;
    }

    if (searchBtn) searchBtn.addEventListener("click", doSearch);
    if (searchInput) searchInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") doSearch();
    });

    // Date picker — reload on date change
    if (datePicker) {
        datePicker.addEventListener("change", () => loadLogs());
    }

    // Level filter chips
    document.querySelectorAll("[data-level]").forEach(chip => {
        chip.addEventListener("click", () => {
            document.querySelectorAll("[data-level]").forEach(c => c.classList.remove("active"));
            chip.classList.add("active");
            currentLevel = chip.dataset.level;
            loadLogs();
        });
    });

    init();

    // Copy to clipboard
    const copyBtn = document.getElementById("copy-logs-btn");
    if (copyBtn) {
        copyBtn.addEventListener("click", () => {
            const entries = logsContainer.querySelectorAll(".log-entry");
            const text = Array.from(entries).map(e => e.textContent.trim()).join("\n");
            navigator.clipboard.writeText(text).then(() => showToast("Copied to clipboard"));
        });
    }

    // Auto-refresh every 5 seconds (only when no date/search is active = live today view)
    setInterval(() => {
        if (!searchMode && currentLevel === "all" && (!datePicker || !datePicker.value)) {
            loadLogs();
        }
    }, 5000);
}


// ── Utilities ───────────────────────────────────────────────────

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}


// ── Init on page load ───────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    initDashboard();
    initSettings();
    initArtists();
    initInsights();
    initLogs();
});
