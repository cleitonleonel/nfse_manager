import { api } from './core/api.js';
import { state } from './core/state.js';
import { maskCnpj, maskPhone, openModal, closeModal, toggleTheme } from './core/ui.js';
import { showPage } from './core/router.js';
import { loadDashboardStats, loadDashboardChart, changeChartPeriod, loadRanking, exportReport } from './pages/dashboard.js';
import { loadClients, renderClients, editClient, toggleAuthType, saveClient, deleteClient, addPathTag, handlePathKey, toggleExplorer, browseFolders, selectCurrentFolder } from './pages/clients.js';
import { loadInvoices, setFilterType, toggleSelectAll, downloadBatch, startSync, pollTask, enrichFromXml, triggerDownload } from './pages/invoices.js';
import { sendSupportMessage, checkUpdates, initAbout, startUpdateDownload, applyDownloadedUpdate } from './pages/about.js';

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
    maskCnpj, maskPhone, openModal, closeModal, toggleTheme,
    
    // Dashboard
    loadDashboardStats, loadDashboardChart, changeChartPeriod, loadRanking, exportReport,
    
    // Clients
    loadClients, renderClients, editClient, toggleAuthType, saveClient, deleteClient, addPathTag, handlePathKey,
    toggleExplorer, browseFolders, selectCurrentFolder,
    
    // Invoices
    loadInvoices, setFilterType, toggleSelectAll, downloadBatch, startSync, pollTask, enrichFromXml, triggerDownload,
    
    // System/About
    sendSupportMessage, checkUpdates, startUpdateDownload, applyDownloadedUpdate,
    initAbout,
    
    onGlobalClientChange() {
        this.loadDashboardStats();
        this.loadDashboardChart(this.chartPeriod);
        this.loadRanking();
        if (this.activePage === 'invoices') {
            this.loadInvoices();
        }
    },
    
    refresh() {
        this.loadClients();
        if (this.activePage === 'invoices') this.loadInvoices();
        this.loadDashboardStats();
        this.loadDashboardChart(this.chartPeriod);
    },
    
    async init() {
        if (localStorage.getItem('theme') === 'light') document.body.classList.add('theme-light');
        
        // Initial load of default page view
        await showPage('dashboard');
        
        this.loadClients();
        this.refresh();
        setInterval(() => this.pollTask(), 2000);
        // initialize about page data (version badge)
        try { this.initAbout(); } catch (e) { console.warn('initAbout failed', e); }
        
        // Global click listener for dropdowns
        document.addEventListener('click', e => {
            if (!e.target.closest('.dropdown')) {
                document.querySelectorAll('.dropdown-menu.show').forEach(m => m.classList.remove('show'));
            }
        });
    }
};

// Start application
window.App.init();
