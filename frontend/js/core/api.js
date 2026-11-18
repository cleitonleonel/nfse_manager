const SERVER_URL_STORAGE_KEY = 'nfse_server_url';

export function getApiBaseUrl() {
    const raw = localStorage.getItem(SERVER_URL_STORAGE_KEY);
    return raw ? raw.trim().replace(/\/+$/, '') : '';
}

export function setApiBaseUrl(url) {
    const normalized = String(url || '').trim().replace(/\/+$/, '');
    if (normalized) {
        localStorage.setItem(SERVER_URL_STORAGE_KEY, normalized);
    } else {
        localStorage.removeItem(SERVER_URL_STORAGE_KEY);
    }
    return normalized;
}

export async function api(endpoint, method = 'GET', body = null) {
    const headers = {};
    const token = localStorage.getItem('nfse_token');
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    const options = { method, headers };
    if (body) {
        if (body instanceof FormData) {
            options.body = body;
        } else {
            headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(body);
        }
    }
    const res = await fetch(`${getApiBaseUrl()}/api${endpoint}`, options);
    if (!res.ok) {
        if (res.status === 401 && !endpoint.startsWith('/auth/login') && !endpoint.startsWith('/auth/register')) {
            if (window.App && window.App.logout) {
                window.App.logout(true);
            }
        }
        let msg = await res.text();
        try {
            const parsed = JSON.parse(msg);
            if (parsed && parsed.detail) msg = parsed.detail;
        } catch (_) {}
        throw new Error(msg);
    }
    return res.json();
}
