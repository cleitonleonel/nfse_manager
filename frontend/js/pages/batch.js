import { api } from '../core/api.js';
import { state } from '../core/state.js';
import { showTaskToast, completeTaskToast, failTaskToast, uiAlert, uiConfirm } from '../core/ui.js';

let activeBatchId = null;
let cachedBatchItems = [];

const fmtBRL = v => new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(v || 0);

export function switchLoteMode(mode = 'planilha') {
    const planilhaEl = document.getElementById('lote-mode-planilha');
    const rapidoEl = document.getElementById('lote-mode-rapido');
    const btnPlanilha = document.getElementById('lote-mode-btn-planilha');
    const btnRapido = document.getElementById('lote-mode-btn-rapido');
    const isPlanilha = mode !== 'rapido';
    if (planilhaEl) planilhaEl.style.display = isPlanilha ? 'block' : 'none';
    if (rapidoEl) rapidoEl.style.display = isPlanilha ? 'none' : 'block';
    if (btnPlanilha) btnPlanilha.className = isPlanilha ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm';
    if (btnRapido) btnRapido.className = !isPlanilha ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm';
}

export function updateBatchSelectionCount() {
    const countEl = document.getElementById('batch-selected-count');
    if (!countEl) return;
    const count = document.querySelectorAll('.batch-item-check:checked').length;
    countEl.textContent = `${count} selecionado(s)`;
}

function escapeHtml(txt) {
    return String(txt || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

async function fetchDownloadWithAuth(url, filename) {
    const headers = {};
    const token = localStorage.getItem('nfse_token');
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(url, { headers });
    if (!res.ok) throw new Error(await res.text());
    const blob = await res.blob();
    const objUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objUrl);
}

export async function downloadBatchTemplate(fmt = 'xlsx') {
    try {
        await fetchDownloadWithAuth(
            `/api/batch-emission/template?format=${encodeURIComponent(fmt)}`,
            `modelo_emissao_nfse_lote.${fmt}`
        );
    } catch (e) {
        await uiAlert({ title: 'Erro ao baixar modelo', message: e.message, variant: 'error' });
    }
}

export async function uploadBatchSpreadsheet(inputEl) {
    const file = inputEl?.files?.[0];
    if (!file) return;
    const clientId = state.getGlobalClientId();
    if (!clientId) {
        inputEl.value = '';
        await uiAlert({ title: 'Empresa não selecionada', message: 'Selecione a empresa Prestadora no topo antes de importar a planilha de notas.', variant: 'warning' });
        return;
    }

    const delimiter = document.getElementById('batch-csv-delimiter')?.value || '';
    const formData = new FormData();
    formData.append('client_id', String(clientId));
    formData.append('file', file);
    if (delimiter) formData.append('delimiter', delimiter);
    formData.append('auto_validate', 'true');

    try {
        showTaskToast('Importando Lote', `Lendo e validando ${file.name} sem transmitir...`, { autoProgress: true });
        const batch = await api('/batch-emission/import', 'POST', formData);
        completeTaskToast('Lote Importado', `${batch.total_items} linha(s) lida(s) (${batch.valid_items} válida(s)).`, 4000);
        activeBatchId = batch.id;
        await loadBatchImports();
        await openBatchDetail(batch.id);
    } catch (e) {
        failTaskToast('Falha na Importação', e.message);
        await uiAlert({ title: 'Erro ao importar planilha de notas', message: e.message, variant: 'error' });
    } finally {
        if (inputEl) inputEl.value = '';
    }
}

export async function loadBatchImports() {
    const tbody = document.getElementById('batch-history-tbody');
    if (!tbody) return;
    const clientId = state.getGlobalClientId();
    const qs = clientId ? `?client_id=${clientId}` : '';

    try {
        const batches = await api(`/batch-emission${qs}`);
        if (!batches || batches.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--text3); padding:14px;">Nenhum lote de planilha importado ainda.</td></tr>`;
            return;
        }
        tbody.innerHTML = batches.map(b => `
            <tr>
              <td style="font-weight:500;">${escapeHtml(b.filename)}</td>
              <td><span class="status-badge">${escapeHtml(b.status)}</span></td>
              <td>${b.total_items}</td>
              <td><span style="color:var(--green);">${b.valid_items}</span> / <span style="color:var(--red);">${b.invalid_items}</span></td>
              <td>${b.authorized_items} / ${b.rejected_items} / ${b.unknown_items}</td>
              <td style="font-size:11.5px; color:var(--text3);">${(b.created_at || '').slice(0, 16).replace('T', ' ')}</td>
              <td>
                <div class="table-actions-inline">
                  <button type="button" class="btn btn-secondary btn-sm" onclick="App.openBatchDetail('${b.id}')">Revisar</button>
                  <button type="button" class="btn btn-secondary btn-sm btn-action-danger" onclick="App.deleteBatch('${b.id}')" title="Excluir lote completo">Excluir</button>
                </div>
              </td>
            </tr>
        `).join('');
    } catch (e) {
        console.warn('Erro ao carregar histórico de lotes:', e);
    }
}

export async function openBatchDetail(batchId) {
    activeBatchId = batchId;
    const box = document.getElementById('batch-detail-box');
    if (box) box.style.display = 'block';
    try {
        const batch = await api(`/batch-emission/${batchId}`);
        const titleEl = document.getElementById('batch-detail-title');
        const metaEl = document.getElementById('batch-detail-meta');
        if (titleEl) titleEl.textContent = `Lote: ${batch.filename} [${batch.status}]`;
        if (metaEl) {
            metaEl.textContent = `Total: ${batch.total_items} | Válidas: ${batch.valid_items} | Inválidas: ${batch.invalid_items} | Autorizadas: ${batch.authorized_items} | Rejeitadas: ${batch.rejected_items} | Unknown: ${batch.unknown_items}`;
        }
        await loadBatchItems();
    } catch (e) {
        await uiAlert({ title: 'Erro ao abrir lote', message: e.message, variant: 'error' });
    }
}

export async function loadBatchItems() {
    if (!activeBatchId) return;
    const tbody = document.getElementById('batch-items-tbody');
    if (!tbody) return;
    const statusFilter = document.getElementById('batch-item-status-filter')?.value || '';
    const qs = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : '';

    try {
        const items = await api(`/batch-emission/${activeBatchId}/items${qs}`);
        cachedBatchItems = items || [];
        if (cachedBatchItems.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--text3); padding:16px;">Nenhum item encontrado para o filtro selecionado.</td></tr>`;
            updateBatchSelectionCount();
            return;
        }
        const masterCheck = document.getElementById('batch-items-check-all');
        if (masterCheck) masterCheck.checked = false;

        tbody.innerHTML = cachedBatchItems.map(it => {
            const p = it.payload || {};
            const deletable = it.status !== 'PROCESSING';
            const editable = !['AUTHORIZED', 'PROCESSING', 'UNKNOWN', 'CANCELLED'].includes(it.status);
            const errs = (it.validation_errors || []).map(e => `[${e.field}] ${e.message}`).join(' | ');
            const diag = errs || it.last_error || (it.status === 'VALID' ? 'Pronta para emissão' : '-');
            return `
                <tr>
                  <td>${deletable ? `<input type="checkbox" class="batch-item-check" value="${it.id}" data-status="${escapeHtml(it.status)}" onchange="App.updateBatchSelectionCount()">` : ''}</td>
                  <td>#${it.row_number}</td>
                  <td>
                    <div style="font-weight:500;">${escapeHtml(p.nome_tomador || '-')}</div>
                    <div style="font-family:var(--mono); font-size:11px; color:var(--text3);">${escapeHtml(p.documento_tomador || '-')}</div>
                  </td>
                  <td style="font-size:12px;">${escapeHtml(p.competencia || '-')}</td>
                  <td style="font-weight:600;">${fmtBRL(p.valor_servico)}</td>
                  <td>
                    <span class="status-badge">${escapeHtml(it.status)}</span>
                    <div style="font-size:11px; color:${errs || it.status === 'REJECTED' || it.status === 'UNKNOWN' ? 'var(--red)' : 'var(--text3)'}; margin-top:3px;">
                      ${escapeHtml(diag)}
                    </div>
                  </td>
                  <td style="font-family:var(--mono); font-size:11px;">${escapeHtml(it.chave_acesso || it.id_dps || '-')}</td>
                  <td>
                    <div class="table-actions-inline">
                      ${editable ? `<button type="button" class="btn btn-secondary btn-sm" onclick="App.openBatchItemEditor('${it.id}')">Corrigir</button>` : ''}
                      ${deletable ? `<button type="button" class="btn btn-secondary btn-sm btn-action-danger" onclick="App.deleteBatchItem('${it.id}')" title="Excluir linha">Excluir</button>` : ''}
                    </div>
                  </td>
                </tr>
            `;
        }).join('');
        updateBatchSelectionCount();
    } catch (e) {
        await uiAlert({ title: 'Erro ao listar itens do lote', message: e.message, variant: 'error' });
    }
}

export function toggleAllBatchItems(master) {
    const checked = Boolean(master?.checked);
    document.querySelectorAll('.batch-item-check').forEach(cb => {
        cb.checked = checked;
    });
    updateBatchSelectionCount();
}

export function openBatchItemEditor(itemId) {
    const it = cachedBatchItems.find(x => x.id === itemId);
    if (!it) return;
    const p = it.payload || {};
    document.getElementById('batch-edit-item-id').value = it.id;
    document.getElementById('batch-edit-title').textContent = `Corrigir Linha #${it.row_number} (${it.status})`;
    document.getElementById('batch-edit-doc').value = p.documento_tomador || '';
    document.getElementById('batch-edit-nome').value = p.nome_tomador || '';
    document.getElementById('batch-edit-valor').value = p.valor_servico ?? '';
    document.getElementById('batch-edit-ctribnac').value = p.c_trib_nac || '';
    document.getElementById('batch-edit-competencia').value = (p.competencia || '').slice(0, 10);
    document.getElementById('batch-edit-municipio').value = p.municipio_prestacao || '';
    document.getElementById('batch-edit-discriminacao').value = p.discriminacao || p.descricao_servico || '';
    document.getElementById('batch-item-editor').style.display = 'block';
}

export function closeBatchItemEditor() {
    const ed = document.getElementById('batch-item-editor');
    if (ed) ed.style.display = 'none';
}

export async function saveBatchItemCorrection() {
    if (!activeBatchId) return;
    const itemId = document.getElementById('batch-edit-item-id')?.value;
    if (!itemId) return;

    const payload = {
        documento_tomador: document.getElementById('batch-edit-doc')?.value,
        nome_tomador: document.getElementById('batch-edit-nome')?.value,
        valor_servico: parseFloat(document.getElementById('batch-edit-valor')?.value || '0'),
        c_trib_nac: document.getElementById('batch-edit-ctribnac')?.value || undefined,
        competencia: document.getElementById('batch-edit-competencia')?.value || undefined,
        municipio_prestacao: document.getElementById('batch-edit-municipio')?.value || undefined,
        discriminacao: document.getElementById('batch-edit-discriminacao')?.value || undefined,
    };

    try {
        await api(`/batch-emission/${activeBatchId}/items/${itemId}`, 'PATCH', payload);
        closeBatchItemEditor();
        await loadBatchImports();
        await openBatchDetail(activeBatchId);
    } catch (e) {
        await uiAlert({ title: 'Erro ao corrigir item', message: e.message, variant: 'error' });
    }
}

export async function revalidateActiveBatch() {
    if (!activeBatchId) return;
    try {
        showTaskToast('Validando Lote', 'Reexecutando validação estrutural, cadastral e fiscal/XSD...', { autoProgress: true });
        await api(`/batch-emission/${activeBatchId}/validate`, 'POST');
        completeTaskToast('Validação Concluída', 'Lote revalidado com sucesso.', 3500);
        await loadBatchImports();
        await openBatchDetail(activeBatchId);
    } catch (e) {
        failTaskToast('Erro ao Revalidar', e.message);
        await uiAlert({ title: 'Erro ao revalidar lote', message: e.message, variant: 'error' });
    }
}

export async function processActiveBatch() {
    if (!activeBatchId) return;
    const checkedBoxes = Array.from(document.querySelectorAll('.batch-item-check:checked'));
    const eligibleCheckedIds = checkedBoxes
        .filter(cb => cb.dataset.status === 'VALID' || cb.dataset.status === 'RETRY')
        .map(cb => cb.value);

    let itemIdsToProcess = eligibleCheckedIds;
    if (checkedBoxes.length === 0) {
        // Se nada estiver marcado, usa todos os itens VALID/RETRY disponíveis no lote carregado
        itemIdsToProcess = cachedBatchItems
            .filter(it => it.status === 'VALID' || it.status === 'RETRY')
            .map(it => it.id);
    }

    if (itemIdsToProcess.length === 0) {
        await uiAlert({ title: 'Nenhum item elegível', message: 'Nenhum item elegível (VALID ou RETRY) selecionado ou disponível para emitir.', variant: 'warning' });
        return;
    }
    const transmitir = document.getElementById('batch-transmitir')?.checked ?? true;
    const enviarEmail = document.getElementById('batch-enviar-email')?.checked ?? false;
    const confirmed = await uiConfirm({
        title: 'Confirmar Emissão em Lote',
        message: `Confirma processar ${itemIdsToProcess.length} nota(s) válida(s)?`,
        infoBadge: transmitir ? 'Transmissão online habilitada para o Ambiente Nacional (ADN).' : 'Modo offline: as DPS serão assinadas e salvas sem transmitir.',
        confirmText: `Processar ${itemIdsToProcess.length} Nota(s)`,
        variant: 'primary',
    });
    if (!confirmed) return;

    try {
        showTaskToast('Processando Lote', `Emitindo ${itemIdsToProcess.length} nota(s) sequencialmente...`, { autoProgress: true });
        await api(`/batch-emission/${activeBatchId}/process`, 'POST', {
            item_ids: itemIdsToProcess,
            transmitir,
            enviar_email: enviarEmail,
        });
        completeTaskToast('Lote Processado', `${itemIdsToProcess.length} nota(s) processada(s).`, 4500);
        await loadBatchImports();
        await openBatchDetail(activeBatchId);
        await window.App?.loadFilaContingencia?.();
    } catch (e) {
        failTaskToast('Erro no Lote', e.message);
        await uiAlert({ title: 'Erro no processamento do lote', message: e.message, variant: 'error' });
    }
}

export async function deleteBatch(batchId) {
    const confirmed = await uiConfirm({
        title: 'Excluir Lote Importado',
        message: 'Excluir este lote e todos os seus itens?',
        infoBadge: 'Pendências na fila de contingência ligadas a ele também serão removidas; notas já autorizadas permanecem no cofre.',
        confirmText: 'Excluir Lote',
        variant: 'danger',
        icon: 'trash',
    });
    if (!confirmed) return;
    try {
        await api(`/batch-emission/${batchId}`, 'DELETE');
        if (activeBatchId === batchId) {
            activeBatchId = null;
            cachedBatchItems = [];
            const box = document.getElementById('batch-detail-box');
            if (box) box.style.display = 'none';
        }
        await loadBatchImports();
        await window.App?.loadFilaContingencia?.();
        completeTaskToast('Lote Excluído', 'Lote removido com sucesso.', 3000);
    } catch (e) {
        await uiAlert({ title: 'Erro ao excluir lote', message: e.message, variant: 'error' });
    }
}

export async function deleteBatchItem(itemId) {
    if (!activeBatchId) return;
    const confirmed = await uiConfirm({
        title: 'Excluir Item do Lote',
        message: 'Excluir este item do lote e remover eventual pendência da fila de contingência?',
        confirmText: 'Excluir Item',
        variant: 'danger',
        icon: 'trash',
    });
    if (!confirmed) return;
    try {
        await api(`/batch-emission/${activeBatchId}/items/${itemId}`, 'DELETE');
        await loadBatchImports();
        await openBatchDetail(activeBatchId);
        await window.App?.loadFilaContingencia?.();
    } catch (e) {
        await uiAlert({ title: 'Erro ao excluir item', message: e.message, variant: 'error' });
    }
}

export async function deleteSelectedBatchItems() {
    if (!activeBatchId) return;
    const selectedIds = Array.from(document.querySelectorAll('.batch-item-check:checked')).map(cb => cb.value);
    if (selectedIds.length === 0) {
        await uiAlert({ title: 'Nenhum item marcado', message: 'Marque pelo menos um item para excluir.', variant: 'warning' });
        return;
    }
    const confirmed = await uiConfirm({
        title: 'Excluir Itens Selecionados',
        message: `Excluir os ${selectedIds.length} item(ns) selecionado(s) deste lote e eventuais pendências na fila?`,
        confirmText: `Excluir ${selectedIds.length} Item(ns)`,
        variant: 'danger',
        icon: 'trash',
    });
    if (!confirmed) return;
    try {
        await api(`/batch-emission/${activeBatchId}/items/delete`, 'POST', {
            item_ids: selectedIds,
            delete_all: false,
        });
        await loadBatchImports();
        await openBatchDetail(activeBatchId);
        await window.App?.loadFilaContingencia?.();
    } catch (e) {
        await uiAlert({ title: 'Erro ao excluir itens selecionados', message: e.message, variant: 'error' });
    }
}

export async function deleteAllBatchItems() {
    if (!activeBatchId) return;
    const confirmed = await uiConfirm({
        title: 'Excluir Todos os Itens',
        message: 'Excluir TODOS os itens importados deste lote e eventuais pendências na fila?',
        confirmText: 'Excluir Todos',
        variant: 'danger',
        icon: 'trash',
    });
    if (!confirmed) return;
    try {
        await api(`/batch-emission/${activeBatchId}/items/delete`, 'POST', {
            delete_all: true,
        });
        await loadBatchImports();
        await openBatchDetail(activeBatchId);
        await window.App?.loadFilaContingencia?.();
    } catch (e) {
        await uiAlert({ title: 'Erro ao excluir todos os itens', message: e.message, variant: 'error' });
    }
}

export async function retryActiveBatch() {
    if (!activeBatchId) return;
    const transmitir = document.getElementById('batch-transmitir')?.checked ?? true;
    try {
        showTaskToast('Consultando / Reprocessando', 'Verificando notas UNKNOWN no ADN e reenviando elegíveis...', { autoProgress: true });
        await api(`/batch-emission/${activeBatchId}/retry`, 'POST', { transmitir });
        completeTaskToast('Reprocessamento Concluído', 'Status do lote atualizado.', 3500);
        await loadBatchImports();
        await openBatchDetail(activeBatchId);
        await window.App?.loadFilaContingencia?.();
    } catch (e) {
        failTaskToast('Erro ao Reprocessar', e.message);
        await uiAlert({ title: 'Erro ao consultar/reprocessar lote', message: e.message, variant: 'error' });
    }
}

export async function cancelActiveBatch() {
    if (!activeBatchId) return;
    const confirmed = await uiConfirm({
        title: 'Cancelar Itens Pendentes',
        message: 'Cancelar os itens pendentes deste lote? Notas já enviadas ou autorizadas não serão afetadas.',
        confirmText: 'Cancelar Pendentes',
        variant: 'warning',
    });
    if (!confirmed) return;
    try {
        await api(`/batch-emission/${activeBatchId}/cancel`, 'POST');
        await loadBatchImports();
        await openBatchDetail(activeBatchId);
    } catch (e) {
        await uiAlert({ title: 'Erro ao cancelar lote', message: e.message, variant: 'error' });
    }
}

export async function exportActiveBatch(fmt = 'xlsx') {
    if (!activeBatchId) return;
    try {
        await fetchDownloadWithAuth(
            `/api/batch-emission/${activeBatchId}/export?format=${encodeURIComponent(fmt)}`,
            `resultado_lote_${activeBatchId.slice(0, 8)}.${fmt}`
        );
    } catch (e) {
        await uiAlert({ title: 'Erro ao exportar lote', message: e.message, variant: 'error' });
    }
}
