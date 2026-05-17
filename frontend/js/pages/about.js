import { api } from '../core/api.js';
import { showTaskToast } from '../core/ui.js';

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
    const updateBox = document.getElementById('update-available-box');
    const statusText = document.getElementById('update-status-text');
    const changelogPreview = document.getElementById('update-changelog-preview');
    const installedVersion = document.getElementById('installed-version-tag');
    
    try {
        btn.disabled = true;
        btn.innerText = 'Verificando...';
        if (statusText) statusText.innerText = 'Consultando a última versão publicada no GitHub...';
        
        const res = await api('/system/check-update');

        if (installedVersion && res.current_version) {
            installedVersion.innerText = res.current_version;
        }
        
        if (res.update_available) {
            statusBox.style.display = 'none';
            updateBox.style.display = 'flex';
            document.getElementById('new-version-tag').innerText = res.latest_version;
            document.getElementById('update-download-link').href = res.download_url;
            if (changelogPreview) {
                changelogPreview.innerText = res.changelog || 'Sem notas de versão disponíveis.';
            }
        } else {
            if (updateBox) updateBox.style.display = 'none';
            if (statusBox) statusBox.style.display = 'flex';
            if (statusText) {
                const extra = res.latest_version ? ` Última release encontrada: ${res.latest_version}.` : '';
                statusText.innerText = `${res.msg || 'Sua versão já é a mais recente.'}${extra}`;
            }
            if (changelogPreview) {
                changelogPreview.innerText = res.changelog || 'Nenhum changelog disponível para esta versão.';
            }
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
