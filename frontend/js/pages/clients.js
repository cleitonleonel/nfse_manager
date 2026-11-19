import { api } from '../core/api.js';
import { state } from '../core/state.js';
import { openModal, closeModal, uiAlert, uiConfirm, completeTaskToast } from '../core/ui.js';

export async function loadClients() {
    state.clients = await api('/clients');
    renderClients();
    
    const menu = document.getElementById('global-client-menu');
    if (menu) {
        const baseItem = `
            <a href="#" class="dropdown-item" onclick="App.setGlobalClient('', 'Todos os Clientes (Visão Geral)'); return false;">
                <svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
                Todos os Clientes (Visão Geral)
            </a>
        `;
        const clientItems = state.clients.map(c => {
            const safeName = c.razao_social.replace(/'/g, "\\'");
            return `
                <a href="#" class="dropdown-item" onclick="App.setGlobalClient('${c.id}', '${safeName}'); return false;">
                    <svg viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                    ${c.razao_social}
                </a>
            `;
        }).join('');
        menu.innerHTML = baseItem + clientItems;
    }
    
    if (window.App && window.App.loadDashboardStats) {
        window.App.loadDashboardStats();
    }
}

function isCurrentUserAdmin() {
    try {
        const raw = localStorage.getItem('nfse_user');
        return raw ? JSON.parse(raw)?.role === 'admin' : false;
    } catch (_) {
        return false;
    }
}

export function syncClientSavePathVisibility() {
    const group = document.getElementById('c-save-path-group');
    if (group) {
        group.style.display = isCurrentUserAdmin() ? 'block' : 'none';
    }
}

export function renderClients() {
    syncClientSavePathVisibility();
    const tbody = document.getElementById('clients-table-body');
    if (!tbody) return;
    
    if (state.clients.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="4">
                    <div class="empty-state">
                        <svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>
                        <div class="empty-state-title">Nenhum cliente cadastrado</div>
                        <div class="empty-state-desc">Adicione o primeiro cliente para começar a sincronizar as notas fiscais.</div>
                        <button class="btn btn-primary" onclick="App.openModal('modal-client')">Novo Cliente</button>
                    </div>
                </td>
            </tr>
        `;
        return;
    }
    
    tbody.innerHTML = state.clients.map(c => {
        let certBadge = '';
        if (c.status_certificado === 'vencido') {
            certBadge = `<span class="badge" style="background:rgba(239,68,68,0.15); color:var(--red);">❌ A1 Vencido</span>`;
        } else if (c.status_certificado === 'expirando') {
            certBadge = `<span class="badge" style="background:rgba(245,158,11,0.15); color:#f59e0b;">⚠️ A1 (${c.dias_para_vencer}d)</span>`;
        } else if (c.status_certificado === 'valido') {
            certBadge = `<span class="badge" style="background:rgba(16,185,129,0.15); color:var(--green);">✓ A1 (${c.dias_para_vencer}d)</span>`;
        }
        const smtpBadge = c.smtp_configurado
            ? `<span class="badge" style="background:rgba(59,130,246,0.15); color:var(--accent);">SMTP ✓</span>`
            : '';
        return `
        <tr>
            <td style="font-family:var(--mono); white-space:nowrap;">${c.cnpj}</td>
            <td style="font-weight:500;">
                <div style="display:flex; align-items:center; flex-wrap:wrap; gap:6px;">
                    <span>${c.razao_social}</span>
                    ${certBadge}${smtpBadge}
                </div>
            </td>
            <td style="color:var(--text3);">${c.description || '-'}</td>
            <td>
                <div style="display:flex; gap:8px;">
                    <button class="btn-action" onclick="App.editClient(${c.id})" title="Editar"><svg viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>
                    <button class="btn-action" onclick="App.deleteClient(${c.id})" title="Excluir"><svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button>
                </div>
            </td>
        </tr>
    `;
    }).join('');
}

export function editClient(id) {
    syncClientSavePathVisibility();
    const c = state.clients.find(x => x.id === id);
    if (!c) return;
    
    // Mark modal as edit mode
    const modal = document.getElementById('modal-client');
    modal.dataset.editId = id;
    
    // Prefill fields
    document.getElementById('c-cnpj').value = c.cnpj;
    document.getElementById('c-razao').value = c.razao_social;
    document.getElementById('c-desc').value = c.description || '';
    document.getElementById('c-user').value = c.username || '';
    // Password not returned by API for security - leave empty (no change if blank on submit)
    document.getElementById('c-pass').value = '';
    document.getElementById('c-save-path').value = c.save_path || '';
    document.getElementById('c-path-structure').value = c.path_structure || '';

    // Campos de E-mail & SMTP do Prestador
    document.getElementById('c-email').value = c.email || '';
    document.getElementById('c-smtp-host').value = c.smtp_host || '';
    document.getElementById('c-smtp-port').value = c.smtp_port ?? 587;
    document.getElementById('c-smtp-user').value = c.smtp_user || '';
    document.getElementById('c-smtp-from').value = c.smtp_from || '';
    const smtpPassEl = document.getElementById('c-smtp-pass');
    if (smtpPassEl) {
        smtpPassEl.value = '';
        delete smtpPassEl.dataset.usingDefault;
        smtpPassEl.placeholder = c.smtp_configurado
            ? 'Deixe em branco para manter a senha salva'
            : 'Senha / App Password SMTP';
    }
    const tlsEl = document.getElementById('c-smtp-tls');
    if (tlsEl) tlsEl.checked = c.smtp_tls !== 0;
    const autoEl = document.getElementById('c-auto-email');
    if (autoEl) autoEl.checked = Boolean(c.enviar_email_automatico);
    const smtpBadge = document.getElementById('c-smtp-status-badge');
    if (smtpBadge) {
        smtpBadge.style.display = c.smtp_configurado ? 'inline-block' : 'none';
        smtpBadge.style.background = 'rgba(16,185,129,0.15)';
        smtpBadge.style.color = 'var(--green)';
        smtpBadge.textContent = 'SMTP Configurado ✓';
    }
    
    // Update modal title
    const title = modal.querySelector('.modal-header h3');
    if (title) title.innerText = 'Editar Cliente';
    
    openModal('modal-client');
}

export async function saveClient() {
    const modalEl = document.getElementById('modal-client');
    const editId = modalEl.dataset.editId;
    
    const cnpj = document.getElementById('c-cnpj').value;
    const razao_social = document.getElementById('c-razao').value;
    const descricao = document.getElementById('c-desc').value;
    const save_path = document.getElementById('c-save-path').value;
    const path_structure = document.getElementById('c-path-structure').value;

    const appendSmtpAndEmailFields = (formData, isEdit) => {
        const email = document.getElementById('c-email')?.value || '';
        const smtpHost = document.getElementById('c-smtp-host')?.value || '';
        const smtpPort = document.getElementById('c-smtp-port')?.value || '587';
        const smtpUser = document.getElementById('c-smtp-user')?.value || '';
        const smtpPass = document.getElementById('c-smtp-pass')?.value || '';
        const smtpFrom = document.getElementById('c-smtp-from')?.value || '';
        const smtpTls = document.getElementById('c-smtp-tls')?.checked ?? true;
        const autoEmail = document.getElementById('c-auto-email')?.checked ?? false;
        const usingDefault = document.getElementById('c-smtp-pass')?.dataset?.usingDefault === '1';

        formData.append('email', email);
        formData.append('smtp_host', smtpHost);
        formData.append('smtp_port', smtpPort || '587');
        formData.append('smtp_user', smtpUser);
        if (usingDefault && smtpPass === '') {
            formData.append('usar_smtp_padrao', 'true');
        } else if (!isEdit || smtpPass !== '') {
            formData.append('smtp_password', smtpPass);
        }
        formData.append('smtp_from', smtpFrom);
        formData.append('smtp_tls', smtpTls ? '1' : '0');
        formData.append('enviar_email_automatico', autoEmail ? '1' : '0');
    };
    
    try {
        if (editId) {
            const data = new FormData();
            data.append('razao_social', razao_social);
            data.append('description', descricao);
            if (isCurrentUserAdmin()) {
                data.append('save_path', save_path);
            }
            data.append('path_structure', path_structure);
            appendSmtpAndEmailFields(data, true);
            
            const authType = document.querySelector('input[name="auth_type"]:checked').value;
            if (authType === 'portal') {
                data.append('username', document.getElementById('c-user').value);
                const portalPass = document.getElementById('c-pass').value;
                if (portalPass) data.append('password', portalPass);
            } else {
                const certFile = document.getElementById('c-cert-file').files[0];
                if (certFile) {
                    data.append('cert_file', certFile);
                }
                const certPass = document.getElementById('c-cert-pass').value;
                if (certPass) data.append('cert_password', certPass);
            }
            
            await api(`/clients/${editId}`, 'PUT', data);
            delete modalEl.dataset.editId;
        } else {
            const data = new FormData();
            data.append('cnpj', cnpj);
            data.append('razao_social', razao_social);
            data.append('description', descricao);
            if (isCurrentUserAdmin() && save_path) {
                data.append('save_path', save_path);
            }
            data.append('path_structure', path_structure);
            appendSmtpAndEmailFields(data, false);
            
            const authType = document.querySelector('input[name="auth_type"]:checked').value;
            if (authType === 'portal') {
                data.append('username', document.getElementById('c-user').value);
                data.append('password', document.getElementById('c-pass').value);
            } else {
                const certFile = document.getElementById('c-cert-file').files[0];
                if (certFile) {
                    data.append('cert_file', certFile);
                }
                data.append('cert_password', document.getElementById('c-cert-pass').value);
            }
            await api('/clients', 'POST', data);
        }
        
        closeModal('modal-client');
        const title = document.querySelector('#modal-client .modal-header h3');
        if (title) {
            title.innerText = 'Adicionar Novo Cliente';
        }
        
        [
            'c-cnpj', 'c-razao', 'c-desc', 'c-user', 'c-pass', 'c-cert-pass',
            'c-save-path', 'c-path-structure', 'c-email', 'c-smtp-host',
            'c-smtp-user', 'c-smtp-pass', 'c-smtp-from'
        ].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.value = '';
            }
        });
        const smtpPortEl = document.getElementById('c-smtp-port');
        if (smtpPortEl) smtpPortEl.value = '587';
        const smtpTlsEl = document.getElementById('c-smtp-tls');
        if (smtpTlsEl) smtpTlsEl.checked = true;
        const autoEmailEl = document.getElementById('c-auto-email');
        if (autoEmailEl) autoEmailEl.checked = false;
        const smtpBadge = document.getElementById('c-smtp-status-badge');
        if (smtpBadge) smtpBadge.style.display = 'none';
        const smtpPassReset = document.getElementById('c-smtp-pass');
        if (smtpPassReset) {
            delete smtpPassReset.dataset.usingDefault;
            smtpPassReset.placeholder = 'Senha SMTP';
        }
        const certFile = document.getElementById('c-cert-file');
        if (certFile) {
            certFile.value = '';
        }
        const certName = document.getElementById('c-cert-name');
        if (certName) {
            certName.textContent = 'Nenhum arquivo...';
        }
        
        await loadClients();
        completeTaskToast('Cliente Salvo', 'Cadastro da empresa atualizado com sucesso.', 3500);
    } catch (e) {
        await uiAlert({ title: 'Erro ao salvar cliente', message: e.message, variant: 'error' });
    }
}

export async function deleteClient(id) {
    const confirmed = await uiConfirm({
        title: 'Excluir Cliente Permanentemente',
        message: 'Tem certeza que deseja excluir este cliente? Toda a configuração, notas e arquivos físicos (certificados e downloads) serão apagados permanentemente.',
        confirmText: 'Sim, Excluir Tudo',
        cancelText: 'Cancelar',
        variant: 'danger',
        icon: 'trash',
    });
    if (confirmed) {
        try {
            await api(`/clients/${id}`, 'DELETE');
            
            // Se o cliente excluído estava ativo no filtro global, reseta para Todos os Clientes
            const currentSelected = state.getGlobalClientId();
            if (String(currentSelected) === String(id)) {
                state.setGlobalClient('', 'Todos os Clientes (Visão Geral)');
            }
            
            // Recarrega lista de clientes na tabela e no dropdown
            await loadClients();
            completeTaskToast('Cliente Excluído', 'Empresa e registros vinculados removidos.', 3500);
            
            // Atualiza estatísticas, gráficos, ranking e lista de notas em tempo real
            if (window.App) {
                if (window.App.loadDashboardStats) window.App.loadDashboardStats();
                if (window.App.loadDashboardChart) window.App.loadDashboardChart(window.App.chartPeriod || '12m');
                if (window.App.loadRanking) window.App.loadRanking();
                if (window.App.activePage === 'invoices' && window.App.loadInvoices) {
                    window.App.loadInvoices();
                }
            }
        } catch (e) {
            await uiAlert({ title: 'Erro ao excluir cliente', message: e.message, variant: 'error' });
        }
    }
}

export function toggleAuthType() {
    const authType = document.querySelector('input[name="auth_type"]:checked').value;
    const authPortal = document.getElementById('auth-portal');
    const authCert = document.getElementById('auth-cert');
    if (authPortal) authPortal.style.display = authType === 'portal' ? 'grid' : 'none';
    if (authCert) authCert.style.display = authType === 'cert' ? 'grid' : 'none';
}

export function addPathTag(tag) {
    const input = document.getElementById('c-path-structure');
    if (!input) return;
    
    let val = input.value.trim();
    if (val && !val.endsWith('/') && !val.endsWith('\\')) {
        val += ' / ';
    }
    input.value = val + tag + ' / ';
    input.focus();
}

export function handlePathKey(e, input) {
    if (e.key === 'Enter' || e.key === ',') {
        e.preventDefault();
        let val = input.value.trim();
        if (val && !val.endsWith('/') && !val.endsWith('\\')) {
            input.value = val + ' / ';
        }
    }
}

export async function toggleExplorer() {
    const explorer = document.getElementById('folder-explorer');
    const btn = document.getElementById('btn-toggle-explorer');
    if (!explorer) return;
    
    if (explorer.style.display === 'none') {
        explorer.style.display = 'block';
        btn.innerText = 'Fechar';
        await browseFolders();
    } else {
        explorer.style.display = 'none';
        btn.innerText = 'Explorar';
    }
}

export async function browseFolders(path = null) {
    const list = document.getElementById('explorer-list');
    const current = document.getElementById('explorer-current');
    if (!list || !current) return;
    
    try {
        list.innerHTML = `<div style="padding:10px; font-size:11px; color:var(--text3);">Carregando...</div>`;
        const res = await api(`/system/list-folders${path ? '?path=' + encodeURIComponent(path) : ''}`);
        
        state.lastExploredPath = res.current;
        current.innerText = res.current;
        
        if (!res.folders || res.folders.length === 0) {
            list.innerHTML = `<div style="padding:10px; font-size:11px; color:var(--text3);">Vazio.</div>`;
            return;
        }

        list.innerHTML = res.folders.map(f => `
            <div class="explorer-item" onclick="App.browseFolders('${f.path.replace(/\\/g, '/')}')" style="padding:4px 8px; cursor:pointer; border-radius:4px; display:flex; align-items:center; gap:8px;">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="${f.is_up ? 'var(--text3)' : 'var(--accent)'}" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
                <span style="font-size:12px; color:var(--text2); font-weight:${f.is_up ? '400' : '500'}">${f.name}</span>
            </div>
        `).join('');

        list.querySelectorAll('.explorer-item').forEach(item => {
            item.onmouseover = () => item.style.background = 'var(--bg4)';
            item.onmouseout = () => item.style.background = 'transparent';
        });

    } catch (e) {
        list.innerHTML = `<div style="padding:10px; font-size:11px; color:var(--red);">Erro ao carregar.</div>`;
    }
}

export function selectCurrentFolder() {
    if (state.lastExploredPath) {
        const input = document.getElementById('c-save-path');
        if (input) input.value = state.lastExploredPath;
        toggleExplorer();
    }
}

export async function usarSmtpPadrao() {
    try {
        const res = await api('/clients/smtp/padrao');
        if (!res.has_env_values && !res.has_password) {
            await uiAlert({
                title: 'SMTP padrão não definido',
                message: 'Nenhuma configuração SMTP padrão foi definida no arquivo .env (DEFAULT_SMTP_HOST / DEFAULT_SMTP_USER / DEFAULT_SMTP_PASSWORD). Preencha manualmente ou configure o .env.',
                variant: 'warning',
            });
            return;
        }

        if (res.smtp_host) document.getElementById('c-smtp-host').value = res.smtp_host;
        document.getElementById('c-smtp-port').value = res.smtp_port || 587;
        if (res.smtp_user) document.getElementById('c-smtp-user').value = res.smtp_user;
        if (res.smtp_from) document.getElementById('c-smtp-from').value = res.smtp_from;
        const emailEl = document.getElementById('c-email');
        if (emailEl && !emailEl.value.trim()) {
            emailEl.value = res.smtp_from || res.smtp_user || '';
        }
        const tlsEl = document.getElementById('c-smtp-tls');
        if (tlsEl) tlsEl.checked = Boolean(res.smtp_tls);

        const passEl = document.getElementById('c-smtp-pass');
        if (passEl) {
            passEl.value = '';
            if (res.has_password) {
                passEl.dataset.usingDefault = '1';
                passEl.placeholder = 'Usando senha padrão do .env ✓ (ou digite outra)';
            } else {
                delete passEl.dataset.usingDefault;
                passEl.placeholder = 'Informe a senha SMTP (DEFAULT_SMTP_PASSWORD vazio)';
            }
        }

        const badge = document.getElementById('c-smtp-status-badge');
        if (badge) {
            badge.style.display = 'inline-block';
            badge.style.background = res.configured ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.15)';
            badge.style.color = res.configured ? 'var(--green)' : 'var(--amber)';
            badge.textContent = res.configured ? 'Padrão .env carregado ✓' : 'Parcial (.env sem senha)';
        }
    } catch (e) {
        await uiAlert({ title: 'Erro ao carregar SMTP padrão', message: e.message, variant: 'error' });
    }
}
