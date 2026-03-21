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
            } else {
                statusBadge.textContent = "Skipping Active";
                statusBadge.className = "status-badge active";
            }

            // Pause button text
            if (pauseBtn) {
                pauseBtn.textContent = data.skipping_paused ? "Resume Skipping" : "Pause Skipping";
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

    let dates = [];
    let currentIdx = -1;

    async function loadDates() {
        const data = await API.get("/api/insights/dates");
        dates = data.dates || [];
        if (dates.length > 0) {
            currentIdx = dates.length - 1; // Latest date
            loadInsights(dates[currentIdx]);
        } else {
            dateText.textContent = "No data yet";
            metricsGrid.innerHTML = '<p class="text-muted text-center">Start playing music and the skipper will track activity here.</p>';
            insightsList.innerHTML = "";
            const dg = document.getElementById("details-grid");
            if (dg) dg.innerHTML = "";
        }
    }

    async function loadInsights(date) {
        dateText.textContent = date;
        const data = await API.get(`/api/insights?date=${date}`);
        const m = data.metrics;

        metricsGrid.innerHTML = `
            <div class="metric-card"><div class="metric-value">${m.songs_played}</div><div class="metric-label">Songs</div></div>
            <div class="metric-card"><div class="metric-value">${m.songs_skipped}</div><div class="metric-label">Skipped</div></div>
            <div class="metric-card"><div class="metric-value">${m.songs_kept}</div><div class="metric-label">Kept</div></div>
            <div class="metric-card"><div class="metric-value">${m.skip_rate.toFixed(0)}%</div><div class="metric-label">Skip Rate</div></div>
            <div class="metric-card"><div class="metric-value">${m.unique_songs}</div><div class="metric-label">Unique Songs</div></div>
            <div class="metric-card"><div class="metric-value">${m.unique_artists}</div><div class="metric-label">Unique Artists</div></div>
        `;

        // Details section
        const detailsGrid = document.getElementById("details-grid");
        if (detailsGrid) {
            const mostSkipped = m.most_skipped;
            const mostPlayed = m.most_played;
            const streak = m.longest_skip_streak;
            const avgDays = m.avg_skip_days;

            detailsGrid.innerHTML = `
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

        insightsList.innerHTML = "";
        (data.insights || []).forEach(i => {
            const iconChar = i.icon === "warning" ? "\u26a0\ufe0f" : "\u2139\ufe0f";
            insightsList.innerHTML += `
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

    if (prevBtn) prevBtn.addEventListener("click", () => {
        if (currentIdx > 0) { currentIdx--; loadInsights(dates[currentIdx]); }
    });
    if (nextBtn) nextBtn.addEventListener("click", () => {
        if (currentIdx < dates.length - 1) { currentIdx++; loadInsights(dates[currentIdx]); }
    });

    loadDates();
}


// ── Logs (logs.html) ────────────────────────────────────────────

function initLogs() {
    const logsContainer = document.getElementById("logs-container");
    const datePicker = document.getElementById("log-date-picker");
    if (!logsContainer) return;

    let currentLevel = "all";

    function init() {
        loadLogs();
    }

    function utcToLocal(ts) {
        if (!ts) return "";
        // SQLite CURRENT_TIMESTAMP is UTC but lacks a Z suffix — add it
        const d = new Date(ts.endsWith("Z") ? ts : ts + "Z");
        return d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false});
    }

    function renderLogEntries(logs) {
        logsContainer.innerHTML = "";
        if (!logs || logs.length === 0) {
            logsContainer.innerHTML = '<p class="text-muted text-center mt-16">No log entries.</p>';
            return;
        }
        logs.forEach(log => {
            const ts = utcToLocal(log.timestamp);
            const levelClass = `log-level-${log.level}`;
            logsContainer.innerHTML += `
                <div class="log-entry">
                    <span class="log-time">${ts}</span>
                    <span class="${levelClass}">${escapeHtml(log.message)}</span>
                </div>
            `;
        });
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

    async function loadLogs() {
        const date = datePicker ? datePicker.value : "";
        const dateParam = date ? `&date=${date}` : "";
        const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        const tzParam = `&tz=${encodeURIComponent(tz)}`;
        const data = await API.get(`/api/logs?level=${currentLevel}${dateParam}${tzParam}`);
        if (!data.logs || data.logs.length === 0) {
            logsContainer.innerHTML = '<p class="text-muted text-center mt-16">No log entries.</p>';
            return;
        }

        if (currentLevel === "skipped" || currentLevel === "kept") {
            const blocks = groupIntoBlocks(data.logs);
            const filtered = blocks.filter(b => b.outcome === currentLevel);
            const flatLogs = filtered.flatMap(b => b.entries);
            // Add separators between blocks
            logsContainer.innerHTML = "";
            if (filtered.length === 0) {
                logsContainer.innerHTML = '<p class="text-muted text-center mt-16">No matching entries.</p>';
                return;
            }
            filtered.forEach((block, i) => {
                block.entries.forEach(log => {
                    const ts = utcToLocal(log.timestamp);
                    const levelClass = `log-level-${log.level}`;
                    logsContainer.innerHTML += `
                        <div class="log-entry">
                            <span class="log-time">${ts}</span>
                            <span class="${levelClass}">${escapeHtml(log.message)}</span>
                        </div>
                    `;
                });
                if (i < filtered.length - 1) {
                    logsContainer.innerHTML += '<div class="log-separator"></div>';
                }
            });
        } else {
            renderLogEntries(data.logs);
        }
        applySearch();
        // Auto-scroll to bottom
        logsContainer.scrollTop = logsContainer.scrollHeight;
    }

    // Search filter — hides non-matching entries in the DOM
    const searchInput = document.getElementById("log-search");
    function applySearch() {
        const query = (searchInput ? searchInput.value : "").toLowerCase();
        logsContainer.querySelectorAll(".log-entry").forEach(el => {
            el.style.display = el.textContent.toLowerCase().includes(query) ? "" : "none";
        });
        logsContainer.querySelectorAll(".log-separator").forEach(el => {
            el.style.display = query ? "none" : "";
        });
    }
    if (searchInput) searchInput.addEventListener("input", applySearch);

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

    // Auto-refresh every 5 seconds (only when no date is selected = today)
    setInterval(() => {
        if (!datePicker || !datePicker.value) {
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
