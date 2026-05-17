export function maskCnpj(input) {
    let v = input.value.replace(/\D/g, '');
    if (v.length <= 11) {
        v = v.replace(/(\d{3})(\d)/, '$1.$2');
        v = v.replace(/(\d{3})(\d)/, '$1.$2');
        v = v.replace(/(\d{3})(\d{1,2})$/, '$1-$2');
        input.maxLength = 14;
        input.placeholder = '000.000.000-00';
    } else {
        v = v.replace(/^(\d{2})(\d)/, '$1.$2');
        v = v.replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3');
        v = v.replace(/\.(\d{3})(\d)/, '.$1/$2');
        v = v.replace(/(\d{4})(\d)/, '$1-$2');
        input.maxLength = 18;
        input.placeholder = '00.000.000/0000-00';
    }
    input.value = v;
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
