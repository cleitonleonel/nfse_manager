import { api, getApiBaseUrl, setApiBaseUrl } from './core/api.js';
import { state } from './core/state.js';
import { maskCnpj, maskCep, formatCnpj, formatCep, maskPhone, openModal, closeModal, toggleTheme, initSidebarState, toggleSidebar, hideTaskToast, uiConfirm, uiAlert, completeTaskToast } from './core/ui.js';
import { showPage } from './core/router.js';
import { loadDashboardStats, loadDashboardChart, changeChartPeriod, loadRanking, exportReport } from './pages/dashboard.js';
import { loadClients, renderClients, editClient, toggleAuthType, saveClient, deleteClient, addPathTag, handlePathKey, toggleExplorer, browseFolders, selectCurrentFolder, usarSmtpPadrao } from './pages/clients.js';
import { loadInvoices, setFilterType, toggleSelectAll, downloadBatch, startSync, pollTask, enrichFromXml, triggerDownload, convertHtmlToXmlAndPdf, syncCofreAdn, sendInvoiceEmailPrompt, cancelInvoicePrompt, loadCompetenciaReport, downloadCompetenciaReport } from './pages/invoices.js';
import { sendSupportMessage, checkUpdates, initAbout, startUpdateDownload, applyDownloadedUpdate, loadSystemEnvironment } from './pages/about.js';
import { loadUsers, filterUsersTable, renderUsersTable, openOperatorModal, saveOperator, toggleUserActive, openResetPasswordModal, submitResetOperatorPassword, deleteUser } from './pages/users.js';
import {
    initEmissionPage, switchEmissionTab, loadSavedCustomersAndServices,
    onSelectSavedCustomer, onSelectSavedService, onChangeCTribNac,
    onSelectNbsOption, loadAllNbsOptions,
    toggleAllClassTribOptions, toggleAllIndOpOptions,
    handleEmissionCnpjInput, handleEmissionCepInput,
    onSelectClassTrib, onSelectIndOp,
    lookupEmissionCnpj, lookupEmissionCep, saveCurrentCustomerFromEmission,
    saveCurrentServiceFromEmission, recalculateEmissionPreview,
    previewDpsXmlModal, submitEmitirDps, loadFilaContingencia,
    reenviarFilaContingencia, cancelarItemFila, deleteSavedCustomer, deleteSavedService,
    toggleAllLoteCustomers, submitEmitirLote, downloadImportTemplate, handleImportSpreadsheet,
    toggleAllSavedCustomers, toggleAllSavedServices, updateSavedSelectionCounts,
    deleteSelectedSavedCustomers, deleteAllSavedCustomers,
    deleteSelectedSavedServices, deleteAllSavedServices
} from './pages/emission.js';
import {
    switchLoteMode, updateBatchSelectionCount,
    downloadBatchTemplate, uploadBatchSpreadsheet, loadBatchImports,
    openBatchDetail, loadBatchItems, toggleAllBatchItems,
    openBatchItemEditor, closeBatchItemEditor, saveBatchItemCorrection,
    revalidateActiveBatch, processActiveBatch, retryActiveBatch,
    cancelActiveBatch, exportActiveBatch,
    deleteBatch, deleteBatchItem, deleteSelectedBatchItems, deleteAllBatchItems
} from './pages/batch.js';

// Construct the global App object for HTML onclick handlers
window.App = {
    // State
    get activePage() { return state.activePage; },
    set activePage(val) { state.activePage = val; },
    get chartPeriod() { return state.chartPeriod; },
    
    getGlobalClientId: state.getGlobalClientId,
    setGlobalClient: state.setGlobalClient,
    
    // Core
    api,
    getApiBaseUrl,
    setApiBaseUrl,
    showPage,
    
    // UI
    maskCnpj, maskCep, formatCnpj, formatCep, maskPhone, openModal, closeModal, toggleTheme, toggleSidebar, hideTaskToast,
    
    // Dashboard
    loadDashboardStats, loadDashboardChart, changeChartPeriod, loadRanking, exportReport,
    
    // Clients
    loadClients, renderClients, editClient, toggleAuthType, saveClient, deleteClient, addPathTag, handlePathKey,
    toggleExplorer, browseFolders, selectCurrentFolder, usarSmtpPadrao,
    
    // Invoices
    loadInvoices, setFilterType, toggleSelectAll, downloadBatch, startSync, pollTask, enrichFromXml, triggerDownload, convertHtmlToXmlAndPdf, loadCompetenciaReport, downloadCompetenciaReport,
    syncCofreAdn, sendInvoiceEmailPrompt, cancelInvoicePrompt,

    // Emission & ADN
    initEmissionPage, switchEmissionTab, loadSavedCustomersAndServices,
    onSelectSavedCustomer, onSelectSavedService, onChangeCTribNac,
    onSelectNbsOption, loadAllNbsOptions,
    toggleAllClassTribOptions, toggleAllIndOpOptions,
    handleEmissionCnpjInput, handleEmissionCepInput,
    onSelectClassTrib, onSelectIndOp,
    lookupEmissionCnpj, lookupEmissionCep, saveCurrentCustomerFromEmission,
    saveCurrentServiceFromEmission, recalculateEmissionPreview,
    previewDpsXmlModal, submitEmitirDps, loadFilaContingencia,
    reenviarFilaContingencia, cancelarItemFila, deleteSavedCustomer, deleteSavedService,
    toggleAllLoteCustomers, submitEmitirLote, downloadImportTemplate, handleImportSpreadsheet,
    toggleAllSavedCustomers, toggleAllSavedServices, updateSavedSelectionCounts,
    deleteSelectedSavedCustomers, deleteAllSavedCustomers,
    deleteSelectedSavedServices, deleteAllSavedServices,
    switchLoteMode, updateBatchSelectionCount,
    downloadBatchTemplate, uploadBatchSpreadsheet, loadBatchImports,
    openBatchDetail, loadBatchItems, toggleAllBatchItems,
    openBatchItemEditor, closeBatchItemEditor, saveBatchItemCorrection,
    revalidateActiveBatch, processActiveBatch, retryActiveBatch,
    cancelActiveBatch, exportActiveBatch,
    deleteBatch, deleteBatchItem, deleteSelectedBatchItems, deleteAllBatchItems,
    
    // System/About & Team Management
    sendSupportMessage, checkUpdates, startUpdateDownload, applyDownloadedUpdate,
    initAbout, loadSystemEnvironment,
    loadUsers, filterUsersTable, renderUsersTable, openOperatorModal, saveOperator,
    toggleUserActive, openResetPasswordModal, submitResetOperatorPassword, deleteUser,

    // Auth (JWT Gatekeeper)
    _pollTimer: null,
    _allowSelfRegister: true,

    setAuthNotice(type, message) {
        const box = document.getElementById('auth-notice');
        if (!box) return;
        box.className = 'auth-notice';
        if (!message) {
            box.textContent = '';
            return;
        }
        box.classList.add(type === 'error' ? 'is-error' : 'is-info');
        box.textContent = message;
    },

    togglePasswordVisibility(inputId, btn) {
        const input = document.getElementById(inputId);
        if (!input) return;
        const showing = input.type === 'text';
        input.type = showing ? 'password' : 'text';
        if (btn) {
            btn.innerHTML = showing
                ? '<svg viewBox="0 0 24 24"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>'
                : '<svg viewBox="0 0 24 24"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
            btn.title = showing ? 'Mostrar senha' : 'Ocultar senha';
        }
    },

    switchAuthTab(tab) {
        const isReg = tab === 'register' && this._allowSelfRegister !== false;
        const loginForm = document.getElementById('auth-form-login');
        const regForm = document.getElementById('auth-form-register');
        const tabLogin = document.getElementById('auth-tab-login');
        const tabReg = document.getElementById('auth-tab-register');
        const titleEl = document.getElementById('auth-panel-title');
        const subEl = document.getElementById('auth-panel-subtitle');
        const footEl = document.getElementById('auth-footer-hint');

        if (loginForm) loginForm.style.display = isReg ? 'none' : 'flex';
        if (regForm) regForm.style.display = isReg ? 'flex' : 'none';
        if (tabLogin) tabLogin.classList.toggle('active', !isReg);
        if (tabReg) tabReg.classList.toggle('active', isReg);

        if (titleEl) titleEl.textContent = isReg ? 'Criar conta de operador' : 'Acesse sua conta';
        if (subEl) {
            subEl.textContent = isReg
                ? 'Preencha os dados abaixo para começar a usar a plataforma.'
                : 'Entre com seu usuário ou e-mail de operador para continuar.';
        }
        if (footEl) {
            if (this._allowSelfRegister === false) {
                footEl.style.display = 'none';
            } else {
                footEl.style.display = 'block';
                footEl.innerHTML = isReg
                    ? 'Já possui conta? <button type="button" class="auth-footer-link" onclick="App.switchAuthTab(\'login\')">Fazer login</button>'
                    : 'Ainda não tem acesso? <button type="button" class="auth-footer-link" onclick="App.switchAuthTab(\'register\')">Cadastre uma conta</button>';
            }
        }

        this.setAuthNotice(null, '');

        const targetId = isReg ? 'reg-fullname' : 'login-username';
        setTimeout(() => document.getElementById(targetId)?.focus(), 20);
    },

    updateServerConfigButton() {
        const btn = document.getElementById('auth-server-config-btn');
        if (!btn) return;
        const base = getApiBaseUrl();
        btn.classList.toggle('is-configured', Boolean(base));
        btn.title = base ? `Servidor Central: ${base}` : 'Configurar URL do Servidor Central';
    },

    async showAuthScreen(defaultTab = null) {
        document.documentElement.classList.remove('auth-checking');
        document.body.classList.remove('is-authenticated');
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
        this.updateAuthTopbar();
        this.updateServerConfigButton();

        let targetTab = defaultTab || 'login';
        let infoMsg = '';
        let allowSelfRegister = true;
        try {
            const st = await this.api('/auth/status');
            const hasUsers = st ? st.has_users !== false : true;
            allowSelfRegister = !hasUsers || st?.allow_self_register !== false;
            if (!hasUsers) {
                targetTab = defaultTab || 'register';
                infoMsg = 'Nenhum operador cadastrado ainda. Crie a primeira conta (Administrador) para acessar o sistema.';
            } else if (!allowSelfRegister) {
                targetTab = 'login';
            }
        } catch (_) {}

        this._allowSelfRegister = allowSelfRegister;
        const tabReg = document.getElementById('auth-tab-register');
        const tabsWrap = tabReg?.closest('.auth-tabs');
        if (tabReg) tabReg.style.display = allowSelfRegister ? 'inline-flex' : 'none';
        if (tabsWrap) tabsWrap.style.gridTemplateColumns = allowSelfRegister ? '1fr 1fr' : '1fr';

        this.switchAuthTab(targetTab);
        if (infoMsg) this.setAuthNotice('info', infoMsg);
    },

    async completeAuthSuccess(res) {
        localStorage.setItem('nfse_token', res.access_token);
        localStorage.setItem('nfse_user', JSON.stringify(res.user));
        this.setAuthNotice(null, '');
        document.documentElement.classList.remove('auth-checking');
        document.body.classList.add('is-authenticated');
        this.updateAuthTopbar();
        await this.startAuthenticatedApp();
    },

    async submitLogin() {
        const username = (document.getElementById('login-username')?.value || '').trim();
        const password = document.getElementById('login-password')?.value || '';
        if (!username || !password) {
            return this.setAuthNotice('error', 'Informe usuário/e-mail e senha.');
        }

        const btn = document.getElementById('auth-login-submit');
        if (btn) { btn.disabled = true; btn.textContent = 'Acessando...'; }
        this.setAuthNotice(null, '');
        try {
            const res = await this.api('/auth/login', 'POST', { username, password });
            const pwdInput = document.getElementById('login-password');
            if (pwdInput) pwdInput.value = '';
            await this.completeAuthSuccess(res);
        } catch (e) {
            this.setAuthNotice('error', e.message || 'Usuário ou senha inválidos.');
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = 'Acessar Sistema'; }
        }
    },

    async submitRegister() {
        const fullName = (document.getElementById('reg-fullname')?.value || '').trim();
        const username = (document.getElementById('reg-username')?.value || '').trim();
        const email = (document.getElementById('reg-email')?.value || '').trim();
        const password = document.getElementById('reg-password')?.value || '';
        const confirmPwd = document.getElementById('reg-password-confirm')?.value || '';

        if (username.length < 3 || /\s/.test(username)) {
            return this.setAuthNotice('error', 'O usuário deve ter pelo menos 3 caracteres e não conter espaços.');
        }
        if (password.length < 4) {
            return this.setAuthNotice('error', 'A senha deve ter pelo menos 4 caracteres.');
        }
        if (password !== confirmPwd) {
            return this.setAuthNotice('error', 'As senhas informadas não conferem.');
        }

        const btn = document.getElementById('auth-register-submit');
        if (btn) { btn.disabled = true; btn.textContent = 'Criando conta...'; }
        this.setAuthNotice(null, '');
        try {
            const res = await this.api('/auth/register', 'POST', {
                username,
                email: email || null,
                full_name: fullName || null,
                password,
            });
            ['reg-password', 'reg-password-confirm'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.value = '';
            });
            await this.completeAuthSuccess(res);
        } catch (e) {
            this.setAuthNotice('error', e.message || 'Não foi possível concluir o cadastro.');
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = 'Criar Conta e Acessar'; }
        }
    },

    async logout(silent = false) {
        if (!silent) {
            const confirmed = await uiConfirm({
                title: 'Encerrar Sessão',
                message: 'Deseja realmente sair da sua conta atual?',
                confirmText: 'Sair',
                cancelText: 'Permanecer',
                variant: 'warning',
                icon: 'logout',
            });
            if (!confirmed) return;
        }
        localStorage.removeItem('nfse_token');
        localStorage.removeItem('nfse_user');
        this.showAuthScreen('login');
        if (silent) {
            this.setAuthNotice('info', 'Sua sessão expirou. Faça login novamente para continuar.');
        }
    },

    updateAuthTopbar() {
        const pill = document.getElementById('auth-user-pill');
        const lbl = document.getElementById('auth-topbar-label');
        const roleBadge = document.getElementById('auth-topbar-role');
        if (!lbl || !pill) return;
        const token = localStorage.getItem('nfse_token');
        const rawUser = localStorage.getItem('nfse_user');
        if (token && rawUser) {
            try {
                const u = JSON.parse(rawUser);
                lbl.innerText = u.full_name || u.username || 'Operador';
                if (roleBadge) {
                    const isAdmin = u.role === 'admin';
                    roleBadge.innerText = isAdmin ? 'Admin' : 'Operador';
                    roleBadge.classList.toggle('is-admin', isAdmin);
                    roleBadge.classList.toggle('is-operador', !isAdmin);
                }
                pill.style.display = 'inline-flex';
                return;
            } catch (e) {}
        }
        pill.style.display = 'none';
    },

    setModalFeedback(elId, type, message) {
        const box = document.getElementById(elId);
        if (!box) return;
        box.className = 'modal-feedback-box';
        if (!message) {
            box.textContent = '';
            return;
        }
        box.classList.add(type === 'error' ? 'is-error' : (type === 'ok' ? 'is-ok' : 'is-info'));
        box.textContent = message;
    },

    openProfileModal() {
        let u = null;
        try {
            const raw = localStorage.getItem('nfse_user');
            u = raw ? JSON.parse(raw) : null;
        } catch (_) {}

        const displayName = u?.full_name || u?.username || 'Operador';
        const initials = displayName.trim().split(/\s+/).filter(Boolean).slice(0, 2).map(p => p[0]).join('').toUpperCase() || 'OP';
        const isAdmin = u?.role === 'admin';

        const avatarEl = document.getElementById('profile-avatar-initials');
        const nameEl = document.getElementById('profile-fullname');
        const userEl = document.getElementById('profile-username');
        const emailEl = document.getElementById('profile-email');
        const badgeEl = document.getElementById('profile-role-badge');

        if (avatarEl) avatarEl.innerText = initials;
        if (nameEl) nameEl.innerText = displayName;
        if (userEl) userEl.innerText = `@${u?.username || 'operador'}`;
        if (emailEl) emailEl.innerText = u?.email || 'Sem e-mail cadastrado';
        if (badgeEl) {
            badgeEl.innerText = isAdmin ? 'Admin' : 'Operador';
            badgeEl.classList.toggle('is-admin', isAdmin);
            badgeEl.classList.toggle('is-operador', !isAdmin);
        }

        ['prof-current-pwd', 'prof-new-pwd', 'prof-confirm-pwd'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        this.setModalFeedback('prof-pwd-feedback', null, '');

        openModal('modal-account-profile');
        setTimeout(() => document.getElementById('prof-current-pwd')?.focus(), 40);
    },

    async submitChangeMyPassword() {
        const currentPassword = document.getElementById('prof-current-pwd')?.value || '';
        const newPassword = document.getElementById('prof-new-pwd')?.value || '';
        const confirmPassword = document.getElementById('prof-confirm-pwd')?.value || '';

        if (!currentPassword) {
            return this.setModalFeedback('prof-pwd-feedback', 'error', 'Informe sua senha atual.');
        }
        if (newPassword.length < 4) {
            return this.setModalFeedback('prof-pwd-feedback', 'error', 'A nova senha deve ter pelo menos 4 caracteres.');
        }
        if (newPassword !== confirmPassword) {
            return this.setModalFeedback('prof-pwd-feedback', 'error', 'A confirmação da nova senha não confere.');
        }

        const btn = document.getElementById('btn-save-my-pwd');
        const originalText = btn ? btn.innerText : 'Atualizar Senha';
        if (btn) { btn.disabled = true; btn.innerText = 'Salvando...'; }
        this.setModalFeedback('prof-pwd-feedback', null, '');

        try {
            await this.api('/auth/change-password', 'POST', {
                current_password: currentPassword,
                new_password: newPassword,
            });
            ['prof-current-pwd', 'prof-new-pwd', 'prof-confirm-pwd'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.value = '';
            });
            closeModal('modal-account-profile');
            completeTaskToast('Senha Alterada', 'Sua senha de acesso foi atualizada com sucesso.', 3500);
        } catch (e) {
            this.setModalFeedback('prof-pwd-feedback', 'error', e?.message || 'Não foi possível alterar a senha.');
        } finally {
            if (btn) { btn.disabled = false; btn.innerText = originalText; }
        }
    },

    openServerUrlModal() {
        const input = document.getElementById('server-url-input');
        if (input) input.value = getApiBaseUrl();
        this.setModalFeedback('server-url-status', null, '');
        openModal('modal-server-url');
        setTimeout(() => input?.focus(), 40);
    },

    async testServerUrl() {
        const raw = (document.getElementById('server-url-input')?.value || '').trim().replace(/\/+$/, '');
        if (raw && !/^https?:\/\//i.test(raw)) {
            this.setModalFeedback('server-url-status', 'error', 'Informe uma URL válida iniciando com http:// ou https://.');
            return false;
        }

        const btn = document.getElementById('btn-test-server-url');
        const originalText = btn ? btn.innerText : 'Testar Conexão';
        if (btn) { btn.disabled = true; btn.innerText = 'Testando...'; }
        this.setModalFeedback('server-url-status', 'info', 'Verificando conexão com o servidor...');

        try {
            let res = await fetch(`${raw}/api/health`);
            if (res.status === 404) {
                res = await fetch(`${raw}/api/auth/status`);
            }
            if (!res.ok) {
                throw new Error(`Servidor respondeu com HTTP ${res.status}`);
            }
            const data = await res.json().catch(() => ({}));
            const ver = data?.version ? ` (v${data.version})` : '';
            this.setModalFeedback('server-url-status', 'ok', `Conexão confirmada com ${raw || window.location.origin}${ver}.`);
            return true;
        } catch (e) {
            this.setModalFeedback('server-url-status', 'error', `Falha ao conectar: ${e?.message || 'servidor inacessível'}`);
            return false;
        } finally {
            if (btn) { btn.disabled = false; btn.innerText = originalText; }
        }
    },

    async saveServerUrl() {
        const raw = (document.getElementById('server-url-input')?.value || '').trim().replace(/\/+$/, '');
        if (raw && !/^https?:\/\//i.test(raw)) {
            this.setModalFeedback('server-url-status', 'error', 'Informe uma URL válida iniciando com http:// ou https:// (ou deixe vazio para modo local).');
            return;
        }

        const prev = getApiBaseUrl();
        const saved = setApiBaseUrl(raw);
        closeModal('modal-server-url');
        this.updateServerConfigButton();

        if (document.body.classList.contains('is-authenticated')) {
            if (prev !== saved) {
                localStorage.removeItem('nfse_token');
                localStorage.removeItem('nfse_user');
                window.location.reload();
                return;
            }
            if (this.activePage === 'about') {
                await loadSystemEnvironment();
            }
            completeTaskToast('Configuração Salva', saved ? `API apontada para ${saved}` : 'Usando servidor local atual.', 3500);
        } else {
            await this.showAuthScreen();
            if (saved) {
                this.setAuthNotice('info', `Conectado ao servidor central: ${saved}`);
            }
        }
    },

    async clearServerUrl() {
        const input = document.getElementById('server-url-input');
        if (input) input.value = '';
        await this.saveServerUrl();
    },

    onGlobalClientChange() {
        this.loadDashboardStats();
        this.loadDashboardChart(this.chartPeriod);
        this.loadRanking();
        if (this.activePage === 'invoices') {
            this.loadInvoices();
        }
        if (this.activePage === 'emission') {
            this.initEmissionPage();
        }
    },

    refresh() {
        this.loadClients();
        if (this.activePage === 'invoices') this.loadInvoices();
        this.loadDashboardStats();
        this.loadDashboardChart(this.chartPeriod);
    },

    async startAuthenticatedApp() {
        await showPage(this.activePage || 'dashboard');
        this.loadClients();
        this.refresh();
        if (!this._pollTimer) {
            this._pollTimer = setInterval(() => this.pollTask(), 2000);
        }
        try { this.initAbout(); } catch (e) { console.warn('initAbout failed', e); }
    },

    async init() {
        if (localStorage.getItem('theme') === 'light') document.body.classList.add('theme-light');
        initSidebarState();

        // Global click listener for dropdowns
        document.addEventListener('click', e => {
            if (!e.target.closest('.dropdown')) {
                document.querySelectorAll('.dropdown-menu.show').forEach(m => m.classList.remove('show'));
            }
        });

        const token = localStorage.getItem('nfse_token');
        if (!token) {
            await this.showAuthScreen();
            return;
        }

        try {
            const user = await this.api('/auth/me');
            localStorage.setItem('nfse_user', JSON.stringify(user));
            document.documentElement.classList.remove('auth-checking');
            document.body.classList.add('is-authenticated');
            this.updateAuthTopbar();
            await this.startAuthenticatedApp();
        } catch (_) {
            localStorage.removeItem('nfse_token');
            localStorage.removeItem('nfse_user');
            await this.showAuthScreen('login');
        }
    }
};

// Start application
window.App.init();
