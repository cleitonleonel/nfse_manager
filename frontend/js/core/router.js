export async function loadView(pageId) {
    const contentDiv = document.getElementById('app-content');
    if (!contentDiv) return false;
    
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
    
    // Trigger animation
    setTimeout(() => {
        newPage.classList.add('active');
    }, 10);
    
    return true;
}

export async function showPage(pageId) {
    document.querySelectorAll('.nav-item').forEach(p => p.classList.remove('active'));
    const navItem = document.getElementById(`nav-${pageId}`);
    if (navItem) navItem.classList.add('active');
    
    const titles = {dashboard: 'Dashboard', clients: 'Clientes', notes: 'Notas Fiscais', about: 'Sobre o Sistema'};
    const titleEl = document.getElementById('page-title');
    if (titleEl) titleEl.innerText = titles[pageId] || 'Dashboard';
    
    await loadView(pageId);
    
    // Trigger page specific initializations via App
    if (window.App) {
        window.App.activePage = pageId;
        if (pageId === 'notes') {
            if (window.App.loadNotes) window.App.loadNotes();
        }
        if (pageId === 'clients') {
            if (window.App.renderClients) window.App.renderClients();
        }
        if (pageId === 'dashboard') {
            if (window.App.loadDashboardStats) window.App.loadDashboardStats();
            if (window.App.loadDashboardChart) window.App.loadDashboardChart(window.App.chartPeriod);
            if (window.App.loadRanking) window.App.loadRanking();
        }
    }
}
