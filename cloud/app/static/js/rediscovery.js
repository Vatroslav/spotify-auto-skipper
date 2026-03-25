// Rediscovery — skeleton (Stage 2: dropdown only)

(async function () {
    const select = document.getElementById('playlist-select');
    const nameInput = document.getElementById('playlist-name');
    const startBtn = document.getElementById('start-btn');

    // Load playlists into dropdown
    try {
        const r = await fetch('/api/rediscovery/playlists');
        if (!r.ok) throw new Error('Failed to load playlists');
        const data = await r.json();
        const playlists = data.playlists || [];

        select.innerHTML = '<option value="">Select a playlist...</option>';
        for (const p of playlists) {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = `${p.name} (${p.track_count} tracks)`;
            select.appendChild(opt);
        }
    } catch (e) {
        select.innerHTML = '<option value="">Error loading playlists</option>';
    }

    // Update default name and enable button on selection
    select.addEventListener('change', function () {
        const selected = select.options[select.selectedIndex];
        if (select.value) {
            nameInput.placeholder = `Rediscovery - ${selected.textContent.replace(/ \(\d+ tracks\)$/, '')}`;
            startBtn.disabled = false;
        } else {
            nameInput.placeholder = 'Rediscovery - ...';
            startBtn.disabled = true;
        }
    });
})();
