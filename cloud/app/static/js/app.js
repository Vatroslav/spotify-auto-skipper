/**
 * Dashboard interactivity — polling, button handlers, page logic.
 */

// ── Toast notification ──────────────────────────────────────────

function showToast(message, duration = 2000) {
    let toast = document.getElementById("toast");
    if (!toast) {
        toast = document.createElement("div");
        toast.id = "toast";
        toast.className = "toast";
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add("show");
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
        await API.put("/api/settings", updates);
        showToast("Settings saved!");
    });

    loadSettings();
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
            await API.put("/api/settings", { enable_never_skip_artists: toggleNeverSkip.checked });
            showToast(toggleNeverSkip.checked ? "Never-skip enabled" : "Never-skip disabled");
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
            const imgHtml = a.image_url
                ? `<img src="${a.image_url}" class="artist-img" alt="">`
                : '<div class="artist-img artist-img-placeholder"></div>';
            div.innerHTML = `
                <div class="artist-info">
                    ${imgHtml}
                    <span class="artist-name-text">${escapeHtml(a.name)}</span>
                </div>
                <button class="artist-remove" data-id="${a.id}" title="Remove">&times;</button>
            `;
            list.appendChild(div);
        });
        // Bind remove buttons
        list.querySelectorAll(".artist-remove").forEach(btn => {
            btn.addEventListener("click", async () => {
                await API.del(`/api/artists/${btn.dataset.id}`);
                loadArtists();
            });
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
                    const imgHtml = a.image_url
                        ? `<img src="${a.image_url}" class="artist-img" alt="">`
                        : '<div class="artist-img"></div>';
                    const followers = a.followers > 0 ? `${(a.followers / 1000).toFixed(0)}K followers` : "";
                    div.innerHTML = `
                        ${imgHtml}
                        <div class="search-result-info">
                            <div class="search-result-name">${escapeHtml(a.name)}</div>
                            <div class="search-result-meta">${followers}</div>
                        </div>
                    `;
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
            dateText.textContent = "No data";
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
                    <span class="detail-value">${mostSkipped ? `${escapeHtml(mostSkipped[0][1])} — ${escapeHtml(mostSkipped[0][0])} (${mostSkipped[1]}x)` : "—"}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">Most played</span>
                    <span class="detail-value">${mostPlayed ? `${escapeHtml(mostPlayed[0][1])} — ${escapeHtml(mostPlayed[0][0])} (${mostPlayed[1]}x)` : "—"}</span>
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
    const dateText = document.getElementById("log-date-text");
    const prevBtn = document.getElementById("log-date-prev");
    const nextBtn = document.getElementById("log-date-next");
    if (!logsContainer) return;

    let dates = [];
    let currentIdx = -1;
    let currentLevel = "all";

    async function loadDates() {
        const data = await API.get("/api/logs/dates");
        dates = data.dates || [];
        if (dates.length > 0) {
            currentIdx = dates.length - 1;
            loadLogs(dates[currentIdx]);
        } else {
            dateText.textContent = "No data";
        }
    }

    async function loadLogs(date) {
        dateText.textContent = date;
        const data = await API.get(`/api/logs?date=${date}&level=${currentLevel}`);
        logsContainer.innerHTML = "";
        if (!data.logs || data.logs.length === 0) {
            logsContainer.innerHTML = '<p class="text-muted text-center mt-16">No log entries.</p>';
            return;
        }
        data.logs.forEach(log => {
            const ts = log.timestamp ? log.timestamp.substring(11, 19) : "";
            const levelClass = `log-level-${log.level}`;
            logsContainer.innerHTML += `
                <div class="log-entry">
                    <span class="log-time">${ts}</span>
                    <span class="${levelClass}">${escapeHtml(log.message)}</span>
                </div>
            `;
        });
    }

    // Date navigation
    if (prevBtn) prevBtn.addEventListener("click", () => {
        if (currentIdx > 0) { currentIdx--; loadLogs(dates[currentIdx]); }
    });
    if (nextBtn) nextBtn.addEventListener("click", () => {
        if (currentIdx < dates.length - 1) { currentIdx++; loadLogs(dates[currentIdx]); }
    });

    // Level filter chips
    document.querySelectorAll("[data-level]").forEach(chip => {
        chip.addEventListener("click", () => {
            document.querySelectorAll("[data-level]").forEach(c => c.classList.remove("active"));
            chip.classList.add("active");
            currentLevel = chip.dataset.level;
            if (dates.length > 0) loadLogs(dates[currentIdx]);
        });
    });

    loadDates();

    // Auto-refresh every 5 seconds
    setInterval(() => {
        if (dates.length > 0 && currentIdx === dates.length - 1) {
            loadLogs(dates[currentIdx]);
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
