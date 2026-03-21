/**
 * API client wrapper for the Spotify Auto-Skipper cloud API.
 */

const API = {
    async get(url) {
        const r = await fetch(url);
        return r.json();
    },

    async post(url, body = null) {
        const opts = { method: "POST", headers: { "Content-Type": "application/json" } };
        if (body) opts.body = JSON.stringify(body);
        const r = await fetch(url, opts);
        return r.json();
    },

    async put(url, body) {
        const r = await fetch(url, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        return r.json();
    },

    async del(url) {
        const r = await fetch(url, { method: "DELETE" });
        return r.json();
    },
};
