import { api } from '../core/api.js';
import { state } from '../core/state.js';
import { showTaskToast, hideTaskToast } from '../core/ui.js';

let progressCloseTimer = null;

export function triggerDownload(path) {
    if (!path) return;
    window.location.href = '/api/download/file?path=' + encodeURIComponent(path);
}

export async function loadInvoices() {
    const tbody = document.getElementById('invoices-table-body');
    if (!tbody) return;
    
    const typeEl = document.getElementById('filter-type');
    const type = typeEl ? typeEl.value : 'emitidas';
    const clientId = state.getGlobalClientId();
    
    const dataInicio = document.getElementById('filter-start')?.value || '';
    const dataFim = document.getElementById('filter-end')?.value || '';
    
    let url = `/invoices?tipo=${type}&data_inicio=${dataInicio}&data_fim=${dataFim}`;
    if (clientId) url += `&client_id=${clientId}`;
    
    try {
        const invoices = await api(url);
        const fmt = v => new Intl.NumberFormat('pt-BR', {style: 'currency', currency: 'BRL'}).format(v);
        
        if (invoices.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg><div class="empty-state-title">Nenhuma nota encontrada</div></div></td></tr>`;
            return;
        }
        
        tbody.innerHTML = invoices.map(i => renderInvoiceRow(i, fmt)).join('');
        initDatePickers();
    } catch (e) {
        console.error("Erro ao carregar notas:", e);
    }
}

function initDatePickers() {
    const config = {
        dateFormat: "d/m/Y",
        allowInput: true,
        locale: "pt",
        disableMobile: true,
        onChange: function() {
            loadInvoices();
        }
    };
    
    if (window.flatpickr) {
        flatpickr("#filter-start", config);
        flatpickr("#filter-end", config);
    }
}

function renderInvoiceRow(i, fmt) {
    let files = '';
    if (i.xml_path) files += `<a href="#" onclick="window.App.triggerDownload(this.dataset.path); return false;" data-path="${i.xml_path}" style="color:var(--green); font-weight:700; font-size:11px; margin-right:8px; text-decoration:none;" title="Download XML">XML</a>`;
    if (i.pdf_path) {
        const isHtml = i.pdf_path.toLowerCase().endsWith('.html') || i.pdf_path.toLowerCase().endsWith('.htm');
        const label = isHtml ? 'HTML' : 'PDF';
        const color = isHtml ? 'var(--amber)' : 'var(--accent)';
        files += `<a href="#" onclick="window.App.triggerDownload(this.dataset.path); return false;" data-path="${i.pdf_path}" style="color:${color}; font-weight:700; font-size:11px; text-decoration:none;" title="Download ${label}">${label}</a>`;
    }
    
    const dataFmt = i.data_emissao ? new Date(i.data_emissao).toLocaleDateString('pt-BR') : '-';
    
    return `
        <tr>
            <td><input type="checkbox" class="row-check" value="${i.id}" data-xml="${i.xml_path}" data-pdf="${i.pdf_path}" data-client-id="${i.client_id}"></td>
            <td>${dataFmt}</td>
            <td>
                <div style="font-size:14px; font-weight:600; color:var(--text);">${i.numero || 'S/N'}</div>
                <div style="font-size:11.5px; color:var(--text3); font-family:var(--mono); margin-top:2px; word-break: break-all;">${i.chave && i.chave !== 'null' ? i.chave : 'Chave não sincronizada'}</div>
            </td>
            <td style="font-weight:600; color:var(--text);">${fmt(i.valor)}</td>
            <td><span class="status-badge status-${i.status || 'unknown'}">${i.status || 'desconhecido'}</span></td>
            <td>${files}</td>
        </tr>
    `;
}

export function setFilterType(val, text) {
    const el = document.getElementById('filter-type');
    if (el) el.value = val;
    const btnSpan = document.querySelector('#filter-type-btn span');
    if (btnSpan) btnSpan.innerText = text;
    
    document.querySelectorAll('.dropdown-menu.show').forEach(m => m.classList.remove('show'));
    loadInvoices();
}

export function toggleSelectAll(cb) {
    document.querySelectorAll('.row-check').forEach(chk => chk.checked = cb.checked);
}

export async function downloadBatch() {
    const selected = Array.from(document.querySelectorAll('.row-check:checked'));
    if (selected.length === 0) {
        alert("Selecione pelo menos uma nota.");
        return;
    }
    
    const invoiceIds = selected.map(chk => chk.value);
    const paths = [];
    const missing = [];
    
    selected.forEach(chk => {
        const xml = chk.dataset.xml;
        const pdf = chk.dataset.pdf;
        const hasXml = xml && xml !== 'null';
        const hasPdf = pdf && pdf !== 'null';
        
        if (hasXml && hasPdf) {
            paths.push(xml);
            paths.push(pdf);
        } else {
            missing.push(chk.value);
        }
    });
    
    if (missing.length > 0) {
        let clientId = state.getGlobalClientId();
        
        if (!clientId && selected.length > 0) {
            clientId = selected[0].dataset.clientId;
        }

        if (!clientId) {
            alert("Não foi possível identificar o cliente para o download.");
            return;
        }

        const actionType = document.getElementById('filter-type').value;
        
        try {
            const res = await api('/download/sync-portal', 'POST', {
                client_id: parseInt(clientId),
                action_type: actionType,
                invoice_ids: invoiceIds.map(id => parseInt(id))
            });
            state.currentTask = res.task_id;
            document.getElementById('sync-indicator').style.display = 'flex';
            showTaskToast('Download Iniciado', 'Buscando arquivos no portal da NFSe...');
        } catch (e) {
            alert("Erro ao iniciar download: " + e.message);
        }
        return;
    }
    
    if (paths.length === 0) {
        alert("Nenhum arquivo disponível para as notas selecionadas no momento.");
        return;
    }

    if (selected.length <= 100) {
        for (const path of paths) {
            triggerDownload(path);
            await new Promise(resolve => setTimeout(resolve, 180));
        }
        return;
    }
    
    try {
        const res = await api('/download/batch', 'POST', {arquivos: paths});
        triggerDownload(res.zip_path);
    } catch (e) {
        alert("Erro ao gerar lote: " + e.message);
    }
}

export async function startSync() {
    const data_inicio = document.getElementById('filter-start').value;
    const data_fim = document.getElementById('filter-end').value;
    const tipo = document.getElementById('filter-type').value;
    const client_id = state.getGlobalClientId();
    
    if (!client_id) return alert("Selecione um cliente no topo.");
    
    const payload = { data_inicio, data_fim, tipo, client_id };
    
    try {
        const res = await api('/sync', 'POST', payload);
        state.currentTask = res.task_id;
        document.getElementById('sync-indicator').style.display = 'flex';
        showTaskToast('Sincronização Iniciada', 'As notas estão sendo buscadas no portal...');
    } catch (e) {
        alert("Erro ao iniciar: " + e.message);
    }
}

function closeProgressIndicatorsAfterDelay(delayMs = 5000) {
    if (progressCloseTimer) {
        clearTimeout(progressCloseTimer);
    }

    progressCloseTimer = setTimeout(() => {
        const syncIndicator = document.getElementById('sync-indicator');
        if (syncIndicator) {
            syncIndicator.style.display = 'none';
        }
        hideTaskToast();
        progressCloseTimer = null;
    }, delayMs);
}

export async function pollTask() {
    if (!state.currentTask) return;
    try {
        const res = await api(`/tasks/${state.currentTask}`);
        const pct = res.progress || 0;
        
        const bar = document.getElementById('task-progress');
        const msg = document.getElementById('task-msg');
        
        if (bar) bar.style.width = pct + '%';
        if (msg) msg.innerText = res.message || 'Processando...';
        
        if (res.status === 'completed') {
            state.currentTask = null;
            if (msg) msg.innerText = 'Concluído com sucesso!';
            closeProgressIndicatorsAfterDelay(5000);
            setTimeout(() => loadInvoices(), 1000);
        } else if (res.status === 'failed') {
            state.currentTask = null;
            if (msg) {
                msg.style.color = 'var(--red)';
                msg.innerText = 'Falha: ' + (res.message || 'Erro desconhecido');
            }
            closeProgressIndicatorsAfterDelay(5000);
        }
    } catch (e) {
        console.warn("Poll erro:", e);
        state.currentTask = null;
    }
}

export async function enrichFromXml() {
    const btn = document.getElementById('btn-enrich');
    if (btn) {
        btn.disabled = true;
        btn.style.opacity = '0.5';
    }
    
    const clientId = state.getGlobalClientId();
    let url = `/analytics/enrich-xml`;
    if (clientId) url += `?client_id=${clientId}`;
    
    try {
        showTaskToast('Enriquecimento', 'Lendo arquivos XML para preencher valores faltantes...');
        const res = await api(url, 'POST');
        showTaskToast('Valores Atualizados', res.message || 'XMLs processados com sucesso.');
        
        if (window.App && window.App.loadDashboardStats) {
            await window.App.loadDashboardStats();
            await window.App.loadDashboardChart(state.chartPeriod);
        }
    } catch (e) {
        showTaskToast('Erro', 'Não foi possível enriquecer os dados via XML.');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.style.opacity = '1';
        }
    }
}
