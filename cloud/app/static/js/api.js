/**
 * API client wrapper for the Spotify Auto-Skipper cloud API.
 */

class ApiError extends Error {
    constructor(status, body) {
        super(body.detail || body.error || `HTTP ${status}`);
        this.status = status;
        this.body = body;
    }
}

async function _handleResponse(r) {
    let body;
    try {
        body = await r.json();
    } catch {
        if (!r.ok) throw new ApiError(r.status, { detail: r.statusText });
        return {};
    }
    if (!r.ok) throw new ApiError(r.status, body);
    return body;
}

const API = {
    async get(url) {
        const r = await fetch(url);
        return _handleResponse(r);
    },

    async post(url, body = null) {
        const opts = { method: "POST", headers: { "Content-Type": "application/json" } };
        if (body) opts.body = JSON.stringify(body);
        const r = await fetch(url, opts);
        return _handleResponse(r);
    },

    async put(url, body) {
        const r = await fetch(url, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        return _handleResponse(r);
    },

    async patch(url, body) {
        const r = await fetch(url, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        return _handleResponse(r);
    },

    async del(url) {
        const r = await fetch(url, { method: "DELETE" });
        return _handleResponse(r);
    },
};
