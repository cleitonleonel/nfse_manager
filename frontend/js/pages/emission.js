import { api } from '../core/api.js';
import { state } from '../core/state.js';
import { showTaskToast, completeTaskToast, failTaskToast, uiAlert, uiConfirm, uiPrompt, maskCnpj, maskCep, formatCnpj, formatCep } from '../core/ui.js';
import { enhanceSelects } from '../core/custom-select.js';
import { loadBatchImports } from './batch.js';

let savedCustomers = [];
let savedServices = [];
let catalogFavorites = [];
let catalogServicos = [];
let catalogIndOps = [];
let catalogCClassTribs = [];
let allAnexoViiiCorrelacoes = null;
let currentCorrelacoes = [];
let currentNbsCombinations = null;
let showingAllNbs = false;
let showingAllClassTrib = false;
let showingAllIndOp = false;

const LC116_GROUP_LABELS = {
    '01': '01 — Informática e Tecnologia da Informação',
    '02': '02 — Pesquisas e Desenvolvimento',
    '03': '03 — Locação e Cessão de Bens/Direitos',
    '04': '04 — Saúde, Medicina e Assistência Médica',
    '05': '05 — Medicina Veterinária',
    '06': '06 — Estética, Cuidados Pessoais e Atividades Físicas',
    '07': '07 — Engenharia, Arquitetura e Construção Civil',
    '08': '08 — Educação, Ensino e Treinamento',
    '09': '09 — Hospedagem e Turismo',
    '10': '10 — Intermediação, Agenciamento e Corretagem',
    '11': '11 — Guarda, Estacionamento, Vigilância e Logística',
    '12': '12 — Diversões, Lazer e Eventos',
    '13': '13 — Fonografia, Fotografia e Reprografia',
    '14': '14 — Manutenção, Reparo e Serviços sobre Bens',
    '15': '15 — Bancos, Serviços Financeiros e Cartões',
    '16': '16 — Transporte Municipal e Fretamento',
    '17': '17 — Apoio Técnico, Administrativo, Jurídico e Contábil',
    '18': '18 — Regulação de Sinistros e Seguros',
    '19': '19 — Loterias, Apostas e Sorteios',
    '20': '20 — Portuários, Aeroportuários e Terminais',
    '21': '21 — Registros Públicos, Cartorários e Notariais',
    '22': '22 — Exploração de Rodovias',
    '23': '23 — Programação e Comunicação Visual',
    '24': '24 — Chaveiros e Carimbos',
    '25': '25 — Serviços Funerários',
    '26': '26 — Coleta, Remessa e Entrega (Correios)',
    '27': '27 — Assistência Social',
    '28': '28 — Avaliação de Bens e Serviços',
    '29': '29 — Biblioteconomia',
    '30': '30 — Biologia e Biotecnologia',
    '31': '31 — Serviços Técnicos em Edificações e Eletrônica',
    '32': '32 — Desenhos Técnicos',
    '33': '33 — Desembaraço Aduaneiro e Despachantes',
    '34': '34 — Investigações Particulares',
    '35': '35 — Jornalismo e Assessoria de Imprensa',
    '36': '36 — Meteorologia',
    '37': '37 — Artistas, Atletas, Modelos e Manequins',
    '38': '38 — Museologia',
    '39': '39 — Ourivesaria e Lapidação',
    '40': '40 — Obras de Arte sob Encomenda',
    '99': '99 — Serviços Especiais sem Incidência de ISSQN/ICMS',
};

const fmtBRL = v => new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(Number(v || 0));

function escapeHtml(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

export async function initEmissionPage() {
    // Substitui os <select> nativos por dropdowns próprios (evita seleção
    // acidental no mesmo clique que abre o popup nativo no Linux/GTK).
    enhanceSelects(document.getElementById('page-emission'));
    await Promise.all([
        loadCatalogOptions(),
        loadSavedCustomersAndServices(),
        loadFilaContingencia(),
    ]);
    // Inicializa a correlação inicial conforme o cTribNac selecionado
    const initialCtrib = document.getElementById('em-ctribnac')?.value || '010101';
    await onChangeCTribNac(initialCtrib);
}

export function switchEmissionTab(tab) {
    const tabs = ['emitir', 'lote', 'fila', 'cadastros'];
    tabs.forEach(t => {
        const el = document.getElementById(`emission-tab-${t}`);
        const btn = document.getElementById(`tab-btn-${t}`);
        if (el) {
            el.style.display = t === tab ? (t === 'emitir' || t === 'cadastros' ? 'grid' : 'block') : 'none';
        }
        if (btn) {
            btn.className = t === tab ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm';
        }
    });
    if (tab === 'lote') {
        renderLoteTab();
        loadBatchImports();
    }
    if (tab === 'fila') loadFilaContingencia();
    if (tab === 'cadastros') renderSavedRegistriesTables();
}

async function loadCatalogOptions() {
    try {
        const [servicos, indops, cclasstribs] = await Promise.all([
            api('/catalogs/servicos?limite=500').catch(() => []),
            api('/catalogs/indop').catch(() => []),
            api('/catalogs/cclasstrib?apenas_nfse=true').catch(() => []),
        ]);
        catalogServicos = servicos || [];
        catalogIndOps = indops || [];
        catalogCClassTribs = cclasstribs || [];

        // Preenche select cTribNac com todos os 338 serviços oficiais da LC 116 agrupados
        const ctribSel = document.getElementById('em-ctribnac');
        if (ctribSel && catalogServicos.length > 0) {
            const currentVal = ctribSel.value || '010101';
            const groups = new Map();
            for (const s of catalogServicos) {
                const gCode = String(s.cTribNac || '').slice(0, 2) || '99';
                if (!groups.has(gCode)) groups.set(gCode, []);
                groups.get(gCode).push(s);
            }
            ctribSel.innerHTML = Array.from(groups.entries()).map(([gCode, list]) => {
                const gLabel = LC116_GROUP_LABELS[gCode] || `Grupo ${gCode}`;
                const opts = list.map(s => {
                    const desc = s.descricao || `Serviço ${s.cTribNac}`;
                    return `<option value="${s.cTribNac}">${s.cTribNac} (${s.item_lc116}) — ${escapeHtml(desc)}</option>`;
                }).join('');
                return `<optgroup label="${escapeHtml(gLabel)}">${opts}</optgroup>`;
            }).join('');
            ctribSel.value = catalogServicos.some(s => s.cTribNac === currentVal) ? currentVal : catalogServicos[0].cTribNac;
        }

        // Preenche select cIndOp com todos os 28 indicadores oficiais
        const indopSel = document.getElementById('em-cindop');
        if (indopSel && catalogIndOps.length > 0) {
            populateIndOpSelect(catalogIndOps, indopSel.value || '100301', false);
        }

        // Preenche select cClassTrib com todas as 66 classificações válidas na NFS-e
        const classSel = document.getElementById('em-cclasstrib');
        if (classSel && catalogCClassTribs.length > 0) {
            populateClassTribSelect(catalogCClassTribs, classSel.value || '000001', false);
        }
    } catch (e) {
        console.warn('Erro ao carregar opções de catálogos:', e);
    }
}

export async function loadSavedCustomersAndServices() {
    const clientId = state.getGlobalClientId();
    const qs = clientId ? `?client_id=${clientId}` : '';
    try {
        const [custs, srvs, favs] = await Promise.all([
            api(`/customers${qs}`).catch(() => []),
            api(`/service-items${qs}`).catch(() => []),
            api('/catalogs/favoritos').catch(() => []),
        ]);
        savedCustomers = custs || [];
        savedServices = srvs || [];
        catalogFavorites = favs || [];

        const custSel = document.getElementById('em-customer-select');
        if (custSel) {
            const count = savedCustomers.length;
            let html = `<option value="">-- Selecionar Tomador Salvo (${count}) --</option>`;
            if (savedCustomers.length > 0) {
                html += savedCustomers.map(c => {
                    const docPart = c.documento ? ` (${c.documento})` : '';
                    const name = c.razao_social || c.documento || 'Tomador';
                    return `<option value="${c.id}">${name}${docPart}</option>`;
                }).join('');
            }
            custSel.innerHTML = html;
        }

        const srvSel = document.getElementById('em-service-select');
        if (srvSel) {
            let html = `<option value="">-- Selecionar Serviço para Emissão --</option>`;
            if (savedServices.length > 0) {
                html += `<optgroup label="Meus Serviços Cadastrados">`;
                html += savedServices.map(s => {
                    const tit = s.titulo || s.descricao || 'Serviço Recorrente';
                    const cTrib = s.c_trib_nac ? `cTribNac ${s.c_trib_nac}` : '';
                    const val = s.valor_unitario > 0 ? fmtBRL(s.valor_unitario) : '';
                    const meta = [cTrib, val].filter(Boolean).join(' - ');
                    const metaStr = meta ? ` (${meta})` : '';
                    return `<option value="srv_${s.id}">★ ${tit}${metaStr}</option>`;
                }).join('');
                html += `</optgroup>`;
            }
            if (catalogFavorites.length > 0) {
                html += `<optgroup label="Modelos Pré-configurados (Anexo VIII / LC 116)">`;
                html += catalogFavorites.map((f, idx) => {
                    const tit = f.nome || f.titulo || f.descricao_nbs || 'Serviço Padrão';
                    const lc = f.item_lc116 ? `LC 116: ${f.item_lc116}` : (f.cTribNac ? `cTribNac: ${f.cTribNac}` : '');
                    const nbs = f.cNBS ? `NBS: ${f.cNBS}` : '';
                    const meta = [lc, nbs].filter(Boolean).join(' | ');
                    const metaStr = meta ? ` (${meta})` : '';
                    return `<option value="fav_${idx}">${tit}${metaStr}</option>`;
                }).join('');
                html += `</optgroup>`;
            }
            srvSel.innerHTML = html;
        }
        renderSavedRegistriesTables();
        renderLoteTab();
    } catch (e) {
        console.warn('Erro ao carregar cadastros recorrentes:', e);
    }
}

export function onSelectSavedCustomer(customerId) {
    if (!customerId) return;
    const c = savedCustomers.find(x => String(x.id) === String(customerId));
    if (!c) return;
    document.getElementById('em-tomador-doc').value = c.documento || '';
    document.getElementById('em-tomador-nome').value = c.razao_social || '';
    document.getElementById('em-tomador-email').value = c.email || '';
    document.getElementById('em-tomador-cep').value = c.cep || '';
    document.getElementById('em-tomador-logradouro').value = c.logradouro || '';
    document.getElementById('em-tomador-numero').value = c.numero || 'S/N';
    document.getElementById('em-tomador-bairro').value = c.bairro || '';
    if (c.complemento) {
        const comp = document.getElementById('em-tomador-complemento');
        if (comp) comp.value = c.complemento;
    }
    document.getElementById('em-tomador-ibge').value = c.codigo_municipio || '3201308';
}

export async function onSelectSavedService(val) {
    if (!val) return;
    if (val.startsWith('srv_')) {
        const id = val.replace('srv_', '');
        const s = savedServices.find(x => String(x.id) === String(id));
        if (!s) return;
        const targetCtrib = s.c_trib_nac || '010101';
        ensureSelectHasOption('em-ctribnac', targetCtrib);
        await onChangeCTribNac(targetCtrib, s.c_nbs || '115021000');
        if (s.c_class_trib) {
            ensureSelectHasOption('em-cclasstrib', s.c_class_trib);
            onSelectClassTrib(s.c_class_trib);
        }
        if (s.c_ind_op) {
            ensureSelectHasOption('em-cindop', s.c_ind_op);
            onSelectIndOp(s.c_ind_op);
        }
        document.getElementById('em-descricao').value = s.descricao || s.titulo || '';
        if (s.valor_unitario > 0) document.getElementById('em-valor').value = s.valor_unitario;
        if (s.aliquota_iss != null) document.getElementById('em-aliq-iss').value = s.aliquota_iss;
        document.getElementById('em-iss-retido').checked = Boolean(s.iss_retido);
        document.getElementById('em-reter-federais').checked = Boolean(s.reter_federais);
    } else if (val.startsWith('fav_')) {
        const idx = parseInt(val.replace('fav_', ''), 10);
        const f = catalogFavorites[idx];
        if (!f) return;
        const targetCtrib = f.cTribNac || '010101';
        ensureSelectHasOption('em-ctribnac', targetCtrib);
        const targetNbs = (f.cNBS || f.nbs || '115021000').replace(/\D/g, '');
        await onChangeCTribNac(targetCtrib, targetNbs);
        if (f.cClassTrib) {
            ensureSelectHasOption('em-cclasstrib', f.cClassTrib);
            onSelectClassTrib(f.cClassTrib);
        }
        if (f.indop) {
            ensureSelectHasOption('em-cindop', f.indop);
            onSelectIndOp(f.indop);
        }
        document.getElementById('em-descricao').value = f.nome || f.titulo || f.descricao_nbs || '';
        if (f.aliquota_iss_padrao != null) document.getElementById('em-aliq-iss').value = f.aliquota_iss_padrao;
    }
    await recalculateEmissionPreview();
}

export function onSelectClassTrib(val) {
    if (!val) return;
    const hintClass = document.getElementById('hint-cclasstrib');
    if (hintClass) {
        const found = catalogCClassTribs.find(c => String(c.codigo) === String(val));
        if (found) {
            let red = '';
            if (found.perc_red_ibs > 0) {
                red = ` | Redução: ${found.perc_red_ibs}% IBS / ${found.perc_red_cbs || found.perc_red_ibs}% CBS`;
            }
            hintClass.innerHTML = `<span>${found.nome || found.nome_reduzido}${red}</span>`;
        } else {
            const opt = document.getElementById('em-cclasstrib')?.selectedOptions?.[0];
            hintClass.innerHTML = `<span>${opt ? opt.text : `Classificação Tributária ${val}`}</span>`;
        }
    }
    recalculateEmissionPreview();
}

export function onSelectIndOp(val) {
    if (!val) return;
    const hintIndop = document.getElementById('hint-cindop');
    if (hintIndop) {
        const found = catalogIndOps.find(i => String(i.cIndOp) === String(val));
        if (found) {
            hintIndop.innerHTML = `<span>Local de incidência: ${found.local_incidencia || 'Padrão'}</span>`;
        } else {
            const opt = document.getElementById('em-cindop')?.selectedOptions?.[0];
            hintIndop.innerHTML = `<span>${opt ? opt.text : `Indicador de Operação ${val}`}</span>`;
        }
    }
    recalculateEmissionPreview();
}

function populateClassTribSelect(list, preferredVal = null, filteredByNbs = false) {
    const classSel = document.getElementById('em-cclasstrib');
    if (!classSel || !list || list.length === 0) return;

    const currentVal = preferredVal || classSel.value || '000001';
    const formatOpt = (c) => {
        const label = c.nome_reduzido || c.nome || `Classificação ${c.codigo}`;
        const redText = c.perc_red_ibs > 0 ? ` (Red. ${c.perc_red_ibs}%)` : '';
        return `<option value="${c.codigo}">${c.codigo} — ${escapeHtml(label)}${redText}</option>`;
    };

    if (filteredByNbs) {
        classSel.innerHTML = `<optgroup label="Compatíveis com a NBS selecionada (${list.length})">${list.map(formatOpt).join('')}</optgroup>`;
    } else {
        const anexo = list.filter(c => c.ind_anexo_viii);
        const outras = list.filter(c => !c.ind_anexo_viii);
        let html = '';
        if (anexo.length > 0) {
            html += `<optgroup label="Anexo VIII — NFS-e (${anexo.length})">${anexo.map(formatOpt).join('')}</optgroup>`;
        }
        if (outras.length > 0) {
            html += `<optgroup label="Demais Classificações Aplicáveis à NFS-e (${outras.length})">${outras.map(formatOpt).join('')}</optgroup>`;
        }
        classSel.innerHTML = html || list.map(formatOpt).join('');
    }
    classSel.value = list.some(c => String(c.codigo) === String(currentVal)) ? String(currentVal) : String(list[0].codigo);
}

function populateIndOpSelect(list, preferredVal = null, filteredByNbs = false) {
    const indopSel = document.getElementById('em-cindop');
    if (!indopSel || !list || list.length === 0) return;

    const currentVal = preferredVal || indopSel.value || '100301';
    const optsHtml = list.map(i => {
        const desc = i.local_incidencia || 'Local de incidência padrão';
        return `<option value="${i.cIndOp}">${i.cIndOp} — ${escapeHtml(desc)}</option>`;
    }).join('');
    indopSel.innerHTML = filteredByNbs
        ? `<optgroup label="Compatíveis com a NBS selecionada (${list.length})">${optsHtml}</optgroup>`
        : optsHtml;
    indopSel.value = list.some(i => String(i.cIndOp) === String(currentVal)) ? String(currentVal) : String(list[0].cIndOp);
}

export function toggleAllClassTribOptions(forceAll = null) {
    const btn = document.getElementById('btn-show-all-cclasstrib');
    const wantAll = forceAll !== null ? forceAll : !showingAllClassTrib;
    const currentVal = document.getElementById('em-cclasstrib')?.value || '000001';

    if (!wantAll && currentNbsCombinations?.cclasstrib_compativeis?.length > 0) {
        showingAllClassTrib = false;
        populateClassTribSelect(currentNbsCombinations.cclasstrib_compativeis, currentVal, true);
        if (btn) btn.textContent = `Ver todas (${catalogCClassTribs.length || 66})`;
    } else {
        showingAllClassTrib = true;
        if (catalogCClassTribs.length > 0) {
            populateClassTribSelect(catalogCClassTribs, currentVal, false);
        }
        if (btn) btn.textContent = 'Filtrar pela NBS';
    }
    onSelectClassTrib(document.getElementById('em-cclasstrib')?.value);
}

export function toggleAllIndOpOptions(forceAll = null) {
    const btn = document.getElementById('btn-show-all-cindop');
    const wantAll = forceAll !== null ? forceAll : !showingAllIndOp;
    const currentVal = document.getElementById('em-cindop')?.value || '100301';

    if (!wantAll && currentNbsCombinations?.cindop_compativeis?.length > 0) {
        showingAllIndOp = false;
        populateIndOpSelect(currentNbsCombinations.cindop_compativeis, currentVal, true);
        if (btn) btn.textContent = `Ver todos (${catalogIndOps.length || 28})`;
    } else {
        showingAllIndOp = true;
        if (catalogIndOps.length > 0) {
            populateIndOpSelect(catalogIndOps, currentVal, false);
        }
        if (btn) btn.textContent = 'Filtrar pela NBS';
    }
    onSelectIndOp(document.getElementById('em-cindop')?.value);
}

function ensureSelectHasOption(selectId, value, label = null) {
    const sel = document.getElementById(selectId);
    if (!sel || !value) return;
    const cleanVal = String(value).trim();
    if (!cleanVal || cleanVal === 'undefined') return;
    const exists = Array.from(sel.options).some(o => o.value === cleanVal);
    if (!exists) {
        const newOpt = document.createElement('option');
        newOpt.value = cleanVal;
        newOpt.text = label && !label.includes('undefined') ? label : `${cleanVal} — Opção Específica`;
        sel.appendChild(newOpt);
    }
    if (sel.value !== cleanVal) {
        sel.value = cleanVal;
    }
}

async function populateNbsSelectFromCorrelacoes(correlacoes, preferredNbs = null, groupLabel = null) {
    const nbsSelect = document.getElementById('em-cnbs-select');
    if (!nbsSelect || !correlacoes || correlacoes.length === 0) return false;

    const nbsMap = new Map();
    for (const c of correlacoes) {
        const rawNbs = (c.cNBS || c.c_nbs || c.nbs || '').replace(/\D/g, '');
        if (rawNbs && !nbsMap.has(rawNbs)) {
            const desc = c.descricao_nbs || c.nome_cClassTrib || 'Serviço tributável';
            nbsMap.set(rawNbs, desc);
        }
    }
    if (nbsMap.size === 0) return false;

    const optsHtml = Array.from(nbsMap.entries()).map(([code, desc]) =>
        `<option value="${code}">${code} — ${escapeHtml(desc)}</option>`
    ).join('');
    nbsSelect.innerHTML = groupLabel
        ? `<optgroup label="${escapeHtml(groupLabel)}">${optsHtml}</optgroup>`
        : optsHtml;

    const chosenNbs = (preferredNbs && nbsMap.has(preferredNbs))
        ? preferredNbs
        : Array.from(nbsMap.keys())[0];

    nbsSelect.value = chosenNbs;
    await onSelectNbsOption(chosenNbs);
    return true;
}

export async function loadAllNbsOptions(forceAll = null) {
    const toggleBtn = document.getElementById('btn-show-all-nbs');
    const hintNbs = document.getElementById('hint-cnbs');
    const wantAll = forceAll !== null ? forceAll : !showingAllNbs;

    if (!wantAll) {
        showingAllNbs = false;
        if (toggleBtn) toggleBtn.textContent = 'Ver todas as NBS';
        const curCtrib = document.getElementById('em-ctribnac')?.value || '010101';
        await onChangeCTribNac(curCtrib);
        return;
    }

    try {
        if (!allAnexoViiiCorrelacoes) {
            if (toggleBtn) toggleBtn.textContent = 'Carregando...';
            allAnexoViiiCorrelacoes = await api('/catalogs/correlacoes?limite=2000');
        }
        showingAllNbs = true;
        currentCorrelacoes = allAnexoViiiCorrelacoes || [];
        const currentNbs = (document.getElementById('em-cnbs-select')?.value || document.getElementById('em-cnbs')?.value || '').replace(/\D/g, '');
        await populateNbsSelectFromCorrelacoes(
            currentCorrelacoes,
            currentNbs || null,
            'Catálogo Completo NBS — Anexo VIII'
        );
        if (toggleBtn) toggleBtn.textContent = 'Filtrar pelo cTribNac';
        if (hintNbs) hintNbs.innerHTML = `<span>Exibindo todas as nomenclaturas NBS oficiais do Anexo VIII (${document.getElementById('em-cnbs-select')?.options.length || 0} códigos)</span>`;
    } catch (e) {
        console.warn('Erro ao carregar todas as NBS:', e);
        if (toggleBtn) toggleBtn.textContent = 'Ver todas as NBS';
    }
}

export async function onChangeCTribNac(cTribNac, preferredNbs = null) {
    const clean = (cTribNac || '').replace(/\D/g, '');
    const hintCtrib = document.getElementById('hint-ctribnac');
    const hintNbs = document.getElementById('hint-cnbs');
    const toggleBtn = document.getElementById('btn-show-all-nbs');
    showingAllNbs = false;
    if (toggleBtn) toggleBtn.textContent = 'Ver todas as NBS';

    if (clean.length === 6) {
        const srvMeta = catalogServicos.find(s => s.cTribNac === clean);
        try {
            // Busca correlações no Anexo VIII para este cTribNac
            const correlacoes = await api(`/catalogs/correlacoes?c_trib_nac=${clean}&limite=200`);
            currentCorrelacoes = correlacoes || [];

            // Atualiza hint do subitem LC 116
            if (hintCtrib) {
                const first = currentCorrelacoes[0];
                const item = srvMeta?.item_lc116 || first?.item_lc116 || `${clean.slice(0, 2)}.${clean.slice(2, 4)}`;
                const desc = srvMeta?.descricao || first?.descricao_lc116 || 'Serviço LC 116/2003';
                const issRule = srvMeta?.regra_incidencia_issqn ? ` · Incidência ISS: ${srvMeta.regra_incidencia_issqn}` : '';
                hintCtrib.innerHTML = `<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 14 14"></polyline></svg><span>Subitem ${escapeHtml(item)} — ${escapeHtml(desc)}${escapeHtml(issRule)}</span>`;
            }

            if (await populateNbsSelectFromCorrelacoes(currentCorrelacoes, preferredNbs)) {
                if (hintNbs) {
                    const count = document.getElementById('em-cnbs-select')?.options.length || 0;
                    hintNbs.innerHTML = `<span>${count} nomenclatura(s) NBS oficial(is) vinculada(s) a este cTribNac</span>`;
                }
                return;
            }

            // Fallback para cTribNac sem correlação direta no Anexo VIII (ex: 990101, 990401)
            await loadAllNbsOptions(true);
            if (hintNbs) {
                hintNbs.innerHTML = `<span>Sem vínculo específico no Anexo VIII; exibindo todas as NBS disponíveis.</span>`;
            }
            return;
        } catch (e) {
            console.warn('Correlação Anexo VIII não encontrada:', e);
        }
    }
    await recalculateEmissionPreview();
}

export async function onSelectNbsOption(nbsCode) {
    if (!nbsCode) return;
    const cleanNbs = nbsCode.replace(/\D/g, '');
    const nbsHidden = document.getElementById('em-cnbs');
    if (nbsHidden) nbsHidden.value = cleanNbs;

    const ctribVal = (document.getElementById('em-ctribnac')?.value || '').replace(/\D/g, '');
    showingAllClassTrib = false;
    showingAllIndOp = false;

    try {
        const qs = ctribVal ? `?c_trib_nac=${encodeURIComponent(ctribVal)}` : '';
        currentNbsCombinations = await api(`/catalogs/nbs/${cleanNbs}/combinacoes${qs}`);
    } catch (_) {
        currentNbsCombinations = null;
    }

    let corr = currentCorrelacoes.find(c => (c.cNBS || c.c_nbs || c.nbs || '').replace(/\D/g, '') === cleanNbs);
    if (!corr && currentCorrelacoes.length > 0) {
        corr = currentCorrelacoes[0];
    }

    const defaultClass = corr?.cClassTrib || corr?.c_class_trib || currentNbsCombinations?.cclasstrib_compativeis?.[0]?.codigo || '000001';
    const defaultIndop = corr?.indop || corr?.c_ind_op || currentNbsCombinations?.cindop_compativeis?.[0]?.cIndOp || '100301';

    const btnCt = document.getElementById('btn-show-all-cclasstrib');
    const btnInd = document.getElementById('btn-show-all-cindop');

    if (currentNbsCombinations?.cclasstrib_compativeis?.length > 0) {
        populateClassTribSelect(currentNbsCombinations.cclasstrib_compativeis, defaultClass, true);
        if (btnCt) btnCt.textContent = `Ver todas (${catalogCClassTribs.length || 66})`;
    } else if (catalogCClassTribs.length > 0) {
        populateClassTribSelect(catalogCClassTribs, defaultClass, false);
        if (btnCt) btnCt.textContent = 'Filtrar pela NBS';
    }

    if (currentNbsCombinations?.cindop_compativeis?.length > 0) {
        populateIndOpSelect(currentNbsCombinations.cindop_compativeis, defaultIndop, true);
        if (btnInd) btnInd.textContent = `Ver todos (${catalogIndOps.length || 28})`;
    } else if (catalogIndOps.length > 0) {
        populateIndOpSelect(catalogIndOps, defaultIndop, false);
        if (btnInd) btnInd.textContent = 'Filtrar pela NBS';
    }

    const hintClass = document.getElementById('hint-cclasstrib');
    if (hintClass) {
        const qtdCt = currentNbsCombinations?.cclasstrib_compativeis?.length || 0;
        const nomeCt = corr?.nome_cClassTrib || 'Classificação padrão';
        hintClass.innerHTML = qtdCt > 0
            ? `<span>${qtdCt} opção(ões) compatível(is) com NBS ${cleanNbs} · ${escapeHtml(nomeCt)}</span>`
            : `<span>${escapeHtml(nomeCt)}</span>`;
    }
    const hintIndop = document.getElementById('hint-cindop');
    if (hintIndop) {
        const qtdInd = currentNbsCombinations?.cindop_compativeis?.length || 0;
        const localInd = corr?.local_incidencia_ibs || 'Incidência padrão';
        hintIndop.innerHTML = qtdInd > 0
            ? `<span>${qtdInd} indicador(es) compatível(is) com NBS ${cleanNbs} · ${escapeHtml(localInd)}</span>`
            : `<span>Incidência: ${escapeHtml(localInd)}</span>`;
    }

    await recalculateEmissionPreview();
}

let lastSearchedCnpj = '';
let lastSearchedCep = '';

export function handleEmissionCnpjInput(input) {
    maskCnpj(input);
    const clean = (input.value || '').toUpperCase().replace(/[^0-9A-Z]/g, '');
    if (clean.length === 14 && clean !== lastSearchedCnpj) {
        lastSearchedCnpj = clean;
        lookupEmissionCnpj();
    }
}

export function handleEmissionCepInput(input) {
    maskCep(input);
    const clean = (input.value || '').replace(/\D/g, '');
    if (clean.length === 8 && clean !== lastSearchedCep) {
        lastSearchedCep = clean;
        lookupEmissionCep();
    }
}

export async function lookupEmissionCnpj() {
    const doc = (document.getElementById('em-tomador-doc')?.value || '').toUpperCase().replace(/[^0-9A-Z]/g, '');
    if (doc.length !== 14) return;
    try {
        showTaskToast('Consultando CNPJ', 'Buscando razão social, endereço e código IBGE...');
        const data = await api(`/lookup/cnpj/${doc}`);
        if (data.razao_social) document.getElementById('em-tomador-nome').value = data.razao_social;
        if (data.email) document.getElementById('em-tomador-email').value = data.email;
        if (data.cep) {
            const cepInput = document.getElementById('em-tomador-cep');
            if (cepInput) cepInput.value = formatCep(data.cep);
        }
        if (data.logradouro) document.getElementById('em-tomador-logradouro').value = data.logradouro;
        if (data.numero) document.getElementById('em-tomador-numero').value = data.numero;
        if (data.bairro) document.getElementById('em-tomador-bairro').value = data.bairro;
        if (data.complemento) {
            const comp = document.getElementById('em-tomador-complemento');
            if (comp) comp.value = data.complemento;
        }
        if (data.codigo_municipio) document.getElementById('em-tomador-ibge').value = data.codigo_municipio;
        completeTaskToast('CNPJ Consultado', 'Dados do tomador preenchidos.', 2500);
    } catch (e) {
        failTaskToast('Consulta CNPJ', 'Não foi possível consultar o CNPJ automaticamente.', 3000);
        console.warn('Não foi possível consultar o CNPJ:', e);
    }
}

export async function lookupEmissionCep() {
    const cep = (document.getElementById('em-tomador-cep')?.value || '').replace(/\D/g, '');
    if (cep.length !== 8) return;
    try {
        const data = await api(`/lookup/cep/${cep}`);
        if (data.logradouro) document.getElementById('em-tomador-logradouro').value = data.logradouro;
        if (data.bairro) document.getElementById('em-tomador-bairro').value = data.bairro;
        if (data.codigo_municipio) document.getElementById('em-tomador-ibge').value = data.codigo_municipio;
    } catch (e) {
        console.warn('CEP não encontrado:', e);
    }
}

export async function saveCurrentCustomerFromEmission() {
    const documento = document.getElementById('em-tomador-doc')?.value || '';
    const razao_social = document.getElementById('em-tomador-nome')?.value || '';
    if (!documento || !razao_social) {
        await uiAlert({ title: 'Dados incompletos', message: 'Preencha CNPJ e Razão Social do tomador antes de salvar.', variant: 'warning' });
        return;
    }
    try {
        const clientId = state.getGlobalClientId();
        await api('/customers', 'POST', {
            client_id: clientId ? parseInt(clientId, 10) : null,
            documento,
            razao_social,
            email: document.getElementById('em-tomador-email')?.value || null,
            cep: document.getElementById('em-tomador-cep')?.value || null,
            logradouro: document.getElementById('em-tomador-logradouro')?.value || null,
            numero: document.getElementById('em-tomador-numero')?.value || 'S/N',
            bairro: document.getElementById('em-tomador-bairro')?.value || null,
            complemento: document.getElementById('em-tomador-complemento')?.value || null,
            codigo_municipio: document.getElementById('em-tomador-ibge')?.value || '3201308',
        });
        await loadSavedCustomersAndServices();
        completeTaskToast('Tomador Salvo', 'Tomador salvo com sucesso para emissões futuras!', 3500);
    } catch (e) {
        await uiAlert({ title: 'Erro ao salvar tomador', message: e.message, variant: 'error' });
    }
}

export async function saveCurrentServiceFromEmission() {
    const descricao = document.getElementById('em-descricao')?.value || '';
    if (!descricao) {
        await uiAlert({ title: 'Descrição obrigatória', message: 'Preencha a descrição do serviço antes de salvar.', variant: 'warning' });
        return;
    }
    const titulo = await uiPrompt({
        title: 'Salvar Serviço Recorrente',
        subtitle: 'Informe um título curto para identificar facilmente este serviço em futuras emissões.',
        label: 'Título do serviço recorrente',
        placeholder: 'Ex: Consultoria mensal em TI',
        defaultValue: descricao.slice(0, 45),
        confirmText: 'Salvar Serviço',
        variant: 'primary',
        icon: 'bookmark',
        emptyMessage: 'Informe um título para identificar o serviço.',
    });
    if (!titulo) return;
    try {
        const clientId = state.getGlobalClientId();
        const nbsVal = document.getElementById('em-cnbs-select')?.value || document.getElementById('em-cnbs')?.value || '115021000';
        const created = await api('/service-items', 'POST', {
            client_id: clientId ? parseInt(clientId, 10) : null,
            titulo,
            descricao,
            valor_unitario: parseFloat(document.getElementById('em-valor')?.value || '0'),
            c_trib_nac: document.getElementById('em-ctribnac')?.value || '010101',
            c_nbs: nbsVal.replace(/\D/g, ''),
            c_class_trib: document.getElementById('em-cclasstrib')?.value || '000001',
            c_ind_op: document.getElementById('em-cindop')?.value || '100301',
            aliquota_iss: parseFloat(document.getElementById('em-aliq-iss')?.value || '2'),
            iss_retido: document.getElementById('em-iss-retido')?.checked || false,
            reter_federais: document.getElementById('em-reter-federais')?.checked || false,
        });
        await loadSavedCustomersAndServices();
        const avisos = (created.avisos_fiscais || []).map(a => `• [${a.codigo}] ${a.mensagem}`).join('\n');
        await uiAlert({
            title: 'Serviço Recorrente Salvo',
            message: 'Serviço salvo com sucesso para emissões futuras!',
            infoBadge: avisos ? `Avisos de compatibilidade NBS:\n${avisos}` : '',
            variant: avisos ? 'warning' : 'success',
        });
    } catch (e) {
        await uiAlert({ title: 'Erro ao salvar serviço', message: e.message, variant: 'error' });
    }
}

export async function recalculateEmissionPreview() {
    const valor = parseFloat(document.getElementById('em-valor')?.value || '0');
    if (!valor || valor <= 0) return;

    const aliqIss = parseFloat(document.getElementById('em-aliq-iss')?.value || '2');
    const cClassTrib = document.getElementById('em-cclasstrib')?.value || '000001';
    const cIndOp = document.getElementById('em-cindop')?.value || '100301';
    const cTribNac = document.getElementById('em-ctribnac')?.value || '010101';
    const cNBS = (document.getElementById('em-cnbs-select')?.value || document.getElementById('em-cnbs')?.value || '115021000').replace(/\D/g, '');
    const issRetido = document.getElementById('em-iss-retido')?.checked || false;
    const reterFed = document.getElementById('em-reter-federais')?.checked || false;

    try {
        const [calc, valid] = await Promise.all([
            api('/tax/calculate', 'POST', {
                valor_servicos: valor,
                regime_prestador: 'normal',
                cClassTrib,
                cIndOp,
                cTribNac,
                cNBS,
                aliquota_iss: aliqIss,
                iss_retido: issRetido,
                reter_federais: reterFed,
            }),
            api('/tax/validate-ibscbs', 'POST', {
                cClassTrib,
                cIndOp,
                cTribNac,
                cNBS,
            }).catch(() => null),
        ]);

        const alertBox = document.getElementById('em-tax-compat-alert');
        if (alertBox && valid) {
            const errs = valid.erros || [];
            const avisos = valid.avisos || [];
            if (errs.length > 0) {
                alertBox.style.display = 'block';
                alertBox.style.background = 'var(--red-bg)';
                alertBox.style.borderColor = 'var(--red)';
                alertBox.style.color = 'var(--red)';
                alertBox.innerHTML = errs.map(e => `<strong>[${escapeHtml(e.codigo)}]</strong> ${escapeHtml(e.mensagem)}`).join('<br>');
            } else if (avisos.length > 0) {
                alertBox.style.display = 'block';
                alertBox.style.background = 'rgba(245, 158, 11, 0.12)';
                alertBox.style.borderColor = 'var(--amber)';
                alertBox.style.color = 'var(--amber)';
                alertBox.innerHTML = avisos.map(a => `<strong>[${escapeHtml(a.codigo)}]</strong> ${escapeHtml(a.mensagem)}`).join('<br>');
            } else {
                alertBox.style.display = 'none';
                alertBox.innerHTML = '';
            }
        }

        document.getElementById('prev-valor-bruto').innerText = fmtBRL(calc.valor_servicos);
        document.getElementById('prev-aliq-iss').innerText = calc.iss?.aliquota || aliqIss;
        document.getElementById('prev-valor-iss').innerText = fmtBRL(calc.iss?.valor || 0);
        document.getElementById('prev-ret-fed').innerText = fmtBRL(calc.retencoes_federais?.total_retencoes_federais || 0);
        document.getElementById('prev-vbc-ibscbs').innerText = fmtBRL(calc.reforma_tributaria?.vBC || 0);
        document.getElementById('prev-valor-ibs').innerText = fmtBRL(calc.reforma_tributaria?.valor_ibs || 0);
        document.getElementById('prev-valor-cbs').innerText = fmtBRL(calc.reforma_tributaria?.valor_cbs || 0);
        document.getElementById('prev-valor-liquido').innerText = fmtBRL(calc.valor_liquido || valor);
    } catch (e) {
        console.warn('Erro ao recalcular prévia tributária:', e);
    }
}

function buildEmissionRequestPayload(transmitir = true) {
    const clientId = state.getGlobalClientId();
    const nbsVal = (document.getElementById('em-cnbs-select')?.value || document.getElementById('em-cnbs')?.value || '115021000').replace(/\D/g, '');
    return {
        client_id: clientId ? parseInt(clientId, 10) : null,
        serie_dps: document.getElementById('em-serie')?.value || '900',
        transmitir,
        enviar_email: document.getElementById('em-enviar-email')?.checked || false,
        email_destinatario: document.getElementById('em-tomador-email')?.value || null,
        prestador: clientId ? {} : {
            cnpj: '12345678000113',
            codigo_municipio: '3201308',
            regime: 'normal',
        },
        tomador: {
            documento: (document.getElementById('em-tomador-doc')?.value || '').replace(/\D/g, '') || '12345678000195',
            razao_social: document.getElementById('em-tomador-nome')?.value || 'TOMADOR PADRAO LTDA',
            email: document.getElementById('em-tomador-email')?.value || undefined,
            endereco: {
                codigo_municipio: document.getElementById('em-tomador-ibge')?.value || '3201308',
                cep: (document.getElementById('em-tomador-cep')?.value || '').replace(/\D/g, '') || '29140000',
                logradouro: document.getElementById('em-tomador-logradouro')?.value || 'AV CENTRAL',
                numero: document.getElementById('em-tomador-numero')?.value || '100',
                bairro: document.getElementById('em-tomador-bairro')?.value || 'CENTRO',
                complemento: document.getElementById('em-tomador-complemento')?.value || undefined,
            },
        },
        servico: {
            codigo_municipio_prestacao: '3201308',
            cTribNac: document.getElementById('em-ctribnac')?.value || '010101',
            cNBS: nbsVal,
            cClassTrib: document.getElementById('em-cclasstrib')?.value || '000001',
            indop: document.getElementById('em-cindop')?.value || '100301',
            descricao: document.getElementById('em-descricao')?.value || 'Servicos prestados',
            valor: parseFloat(document.getElementById('em-valor')?.value || '1500'),
            aliquota_iss: parseFloat(document.getElementById('em-aliq-iss')?.value || '2'),
            iss_retido: document.getElementById('em-iss-retido')?.checked || false,
            reter_federais: document.getElementById('em-reter-federais')?.checked || false,
        },
    };
}

export async function previewDpsXmlModal() {
    try {
        const payload = buildEmissionRequestPayload(false);
        const res = await api('/adn/dps/preview', 'POST', payload);
        const box = document.getElementById('em-xml-preview-box');
        const badge = document.getElementById('em-xsd-badge');
        if (badge) {
            const ok = res.validacao_xsd?.valido;
            badge.innerText = ok ? 'XSD v1.01 VÁLIDO ✓' : 'ERRO XSD';
            badge.style.color = ok ? 'var(--green)' : 'var(--red)';
        }
        if (box) {
            box.style.display = 'block';
            box.textContent = res.xml_dps || '';
        }
    } catch (e) {
        await uiAlert({ title: 'Erro ao gerar preview do XML DPS', message: e.message, variant: 'error' });
    }
}

export async function submitEmitirDps() {
    const clientId = state.getGlobalClientId();
    if (!clientId) {
        await uiAlert({ title: 'Empresa não selecionada', message: 'Selecione a empresa Prestadora no seletor do topo da página antes de emitir.', variant: 'warning' });
        return;
    }
    const transmitir = document.getElementById('em-transmitir')?.checked ?? true;
    try {
        showTaskToast('Emitindo NFS-e', 'Assinando DPS v1.01, validando XSD e transmitindo ao ADN...', { autoProgress: true });
        const payload = buildEmissionRequestPayload(transmitir);
        const res = await api('/adn/dps/emitir', 'POST', payload);
        completeTaskToast('DPS Processada', 'Emissão processada com sucesso!', 4500);
        await loadFilaContingencia();
        if (res.status_nota === 'gerada') {
            await uiAlert({
                title: 'NFS-e Autorizada!',
                message: 'Nota Fiscal de Serviço eletrônica autorizada com sucesso no ADN.',
                infoBadge: `Chave: ${res.chave_acesso}`,
                infoMono: true,
                variant: 'success',
            });
        } else if (res.status_nota === 'fila_contingencia') {
            await uiAlert({
                title: 'Salva na Fila de Contingência',
                message: 'Nota validada e salva na Fila de Contingência para envio posterior.',
                infoBadge: `ID DPS: ${res.id_dps}`,
                infoMono: true,
                variant: 'warning',
            });
        } else {
            await uiAlert({
                title: 'DPS Validada Offline',
                message: 'DPS gerada e validada contra o XSD v1.01 com sucesso.',
                infoBadge: `ID DPS: ${res.id_dps}`,
                infoMono: true,
                variant: 'success',
            });
        }
    } catch (e) {
        failTaskToast('Erro na Emissão', e.message);
        await uiAlert({ title: 'Erro na emissão da DPS', message: e.message, variant: 'error' });
    }
}

export async function loadFilaContingencia() {
    const clientId = state.getGlobalClientId();
    const qs = clientId ? `?client_id=${clientId}` : '';
    try {
        const items = await api(`/adn/fila${qs}`);
        const badge = document.getElementById('fila-badge');
        if (badge) badge.innerText = String(items.length);

        const tbody = document.getElementById('fila-table-body');
        if (!tbody) return;

        if (items.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--text3); padding:24px;">Nenhuma nota pendente na fila de contingência.</td></tr>`;
            return;
        }

        tbody.innerHTML = items.map(i => `
            <tr>
              <td style="font-family:var(--mono); font-size:12px;">#${i.numero} (${i.id_dps || i.chave})</td>
              <td>${i.tomador_nome || i.tomador_documento || '-'}</td>
              <td style="font-weight:600;">${fmtBRL(i.valor)}</td>
              <td><span class="status-badge status-${i.status}">${i.status}</span></td>
              <td style="font-size:11.5px; color:var(--text3);">${i.tentativas_envio || 0} tent. — ${i.ultimo_erro_envio || 'Pronta para envio'}</td>
              <td>
                <div class="table-actions-inline">
                  <button class="btn btn-primary btn-sm" onclick="App.reenviarFilaContingencia([${i.id}])" style="font-size:11px; padding:6px 12px;">Transmitir Agora</button>
                  <button class="btn btn-secondary btn-sm btn-action-danger" onclick="App.cancelarItemFila(${i.id})" style="font-size:11px; padding:6px 10px;" title="Cancelar e remover da fila">Cancelar</button>
                </div>
              </td>
            </tr>
        `).join('');
    } catch (e) {
        console.warn('Erro ao carregar fila de contingência:', e);
    }
}

export async function reenviarFilaContingencia(invoiceIds = null) {
    const clientId = state.getGlobalClientId();
    try {
        showTaskToast('Reenviando Fila', 'Transmitindo DPS pendentes ao ADN Nacional...', { autoProgress: true });
        const res = await api('/adn/fila/reenviar', 'POST', {
            client_id: clientId ? parseInt(clientId, 10) : null,
            invoice_ids: invoiceIds,
        });
        completeTaskToast('Fila Reenviada', `${res.autorizadas} autorizada(s), ${res.falhas} pendente(s).`, 4500);
        await loadFilaContingencia();
    } catch (e) {
        failTaskToast('Erro ao Reenviar Fila', e.message);
        await uiAlert({ title: 'Erro ao reenviar fila', message: e.message, variant: 'error' });
    }
}

export async function cancelarItemFila(invoiceId) {
    const confirmed = await uiConfirm({
        title: 'Cancelar Item da Fila',
        message: 'Cancelar esta DPS pendente e removê-la da fila de contingência?',
        confirmText: 'Sim, Cancelar DPS',
        variant: 'danger',
        icon: 'trash',
    });
    if (!confirmed) return;
    try {
        await api(`/adn/fila/${invoiceId}`, 'DELETE');
        await loadFilaContingencia();
        await loadBatchImports();
        completeTaskToast('Item Removido', 'DPS pendente cancelada da fila.', 3000);
    } catch (e) {
        await uiAlert({ title: 'Erro ao cancelar item da fila', message: e.message, variant: 'error' });
    }
}

export function renderSavedRegistriesTables() {
    const custMaster = document.getElementById('cust-check-all');
    if (custMaster) custMaster.checked = false;
    const custTbody = document.getElementById('saved-customers-tbody');
    if (custTbody) {
        custTbody.innerHTML = savedCustomers.length === 0
            ? `<tr><td colspan="5" style="text-align:center; color:var(--text3); padding:16px;">Nenhum tomador cadastrado.</td></tr>`
            : savedCustomers.map(c => `
                <tr>
                  <td><input type="checkbox" class="saved-cust-check" value="${c.id}" onchange="App.updateSavedSelectionCounts()"></td>
                  <td style="font-family:var(--mono); font-size:12px;">${c.documento}</td>
                  <td style="font-weight:500;">${c.razao_social || '-'}</td>
                  <td>${c.codigo_municipio || '-'}</td>
                  <td>
                    <button type="button" class="btn btn-secondary btn-sm btn-action-danger" onclick="App.deleteSavedCustomer(${c.id})" title="Excluir tomador">Excluir</button>
                  </td>
                </tr>
            `).join('');
    }

    const srvMaster = document.getElementById('srv-check-all');
    if (srvMaster) srvMaster.checked = false;
    const srvTbody = document.getElementById('saved-services-tbody');
    if (srvTbody) {
        srvTbody.innerHTML = savedServices.length === 0
            ? `<tr><td colspan="5" style="text-align:center; color:var(--text3); padding:16px;">Nenhum serviço recorrente cadastrado.</td></tr>`
            : savedServices.map(s => `
                <tr>
                  <td><input type="checkbox" class="saved-srv-check" value="${s.id}" onchange="App.updateSavedSelectionCounts()"></td>
                  <td style="font-weight:500;">${s.titulo || s.descricao || '-'}</td>
                  <td style="font-family:var(--mono); font-size:12px;">${s.c_trib_nac} / ${s.c_class_trib}</td>
                  <td style="font-weight:600;">${fmtBRL(s.valor_unitario)}</td>
                  <td>
                    <button type="button" class="btn btn-secondary btn-sm btn-action-danger" onclick="App.deleteSavedService(${s.id})" title="Excluir serviço">Excluir</button>
                  </td>
                </tr>
            `).join('');
    }
    updateSavedSelectionCounts();
}

export function updateSavedSelectionCounts() {
    const custCount = document.getElementById('cust-selected-count');
    if (custCount) {
        custCount.textContent = `${document.querySelectorAll('.saved-cust-check:checked').length} selecionado(s)`;
    }
    const srvCount = document.getElementById('srv-selected-count');
    if (srvCount) {
        srvCount.textContent = `${document.querySelectorAll('.saved-srv-check:checked').length} selecionado(s)`;
    }
}

export function toggleAllSavedCustomers(master) {
    const checked = Boolean(master?.checked);
    document.querySelectorAll('.saved-cust-check').forEach(cb => { cb.checked = checked; });
    updateSavedSelectionCounts();
}

export function toggleAllSavedServices(master) {
    const checked = Boolean(master?.checked);
    document.querySelectorAll('.saved-srv-check').forEach(cb => { cb.checked = checked; });
    updateSavedSelectionCounts();
}

export async function deleteSavedCustomer(id) {
    const confirmed = await uiConfirm({
        title: 'Remover Tomador',
        message: 'Remover este tomador recorrente do cadastro?',
        confirmText: 'Remover',
        variant: 'danger',
        icon: 'trash',
    });
    if (!confirmed) return;
    await api(`/customers/${id}`, 'DELETE');
    await loadSavedCustomersAndServices();
}

export async function deleteSelectedSavedCustomers() {
    const ids = Array.from(document.querySelectorAll('.saved-cust-check:checked')).map(cb => parseInt(cb.value, 10));
    if (ids.length === 0) {
        await uiAlert({ title: 'Nenhum tomador selecionado', message: 'Selecione pelo menos um tomador para excluir.', variant: 'warning' });
        return;
    }
    const confirmed = await uiConfirm({
        title: 'Excluir Tomadores Selecionados',
        message: `Excluir os ${ids.length} tomador(es) selecionado(s)?`,
        confirmText: `Excluir ${ids.length}`,
        variant: 'danger',
        icon: 'trash',
    });
    if (!confirmed) return;
    await api('/customers/delete-batch', 'POST', { ids, delete_all: false });
    await loadSavedCustomersAndServices();
}

export async function deleteAllSavedCustomers() {
    if (savedCustomers.length === 0) {
        await uiAlert({ title: 'Lista vazia', message: 'Não há tomadores cadastrados para excluir.', variant: 'info' });
        return;
    }
    const confirmed = await uiConfirm({
        title: 'Excluir Todos os Tomadores',
        message: `Excluir TODOS os ${savedCustomers.length} tomador(es) listados?`,
        confirmText: 'Excluir Todos',
        variant: 'danger',
        icon: 'trash',
    });
    if (!confirmed) return;
    const clientId = state.getGlobalClientId();
    await api('/customers/delete-batch', 'POST', {
        client_id: clientId ? parseInt(clientId, 10) : null,
        delete_all: true,
    });
    await loadSavedCustomersAndServices();
}

export async function deleteSavedService(id) {
    const confirmed = await uiConfirm({
        title: 'Remover Serviço',
        message: 'Remover este serviço recorrente do cadastro?',
        confirmText: 'Remover',
        variant: 'danger',
        icon: 'trash',
    });
    if (!confirmed) return;
    await api(`/service-items/${id}`, 'DELETE');
    await loadSavedCustomersAndServices();
}

export async function deleteSelectedSavedServices() {
    const ids = Array.from(document.querySelectorAll('.saved-srv-check:checked')).map(cb => parseInt(cb.value, 10));
    if (ids.length === 0) {
        await uiAlert({ title: 'Nenhum serviço selecionado', message: 'Selecione pelo menos um serviço para excluir.', variant: 'warning' });
        return;
    }
    const confirmed = await uiConfirm({
        title: 'Excluir Serviços Selecionados',
        message: `Excluir os ${ids.length} serviço(s) selecionado(s)?`,
        confirmText: `Excluir ${ids.length}`,
        variant: 'danger',
        icon: 'trash',
    });
    if (!confirmed) return;
    await api('/service-items/delete-batch', 'POST', { ids, delete_all: false });
    await loadSavedCustomersAndServices();
}

export async function deleteAllSavedServices() {
    if (savedServices.length === 0) {
        await uiAlert({ title: 'Lista vazia', message: 'Não há serviços cadastrados para excluir.', variant: 'info' });
        return;
    }
    const confirmed = await uiConfirm({
        title: 'Excluir Todos os Serviços',
        message: `Excluir TODOS os ${savedServices.length} serviço(s) listado(s)?`,
        confirmText: 'Excluir Todos',
        variant: 'danger',
        icon: 'trash',
    });
    if (!confirmed) return;
    const clientId = state.getGlobalClientId();
    await api('/service-items/delete-batch', 'POST', {
        client_id: clientId ? parseInt(clientId, 10) : null,
        delete_all: true,
    });
    await loadSavedCustomersAndServices();
}

export function renderLoteTab() {
    const srvSel = document.getElementById('lote-service-select');
    if (srvSel) {
        const prev = srvSel.value;
        let html = `<option value="">-- Selecione um Serviço Cadastrado --</option>`;
        if (savedServices.length > 0) {
            html += savedServices.map(s => {
                const tit = s.titulo || s.descricao || 'Serviço Recorrente';
                const val = s.valor_unitario > 0 ? ` (${fmtBRL(s.valor_unitario)})` : '';
                return `<option value="${s.id}">${tit}${val}</option>`;
            }).join('');
        }
        srvSel.innerHTML = html;
        if (prev && savedServices.some(s => String(s.id) === String(prev))) {
            srvSel.value = prev;
        }
    }

    const compInput = document.getElementById('lote-competencia');
    if (compInput && !compInput.value) {
        compInput.value = new Date().toISOString().slice(0, 10);
    }

    const tbody = document.getElementById('lote-customers-tbody');
    if (!tbody) return;
    if (savedCustomers.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:var(--text3); padding:16px;">Nenhum tomador cadastrado. Importe uma planilha na aba Cadastros Recorrentes.</td></tr>`;
        return;
    }

    tbody.innerHTML = savedCustomers.map(c => `
        <tr>
          <td><input type="checkbox" class="lote-customer-check" value="${c.id}"></td>
          <td style="font-family:var(--mono); font-size:12px;">${c.documento || '-'}</td>
          <td style="font-weight:500;">${c.razao_social || '-'}</td>
          <td>${c.email || '-'}</td>
          <td>
            <input type="number" step="0.01" min="0" class="form-input lote-valor-custom" data-customer-id="${c.id}" placeholder="Padrão do serviço" style="max-width:160px; padding:6px 10px;">
          </td>
        </tr>
    `).join('');
}

export function toggleAllLoteCustomers(masterCheckbox) {
    const checked = Boolean(masterCheckbox?.checked);
    document.querySelectorAll('.lote-customer-check').forEach(cb => {
        cb.checked = checked;
    });
}

export async function submitEmitirLote() {
    const clientId = state.getGlobalClientId();
    if (!clientId) {
        await uiAlert({ title: 'Empresa não selecionada', message: 'Selecione a empresa Prestadora no seletor do topo da página antes de emitir em lote.', variant: 'warning' });
        return;
    }
    const serviceIdRaw = document.getElementById('lote-service-select')?.value;
    if (!serviceIdRaw) {
        await uiAlert({ title: 'Serviço não selecionado', message: 'Selecione um Serviço Recorrente padrão para o lote.', variant: 'warning' });
        return;
    }
    const selectedChecks = Array.from(document.querySelectorAll('.lote-customer-check:checked'));
    if (selectedChecks.length === 0) {
        await uiAlert({ title: 'Tomadores não selecionados', message: 'Selecione pelo menos um tomador na lista para emitir em lote.', variant: 'warning' });
        return;
    }

    const serviceId = parseInt(serviceIdRaw, 10);
    const dataCompetencia = document.getElementById('lote-competencia')?.value || null;
    const valorOverrideRaw = document.getElementById('lote-valor-override')?.value;
    const transmitir = document.getElementById('lote-transmitir')?.checked ?? true;
    const enviarEmail = document.getElementById('lote-enviar-email')?.checked ?? false;

    const itens = selectedChecks.map(cb => {
        const customerId = parseInt(cb.value, 10);
        const customInput = document.querySelector(`.lote-valor-custom[data-customer-id="${customerId}"]`);
        const rawValor = customInput?.value || valorOverrideRaw;
        const item = {
            customer_id: customerId,
            service_item_id: serviceId,
        };
        if (rawValor && parseFloat(rawValor) > 0) {
            item.servico = { valor: parseFloat(rawValor) };
        }
        return item;
    });

    try {
        showTaskToast('Emissão em Lote', `Processando ${itens.length} DPS no padrão ADN v1.01...`, { autoProgress: true });
        const res = await api('/adn/dps/emitir-lote', 'POST', {
            client_id: parseInt(clientId, 10),
            transmitir,
            enviar_email: enviarEmail,
            data_competencia: dataCompetencia,
            itens,
        });
        completeTaskToast('Emissão em Lote Concluída', `Autorizadas: ${res.autorizadas} | Contingência: ${res.fila_contingencia} | Erros: ${res.erros}`, 5000);
        await loadFilaContingencia();

        const resultBox = document.getElementById('lote-result-box');
        if (resultBox) {
            const rowsHtml = (res.resultados || []).map(r => `
                <div style="display:flex; justify-content:space-between; gap:12px; padding:4px 0; border-bottom:1px solid var(--border);">
                  <span>#${r.indice} (${r.tomador_documento || `Tomador ${r.customer_id || '-'}`})</span>
                  <span style="font-family:var(--mono); font-size:11.5px;">${r.status_nota} ${r.chave_acesso || r.id_dps || r.erro || ''}</span>
                </div>
            `).join('');
            resultBox.style.display = 'block';
            resultBox.innerHTML = `
                <div style="font-weight:700; margin-bottom:8px;">
                  Lote finalizado — Total: ${res.total} | Autorizadas: ${res.autorizadas} | Fila Contingência: ${res.fila_contingencia} | Offline: ${res.geradas_offline} | Erros: ${res.erros}
                </div>
                ${rowsHtml}
            `;
        }
    } catch (e) {
        failTaskToast('Erro na Emissão em Lote', e.message);
        await uiAlert({ title: 'Erro ao processar emissão em lote', message: e.message, variant: 'error' });
    }
}

export async function downloadImportTemplate(kind, fmt = 'xlsx') {
    const endpoint = kind === 'customers'
        ? `/api/customers/import/template?format=${encodeURIComponent(fmt)}`
        : `/api/service-items/import/template?format=${encodeURIComponent(fmt)}`;
    const headers = {};
    const token = localStorage.getItem('nfse_token');
    if (token) headers['Authorization'] = `Bearer ${token}`;

    try {
        const res = await fetch(endpoint, { headers });
        if (!res.ok) {
            throw new Error(await res.text());
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `modelo_${kind === 'customers' ? 'tomadores' : 'servicos'}.${fmt}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    } catch (e) {
        await uiAlert({ title: 'Erro ao baixar modelo', message: e.message, variant: 'error' });
    }
}

export async function handleImportSpreadsheet(kind, inputEl) {
    const file = inputEl?.files?.[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);
    formData.append('atualizar_existentes', 'true');
    const clientId = state.getGlobalClientId();
    if (clientId) {
        formData.append('client_id', String(clientId));
    }

    const endpoint = kind === 'customers' ? '/customers/import' : '/service-items/import';
    const label = kind === 'customers' ? 'Tomadores' : 'Serviços';

    try {
        showTaskToast(`Importando ${label}`, `Processando arquivo ${file.name}...`, { autoProgress: true });
        const res = await api(endpoint, 'POST', formData);
        completeTaskToast(`Importação de ${label} Concluída`, `Criados: ${res.criados} | Atualizados: ${res.atualizados}`, 4500);
        await loadSavedCustomersAndServices();
        const errs = (res.erros || []).slice(0, 5).join('\n');
        await uiAlert({
            title: `Importação de ${label} Concluída`,
            message: `Linhas lidas: ${res.total_lidas}\nCriados: ${res.criados}\nAtualizados: ${res.atualizados}\nIgnorados: ${res.ignorados}`,
            infoBadge: errs ? `Avisos:\n${errs}` : '',
            variant: errs ? 'warning' : 'success',
        });
    } catch (e) {
        failTaskToast(`Erro ao Importar ${label}`, e.message);
        await uiAlert({ title: `Erro ao importar planilha de ${label}`, message: e.message, variant: 'error' });
    } finally {
        if (inputEl) inputEl.value = '';
    }
}
