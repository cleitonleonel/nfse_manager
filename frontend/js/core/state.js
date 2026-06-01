export const state = {
    clients: [],
    activePage: 'dashboard',
    chartPeriod: '12m',
    currentTask: null,
    updateTask: null,
    updateReady: false,
    updateInfo: null,
    
    getGlobalClientId() {
        const el = document.getElementById('global-client-filter');
        return el ? el.value : '';
    },
    
    setGlobalClient(id, name) {
        const filter = document.getElementById('global-client-filter');
        if (filter) filter.value = id;
        const btnSpan = document.querySelector('#global-client-btn span');
        if (btnSpan) btnSpan.innerText = name;
        
        document.querySelectorAll('.dropdown-menu.show').forEach(m => m.classList.remove('show'));
        
        // Trigger global refresh
        if (window.App && window.App.onGlobalClientChange) {
            window.App.onGlobalClientChange();
        }
    }
};
