import { api, getApiBaseUrl } from '../core/api.js';
import { showTaskToast, setTaskProgress, completeTaskToast, failTaskToast, uiAlert } from '../core/ui.js';
import { state } from '../core/state.js';
import { loadUsers } from './users.js';

let updatePollTimer = null;

function setDisplay(id, value) {
    const el = document.getElementById(id);
    if (el) el.style.display = value;
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.innerText = value;
}

function setProgress(percent) {
    const bar = document.getElementById('update-progress-bar');
    if (bar) bar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
}

function resetUpdateUi() {
    setDisplay('update-progress-area', 'none');
    setDisplay('btn-download-update', 'none');
    setDisplay('btn-apply-update', 'none');
    setDisplay('btn-check-update', 'block');
    setText('update-progress-text', 'Aguardando ação...');
    setProgress(0);
    state.updateReady = false;
}

function showDownloadActions() {
    setDisplay('btn-check-update', 'none');
    setDisplay('btn-download-update', 'block');
    setDisplay('btn-apply-update', 'none');
    setDisplay('update-progress-area', 'block');
}

function showApplyAction() {
    setDisplay('btn-check-update', 'none');
    setDisplay('btn-download-update', 'none');
    setDisplay('btn-apply-update', 'block');
    setDisplay('update-progress-area', 'block');
}

function stopUpdatePoll() {
    if (updatePollTimer) {
        clearInterval(updatePollTimer);
        updatePollTimer = null;
    }
}

async function pollUpdateTask() {
    if (!state.updateTask) return;

    try {
        const res = await api(`/tasks/${state.updateTask}`);
        const pct = res.progress || 0;
        setProgress(pct);
        setText('update-progress-text', res.message || 'Processando atualização...');
        setTaskProgress(pct, res.message || 'Processando atualização...', 'Baixando Atualização');

        if (res.status === 'completed' && res.restart_required) {
            stopUpdatePoll();
            state.updateReady = true;
            setProgress(100);
            setText('update-progress-text', 'Atualização baixada e pronta para aplicação segura.');
            completeTaskToast('Atualização Pronta', 'Download concluído! Clique em "Reiniciar e aplicar".', 5000);
            showApplyAction();
            setDisplay('btn-apply-update', 'block');
        } else if (res.status === 'failed') {
            state.updateTask = null;
            stopUpdatePoll();
            setProgress(0);
            setText('update-progress-text', `Falha na atualização: ${res.message || 'erro desconhecido'}`);
            failTaskToast('Falha na Atualização', res.message || 'Erro desconhecido', 6000);
            resetUpdateUi();
            setDisplay('update-status-box', 'flex');
            setText('update-status-text', `Falha na atualização: ${res.message || 'erro desconhecido'}`);
        }
    } catch (e) {
        console.warn('pollUpdateTask erro:', e);
    }
}

function startUpdatePoll() {
    stopUpdatePoll();
    updatePollTimer = setInterval(pollUpdateTask, 1000);
}

export async function sendSupportMessage() {
    const email = document.getElementById('sup-email').value;
    const whatsapp = document.getElementById('sup-whatsapp').value;
    const message = document.getElementById('sup-msg').value;
    
    if (!email || !message) {
        await uiAlert({ title: 'Campos obrigatórios', message: 'Por favor, preencha pelo menos seu e-mail e a mensagem.', variant: 'warning' });
        return;
    }
    
    const btn = document.getElementById('btn-send-sup');
    const originalText = btn.innerText;
    
    try {
        btn.disabled = true;
        btn.innerText = 'Enviando...';
        showTaskToast('Enviando Mensagem', 'Encaminhando mensagem ao suporte...', { autoProgress: true });
        
        await api('/support/message', 'POST', { email, whatsapp, message });
        
        completeTaskToast('Mensagem Enviada', 'Sua mensagem foi enviada! Obrigado pelo feedback.', 4500);
        
        // Clear fields
        document.getElementById('sup-email').value = '';
        document.getElementById('sup-whatsapp').value = '';
        document.getElementById('sup-msg').value = '';
        
    } catch (e) {
        failTaskToast('Falha ao Enviar', e.message);
        await uiAlert({ title: 'Erro ao enviar mensagem', message: e.message, variant: 'error' });
    } finally {
        btn.disabled = false;
        btn.innerText = originalText;
    }
}

export async function checkUpdates() {
    const btn = document.getElementById('btn-check-update');
    const statusBox = document.getElementById('update-status-box');
    const statusText = document.getElementById('update-status-text');
    const changelogPreview = document.getElementById('update-changelog-preview');
    const installedVersion = document.getElementById('installed-version-tag');
    
    try {
        btn.disabled = true;
        btn.innerText = 'Verificando...';
        if (statusText) statusText.innerText = 'Consultando a última versão publicada no GitHub...';
        resetUpdateUi();
        
        const res = await api('/system/check-update');
        state.updateInfo = res;

        if (installedVersion && res.current_version) {
            installedVersion.innerText = res.current_version;
        }
        
        if (res.update_available) {
            if (changelogPreview) {
                changelogPreview.innerText = res.changelog || 'Sem notas de versão disponíveis.';
            }
            showDownloadActions();
            if (statusText) {
                statusText.innerText = `Nova versão disponível: ${res.latest_version}. Clique em “Baixar atualização” para baixar e extrair com segurança.`;
            }
            setText('update-progress-text', 'Clique em “Baixar atualização” para baixar e extrair com segurança.');
        } else {
            if (statusBox) statusBox.style.display = 'flex';
            if (statusText) {
                const extra = res.latest_version ? ` Última release encontrada: ${res.latest_version}.` : '';
                statusText.innerText = `${res.msg || 'Sua versão já é a mais recente.'}${extra}`;
            }
            if (changelogPreview) {
                changelogPreview.innerText = res.changelog || 'Nenhum changelog disponível para esta versão.';
            }
            resetUpdateUi();
        }
    } catch (e) {
        if (statusText) {
            statusText.innerText = 'Não foi possível consultar o GitHub agora. Tente novamente em instantes.';
        } else {
            await uiAlert({ title: 'Erro ao verificar atualizações', message: e.message, variant: 'error' });
        }
    } finally {
        btn.disabled = false;
        btn.innerText = 'Verificar nova versão';
    }
}

export async function startUpdateDownload() {
    const btn = document.getElementById('btn-download-update');
    const statusText = document.getElementById('update-status-text');

    try {
        if (btn) {
            btn.disabled = true;
            btn.innerText = 'Baixando...';
        }

        if (!state.updateInfo?.latest_version) {
            await checkUpdates();
        }

        const res = await api('/system/update/download', 'POST', {
            version: state.updateInfo?.latest_version || null
        });

        state.updateTask = res.task_id;
        state.updateReady = false;
        setDisplay('update-progress-area', 'block');
        setProgress(2);
        setText('update-progress-text', 'Iniciando download seguro da release...');
        if (statusText) {
            statusText.innerText = 'Baixando atualização em segundo plano...';
        }
        startUpdatePoll();
        showTaskToast('Atualização Iniciada', 'O download da nova versão começou em segundo plano.', { progress: 5, autoProgress: false });
    } catch (e) {
        await uiAlert({ title: 'Erro ao iniciar download', message: e.message, variant: 'error' });
        setDisplay('update-status-box', 'flex');
        if (btn) {
            btn.disabled = false;
            btn.innerText = 'Baixar atualização';
        }
    }
}

export async function applyDownloadedUpdate() {
    const btn = document.getElementById('btn-apply-update');
    try {
        if (!state.updateTask || !state.updateReady) {
            await uiAlert({ title: 'Nenhuma atualização pronta', message: 'Nenhuma atualização preparada para aplicar.', variant: 'warning' });
            return;
        }

        if (btn) {
            btn.disabled = true;
            btn.innerText = 'Aplicando...';
        }

        setText('update-progress-text', 'Aplicando arquivos da atualização...');
        setProgress(100);

        await api('/system/update/apply', 'POST', { task_id: state.updateTask });
        setText('update-status-text', 'Atualização aplicada. O sistema será reiniciado automaticamente.');
        completeTaskToast('Atualização Aplicada', 'O sistema está reiniciando...', 4000);
        state.updateReady = false;

        // Após o backend reiniciar, o frontend pode recarregar se ainda estiver ativo.
        setTimeout(() => {
            try {
                window.location.reload();
            } catch (_) {
                // ignore
            }
        }, 2500);
    } catch (e) {
        await uiAlert({ title: 'Falha ao aplicar atualização', message: e.message, variant: 'error' });
        setText('update-progress-text', 'Falha ao aplicar a atualização. Nenhum arquivo foi substituído.');
        if (btn) {
            btn.disabled = false;
            btn.innerText = 'Reiniciar e aplicar';
        }
    }
}

function formatDbLabel(dialect) {
    const norm = String(dialect || '').toLowerCase();
    if (norm.includes('postgres')) return 'PostgreSQL (Multiusuário)';
    if (norm.includes('sqlite')) return 'SQLite (Local / WAL)';
    return dialect ? String(dialect) : '-';
}

function formatModeLabel(mode) {
    const norm = String(mode || '').toLowerCase();
    if (norm === 'server' || norm === 'central' || norm === 'multiuser') return 'Servidor Central';
    if (norm === 'desktop' || norm === 'local' || norm === 'standalone') return 'Estação Local';
    return mode ? String(mode) : '-';
}

function formatWorkerLabel(env) {
    const mode = String(env?.scheduler_mode || env?.worker_status || '').toLowerCase();
    if (mode === 'disabled' || env?.scheduler_active === false) return 'Desabilitado (Worker externo)';
    if (env?.scheduler_is_leader === true || mode === 'leader') return 'Ativo (Líder)';
    if (env?.scheduler_is_leader === false && mode === 'auto') return 'Em espera (Standby)';
    if (mode === 'auto' || env?.scheduler_active === true) return 'Ativo (Auto)';
    return env?.scheduler_mode || 'Ativo';
}

export async function loadSystemEnvironment() {
    const originEl = document.getElementById('env-api-origin');
    const customBase = getApiBaseUrl();
    if (originEl) {
        originEl.innerText = customBase || window.location.origin;
    }

    const dbEl = document.getElementById('env-db-type');
    if (!dbEl) return;

    try {
        const env = await api('/system/environment');
        const dialect = env?.db_dialect || env?.database_dialect || env?.database?.dialect || env?.db_type || '';
        const opMode = env?.deployment_mode || env?.operation_mode || env?.mode || (env?.multiuser_ready ? 'server' : 'local');
        const certsDir = env?.certs_dir || env?.directories?.certs_dir || env?.directories?.certs || '-';
        const downloadsDir = env?.downloads_dir || env?.directories?.downloads_dir || env?.directories?.downloads || '-';
        const multiuserReady = Boolean(env?.multiuser_ready ?? String(dialect).toLowerCase().includes('postgres'));

        setText('env-db-type', formatDbLabel(dialect));
        setText('env-op-mode', formatModeLabel(opMode));
        setText('env-worker-status', formatWorkerLabel(env));
        setText('env-certs-dir', certsDir);
        setText('env-downloads-dir', downloadsDir);

        const banner = document.getElementById('env-wts-banner');
        const guidance = document.getElementById('env-wts-guidance');
        if (banner && guidance) {
            banner.classList.remove('is-ready', 'is-warn');
            if (multiuserReady) {
                banner.classList.add('is-ready');
                guidance.innerText = 'Ambiente configurado para operação multiusuário simultânea (PostgreSQL + storage compartilhado). Sessões WTS e estações Desktop podem apontar para este servidor sem conflito de porta ou banco.';
            } else {
                banner.classList.add('is-warn');
                guidance.innerText = 'Executando com banco local (SQLite). Para múltiplos colaboradores simultâneos em rede ou Windows Server (WTS), utilize PostgreSQL em um servidor central e configure a URL no botão "Configurar Servidor".';
            }
        }
    } catch (e) {
        setText('env-db-type', 'Indisponível');
        setText('env-op-mode', '-');
        setText('env-worker-status', '-');
        const guidance = document.getElementById('env-wts-guidance');
        if (guidance) {
            guidance.innerText = 'Não foi possível consultar /api/system/environment neste servidor.';
        }
    }
}

export async function initAbout() {
    // Try to fetch installed version without triggering a GitHub check
    try {
        const res = await api('/system/version');
        if (res && res.current_version) {
            const installedVersion = document.getElementById('installed-version-tag');
            if (installedVersion) installedVersion.innerText = res.current_version;

            const changelogPreview = document.getElementById('update-changelog-preview');
            if (changelogPreview && res.changelog) {
                changelogPreview.innerText = res.changelog;
            }

            // update any badge that shows version (either explicit text or data-version attribute)
            // 1) elements explicitly marked with data-version
            const dataBadges = document.querySelectorAll('[data-version]');
            dataBadges.forEach(b => { b.innerText = 'v' + res.current_version; });

            // 2) fallback: any badge whose content looks like a semver string
            const badges = document.querySelectorAll('.badge');
            badges.forEach(b => {
                if (/^v?\d+\.\d+\.\d+$/.test(b.innerText.trim())) {
                    b.innerText = 'v' + res.current_version;
                }
            });
        }
    } catch (e) {
        // silently ignore
        console.warn('Could not fetch system version on init:', e);
    }

    if (document.getElementById('about-env-card')) {
        await loadSystemEnvironment();
    }

    if (document.getElementById('about-catalogs-card')) {
        await loadCatalogsStatus(false);
    }

    const adminSection = document.getElementById('admin-users-section');
    const syncCatalogBtn = document.getElementById('btn-sync-catalogs');
    let role = null;
    try {
        const raw = localStorage.getItem('nfse_user');
        role = raw ? JSON.parse(raw)?.role : null;
    } catch (_) {}

    if (syncCatalogBtn) {
        syncCatalogBtn.style.display = role === 'admin' ? 'inline-flex' : 'none';
    }

    if (adminSection) {
        if (role === 'admin') {
            adminSection.style.display = 'block';
            await loadUsers();
        } else {
            adminSection.style.display = 'none';
        }
    }
}

function renderCatalogsStatus(status) {
    const versaoDb = status?.versao_db ? `${status.versao_db}${status.data_versao_db ? ` (${status.data_versao_db})` : ''}` : '-';
    const totais = status?.totais || {};
    const totaisLabel = `${totais.nbs ?? 0} NBS · ${totais.cclasstrib ?? 0} cClass · ${totais.indop ?? 0} cIndOp`;
    const updatedAt = status?.atualizado_em ? String(status.atualizado_em).slice(0, 10) : 'Embutido';
    const modeLabel = status?.usando_override_externo ? 'Cache Compartilhado (Override)' : 'Embutido (pynfse)';
    const anexosLabel = [status?.anexo_vii_versao, status?.anexo_viii_versao].filter(Boolean).join(' | ') || '-';

    setText('cat-versao-db', versaoDb);
    setText('cat-totais', totaisLabel);
    setText('cat-updated-at', updatedAt);
    setText('cat-source-mode', modeLabel);
    setText('cat-dir-path', status?.catalogs_dir_configurado || status?.catalogs_dir || '-');
    setText('cat-anexos-ver', anexosLabel);

    const banner = document.getElementById('cat-sync-banner');
    const guidance = document.getElementById('cat-sync-guidance');
    if (banner && guidance) {
        banner.classList.remove('is-ready', 'is-warn');
        const rem = status?.remoto;
        if (rem?.erro) {
            banner.classList.add('is-warn');
            guidance.innerText = `Base local ativa (${versaoDb}). Não foi possível consultar as fontes oficiais agora: ${rem.erro}`;
        } else if (rem?.atualizacao_disponivel ?? rem?.precisa_atualizar) {
            banner.classList.add('is-warn');
            const novas = rem?.versao_remota || rem?.alteracoes?.join(', ') || rem?.remoto?.versao_db || 'nova versão disponível';
            guidance.innerText = `Atualização oficial disponível (${novas}). Administradores podem clicar em "Sincronizar Oficiais" para atualizar sem reinstalar o app.`;
        } else if (rem) {
            banner.classList.add('is-ready');
            guidance.innerText = `Catálogos oficiais sincronizados com a Receita Federal (${rem.versao_remota || versaoDb}) e Portal Nacional NFS-e.`;
        } else {
            banner.classList.add('is-ready');
            guidance.innerText = `Catálogos carregados (${versaoDb}). Clique em "Verificar Tabelas" para checar novidades na Receita Federal e gov.br/nfse.`;
        }
    }
}

export async function loadCatalogsStatus(checkRemote = false) {
    const card = document.getElementById('about-catalogs-card');
    if (!card) return;
    const btnCheck = document.getElementById('btn-check-catalogs');
    const originalCheckHtml = btnCheck ? btnCheck.innerHTML : '';
    if (btnCheck && checkRemote) {
        btnCheck.disabled = true;
        btnCheck.innerText = 'Verificando...';
    }
    try {
        const qs = checkRemote ? '?check_remote=true' : '';
        const res = await api(`/catalogs/status${qs}`);
        renderCatalogsStatus(res);
        if (checkRemote && res?.remoto) {
            const hasNew = Boolean(res.remoto.atualizacao_disponivel ?? res.remoto.precisa_atualizar);
            if (res.remoto.erro) {
                failTaskToast('Verificação de Catálogos', res.remoto.erro, 4500);
            } else if (hasNew) {
                completeTaskToast('Nova Versão Oficial', `Disponível na RFB: ${res.remoto.versao_remota || 'atualização encontrada'}.`, 5000);
            } else {
                completeTaskToast('Tabelas Atualizadas', `Base local já está na última versão RFB (${res.versao_db || 'OK'}).`, 3500);
            }
        }
    } catch (e) {
        setText('cat-sync-guidance', `Erro ao consultar catálogos: ${e.message}`);
        if (checkRemote) {
            failTaskToast('Erro ao Verificar Tabelas', e.message || 'Falha na consulta oficial.');
        }
    } finally {
        if (btnCheck) {
            btnCheck.disabled = false;
            if (checkRemote) btnCheck.innerHTML = originalCheckHtml;
        }
    }
}

export async function syncOfficialCatalogs() {
    const btn = document.getElementById('btn-sync-catalogs');
    const originalHtml = btn ? btn.innerHTML : '';
    if (btn) {
        btn.disabled = true;
        btn.innerText = 'Sincronizando...';
    }
    showTaskToast(
        'Catálogos Oficiais',
        'Consultando API da Receita Federal e Portal Nacional NFS-e...',
        { progress: 25, autoProgress: true },
    );
    try {
        setTaskProgress(45, 'Baixando CST, cClassTrib, 920 NBS e Anexos VII/VIII...', 'Catálogos Oficiais');
        const res = await api('/catalogs/sync?force=true', 'POST');
        const meta = res?.metadados || {};
        renderCatalogsStatus(meta);
        completeTaskToast(
            'Catálogos Sincronizados',
            `Tabelas oficiais atualizadas (${meta.versao_db || 'OK'}).`,
            4500,
        );
    } catch (e) {
        failTaskToast('Falha na Sincronização', e.message || 'Erro ao sincronizar catálogos.');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    }
}

