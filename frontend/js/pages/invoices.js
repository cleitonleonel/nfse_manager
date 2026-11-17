import { api } from '../core/api.js';
import { state } from '../core/state.js';
import { showTaskToast, setTaskProgress, completeTaskToast, failTaskToast, hideTaskToast, uiAlert, uiPrompt, escapeAttr, renderInvoiceFileButtons, renderInvoiceSummaryCells } from '../core/ui.js';

let progressCloseTimer = null;

export function triggerDownload(path) {
    if (!path) return;
    window.location.href = '/api/download/file?path=' + encodeURIComponent(path);
}

export async function convertHtmlToXmlAndPdf(invoiceId, htmlPath, status = 'NORMAL') {
    try {
        showTaskToast('Convertendo HTML', 'Gerando XML a partir do HTML baixado...', { progress: 30, autoProgress: false });
        const resXml = await api('/download/html-to-xml', 'POST', {
            invoice_id: invoiceId || null,
            html_path: htmlPath || null,
        });

        setTaskProgress(70, 'Enviando XML gerado para conversão em PDF...', 'Gerando PDF (pynfse)');
        const resPdf = await api('/download/xml-to-pdf', 'POST', {
            invoice_id: invoiceId || resXml.invoice_id || null,
            xml_content: resXml.xml_content,
            xml_path: resXml.xml_path,
            status: status || 'NORMAL',
        });

        await loadInvoices();
        completeTaskToast('Conversão Concluída', 'XML e PDF gerados com sucesso!', 3500);
        if (resPdf && resPdf.pdf_path) {
            triggerDownload(resPdf.pdf_path);
        }
    } catch (e) {
        failTaskToast('Falha na Conversão', e.message);
        await uiAlert({ title: 'Erro ao converter HTML em XML/PDF', message: e.message, variant: 'error' });
    }
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
            tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state"><svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg><div class="empty-state-title">Nenhuma nota encontrada</div></div></td></tr>`;
            return;
        }
        
        tbody.innerHTML = invoices.map(i => renderInvoiceRow(i, fmt)).join('');
        initDatePickers();
        loadCompetenciaReport();
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
    const files = renderInvoiceFileButtons(i, 'Pendente');

    let actions = `
        <button type="button" class="btn btn-secondary btn-sm" onclick="window.App.sendInvoiceEmailPrompt(${i.id}, this.dataset.email); return false;" data-email="${escapeAttr(i.tomador_email || '')}" title="Enviar XML + PDF por E-mail">
            <svg viewBox="0 0 24 24"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>
            E-mail
        </button>
    `;
    if (i.status !== 'cancelada' && i.chave && i.chave.length === 50) {
        actions += `
            <button type="button" class="btn btn-secondary btn-sm btn-action-danger" onclick="window.App.cancelInvoicePrompt(${i.id}, this.dataset.chave); return false;" data-chave="${escapeAttr(i.chave)}" title="Cancelar NFS-e no ADN (e101101)">
                <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
                Cancelar
            </button>
        `;
    }
    
    return `
        <tr>
            <td><input type="checkbox" class="row-check" value="${i.id}" data-xml="${escapeAttr(i.xml_path)}" data-pdf="${escapeAttr(i.pdf_path)}" data-client-id="${i.client_id}"></td>
            ${renderInvoiceSummaryCells(i, fmt(i.valor))}
            <td>${files}</td>
            <td><div class="table-actions-inline">${actions}</div></td>
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
        await uiAlert({ title: 'Nenhuma nota selecionada', message: 'Selecione pelo menos uma nota na lista para baixar.', variant: 'warning' });
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
            await uiAlert({ title: 'Empresa não identificada', message: 'Não foi possível identificar o cliente para o download.', variant: 'warning' });
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
            showTaskToast('Download Iniciado', 'Buscando arquivos no portal da NFSe...', { progress: 5, autoProgress: false });
        } catch (e) {
            await uiAlert({ title: 'Erro ao iniciar download', message: e.message, variant: 'error' });
        }
        return;
    }
    
    if (paths.length === 0) {
        await uiAlert({ title: 'Arquivos indisponíveis', message: 'Nenhum arquivo disponível para as notas selecionadas no momento.', variant: 'info' });
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
        showTaskToast('Compactando Lote', 'Gerando arquivo ZIP com os documentos selecionados...', { autoProgress: true });
        const res = await api('/download/batch', 'POST', {arquivos: paths});
        completeTaskToast('Lote Pronto', 'Download do arquivo ZIP iniciado.', 3500);
        triggerDownload(res.zip_path);
    } catch (e) {
        failTaskToast('Erro ao Gerar Lote', e.message);
        await uiAlert({ title: 'Erro ao gerar lote', message: e.message, variant: 'error' });
    }
}

export async function startSync() {
    const data_inicio = document.getElementById('filter-start').value;
    const data_fim = document.getElementById('filter-end').value;
    const tipo = document.getElementById('filter-type').value;
    const client_id = state.getGlobalClientId();
    
    if (!client_id) {
        await uiAlert({ title: 'Selecione uma empresa', message: 'Selecione um cliente no seletor do topo da página antes de sincronizar.', variant: 'warning' });
        return;
    }
    
    const payload = { data_inicio, data_fim, tipo, client_id };
    
    try {
        const res = await api('/sync', 'POST', payload);
        state.currentTask = res.task_id;
        document.getElementById('sync-indicator').style.display = 'flex';
        showTaskToast('Sincronização Iniciada', 'As notas estão sendo buscadas no portal...', { progress: 5, autoProgress: false });
    } catch (e) {
        await uiAlert({ title: 'Erro ao iniciar sincronização', message: e.message, variant: 'error' });
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
        
        setTaskProgress(pct, res.message || 'Processando...');
        
        if (res.status === 'completed') {
            state.currentTask = null;
            completeTaskToast('Sincronização Concluída', res.message || 'Concluído com sucesso!', 5000);
            closeProgressIndicatorsAfterDelay(5000);
            setTimeout(() => loadInvoices(), 1000);
        } else if (res.status === 'failed') {
            state.currentTask = null;
            failTaskToast('Falha na Tarefa', res.message || 'Erro desconhecido', 6000);
            closeProgressIndicatorsAfterDelay(6000);
        }
    } catch (e) {
        console.warn("Poll erro:", e);
        state.currentTask = null;
    }
}

export async function syncCofreAdn() {
    const client_id = state.getGlobalClientId();
    if (!client_id) {
        await uiAlert({ title: 'Cliente não selecionado', message: 'Selecione um cliente com Certificado A1 no topo para sincronizar o Cofre ADN.', variant: 'warning' });
        return;
    }
    try {
        showTaskToast('Cofre ADN (DistDFe/NSU)', 'Sincronizando notas emitidas e recebidas no Ambiente Nacional...', { autoProgress: true });
        const res = await api('/adn/cofre/sincronizar', 'POST', {
            client_id: parseInt(client_id, 10),
            max_paginas: 5,
        });
        await loadInvoices();
        completeTaskToast('Cofre ADN Sincronizado', `${res.novas_notas} nova(s) nota(s), NSU atual: ${res.ultimo_nsu}.`, 4500);
    } catch (e) {
        failTaskToast('Erro no Cofre ADN', e.message);
        await uiAlert({ title: 'Erro ao sincronizar Cofre ADN', message: e.message, variant: 'error' });
    }
}

export async function sendInvoiceEmailPrompt(invoiceId, defaultEmail = '') {
    const destinatario = await uiPrompt({
        title: 'Enviar NFS-e por E-mail',
        subtitle: 'Informe o e-mail do destinatário para encaminhar os arquivos fiscais desta nota.',
        label: 'E-mail do destinatário',
        type: 'email',
        placeholder: 'cliente@empresa.com.br',
        defaultValue: defaultEmail || '',
        infoBadge: 'Serão anexados automaticamente o XML oficial da NFS-e e o DANFSe em PDF.',
        confirmText: 'Enviar E-mail',
        cancelText: 'Cancelar',
        variant: 'primary',
        icon: 'mail',
        emptyMessage: 'Informe o e-mail do destinatário.',
        validate: (val) => {
            const emails = val.split(/[;,]/).map(s => s.trim()).filter(Boolean);
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (emails.length === 0 || emails.some(em => !emailRegex.test(em))) {
                return 'Informe um endereço de e-mail válido (ex: contato@empresa.com.br).';
            }
            return null;
        },
    });
    if (!destinatario) return;
    try {
        showTaskToast('Enviando E-mail', `Preparando XML + DANFSe e enviando para ${destinatario}...`, { autoProgress: true });
        const res = await api(`/adn/nfse/${invoiceId}/enviar-email`, 'POST', { destinatario });
        const anexosStr = (res.anexos || []).map(a => a.toUpperCase()).join(' + ');
        completeTaskToast('E-mail Enviado', `Enviado para ${res.destinatario}${anexosStr ? ` (${anexosStr})` : ''}!`, 5000);
    } catch (e) {
        failTaskToast('Falha ao Enviar E-mail', e.message);
        await uiAlert({ title: 'Erro ao enviar e-mail', message: e.message, variant: 'error', icon: 'mail' });
    }
}

export async function cancelInvoicePrompt(invoiceId, chaveNfse) {
    const motivo = await uiPrompt({
        title: 'Cancelar NFS-e no ADN',
        subtitle: 'Esta operação gera e transmite o evento e101101 de cancelamento junto ao Ambiente Nacional.',
        infoBadge: `Chave de acesso: ${chaveNfse}`,
        infoMono: true,
        label: 'Justificativa do cancelamento',
        type: 'textarea',
        placeholder: 'Descreva o motivo do cancelamento...',
        defaultValue: 'Cancelamento efetuado devido a erro no preenchimento da nota fiscal.',
        minLength: 15,
        confirmText: 'Confirmar Cancelamento',
        cancelText: 'Voltar',
        variant: 'danger',
        icon: 'warning',
    });
    if (!motivo || motivo.trim().length < 15) return;
    try {
        showTaskToast('Cancelando NFS-e', 'Gerando, assinando e transmitindo evento e101101...', { autoProgress: true });
        await api('/adn/nfse/cancelar', 'POST', {
            invoice_id: invoiceId,
            chave_nfse: chaveNfse,
            motivo_codigo: 1,
            motivo_descricao: motivo.trim(),
            transmitir: true,
        });
        await loadInvoices();
        completeTaskToast('NFS-e Cancelada', 'Evento de cancelamento processado com sucesso.', 4500);
    } catch (e) {
        failTaskToast('Erro ao Cancelar NFS-e', e.message);
        await uiAlert({ title: 'Erro ao cancelar NFS-e', message: e.message, variant: 'error' });
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
        showTaskToast('Enriquecimento', 'Lendo arquivos XML para preencher valores faltantes...', { autoProgress: true });
        const res = await api(url, 'POST');
        completeTaskToast('Valores Atualizados', res.message || 'XMLs processados com sucesso.', 4500);
        
        if (window.App && window.App.loadDashboardStats) {
            await window.App.loadDashboardStats();
            await window.App.loadDashboardChart(state.chartPeriod);
        }
    } catch (e) {
        failTaskToast('Erro no Enriquecimento', 'Não foi possível enriquecer os dados via XML.');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.style.opacity = '1';
        }
    }
}

export async function loadCompetenciaReport() {
    const grid = document.getElementById('comp-summary-grid');
    if (!grid) return;

    const monthInput = document.getElementById('comp-month');
    if (monthInput && !monthInput.value) {
        monthInput.value = new Date().toISOString().slice(0, 7);
    }
    const competencia = monthInput?.value || new Date().toISOString().slice(0, 7);
    const clientId = state.getGlobalClientId();
    const qs = new URLSearchParams({ competencia, format: 'json' });
    if (clientId) qs.set('client_id', String(clientId));

    try {
        const res = await api(`/reports/competencia?${qs.toString()}`);
        const r = res.resumo || {};
        const fmt = v => new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(v || 0);
        grid.innerHTML = `
            <div style="padding:10px 12px; border-radius:8px; background:var(--bg3); border:1px solid var(--border);">
              <div style="color:var(--text3); font-size:11px;">Emitidas Ativas (${r.qtd_emitidas_ativas || 0})</div>
              <div style="font-weight:700; color:var(--green); font-size:14px;">${fmt(r.total_emitidas_bruto)}</div>
              <div style="color:var(--text3); font-size:11px;">Líquido: ${fmt(r.total_emitidas_liquido)}</div>
            </div>
            <div style="padding:10px 12px; border-radius:8px; background:var(--bg3); border:1px solid var(--border);">
              <div style="color:var(--text3); font-size:11px;">Recebidas Ativas (${r.qtd_recebidas_ativas || 0})</div>
              <div style="font-weight:700; color:var(--accent); font-size:14px;">${fmt(r.total_recebidas)}</div>
              <div style="color:var(--text3); font-size:11px;">Saldo: ${fmt(r.saldo_operacional)}</div>
            </div>
            <div style="padding:10px 12px; border-radius:8px; background:var(--bg3); border:1px solid var(--border);">
              <div style="color:var(--text3); font-size:11px;">Tributos (Emitidas Ativas)</div>
              <div style="font-weight:700; font-size:13px;">ISS: ${fmt(r.total_iss)}</div>
              <div style="color:var(--text3); font-size:11px;">IBS: ${fmt(r.total_ibs)} | CBS: ${fmt(r.total_cbs)}</div>
            </div>
            <div style="padding:10px 12px; border-radius:8px; background:var(--bg3); border:1px solid var(--border);">
              <div style="color:var(--text3); font-size:11px;">Exceções na Competência</div>
              <div style="font-weight:700; font-size:13px;">Canceladas/Subst.: ${r.qtd_canceladas_substituidas || 0}</div>
              <div style="color:var(--text3); font-size:11px;">Fila Contingência: ${r.qtd_pendentes_fila || 0}</div>
            </div>
        `;
    } catch (e) {
        grid.innerHTML = `<div style="color:var(--red); font-size:12px;">Erro ao carregar competência: ${e.message}</div>`;
    }
}

export async function downloadCompetenciaReport(fmt = 'xlsx') {
    const monthInput = document.getElementById('comp-month');
    const competencia = monthInput?.value || new Date().toISOString().slice(0, 7);
    const clientId = state.getGlobalClientId();
    const qs = new URLSearchParams({ competencia, format: fmt });
    if (clientId) qs.set('client_id', String(clientId));

    const headers = {};
    const token = localStorage.getItem('nfse_token');
    if (token) headers['Authorization'] = `Bearer ${token}`;

    try {
        const res = await fetch(`/api/reports/competencia?${qs.toString()}`, { headers });
        if (!res.ok) throw new Error(await res.text());
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `relatorio_competencia_${competencia}.${fmt}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    } catch (e) {
        await uiAlert({ title: 'Erro ao exportar relatório', message: e.message, variant: 'error' });
    }
}
