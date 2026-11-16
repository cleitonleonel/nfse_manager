export function formatCnpj(val) {
    const clean = String(val || '').toUpperCase().replace(/[^0-9A-Z]/g, '').slice(0, 14);
    if (clean.length <= 2) return clean;
    if (clean.length <= 5) return `${clean.slice(0, 2)}.${clean.slice(2)}`;
    if (clean.length <= 8) return `${clean.slice(0, 2)}.${clean.slice(2, 5)}.${clean.slice(5)}`;
    if (clean.length <= 12) return `${clean.slice(0, 2)}.${clean.slice(2, 5)}.${clean.slice(5, 8)}/${clean.slice(8)}`;
    return `${clean.slice(0, 2)}.${clean.slice(2, 5)}.${clean.slice(5, 8)}/${clean.slice(8, 12)}-${clean.slice(12, 14)}`;
}

export function formatCep(val) {
    const clean = String(val || '').replace(/\D/g, '').slice(0, 8);
    if (clean.length <= 5) return clean;
    return `${clean.slice(0, 5)}-${clean.slice(5, 8)}`;
}

export function maskCnpj(input) {
    input.value = formatCnpj(input.value);
    input.maxLength = 18;
    input.placeholder = '00.000.000/0000-00';
}

export function maskCep(input) {
    input.value = formatCep(input.value);
    input.maxLength = 9;
    input.placeholder = '00000-000';
}

export function openModal(id) {
    document.getElementById(id).classList.add('open');
}

export function closeModal(id) {
    document.getElementById(id).classList.remove('open');
}

export function showTaskToast(title, msg) {
    const toast = document.getElementById('task-toast');
    if(toast) {
        document.getElementById('task-title').innerText = title;
        document.getElementById('task-msg').innerText = msg;
        document.getElementById('task-progress').style.width = '0%';
        toast.style.display = 'block';
    }
}

export function hideTaskToast() {
    const toast = document.getElementById('task-toast');
    if (toast) {
        toast.style.display = 'none';
    }
}

export function toggleTheme() {
    const isLight = document.body.classList.toggle('theme-light');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
    return isLight;
}

export function maskPhone(input) {
    let v = input.value.replace(/\D/g, '');
    if (v.length > 11) v = v.slice(0, 11);
    
    if (v.length > 10) {
        v = v.replace(/^(\d{2})(\d{5})(\d{4})/, '($1) $2-$3');
    } else if (v.length > 2) {
        v = v.replace(/^(\d{2})(\d*)/, '($1) $2');
    } else if (v.length > 0) {
        v = v.replace(/^(\d*)/, '($1');
    }
    input.value = v;
}
