import { getApiBaseUrl } from './api.js';

const DB_NAME = 'nfse_local_mirror_db';
const STORE_NAME = 'handles';
const AUTO_MIRROR_STORAGE_KEY = 'nfse_local_mirror_auto';

function getCurrentUserKey() {
    try {
        const raw = localStorage.getItem('nfse_user');
        const user = raw ? JSON.parse(raw) : null;
        if (user && user.username) {
            return `mirror_${String(user.username).trim().toLowerCase()}`;
        }
    } catch (_) {}
    return 'mirror_default';
}

export function supportsLocalDirectoryMirror() {
    return typeof window !== 'undefined' && typeof window.showDirectoryPicker === 'function';
}

export function isAutoMirrorEnabled() {
    try {
        return localStorage.getItem(`${AUTO_MIRROR_STORAGE_KEY}_${getCurrentUserKey()}`) === '1';
    } catch (_) {
        return false;
    }
}

export function setAutoMirrorEnabled(enabled) {
    try {
        localStorage.setItem(`${AUTO_MIRROR_STORAGE_KEY}_${getCurrentUserKey()}`, enabled ? '1' : '0');
    } catch (_) {}
    return Boolean(enabled);
}

function openMirrorDb() {
    return new Promise((resolve, reject) => {
        if (typeof indexedDB === 'undefined') {
            reject(new Error('IndexedDB indisponível neste navegador.'));
            return;
        }
        const req = indexedDB.open(DB_NAME, 1);
        req.onupgradeneeded = () => {
            const db = req.result;
            if (!db.objectStoreNames.contains(STORE_NAME)) {
                db.createObjectStore(STORE_NAME);
            }
        };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error || new Error('Erro ao abrir IndexedDB.'));
    });
}

async function readSavedHandle() {
    try {
        const db = await openMirrorDb();
        return await new Promise((resolve) => {
            const tx = db.transaction(STORE_NAME, 'readonly');
            const store = tx.objectStore(STORE_NAME);
            const req = store.get(getCurrentUserKey());
            req.onsuccess = () => resolve(req.result || null);
            req.onerror = () => resolve(null);
            tx.oncomplete = () => db.close();
        });
    } catch (_) {
        return null;
    }
}

async function saveHandle(handle) {
    const db = await openMirrorDb();
    return await new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        const store = tx.objectStore(STORE_NAME);
        const req = store.put(handle, getCurrentUserKey());
        req.onsuccess = () => resolve();
        req.onerror = () => reject(req.error || new Error('Erro ao salvar pasta local.'));
        tx.oncomplete = () => db.close();
    });
}

async function removeSavedHandle() {
    try {
        const db = await openMirrorDb();
        await new Promise((resolve) => {
            const tx = db.transaction(STORE_NAME, 'readwrite');
            tx.objectStore(STORE_NAME).delete(getCurrentUserKey());
            tx.oncomplete = () => {
                db.close();
                resolve();
            };
            tx.onerror = () => {
                db.close();
                resolve();
            };
        });
    } catch (_) {}
}

export async function getLocalMirrorState() {
    const supported = supportsLocalDirectoryMirror();
    const handle = supported ? await readSavedHandle() : null;
    let permission = 'denied';
    if (handle && typeof handle.queryPermission === 'function') {
        try {
            permission = await handle.queryPermission({ mode: 'readwrite' });
        } catch (_) {
            permission = 'prompt';
        }
    }
    return {
        supported,
        configured: Boolean(handle),
        folderName: handle?.name || '',
        permission,
        autoMirror: isAutoMirrorEnabled(),
    };
}

export async function chooseLocalMirrorDirectory() {
    if (!supportsLocalDirectoryMirror()) {
        const err = new Error(
            'Seu navegador não permite gravação direta em pasta local (File System Access API). Utilize Google Chrome ou Microsoft Edge em HTTPS/localhost, ou use o Download em Lote (.zip).'
        );
        err.code = 'UNSUPPORTED_BROWSER';
        throw err;
    }
    const handle = await window.showDirectoryPicker({
        id: 'nfse-local-mirror',
        mode: 'readwrite',
    });
    await saveHandle(handle);
    return await getLocalMirrorState();
}

export async function clearLocalMirrorDirectory() {
    await removeSavedHandle();
    setAutoMirrorEnabled(false);
    return await getLocalMirrorState();
}

async function ensureWritePermission(handle, interactive = false) {
    if (!handle || typeof handle.queryPermission !== 'function') return false;
    try {
        let perm = await handle.queryPermission({ mode: 'readwrite' });
        if (perm === 'granted') return true;
        if (interactive && typeof handle.requestPermission === 'function') {
            perm = await handle.requestPermission({ mode: 'readwrite' });
            return perm === 'granted';
        }
    } catch (_) {}
    return false;
}

function sanitizePathSegment(seg) {
    return String(seg || '')
        .replace(/[<>:"|?*\x00-\x1f]/g, '_')
        .trim();
}

function buildLocalRelativeSegments(rawPath, invoice = null) {
    const normalized = String(rawPath || '').replace(/\\/g, '/').trim();
    if (!normalized || normalized === 'null') return [];

    let segments = normalized.split('/').filter((s) => s && s !== '.' && s !== '..');
    const dlIdx = segments.findIndex((s) => s.toLowerCase() === 'downloads');
    if (dlIdx >= 0 && dlIdx < segments.length - 1) {
        segments = segments.slice(dlIdx + 1);
    } else if (/^[a-zA-Z]:$/.test(segments[0] || '') || normalized.startsWith('/')) {
        // Caminho absoluto legado sem âncora "downloads": usa tipo/ano/mes/arquivo
        const filename = segments[segments.length - 1];
        const tipo = String(invoice?.tipo || 'notas').trim();
        const dt = invoice?.data_emissao ? new Date(invoice.data_emissao) : null;
        if (dt && !Number.isNaN(dt.getTime())) {
            const ano = String(dt.getFullYear());
            const mes = String(dt.getMonth() + 1).padStart(2, '0');
            return [tipo, ano, mes, filename].map(sanitizePathSegment).filter(Boolean);
        }
        return [tipo, filename].map(sanitizePathSegment).filter(Boolean);
    }

    return segments.map(sanitizePathSegment).filter(Boolean);
}

async function resolveSubdirHandle(rootHandle, dirSegments) {
    let curr = rootHandle;
    for (const seg of dirSegments) {
        curr = await curr.getDirectoryHandle(seg, { create: true });
    }
    return curr;
}

async function localFileAlreadyExists(dirHandle, filename) {
    try {
        const fh = await dirHandle.getFileHandle(filename, { create: false });
        const file = await fh.getFile();
        return Boolean(file && file.size > 0);
    } catch (_) {
        return false;
    }
}

export async function mirrorInvoicesToLocalDir(invoices, options = {}) {
    const interactive = Boolean(options.interactive);
    const overwrite = Boolean(options.overwrite);
    const onProgress = typeof options.onProgress === 'function' ? options.onProgress : null;

    if (!supportsLocalDirectoryMirror()) {
        return { skipped: true, reason: 'unsupported' };
    }

    const handle = await readSavedHandle();
    if (!handle) {
        return { skipped: true, reason: 'not_configured' };
    }

    const granted = await ensureWritePermission(handle, interactive);
    if (!granted) {
        return { skipped: true, reason: 'permission_required', folderName: handle.name || '' };
    }

    const queue = [];
    const seenPaths = new Set();
    for (const inv of invoices || []) {
        for (const field of ['xml_path', 'pdf_path']) {
            const raw = inv?.[field];
            if (!raw || raw === 'null' || seenPaths.has(raw)) continue;
            const segments = buildLocalRelativeSegments(raw, inv);
            if (segments.length === 0) continue;
            seenPaths.add(raw);
            queue.push({ raw, segments });
        }
    }

    if (queue.length === 0) {
        return { written: 0, existing: 0, failed: 0, total: 0, folderName: handle.name || '' };
    }

    const token = localStorage.getItem('nfse_token');
    const headers = token ? { Authorization: `Bearer ${token}` } : {};

    let written = 0;
    let existing = 0;
    let failed = 0;

    for (let idx = 0; idx < queue.length; idx++) {
        const item = queue[idx];
        const dirSegments = item.segments.slice(0, -1);
        const filename = item.segments[item.segments.length - 1];

        try {
            const targetDir = await resolveSubdirHandle(handle, dirSegments);
            if (!overwrite && (await localFileAlreadyExists(targetDir, filename))) {
                existing += 1;
            } else {
                const url = `${getApiBaseUrl()}/api/download/file?path=${encodeURIComponent(item.raw)}`;
                const res = await fetch(url, { headers });
                if (!res.ok) {
                    failed += 1;
                } else {
                    const blob = await res.blob();
                    const fh = await targetDir.getFileHandle(filename, { create: true });
                    const writable = await fh.createWritable();
                    await writable.write(blob);
                    await writable.close();
                    written += 1;
                }
            }
        } catch (err) {
            console.warn('Falha ao espelhar arquivo localmente:', item.raw, err);
            failed += 1;
        }

        if (onProgress) {
            const pct = Math.round(((idx + 1) / queue.length) * 100);
            onProgress({ current: idx + 1, total: queue.length, pct, written, existing, failed });
        }
    }

    return {
        skipped: false,
        written,
        existing,
        failed,
        total: queue.length,
        folderName: handle.name || '',
    };
}
