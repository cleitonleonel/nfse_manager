import { api } from '../core/api.js';
import { state } from '../core/state.js';

let chartInstance = null;

export async function loadDashboardStats() {
    const stat1 = document.getElementById('stat-total-value');
    if (!stat1) return; // not on dashboard page
    
    const clientId = state.getGlobalClientId();
    let url = '/analytics/stats';
    if (clientId) url += `?client_id=${clientId}`;
    
    try {
        const data = await api(url);
        const fmt = v => new Intl.NumberFormat('pt-BR', {style: 'currency', currency: 'BRL'}).format(v || 0);
        
        document.getElementById('stat-total-value').innerText = fmt(data.valor_emitidas);
        document.getElementById('stat-total-recebidas').innerText = fmt(data.valor_recebidas);
        document.getElementById('stat-saldo-liquido').innerText = `Saldo: ${fmt((data.valor_emitidas || 0) - (data.valor_recebidas || 0))}`;
        document.getElementById('stat-total-notes').innerText = (data.total_emitidas || 0) + (data.total_recebidas || 0);
        document.getElementById('stat-emitidas-recebidas').innerText = `${data.total_emitidas || 0} emitidas / ${data.total_recebidas || 0} recebidas`;
        document.getElementById('stat-active-clients').innerText = data.total_clientes || 0;
        
        const pendingEl = document.getElementById('stat-pending-dl');
        if (pendingEl) pendingEl.innerText = `${data.downloads_pendentes || 0} downloads pendentes`;
        
        await loadRecentInvoices();
    } catch (e) {
        console.error("Erro dashboard stats:", e);
    }
}

export async function loadRecentInvoices() {
    const tbody = document.getElementById('recent-invoices-body');
    if (!tbody) return;
    
    const clientId = state.getGlobalClientId();
    let url = '/invoices?tipo=emitidas';
    if (clientId) url += `&client_id=${clientId}`;
    
    try {
        const invoices = await api(url);
        const fmt = v => new Intl.NumberFormat('pt-BR', {style: 'currency', currency: 'BRL'}).format(v || 0);
        
        if (!invoices || invoices.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:30px; color:var(--text3);">Nenhuma nota recente encontrada.</td></tr>`;
            return;
        }
        
        tbody.innerHTML = invoices.slice(0, 5).map(n => {
            let files = '';
            if (n.xml_path) files += `<a href="#" onclick="window.App.triggerDownload(${JSON.stringify(n.xml_path)}); return false;" style="color:var(--green); font-weight:700; font-size:11px; margin-right:8px; text-decoration:none;" title="Baixar XML">XML</a>`;
            if (n.pdf_path) files += `<a href="#" onclick="window.App.triggerDownload(${JSON.stringify(n.pdf_path)}); return false;" style="color:var(--accent); font-weight:700; font-size:11px; text-decoration:none;" title="Baixar PDF">PDF</a>`;
            
            const dataFmt = n.data_emissao ? new Date(n.data_emissao).toLocaleDateString('pt-BR') : '-';
            return `
                <tr>
                    <td>${dataFmt}</td>
                    <td>
                        <div style="font-size:14px; font-weight:600; color:var(--text);">${n.numero || 'S/N'}</div>
                        <div style="font-size:11px; color:var(--text3); font-family:var(--mono); margin-top:2px; word-break:break-all;">${n.chave && n.chave !== 'null' ? n.chave : 'Chave não sincronizada'}</div>
                    </td>
                    <td style="font-weight:600; color:var(--text);">${fmt(n.valor)}</td>
                    <td><span class="badge" style="background:var(--green-bg); color:var(--green);"><div class="badge-dot"></div> ${n.status}</span></td>
                    <td>${files || '-'}</td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        console.error("Erro notas recentes:", e);
    }
}


export async function loadDashboardChart(period) {
    const canvas = document.getElementById('dashboardChart');
    if (!canvas) return;
    
    state.chartPeriod = period;
    const clientId = state.getGlobalClientId();
    let url = `/analytics/chart?period=${period}`;
    if (clientId) url += `&client_id=${clientId}`;
    
    try {
        const raw = await api(url);
        // Backend returns {points: [{label, emitidas, recebidas, valor}]}
        const points = (raw.points || []);
        const labels = points.map(p => p.label);
        const valoresEmitidos = points.map(p => p.valor || 0);
        const qtdRecebidas = points.map(p => p.recebidas || 0);
        
        const isDark = !document.body.classList.contains('theme-light');
        const textColor = isDark ? '#94a3b8' : '#64748b';
        const gridColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
        const tooltipBg = isDark ? '#1e293b' : '#ffffff';
        const tooltipText = isDark ? '#f8fafc' : '#0f172a';
        
        const ctx = canvas.getContext('2d');
        if (chartInstance) chartInstance.destroy();
        
        chartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Valor Emitido (R$)',
                        data: valoresEmitidos,
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59,130,246,0.1)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.4
                    },
                    {
                        label: 'Qtd. Recebidas',
                        data: qtdRecebidas,
                        borderColor: '#10b981',
                        backgroundColor: 'transparent',
                        borderWidth: 2,
                        borderDash: [5, 5],
                        fill: false,
                        tension: 0.4
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: tooltipBg,
                        titleColor: tooltipText,
                        bodyColor: textColor,
                        borderColor: gridColor,
                        borderWidth: 1,
                        padding: 12
                    }
                },
                scales: {
                    x: { grid: { display: false, drawBorder: false }, ticks: { color: textColor, font: {family: "'Outfit', sans-serif"} } },
                    y: { grid: { color: gridColor, drawBorder: false }, ticks: { color: textColor, font: {family: "'Outfit', sans-serif"} }, beginAtZero: true }
                }
            }
        });
    } catch (e) {
        console.error("Erro chart:", e);
    }
}


export function changeChartPeriod(period, btn) {
    document.querySelectorAll('.btn-group .btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    loadDashboardChart(period);
    
    if (window.App && window.App.loadRanking) {
        window.App.loadRanking();
    }
}

export async function loadRanking() {
    const rankingSection = document.getElementById('ranking-section');
    if (!rankingSection) return;
    
    const clientId = state.getGlobalClientId();
    if (clientId) {
        rankingSection.style.display = 'none';
        return;
    }
    
    rankingSection.style.display = 'flex';
    try {
        const data = await api(`/analytics/ranking?period=${state.chartPeriod}`);
        const fmt = v => new Intl.NumberFormat('pt-BR', {style: 'currency', currency: 'BRL'}).format(v);
        
        const renderList = (items, emptyMsg) => {
            if (!items || items.length === 0) return `<div style="color:var(--text3); font-size:13px;">${emptyMsg}</div>`;
            return items.map((item, i) => `
                <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 0; border-bottom:1px solid var(--border);">
                    <div style="display:flex; align-items:center; gap:12px;">
                        <div style="width:24px; height:24px; border-radius:50%; background:var(--bg-card); display:flex; align-items:center; justify-content:center; font-size:12px; font-weight:700; color:var(--text); border:1px solid var(--border);">${i + 1}</div>
                        <div style="font-weight:500; font-size:13px;" title="${item.razao_social}">${item.razao_social.length > 25 ? item.razao_social.substring(0, 25) + '...' : item.razao_social}</div>
                    </div>
                    <div style="font-weight:600; font-size:13px; color:var(--text);">${fmt(item.valor)}</div>
                </div>
            `).join('');
        };
        
        document.getElementById('ranking-emitidas').innerHTML = renderList(data.top_emitidas, 'Nenhum faturamento no período.');
        document.getElementById('ranking-recebidas').innerHTML = renderList(data.top_recebidas, 'Nenhuma despesa no período.');
    } catch (e) {
        console.warn('Erro ao carregar ranking:', e);
    }
}

export function exportReport(format) {
    if (!format) return;
    
    const clientId = state.getGlobalClientId();
    let url = `http://localhost:8000/api/reports/export?format=${format}&period=${state.chartPeriod}`;
    if (clientId) url += `&client_id=${clientId}`;
    
    if (format === 'json') {
        window.open(url, '_blank');
    } else {
        const a = document.createElement('a');
        a.href = url;
        a.download = `relatorio_nfse.${format}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }
    document.querySelectorAll('.dropdown-menu.show').forEach(m => m.classList.remove('show'));
}
