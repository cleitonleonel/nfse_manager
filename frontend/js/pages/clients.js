import { api } from '../core/api.js';
import { state } from '../core/state.js';
import { openModal, closeModal } from '../core/ui.js';

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

export function renderClients() {
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
    
    tbody.innerHTML = state.clients.map(c => `
        <tr>
            <td style="font-family:var(--mono);">${c.cnpj}</td>
            <td style="font-weight:500;">${c.razao_social}</td>
            <td style="color:var(--text3);">${c.description || '-'}</td>
            <td>
                <div style="display:flex; gap:8px;">
                    <button class="btn-action" onclick="App.editClient(${c.id})" title="Editar"><svg viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg></button>
                    <button class="btn-action" onclick="App.deleteClient(${c.id})" title="Excluir"><svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button>
                </div>
            </td>
        </tr>
    `).join('');
}

export function editClient(id) {
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
    
    try {
        if (editId) {
            const data = new FormData();
            data.append('razao_social', razao_social);
            data.append('description', descricao);
            data.append('save_path', save_path);
            data.append('path_structure', path_structure);
            
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
            
            await api(`/clients/${editId}`, 'PUT', data);
            delete modalEl.dataset.editId;
        } else {
            const data = new FormData();
            data.append('cnpj', cnpj);
            data.append('razao_social', razao_social);
            data.append('description', descricao);
            data.append('save_path', save_path);
            data.append('path_structure', path_structure);
            
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
        
        ['c-cnpj','c-razao','c-desc','c-user','c-pass','c-cert-pass', 'c-save-path', 'c-path-structure'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.value = '';
            }
        });
        const certFile = document.getElementById('c-cert-file');
        if (certFile) {
            certFile.value = '';
        }
        const certName = document.getElementById('c-cert-name');
        if (certName) {
            certName.textContent = 'Nenhum arquivo...';
        }
        
        await loadClients();
    } catch (e) {
        alert("Erro ao salvar cliente: " + e.message);
    }
}

export async function deleteClient(id) {
    if (confirm('Tem certeza que deseja excluir este cliente? Todas as notas associadas serão perdidas.')) {
        try {
            await api(`/clients/${id}`, 'DELETE');
            await loadClients();
        } catch (e) {
            alert("Erro: " + e.message);
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
