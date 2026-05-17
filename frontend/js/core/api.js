export async function api(endpoint, method = 'GET', body = null) {
    const options = {method};
    if (body) {
        if (body instanceof FormData) {
            options.body = body;
        } else {
            options.headers = {'Content-Type': 'application/json'};
            options.body = JSON.stringify(body);
        }
    }
    const res = await fetch(`/api${endpoint}`, options);
    if (!res.ok) {
        let msg = await res.text();
        throw new Error(msg);
    }
    return res.json();
}
