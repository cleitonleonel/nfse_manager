import { api } from '../core/api.js';
import { showTaskToast } from '../core/ui.js';
import { state } from '../core/state.js';

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

        if (res.status === 'completed' && res.restart_required) {
            stopUpdatePoll();
            state.updateReady = true;
            setProgress(100);
            setText('update-progress-text', 'Atualização baixada e pronta para aplicação segura.');
            showApplyAction();
            setDisplay('btn-apply-update', 'block');
        } else if (res.status === 'failed') {
            state.updateTask = null;
            stopUpdatePoll();
            setProgress(0);
            setText('update-progress-text', `Falha na atualização: ${res.message || 'erro desconhecido'}`);
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
        alert("Por favor, preencha pelo menos seu e-mail e a mensagem.");
        return;
    }
    
    const btn = document.getElementById('btn-send-sup');
    const originalText = btn.innerText;
    
    try {
        btn.disabled = true;
        btn.innerText = 'Enviando...';
        
        await api('/support/message', 'POST', { email, whatsapp, message });
        
        showTaskToast('Sucesso', 'Sua mensagem foi enviada! Obrigado pelo feedback.');
        
        // Clear fields
        document.getElementById('sup-email').value = '';
        document.getElementById('sup-whatsapp').value = '';
        document.getElementById('sup-msg').value = '';
        
    } catch (e) {
        alert("Erro ao enviar: " + e.message);
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
            alert("Erro ao verificar atualizações: " + e.message);
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
        showTaskToast('Atualização Iniciada', 'O download da nova versão começou em segundo plano.');
    } catch (e) {
        alert('Erro ao iniciar download: ' + e.message);
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
            alert('Nenhuma atualização preparada para aplicar.');
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
        showTaskToast('Atualização Aplicada', 'O sistema está reiniciando...');
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
        alert('Falha ao aplicar atualização: ' + e.message);
        setText('update-progress-text', 'Falha ao aplicar a atualização. Nenhum arquivo foi substituído.');
        if (btn) {
            btn.disabled = false;
            btn.innerText = 'Reiniciar e aplicar';
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
}

