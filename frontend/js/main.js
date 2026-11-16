import { api } from './core/api.js';
import { state } from './core/state.js';
import { maskCnpj, maskCep, formatCnpj, formatCep, maskPhone, openModal, closeModal, toggleTheme } from './core/ui.js';
import { showPage } from './core/router.js';
import { loadDashboardStats, loadDashboardChart, changeChartPeriod, loadRanking, exportReport } from './pages/dashboard.js';
import { loadClients, renderClients, editClient, toggleAuthType, saveClient, deleteClient, addPathTag, handlePathKey, toggleExplorer, browseFolders, selectCurrentFolder } from './pages/clients.js';
import { loadInvoices, setFilterType, toggleSelectAll, downloadBatch, startSync, pollTask, enrichFromXml, triggerDownload, convertHtmlToXmlAndPdf, syncCofreAdn, sendInvoiceEmailPrompt, cancelInvoicePrompt } from './pages/invoices.js';
import { sendSupportMessage, checkUpdates, initAbout, startUpdateDownload, applyDownloadedUpdate } from './pages/about.js';
import {
    initEmissionPage, switchEmissionTab, loadSavedCustomersAndServices,
    onSelectSavedCustomer, onSelectSavedService, onChangeCTribNac,
    onSelectNbsOption, loadAllNbsOptions,
    handleEmissionCnpjInput, handleEmissionCepInput,
    onSelectClassTrib, onSelectIndOp,
    lookupEmissionCnpj, lookupEmissionCep, saveCurrentCustomerFromEmission,
    saveCurrentServiceFromEmission, recalculateEmissionPreview,
    previewDpsXmlModal, submitEmitirDps, loadFilaContingencia,
    reenviarFilaContingencia, deleteSavedCustomer, deleteSavedService
} from './pages/emission.js';

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
    showPage,
    
    // UI
    maskCnpj, maskCep, formatCnpj, formatCep, maskPhone, openModal, closeModal, toggleTheme,
    
    // Dashboard
    loadDashboardStats, loadDashboardChart, changeChartPeriod, loadRanking, exportReport,
    
    // Clients
    loadClients, renderClients, editClient, toggleAuthType, saveClient, deleteClient, addPathTag, handlePathKey,
    toggleExplorer, browseFolders, selectCurrentFolder,
    
    // Invoices
    loadInvoices, setFilterType, toggleSelectAll, downloadBatch, startSync, pollTask, enrichFromXml, triggerDownload, convertHtmlToXmlAndPdf,
    syncCofreAdn, sendInvoiceEmailPrompt, cancelInvoicePrompt,

    // Emission & ADN
    initEmissionPage, switchEmissionTab, loadSavedCustomersAndServices,
    onSelectSavedCustomer, onSelectSavedService, onChangeCTribNac,
    onSelectNbsOption, loadAllNbsOptions,
    handleEmissionCnpjInput, handleEmissionCepInput,
    onSelectClassTrib, onSelectIndOp,
    lookupEmissionCnpj, lookupEmissionCep, saveCurrentCustomerFromEmission,
    saveCurrentServiceFromEmission, recalculateEmissionPreview,
    previewDpsXmlModal, submitEmitirDps, loadFilaContingencia,
    reenviarFilaContingencia, deleteSavedCustomer, deleteSavedService,
    
    // System/About
    sendSupportMessage, checkUpdates, startUpdateDownload, applyDownloadedUpdate,
    initAbout,

    // Auth (JWT Gatekeeper)
    _pollTimer: null,

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
        const isReg = tab === 'register';
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
            footEl.innerHTML = isReg
                ? 'Já possui conta? <button type="button" class="auth-footer-link" onclick="App.switchAuthTab(\'login\')">Fazer login</button>'
                : 'Ainda não tem acesso? <button type="button" class="auth-footer-link" onclick="App.switchAuthTab(\'register\')">Cadastre uma conta</button>';
        }

        this.setAuthNotice(null, '');

        const targetId = isReg ? 'reg-fullname' : 'login-username';
        setTimeout(() => document.getElementById(targetId)?.focus(), 20);
    },

    async showAuthScreen(defaultTab = null) {
        document.documentElement.classList.remove('auth-checking');
        document.body.classList.remove('is-authenticated');
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
        this.updateAuthTopbar();

        let targetTab = defaultTab || 'login';
        let infoMsg = '';
        try {
            const st = await this.api('/auth/status');
            if (st && st.has_users === false) {
                targetTab = defaultTab || 'register';
                infoMsg = 'Nenhum operador cadastrado ainda. Crie a primeira conta (Administrador) para acessar o sistema.';
            }
        } catch (_) {}

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

    logout(silent = false) {
        if (!silent && !confirm('Deseja encerrar a sessão atual?')) return;
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
        if (!lbl || !pill) return;
        const token = localStorage.getItem('nfse_token');
        const rawUser = localStorage.getItem('nfse_user');
        if (token && rawUser) {
            try {
                const u = JSON.parse(rawUser);
                lbl.innerText = u.full_name || u.username || 'Operador';
                pill.style.display = 'inline-flex';
                return;
            } catch (e) {}
        }
        pill.style.display = 'none';
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
