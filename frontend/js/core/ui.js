export function formatCnpj(val) {
    const clean = String(val || '').toUpperCase().replace(/[^0-9A-Z]/g, '').slice(0, 14);
    if (clean.length <= 2) return clean;
    if (clean.length <= 5) return `${clean.slice(0, 2)}.${clean.slice(2)}`;
    if (clean.length <= 8) return `${clean.slice(0, 2)}.${clean.slice(2, 5)}.${clean.slice(5)}`;
    if (clean.length <= 12) return `${clean.slice(0, 2)}.${clean.slice(2, 5)}.${clean.slice(5, 8)}/${clean.slice(8)}`;
    return `${clean.slice(0, 2)}.${clean.slice(2, 5)}.${clean.slice(5, 8)}/${clean.slice(8, 12)}-${clean.slice(12, 14)}`;
}

export function formatCep(val) {
    const clean = String(val || '').replace(/\D/g, '').slice(0, 8);
    if (clean.length <= 5) return clean;
    return `${clean.slice(0, 5)}-${clean.slice(5, 8)}`;
}

export function maskCnpj(input) {
    input.value = formatCnpj(input.value);
    input.maxLength = 18;
    input.placeholder = '00.000.000/0000-00';
}

export function maskCep(input) {
    input.value = formatCep(input.value);
    input.maxLength = 9;
    input.placeholder = '00000-000';
}

let staticModalEscapeBound = false;

export function openModal(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.add('open');
    if (!staticModalEscapeBound) {
        staticModalEscapeBound = true;
        document.addEventListener('keydown', (evt) => {
            if (evt.key !== 'Escape') return;
            const openOverlays = Array.from(document.querySelectorAll('.modal-overlay.open:not(#app-dialog-overlay)'));
            const top = openOverlays[openOverlays.length - 1];
            if (top) {
                top.classList.remove('open');
            }
        });
    }
}

export function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove('open');
}

let toastProgressTimer = null;
let toastAutoHideTimer = null;
let toastCurrentProgress = 0;
let activeDialogCleanup = null;

function clearToastTimers() {
    if (toastProgressTimer) {
        clearInterval(toastProgressTimer);
        toastProgressTimer = null;
    }
    if (toastAutoHideTimer) {
        clearTimeout(toastAutoHideTimer);
        toastAutoHideTimer = null;
    }
}

function escapeDialogHtml(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function getIconSvg(kind) {
    switch (kind) {
        case 'mail':
            return `<svg viewBox="0 0 24 24"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>`;
        case 'warning':
        case 'danger':
            return `<svg viewBox="0 0 24 24"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;
        case 'error':
            return `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`;
        case 'success':
            return `<svg viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`;
        case 'trash':
            return `<svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>`;
        case 'bookmark':
            return `<svg viewBox="0 0 24 24"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>`;
        case 'logout':
            return `<svg viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>`;
        default:
            return `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`;
    }
}

function applyToastVisuals(variant, progressValue, pctText = null) {
    const toast = document.getElementById('task-toast');
    const bar = document.getElementById('task-progress');
    const icon = document.getElementById('task-icon');
    const pctEl = document.getElementById('task-pct');
    if (!toast) return;

    toast.classList.remove('is-loading', 'is-success', 'is-error', 'is-warning');
    const stateClass = variant === 'success'
        ? 'is-success'
        : (variant === 'error' ? 'is-error' : (variant === 'warning' ? 'is-warning' : 'is-loading'));
    toast.classList.add(stateClass);

    if (bar) {
        const clamped = Math.max(0, Math.min(100, Number(progressValue) || 0));
        toastCurrentProgress = clamped;
        bar.style.width = `${clamped}%`;
        bar.classList.toggle('is-loading', variant === 'loading');
    }

    if (pctEl) {
        pctEl.innerText = pctText !== null ? pctText : `${Math.round(toastCurrentProgress)}%`;
    }

    if (icon) {
        if (variant === 'loading') {
            icon.innerHTML = '<span class="task-toast-spinner"></span>';
        } else if (variant === 'success') {
            icon.innerHTML = getIconSvg('success');
        } else if (variant === 'error') {
            icon.innerHTML = getIconSvg('error');
        } else if (variant === 'warning') {
            icon.innerHTML = getIconSvg('warning');
        } else {
            icon.innerHTML = getIconSvg('info');
        }
    }
}

export function showTaskToast(title, msg, options = {}) {
    const toast = document.getElementById('task-toast');
    if (!toast) return;

    clearToastTimers();

    const variant = options.variant || 'loading';
    const hasExplicitProgress = typeof options.progress === 'number';
    const initialProgress = hasExplicitProgress ? options.progress : (variant === 'loading' ? 12 : 100);
    const shouldAutoProgress = options.autoProgress !== undefined
        ? Boolean(options.autoProgress)
        : (variant === 'loading' && !hasExplicitProgress);

    const titleEl = document.getElementById('task-title');
    const msgEl = document.getElementById('task-msg');
    if (titleEl) titleEl.innerText = title || 'Processando...';
    if (msgEl) {
        msgEl.style.color = variant === 'error' ? 'var(--red-text)' : 'var(--text2)';
        msgEl.innerText = msg || '';
    }

    applyToastVisuals(variant, initialProgress, options.pctLabel ?? null);
    toast.style.display = 'block';

    if (shouldAutoProgress) {
        toastProgressTimer = setInterval(() => {
            if (toastCurrentProgress >= 90) return;
            const remaining = 92 - toastCurrentProgress;
            const step = Math.max(1.2, remaining * 0.14);
            applyToastVisuals('loading', Math.min(90, toastCurrentProgress + step));
        }, 220);
    }

    if (options.autoHideMs && options.autoHideMs > 0) {
        toastAutoHideTimer = setTimeout(() => {
            hideTaskToast();
        }, options.autoHideMs);
    }
}

export function setTaskProgress(pct, msg = null, title = null) {
    if (toastProgressTimer) {
        clearInterval(toastProgressTimer);
        toastProgressTimer = null;
    }
    const toast = document.getElementById('task-toast');
    if (!toast) return;
    if (title !== null) {
        const titleEl = document.getElementById('task-title');
        if (titleEl) titleEl.innerText = title;
    }
    if (msg !== null) {
        const msgEl = document.getElementById('task-msg');
        if (msgEl) {
            msgEl.style.color = 'var(--text2)';
            msgEl.innerText = msg;
        }
    }
    toast.style.display = 'block';
    applyToastVisuals('loading', pct);
}

export function completeTaskToast(title, msg, autoHideMs = 4500) {
    showTaskToast(title || 'Concluído', msg || 'Operação realizada com sucesso.', {
        variant: 'success',
        progress: 100,
        pctLabel: '100%',
        autoProgress: false,
        autoHideMs,
    });
}

export function failTaskToast(title, msg, autoHideMs = 6000) {
    showTaskToast(title || 'Falha na operação', msg || 'Não foi possível concluir a ação.', {
        variant: 'error',
        progress: 100,
        pctLabel: 'Erro',
        autoProgress: false,
        autoHideMs,
    });
}

export function hideTaskToast() {
    clearToastTimers();
    const toast = document.getElementById('task-toast');
    if (toast) {
        toast.style.display = 'none';
    }
}

function getOrCreateDialogOverlay() {
    let overlay = document.getElementById('app-dialog-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'app-dialog-overlay';
        overlay.className = 'modal-overlay app-dialog-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        document.body.appendChild(overlay);
    }
    return overlay;
}

function openDialogBase({
    title,
    subtitle = '',
    variant = 'primary',
    icon = null,
    infoBadge = '',
    infoMono = false,
    bodyHtml = '',
    confirmText = 'Confirmar',
    cancelText = 'Cancelar',
    showCancel = true,
    onConfirm,
    onReady,
}) {
    if (activeDialogCleanup) {
        activeDialogCleanup();
    }

    const overlay = getOrCreateDialogOverlay();
    const iconName = icon || (variant === 'danger' ? 'warning' : (variant === 'error' ? 'error' : (variant === 'warning' ? 'warning' : (variant === 'success' ? 'success' : 'info'))));
    const iconClass = variant === 'danger' || variant === 'error'
        ? 'is-danger'
        : (variant === 'warning' ? 'is-warning' : (variant === 'success' ? 'is-success' : ''));
    const confirmClass = variant === 'danger' || variant === 'error'
        ? 'btn-danger'
        : (variant === 'warning' ? 'btn-warning' : 'btn-primary');

    overlay.innerHTML = `
      <div class="modal app-dialog">
        <div class="app-dialog-header">
          <div class="app-dialog-heading">
            <div class="app-dialog-icon ${iconClass}">${getIconSvg(iconName)}</div>
            <div>
              <div class="app-dialog-title">${escapeDialogHtml(title)}</div>
              ${subtitle ? `<div class="app-dialog-subtitle">${escapeDialogHtml(subtitle)}</div>` : ''}
            </div>
          </div>
          <button type="button" class="btn-ghost task-toast-close" id="app-dialog-close" aria-label="Fechar">&times;</button>
        </div>
        ${(infoBadge || bodyHtml) ? `
          <div class="app-dialog-body">
            ${infoBadge ? `<div class="app-dialog-info ${infoMono ? 'is-mono' : ''}">${escapeDialogHtml(infoBadge)}</div>` : ''}
            ${bodyHtml}
            <div class="app-dialog-error" id="app-dialog-error"></div>
          </div>
        ` : `<div class="app-dialog-error" id="app-dialog-error" style="margin:0 22px 14px;"></div>`}
        <div class="app-dialog-footer">
          ${showCancel ? `<button type="button" class="btn btn-secondary" id="app-dialog-cancel">${escapeDialogHtml(cancelText)}</button>` : ''}
          <button type="button" class="btn ${confirmClass}" id="app-dialog-confirm">${escapeDialogHtml(confirmText)}</button>
        </div>
      </div>
    `;

    return new Promise((resolve) => {
        let settled = false;
        const finish = (value) => {
            if (settled) return;
            settled = true;
            overlay.classList.remove('open');
            document.removeEventListener('keydown', handleKeydown);
            overlay.removeEventListener('click', handleBackdropClick);
            activeDialogCleanup = null;
            resolve(value);
        };

        activeDialogCleanup = () => finish(null);

        const showError = (msg) => {
            const errEl = document.getElementById('app-dialog-error');
            if (!errEl) return;
            if (msg) {
                errEl.innerText = msg;
                errEl.style.display = 'block';
            } else {
                errEl.style.display = 'none';
            }
        };

        const handleBackdropClick = (e) => {
            if (e.target === overlay) {
                finish(null);
            }
        };

        const confirmBtn = document.getElementById('app-dialog-confirm');
        const cancelBtn = document.getElementById('app-dialog-cancel');
        const closeBtn = document.getElementById('app-dialog-close');

        const tryConfirm = () => {
            if (onConfirm) {
                const outcome = onConfirm(showError);
                if (outcome && outcome.valid === false) return;
                finish(outcome ? outcome.value : true);
            } else {
                finish(true);
            }
        };

        const handleKeydown = (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                finish(null);
            } else if (e.key === 'Enter') {
                const active = document.activeElement;
                if (active && active.tagName === 'TEXTAREA' && !e.ctrlKey && !e.metaKey) {
                    return;
                }
                e.preventDefault();
                tryConfirm();
            }
        };

        confirmBtn?.addEventListener('click', tryConfirm);
        cancelBtn?.addEventListener('click', () => finish(null));
        closeBtn?.addEventListener('click', () => finish(null));
        overlay.addEventListener('click', handleBackdropClick);
        document.addEventListener('keydown', handleKeydown);

        requestAnimationFrame(() => {
            overlay.classList.add('open');
            if (onReady) {
                onReady({ showError, tryConfirm });
            } else {
                confirmBtn?.focus();
            }
        });
    });
}

export async function uiAlert(messageOrOpts, maybeOpts = {}) {
    const opts = typeof messageOrOpts === 'string'
        ? { message: messageOrOpts, ...maybeOpts }
        : (messageOrOpts || {});
    const variant = opts.variant || 'info';
    const defaultTitle = variant === 'error' || variant === 'danger'
        ? 'Atenção — Erro na Operação'
        : (variant === 'success' ? 'Operação Concluída' : (variant === 'warning' ? 'Aviso' : 'Informação'));

    await openDialogBase({
        title: opts.title || defaultTitle,
        subtitle: opts.message || opts.subtitle || '',
        variant,
        icon: opts.icon || null,
        infoBadge: opts.infoBadge || opts.details || '',
        infoMono: Boolean(opts.infoMono),
        confirmText: opts.confirmText || 'Entendi',
        showCancel: false,
    });
}

export async function uiConfirm(messageOrOpts, maybeOpts = {}) {
    const opts = typeof messageOrOpts === 'string'
        ? { message: messageOrOpts, ...maybeOpts }
        : (messageOrOpts || {});

    const res = await openDialogBase({
        title: opts.title || 'Confirmar Ação',
        subtitle: opts.message || opts.subtitle || '',
        variant: opts.variant || 'warning',
        icon: opts.icon || null,
        infoBadge: opts.infoBadge || opts.details || '',
        infoMono: Boolean(opts.infoMono),
        confirmText: opts.confirmText || 'Confirmar',
        cancelText: opts.cancelText || 'Cancelar',
        showCancel: true,
    });
    return res === true;
}

export async function uiPrompt(opts = {}) {
    const isTextarea = opts.type === 'textarea';
    const inputType = isTextarea ? 'textarea' : (opts.type || 'text');
    const minLength = opts.minLength || 0;
    const required = opts.required !== undefined ? Boolean(opts.required) : true;
    const initialVal = opts.defaultValue ?? '';

    const fieldHtml = `
      <div class="app-dialog-field">
        ${opts.label ? `<label for="app-dialog-input">${escapeDialogHtml(opts.label)}</label>` : ''}
        ${isTextarea
            ? `<textarea id="app-dialog-input" placeholder="${escapeDialogHtml(opts.placeholder || '')}">${escapeDialogHtml(initialVal)}</textarea>`
            : `<input id="app-dialog-input" type="${escapeDialogHtml(inputType)}" placeholder="${escapeDialogHtml(opts.placeholder || '')}" value="${escapeDialogHtml(initialVal)}" autocomplete="off" />`}
        ${(opts.hint || minLength > 0) ? `
          <div class="app-dialog-hint-row">
            <span>${escapeDialogHtml(opts.hint || (isTextarea ? 'Dica: Ctrl+Enter para confirmar.' : ''))}</span>
            ${minLength > 0 ? `<span class="app-dialog-counter" id="app-dialog-counter">0 / ${minLength} mín.</span>` : ''}
          </div>
        ` : ''}
      </div>
    `;

    const res = await openDialogBase({
        title: opts.title || 'Informar Valor',
        subtitle: opts.subtitle || '',
        variant: opts.variant || 'primary',
        icon: opts.icon || null,
        infoBadge: opts.infoBadge || '',
        infoMono: Boolean(opts.infoMono),
        bodyHtml: fieldHtml,
        confirmText: opts.confirmText || 'Confirmar',
        cancelText: opts.cancelText || 'Cancelar',
        showCancel: true,
        onReady: () => {
            const input = document.getElementById('app-dialog-input');
            const counter = document.getElementById('app-dialog-counter');
            if (!input) return;

            const syncCounter = () => {
                if (!counter || !minLength) return;
                const len = input.value.trim().length;
                counter.textContent = `${len} / ${minLength} mín.`;
                counter.classList.toggle('is-valid', len >= minLength);
                counter.classList.toggle('is-invalid', len < minLength);
            };
            syncCounter();
            input.addEventListener('input', () => {
                syncCounter();
                const errEl = document.getElementById('app-dialog-error');
                if (errEl) errEl.style.display = 'none';
            });

            input.focus();
            if (!isTextarea && typeof input.select === 'function') {
                input.select();
            }
        },
        onConfirm: (showError) => {
            const input = document.getElementById('app-dialog-input');
            const val = (input?.value || '').trim();
            if (required && !val) {
                showError(opts.emptyMessage || 'Este campo é obrigatório.');
                input?.focus();
                return { valid: false };
            }
            if (minLength > 0 && val.length < minLength) {
                showError(`Informe pelo menos ${minLength} caracteres (atual: ${val.length}).`);
                input?.focus();
                return { valid: false };
            }
            if (typeof opts.validate === 'function') {
                const err = opts.validate(val);
                if (err) {
                    showError(err);
                    input?.focus();
                    return { valid: false };
                }
            }
            return { valid: true, value: val };
        },
    });

    return typeof res === 'string' ? res : null;
}

export function toggleTheme() {
    const isLight = document.body.classList.toggle('theme-light');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
    return isLight;
}

export function initSidebarState() {
    const expanded = localStorage.getItem('sidebar_expanded') === '1';
    document.body.classList.toggle('sidebar-expanded', expanded);
    const btn = document.getElementById('sidebar-toggle-btn');
    if (btn) btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
}

export function toggleSidebar() {
    const expanded = document.body.classList.toggle('sidebar-expanded');
    localStorage.setItem('sidebar_expanded', expanded ? '1' : '0');
    const btn = document.getElementById('sidebar-toggle-btn');
    if (btn) btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    return expanded;
}

export function maskPhone(input) {
    let v = input.value.replace(/\D/g, '');
    if (v.length > 11) v = v.slice(0, 11);
    
    if (v.length > 10) {
        v = v.replace(/^(\d{2})(\d{5})(\d{4})/, '($1) $2-$3');
    } else if (v.length > 2) {
        v = v.replace(/^(\d{2})(\d*)/, '($1) $2');
    } else if (v.length > 0) {
        v = v.replace(/^(\d*)/, '($1');
    }
    input.value = v;
}

export function escapeAttr(str) {
    return escapeDialogHtml(str);
}

export function renderInvoiceStatusBadge(status) {
    const raw = String(status || 'desconhecido');
    const norm = raw.toLowerCase();
    let style = 'background:var(--amber-bg); color:var(--amber-text); border-color:rgba(245,158,11,0.28);';
    if (['gerada', 'emitida', 'autorizada', 'normal'].includes(norm)) {
        style = 'background:var(--green-bg); color:var(--green-text); border-color:rgba(16,185,129,0.28);';
    } else if (['cancelada', 'substituida', 'erro', 'rejeitada'].includes(norm)) {
        style = 'background:var(--red-bg); color:var(--red-text); border-color:rgba(239,68,68,0.28);';
    }
    return `<span class="badge badge-ctrl" style="${style}"><span class="badge-dot"></span> ${escapeDialogHtml(raw)}</span>`;
}

export function renderInvoiceSummaryCells(invoice, formattedValue) {
    const dataFmt = invoice?.data_emissao ? new Date(invoice.data_emissao).toLocaleDateString('pt-BR') : '-';
    const hasChave = invoice?.chave && invoice.chave !== 'null';
    const hasNumero = invoice?.numero && invoice.numero !== 'null';
    const chaveDisplay = hasChave ? String(invoice.chave) : (hasNumero ? String(invoice.numero) : 'Chave não sincronizada');
    const keyLabel = (hasChave && hasNumero && String(invoice.numero) !== String(invoice.chave))
        ? `#${invoice.numero} · ${invoice.chave}`
        : chaveDisplay;

    const metaParts = [];
    if (invoice?.ambiente === 'homologacao') {
        metaParts.push('<span class="inv-meta-tag is-homolog" title="Nota gerada em ambiente de Homologação (sem validade fiscal)">Homologação</span>');
    } else if (invoice?.ambiente === 'producao') {
        metaParts.push('<span class="inv-meta-tag is-prod" title="Emitida em ambiente de Produção">Produção</span>');
    }
    if (invoice?.created_by_username) {
        metaParts.push(`<span class="inv-meta-tag is-author" title="Emitida pelo operador @${escapeDialogHtml(invoice.created_by_username)}">@${escapeDialogHtml(invoice.created_by_username)}</span>`);
    }
    const metaHtml = metaParts.length ? `<div class="inv-meta-row">${metaParts.join('')}</div>` : '';

    return `
        <td><span class="tbl-cell-chip">${escapeDialogHtml(dataFmt)}</span></td>
        <td>
            <span class="tbl-cell-chip tbl-cell-chip--key" title="${escapeDialogHtml(chaveDisplay)}">${escapeDialogHtml(keyLabel)}</span>
            ${metaHtml}
        </td>
        <td><span class="tbl-cell-chip tbl-cell-chip--value">${escapeDialogHtml(formattedValue)}</span></td>
        <td>${renderInvoiceStatusBadge(invoice?.status)}</td>
    `;
}

export function renderInvoiceFileButtons(invoice, emptyLabel = 'Pendente') {
    const parts = [];
    if (invoice?.xml_path) {
        parts.push(
            `<a href="#" class="btn btn-sm btn-file-xml" onclick="window.App.triggerDownload(this.dataset.path); return false;" data-path="${escapeDialogHtml(invoice.xml_path)}" title="Download XML">` +
            `<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>XML</a>`
        );
    }
    if (invoice?.pdf_path) {
        const lower = String(invoice.pdf_path).toLowerCase();
        if (lower.endsWith('.html') || lower.endsWith('.htm')) {
            parts.push(
                `<a href="#" class="btn btn-sm btn-file-html" onclick="window.App.convertHtmlToXmlAndPdf(${invoice.id}, this.dataset.path, '${escapeDialogHtml(invoice.status || 'NORMAL')}'); return false;" data-path="${escapeDialogHtml(invoice.pdf_path)}" title="Converter HTML em XML e PDF via pynfse">` +
                `<svg viewBox="0 0 24 24"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>HTML → XML/PDF</a>`
            );
        } else {
            parts.push(
                `<a href="#" class="btn btn-sm btn-file-pdf" onclick="window.App.triggerDownload(this.dataset.path); return false;" data-path="${escapeDialogHtml(invoice.pdf_path)}" title="Download PDF">` +
                `<svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>PDF</a>`
            );
        }
    }
    if (parts.length === 0) {
        return `<span style="font-size:12px; color:var(--text3);">${escapeDialogHtml(emptyLabel)}</span>`;
    }
    return `<div class="table-actions-inline">${parts.join('')}</div>`;
}
