import { api } from '../core/api.js';
import { state } from '../core/state.js';
import { enhanceSelects } from '../core/custom-select.js';
import { openModal, closeModal, completeTaskToast, uiAlert, uiConfirm, escapeAttr, formatCnpj } from '../core/ui.js';

let cachedUsers = [];
let operatorRoleBound = false;
let operatorSelectedClientIds = new Set();

function getStoredUser() {
    try {
        const raw = localStorage.getItem('nfse_user');
        return raw ? JSON.parse(raw) : null;
    } catch (_) {
        return null;
    }
}

function getInitials(user) {
    const label = (user?.full_name || user?.username || 'OP').trim();
    const parts = label.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }
    return label.slice(0, 2).toUpperCase();
}

export async function loadUsers() {
    const tbody = document.getElementById('users-table-body');
    const me = getStoredUser();
    if (!me || me.role !== 'admin') {
        return;
    }

    try {
        const [list, clients] = await Promise.all([
            api('/auth/users'),
            Array.isArray(state.clients) && state.clients.length > 0 ? Promise.resolve(state.clients) : api('/clients').catch(() => []),
        ]);
        if (Array.isArray(clients) && clients.length > 0) {
            state.clients = clients;
        }
        cachedUsers = Array.isArray(list) ? list : [];
        filterUsersTable();
    } catch (e) {
        if (tbody) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" style="text-align:center; color:var(--red-text); padding:24px;">
                        Não foi possível carregar os operadores: ${escapeAttr(e?.message || 'Erro desconhecido')}
                    </td>
                </tr>
            `;
        }
    }
}

export function filterUsersTable() {
    const term = (document.getElementById('users-search-input')?.value || '').trim().toLowerCase();
    if (!term) {
        renderUsersTable(cachedUsers);
        return;
    }
    const filtered = cachedUsers.filter(u => {
        const haystack = [
            u.full_name || '',
            u.username || '',
            u.email || '',
            u.role === 'admin' ? 'administrador admin' : 'operador',
        ].join(' ').toLowerCase();
        return haystack.includes(term);
    });
    renderUsersTable(filtered);
}

export function renderUsersTable(users = cachedUsers) {
    const tbody = document.getElementById('users-table-body');
    if (!tbody) return;

    if (!Array.isArray(users) || users.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6">
                    <div class="empty-state">
                        <svg viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>
                        <div class="empty-state-title">Nenhum operador encontrado</div>
                        <div class="empty-state-desc">Ajuste o filtro ou cadastre um novo colaborador para acessar o sistema.</div>
                    </div>
                </td>
            </tr>
        `;
        return;
    }

    const me = getStoredUser();
    const myId = me?.id;
    const clientsById = new Map((state.clients || []).map(c => [Number(c.id), c.razao_social || c.cnpj]));

    tbody.innerHTML = users.map(u => {
        const isSelf = myId !== undefined && Number(u.id) === Number(myId);
        const isAdmin = u.role === 'admin';
        const isActive = Boolean(u.is_active);
        const displayName = u.full_name || u.username || 'Operador';
        const initials = getInitials(u);
        const clientIds = Array.isArray(u.client_ids) ? u.client_ids : [];
        const clientNames = clientIds.map(id => clientsById.get(Number(id)) || `ID ${id}`);
        let clientsCellHtml = '';
        if (isAdmin) {
            clientsCellHtml = '<span class="clients-scope-pill is-all" title="Acesso irrestrito a todas as empresas">Todas (Admin)</span>';
        } else if (clientIds.length === 0) {
            clientsCellHtml = '<span class="clients-scope-pill is-none" title="Este operador não vê nenhuma empresa ainda">Nenhuma empresa</span>';
        } else {
            const label = clientIds.length === 1 ? (clientNames[0] || '1 empresa') : `${clientIds.length} empresas`;
            clientsCellHtml = `<span class="clients-scope-pill is-scoped" title="${escapeAttr(clientNames.join(', '))}">${escapeAttr(label)}</span>`;
        }

        return `
            <tr>
                <td>
                    <div class="user-identity-cell">
                        <span class="users-avatar ${isAdmin ? 'is-admin' : ''}">${escapeAttr(initials)}</span>
                        <div class="user-identity-meta">
                            <div class="user-display-name">
                                <span>${escapeAttr(displayName)}</span>
                                ${isSelf ? '<span class="user-self-tag">Você</span>' : ''}
                            </div>
                            <div class="user-username-sub">@${escapeAttr(u.username || '')}</div>
                        </div>
                    </div>
                </td>
                <td>${u.email ? escapeAttr(u.email) : '<span style="color:var(--text3);">—</span>'}</td>
                <td>
                    <span class="role-pill ${isAdmin ? 'is-admin' : 'is-operador'}">
                        ${isAdmin ? 'Administrador' : 'Operador'}
                    </span>
                </td>
                <td>${clientsCellHtml}</td>
                <td>
                    <span class="status-pill ${isActive ? 'is-active' : 'is-inactive'}">
                        <span class="badge-dot"></span>
                        ${isActive ? 'Ativo' : 'Inativo'}
                    </span>
                </td>
                <td style="text-align:right;">
                    <div class="users-actions-row">
                        <button type="button" class="btn-action btn-action--neutral" onclick="App.openOperatorModal(${Number(u.id)})" title="Editar operador" aria-label="Editar operador ${escapeAttr(displayName)}">
                            <svg viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                        </button>
                        <button type="button" class="btn-action btn-action--neutral" onclick="App.openResetPasswordModal(${Number(u.id)})" title="Redefinir senha" aria-label="Redefinir senha de ${escapeAttr(displayName)}">
                            <svg viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                        </button>
                        <button type="button" class="btn-action btn-action--warn ${isSelf ? 'is-disabled' : ''}" ${isSelf ? 'disabled' : ''} onclick="App.toggleUserActive(${Number(u.id)})" title="${isSelf ? 'Não é possível desativar o próprio usuário' : (isActive ? 'Desativar operador' : 'Reativar operador')}" aria-label="${isActive ? 'Desativar' : 'Reativar'} ${escapeAttr(displayName)}">
                            <svg viewBox="0 0 24 24"><path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/></svg>
                        </button>
                        <button type="button" class="btn-action ${isSelf ? 'is-disabled' : ''}" ${isSelf ? 'disabled' : ''} onclick="App.deleteUser(${Number(u.id)})" title="${isSelf ? 'Não é possível excluir o próprio usuário' : 'Excluir operador'}" aria-label="Excluir operador ${escapeAttr(displayName)}">
                            <svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function syncOperatorClientsVisibility() {
    const role = document.getElementById('op-role')?.value || 'operador';
    const group = document.getElementById('op-clients-group');
    const note = document.getElementById('op-clients-admin-note');
    const isAdmin = role === 'admin';
    if (group) group.style.display = isAdmin ? 'none' : 'block';
    if (note) note.style.display = isAdmin ? 'block' : 'none';
}

function renderOperatorClientsCheckboxes() {
    const listEl = document.getElementById('op-clients-list');
    if (!listEl) return;

    const term = (document.getElementById('op-clients-search')?.value || '').trim().toLowerCase();
    const clients = Array.isArray(state.clients) ? state.clients : [];
    const filtered = term
        ? clients.filter(c => {
              const hay = `${c.razao_social || ''} ${c.cnpj || ''} ${formatCnpj(c.cnpj || '')}`.toLowerCase();
              return hay.includes(term);
          })
        : clients;

    if (clients.length === 0) {
        listEl.innerHTML = '<div style="font-size:12px; color:var(--text3); padding:10px;">Nenhuma empresa cadastrada no momento.</div>';
        return;
    }
    if (filtered.length === 0) {
        listEl.innerHTML = '<div style="font-size:12px; color:var(--text3); padding:10px;">Nenhuma empresa encontrada para este filtro.</div>';
        return;
    }

    listEl.innerHTML = filtered.map(c => {
        const cid = Number(c.id);
        const checked = operatorSelectedClientIds.has(cid) ? 'checked' : '';
        return `
            <label class="op-client-check-item">
                <input type="checkbox" class="op-client-checkbox" value="${cid}" ${checked}>
                <div class="op-client-check-meta">
                    <span class="op-client-check-name">${escapeAttr(c.razao_social || 'Sem razão social')}</span>
                    <span class="op-client-check-cnpj">${escapeAttr(formatCnpj(c.cnpj || ''))}</span>
                </div>
            </label>
        `;
    }).join('');

    listEl.querySelectorAll('.op-client-checkbox').forEach(chk => {
        chk.addEventListener('change', () => {
            const cid = Number(chk.value);
            if (chk.checked) operatorSelectedClientIds.add(cid);
            else operatorSelectedClientIds.delete(cid);
        });
    });
}

export function filterOperatorClientsList() {
    renderOperatorClientsCheckboxes();
}

export function toggleAllOperatorClients(selectAll) {
    const clients = Array.isArray(state.clients) ? state.clients : [];
    if (selectAll) {
        clients.forEach(c => operatorSelectedClientIds.add(Number(c.id)));
    } else {
        operatorSelectedClientIds.clear();
    }
    renderOperatorClientsCheckboxes();
}

export async function openOperatorModal(userId = null) {
    const modal = document.getElementById('modal-operator');
    if (modal) enhanceSelects(modal);

    if (!Array.isArray(state.clients) || state.clients.length === 0) {
        try {
            state.clients = await api('/clients');
        } catch (_) {}
    }

    const user = userId !== null ? cachedUsers.find(u => Number(u.id) === Number(userId)) : null;
    const isEdit = Boolean(user);

    const idEl = document.getElementById('op-id');
    const titleEl = document.getElementById('op-modal-title');
    const fullnameEl = document.getElementById('op-fullname');
    const usernameEl = document.getElementById('op-username');
    const emailEl = document.getElementById('op-email');
    const roleEl = document.getElementById('op-role');
    const pwdGroup = document.getElementById('op-password-group');
    const pwdEl = document.getElementById('op-password');
    const activeGroup = document.getElementById('op-active-group');
    const activeEl = document.getElementById('op-is-active');
    const searchClientsEl = document.getElementById('op-clients-search');

    if (idEl) idEl.value = isEdit ? String(user.id) : '';
    if (titleEl) titleEl.innerText = isEdit ? 'Editar Operador' : 'Novo Operador';
    if (fullnameEl) fullnameEl.value = user?.full_name || '';
    if (usernameEl) {
        usernameEl.value = user?.username || '';
        usernameEl.disabled = isEdit;
    }
    if (emailEl) emailEl.value = user?.email || '';
    if (roleEl) roleEl.value = user?.role === 'admin' ? 'admin' : 'operador';
    if (pwdGroup) pwdGroup.style.display = isEdit ? 'none' : 'block';
    if (pwdEl) pwdEl.value = '';
    if (activeGroup) activeGroup.style.display = isEdit ? 'block' : 'none';
    if (activeEl) activeEl.checked = isEdit ? Boolean(user.is_active) : true;
    if (searchClientsEl) searchClientsEl.value = '';

    operatorSelectedClientIds = new Set(
        isEdit && Array.isArray(user?.client_ids) ? user.client_ids.map(Number) : []
    );
    renderOperatorClientsCheckboxes();
    syncOperatorClientsVisibility();

    if (roleEl && !operatorRoleBound) {
        operatorRoleBound = true;
        roleEl.addEventListener('change', syncOperatorClientsVisibility);
    }

    openModal('modal-operator');
    setTimeout(() => (isEdit ? fullnameEl : usernameEl)?.focus(), 40);
}

export async function saveOperator() {
    const opId = (document.getElementById('op-id')?.value || '').trim();
    const isEdit = Boolean(opId);
    const fullName = (document.getElementById('op-fullname')?.value || '').trim();
    const username = (document.getElementById('op-username')?.value || '').trim();
    const email = (document.getElementById('op-email')?.value || '').trim();
    const role = document.getElementById('op-role')?.value || 'operador';
    const password = document.getElementById('op-password')?.value || '';
    const isActive = Boolean(document.getElementById('op-is-active')?.checked);

    if (!isEdit) {
        if (username.length < 3 || /\s/.test(username)) {
            await uiAlert({ title: 'Usuário inválido', message: 'O nome de usuário deve ter pelo menos 3 caracteres e não pode conter espaços.', variant: 'warning' });
            return;
        }
        if (password.length < 4) {
            await uiAlert({ title: 'Senha inválida', message: 'A senha inicial deve ter pelo menos 4 caracteres.', variant: 'warning' });
            return;
        }
    }

    const btn = document.getElementById('btn-save-operator');
    const originalText = btn ? btn.innerText : 'Salvar Operador';
    if (btn) {
        btn.disabled = true;
        btn.innerText = 'Salvando...';
    }

    const selectedClientIds = role === 'admin' ? [] : Array.from(operatorSelectedClientIds);

    try {
        if (isEdit) {
            const updated = await api(`/auth/users/${opId}`, 'PATCH', {
                full_name: fullName || null,
                email: email || null,
                role,
                is_active: isActive ? 1 : 0,
                client_ids: selectedClientIds,
            });
            const me = getStoredUser();
            if (me && Number(me.id) === Number(opId) && updated) {
                localStorage.setItem('nfse_user', JSON.stringify(updated));
                window.App?.updateAuthTopbar?.();
            }
            completeTaskToast('Operador Atualizado', `Dados de ${updated?.username || username} salvos com sucesso.`, 3500);
        } else {
            const created = await api('/auth/users', 'POST', {
                username,
                email: email || null,
                full_name: fullName || null,
                password,
                role,
                client_ids: selectedClientIds,
            });
            completeTaskToast('Operador Criado', `Operador ${created?.username || username} cadastrado com sucesso.`, 3500);
        }
        closeModal('modal-operator');
        await loadUsers();
    } catch (e) {
        await uiAlert({ title: 'Erro ao salvar operador', message: e?.message || 'Não foi possível salvar o operador.', variant: 'error' });
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = originalText;
        }
    }
}

export async function toggleUserActive(userId) {
    const user = cachedUsers.find(u => Number(u.id) === Number(userId));
    if (!user) return;

    const me = getStoredUser();
    if (me && Number(me.id) === Number(user.id)) {
        await uiAlert({ title: 'Ação não permitida', message: 'Você não pode desativar o próprio usuário autenticado.', variant: 'warning' });
        return;
    }

    const nextActive = user.is_active ? 0 : 1;
    const confirmed = await uiConfirm({
        title: nextActive ? 'Reativar Operador' : 'Desativar Operador',
        message: `Deseja ${nextActive ? 'reativar' : 'desativar'} o acesso do operador ${user.full_name || user.username} (@${user.username})?`,
        confirmText: nextActive ? 'Reativar' : 'Desativar',
        cancelText: 'Cancelar',
        variant: nextActive ? 'primary' : 'warning',
    });
    if (!confirmed) return;

    try {
        await api(`/auth/users/${userId}`, 'PATCH', { is_active: nextActive });
        completeTaskToast('Status Atualizado', `Operador @${user.username} ${nextActive ? 'ativado' : 'desativado'}.`, 3500);
        await loadUsers();
    } catch (e) {
        await uiAlert({ title: 'Erro ao alterar status', message: e?.message || 'Não foi possível alterar o status do operador.', variant: 'error' });
    }
}

export function openResetPasswordModal(userId) {
    const user = cachedUsers.find(u => Number(u.id) === Number(userId));
    if (!user) return;

    const idEl = document.getElementById('reset-op-id');
    const lblEl = document.getElementById('reset-op-user-label');
    const pwdEl = document.getElementById('reset-op-pwd');
    const confirmEl = document.getElementById('reset-op-pwd-confirm');

    if (idEl) idEl.value = String(user.id);
    if (lblEl) {
        lblEl.innerText = user.full_name ? `${user.full_name} (@${user.username})` : `@${user.username}`;
    }
    if (pwdEl) pwdEl.value = '';
    if (confirmEl) confirmEl.value = '';

    openModal('modal-operator-reset-pwd');
    setTimeout(() => pwdEl?.focus(), 40);
}

export async function submitResetOperatorPassword() {
    const userId = (document.getElementById('reset-op-id')?.value || '').trim();
    const pwd = document.getElementById('reset-op-pwd')?.value || '';
    const confirmPwd = document.getElementById('reset-op-pwd-confirm')?.value || '';

    if (!userId) return;
    if (pwd.length < 4) {
        await uiAlert({ title: 'Senha inválida', message: 'A nova senha deve ter pelo menos 4 caracteres.', variant: 'warning' });
        return;
    }
    if (pwd !== confirmPwd) {
        await uiAlert({ title: 'Senhas divergentes', message: 'A confirmação de senha não confere.', variant: 'warning' });
        return;
    }

    const btn = document.getElementById('btn-submit-reset-pwd');
    const originalText = btn ? btn.innerText : 'Redefinir Senha';
    if (btn) {
        btn.disabled = true;
        btn.innerText = 'Salvando...';
    }

    try {
        await api(`/auth/users/${userId}`, 'PATCH', { password: pwd });
        closeModal('modal-operator-reset-pwd');
        completeTaskToast('Senha Redefinida', 'A senha do operador foi atualizada com sucesso.', 3500);
    } catch (e) {
        await uiAlert({ title: 'Erro ao redefinir senha', message: e?.message || 'Não foi possível redefinir a senha.', variant: 'error' });
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerText = originalText;
        }
    }
}

export async function deleteUser(userId) {
    const user = cachedUsers.find(u => Number(u.id) === Number(userId));
    if (!user) return;

    const me = getStoredUser();
    if (me && Number(me.id) === Number(user.id)) {
        await uiAlert({ title: 'Ação não permitida', message: 'Não é permitido excluir o próprio usuário autenticado.', variant: 'warning' });
        return;
    }

    const confirmed = await uiConfirm({
        title: 'Excluir Operador',
        message: `Deseja excluir permanentemente o operador ${user.full_name || user.username} (@${user.username})?`,
        confirmText: 'Excluir Operador',
        cancelText: 'Cancelar',
        variant: 'danger',
        icon: 'trash',
    });
    if (!confirmed) return;

    try {
        await api(`/auth/users/${userId}`, 'DELETE');
        completeTaskToast('Operador Removido', `O usuário @${user.username} foi excluído.`, 3500);
        await loadUsers();
    } catch (e) {
        await uiAlert({ title: 'Erro ao excluir operador', message: e?.message || 'Não foi possível excluir o operador.', variant: 'error' });
    }
}
