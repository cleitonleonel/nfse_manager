import { api } from './core/api.js';
import { state } from './core/state.js';
import { maskCnpj, maskPhone, openModal, closeModal, toggleTheme } from './core/ui.js';
import { showPage } from './core/router.js';
import { loadDashboardStats, loadDashboardChart, changeChartPeriod, loadRanking, exportReport } from './pages/dashboard.js';
import { loadClients, renderClients, editClient, toggleAuthType, saveClient, deleteClient, addPathTag, handlePathKey, toggleExplorer, browseFolders, selectCurrentFolder } from './pages/clients.js';
import { loadNotes, setFilterType, toggleSelectAll, downloadBatch, startSync, pollTask, enrichFromXml, triggerDownload } from './pages/notes.js';
import { sendSupportMessage, checkUpdates } from './pages/about.js';

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
    
    // Notes
    loadNotes, setFilterType, toggleSelectAll, downloadBatch, startSync, pollTask, enrichFromXml, triggerDownload,
    
    // System/About
    sendSupportMessage, checkUpdates,
    
    onGlobalClientChange() {
        this.loadDashboardStats();
        this.loadDashboardChart(this.chartPeriod);
        this.loadRanking();
        if (this.activePage === 'notes') {
            this.loadNotes();
        }
    },
    
    refresh() {
        this.loadClients();
        if (this.activePage === 'notes') this.loadNotes();
        this.loadDashboardStats();
        this.loadDashboardChart(this.chartPeriod);
    },
    
    async init() {
        if (localStorage.getItem('theme') === 'light') document.body.classList.add('theme-light');
        
        // Initial load of default page view
        await showPage('dashboard');
        
        this.loadClients();
        this.refresh();
        setInterval(() => pollTask(), 2000);
        
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
