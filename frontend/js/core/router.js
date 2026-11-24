import { closeCustomSelects, enhanceSelects } from './custom-select.js';

export async function loadView(pageId) {
    const contentDiv = document.getElementById('app-content');
    if (!contentDiv) return false;
    closeCustomSelects();
    
    // Simple caching mechanism
    if (!window.viewCache) window.viewCache = {};
    
    if (!window.viewCache[pageId]) {
        try {
            const res = await fetch(`/views/${pageId}.html`);
            if (res.ok) {
                window.viewCache[pageId] = await res.text();
            } else {
                console.error("View not found:", pageId, res.status);
                return false;
            }
        } catch(e) {
            console.error("Error loading view:", e);
            return false;
        }
    }
    
    // Remove existing page content
    const existing = contentDiv.querySelector('.page-content');
    if (existing) existing.remove();
    
    // Inject view before footer
    const footer = contentDiv.querySelector('footer');
    const wrapper = document.createElement('div');
    wrapper.innerHTML = window.viewCache[pageId];
    const newPage = wrapper.firstElementChild;
    
    if (!newPage) {
        console.error('View HTML has no root element:', pageId);
        return false;
    }
    
    contentDiv.insertBefore(newPage, footer || null);
    enhanceSelects(newPage);
    
    // Trigger animation
    setTimeout(() => {
        newPage.classList.add('active');
    }, 10);
    
    return true;
}

export async function showPage(pageId) {
    if (pageId === 'users') {
        try {
            const raw = localStorage.getItem('nfse_user');
            const u = raw ? JSON.parse(raw) : null;
            if (!u || u.role !== 'admin') {
                pageId = 'dashboard';
            }
        } catch (_) {
            pageId = 'dashboard';
        }
    }

    document.querySelectorAll('.nav-item').forEach(p => p.classList.remove('active'));
    const navItem = document.getElementById(`nav-${pageId}`);
    if (navItem) navItem.classList.add('active');
    
    const titles = {
        dashboard: 'Dashboard',
        clients: 'Clientes',
        invoices: 'Notas Fiscais',
        emission: 'Emissor NFS-e Nacional (ADN)',
        users: 'Gestão de Equipe',
        help: 'Ajuda & Suporte',
        about: 'Sobre o Sistema',
    };
    const titleEl = document.getElementById('page-title');
    if (titleEl) titleEl.innerText = titles[pageId] || 'Dashboard';
    
    await loadView(pageId);
    
    // Trigger page specific initializations via App
     if (window.App) {
         window.App.activePage = pageId;
         if (pageId === 'invoices') {
             if (window.App.loadInvoices) window.App.loadInvoices();
         }
         if (pageId === 'clients') {
             if (window.App.renderClients) window.App.renderClients();
         }
         if (pageId === 'dashboard') {
             if (window.App.loadDashboardStats) window.App.loadDashboardStats();
             if (window.App.loadDashboardChart) window.App.loadDashboardChart(window.App.chartPeriod);
             if (window.App.loadRanking) window.App.loadRanking();
         }
         if (pageId === 'users') {
             if (window.App.loadUsers) window.App.loadUsers();
         }
         if (pageId === 'help') {
             if (window.App.initHelpPage) window.App.initHelpPage();
         }
         if (pageId === 'about') {
             if (window.App.initAbout) window.App.initAbout();
         }
         if (pageId === 'emission') {
             if (window.App.initEmissionPage) window.App.initEmissionPage();
         }
     }
}
