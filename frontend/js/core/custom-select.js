/**
 * Dropdown customizado que substitui visualmente o <select> nativo.
 *
 * Motivo: no Chromium/WebKitGTK sob Linux o popup nativo do <select> abre
 * posicionado com a opção atual sob o cursor; o `mouseup` do mesmo clique que
 * abriu o popup acaba selecionando a opção imediatamente, fechando a lista
 * antes que o usuário consiga vê-la.
 *
 * O <select> original permanece no DOM (oculto) e continua sendo a fonte de
 * verdade: `id`, `value`, `onchange` inline e leituras via JS seguem funcionando.
 */

const OPEN_GUARD_MS = 250;
const SEARCH_THRESHOLD = 8;

const normalizeText = (s) =>
    String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

const valueDesc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
const indexDesc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'selectedIndex');

let activeInstance = null;
let lastWindowWidth = typeof window !== 'undefined' ? window.innerWidth : 0;

function closeActive() {
    if (activeInstance) activeInstance.close();
}

function isMobileOrTouchSheet() {
    if (typeof window === 'undefined') return false;
    return window.innerWidth <= 768 || (typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches);
}

document.addEventListener('mousedown', (e) => {
    if (!activeInstance) return;
    if (activeInstance.panel.contains(e.target) || activeInstance.trigger.contains(e.target)) return;
    if (performance.now() - activeInstance.openedAt < OPEN_GUARD_MS) return;
    closeActive();
}, true);

window.addEventListener('resize', () => {
    if (!activeInstance) {
        lastWindowWidth = window.innerWidth;
        return;
    }
    const widthDelta = Math.abs(window.innerWidth - lastWindowWidth);
    lastWindowWidth = window.innerWidth;
    // No mobile (bottom sheet ou abertura do teclado virtual / barra de URL que altera apenas innerHeight),
    // nunca fechar o select — apenas reposicionar.
    if (activeInstance.panel.classList.contains('cs-sheet') || widthDelta < 40) {
        activeInstance.position();
        return;
    }
    closeActive();
});

document.addEventListener('scroll', (e) => {
    if (!activeInstance) return;
    if (activeInstance.panel.contains(e.target)) return;
    activeInstance.position();
}, true);

class CustomSelect {
    constructor(select) {
        this.select = select;
        this.openedAt = 0;
        this.focusIndex = -1;
        this.items = [];

        this.wrap = document.createElement('div');
        this.wrap.className = 'cs-wrap';

        this.trigger = document.createElement('button');
        this.trigger.type = 'button';
        this.trigger.className = select.classList.contains('form-input-sm')
            ? 'cs-trigger form-input form-input-sm'
            : 'cs-trigger form-input';
        this.trigger.setAttribute('aria-haspopup', 'listbox');
        this.trigger.setAttribute('aria-expanded', 'false');
        if (select.title) this.trigger.title = select.title;

        this.label = document.createElement('span');
        this.label.className = 'cs-label';
        this.trigger.appendChild(this.label);

        select.parentNode.insertBefore(this.wrap, select);
        this.wrap.appendChild(this.trigger);
        this.wrap.appendChild(select);
        select.classList.add('cs-native');
        select.tabIndex = -1;
        select.setAttribute('aria-hidden', 'true');

        this.backdrop = document.createElement('div');
        this.backdrop.className = 'cs-backdrop';
        this.backdrop.setAttribute('aria-hidden', 'true');
        this.backdrop.addEventListener('click', (e) => {
            e.preventDefault();
            if (performance.now() - this.openedAt < OPEN_GUARD_MS) return;
            this.close();
        });

        this.panel = document.createElement('div');
        this.panel.className = 'cs-panel';
        this.panel.setAttribute('role', 'listbox');

        this.bindEvents();
        this.patchSelect();
        this.refreshLabel();
    }

    bindEvents() {
        // `click` só dispara após o mouseup: a lista é criada depois do clique
        // terminar, então não há seleção acidental.
        this.trigger.addEventListener('click', (e) => {
            e.preventDefault();
            if (this.isOpen()) this.close();
            else this.open();
        });

        this.trigger.addEventListener('keydown', (e) => {
            if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) {
                e.preventDefault();
                if (!this.isOpen()) this.open();
            } else if (e.key === 'Escape') {
                this.close();
            }
        });

        this.panel.addEventListener('keydown', (e) => this.onPanelKey(e));

        new MutationObserver(() => {
            this.refreshLabel();
            if (this.isOpen()) this.renderList();
        }).observe(this.select, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['disabled'] });

        this.select.addEventListener('change', () => this.refreshLabel());
    }

    /** Atualiza o rótulo quando o JS altera `value`/`selectedIndex` diretamente. */
    patchSelect() {
        const self = this;
        Object.defineProperty(this.select, 'value', {
            configurable: true,
            get() { return valueDesc.get.call(this); },
            set(v) { valueDesc.set.call(this, v); self.refreshLabel(); },
        });
        Object.defineProperty(this.select, 'selectedIndex', {
            configurable: true,
            get() { return indexDesc.get.call(this); },
            set(v) { indexDesc.set.call(this, v); self.refreshLabel(); },
        });
    }

    isOpen() {
        return this.panel.isConnected;
    }

    refreshLabel() {
        const opt = this.select.options[this.select.selectedIndex];
        const text = opt ? opt.text : '';
        this.label.textContent = text || '—';
        this.trigger.title = text;
        this.trigger.disabled = this.select.disabled;
        this.trigger.classList.toggle('cs-placeholder', !opt || opt.value === '');
    }

    getFieldTitle() {
        const explicit = this.select.getAttribute('aria-label') || this.select.dataset?.title;
        if (explicit) return explicit.trim();

        if (this.select.id) {
            try {
                const byFor = document.querySelector(`label[for="${CSS.escape(this.select.id)}"]`);
                if (byFor && byFor.textContent) return byFor.textContent.trim();
            } catch (_) {}
        }

        const groupLabel = this.select.closest('.form-group')?.querySelector('.form-label, label');
        if (groupLabel && groupLabel.textContent) {
            return groupLabel.textContent.trim();
        }

        const firstOpt = this.select.options[0];
        if (firstOpt && firstOpt.value === '' && firstOpt.text) {
            const cleaned = firstOpt.text.replace(/^[\s\-–—]+|[\s\-–—]+$/g, '').trim();
            if (cleaned) return cleaned;
        }

        return 'Selecionar opção';
    }

    open() {
        if (this.select.disabled) return;
        closeActive();
        activeInstance = this;
        lastWindowWidth = window.innerWidth;
        this.openedAt = performance.now();

        this.panel.innerHTML = '';

        // Cabeçalho Material Design 3 para Modal Bottom Sheet (exibido via CSS em .cs-sheet)
        const sheetHeader = document.createElement('div');
        sheetHeader.className = 'cs-sheet-header';
        const handle = document.createElement('div');
        handle.className = 'cs-sheet-handle';
        handle.setAttribute('aria-hidden', 'true');
        const titleRow = document.createElement('div');
        titleRow.className = 'cs-sheet-title-row';
        const titleEl = document.createElement('span');
        titleEl.className = 'cs-sheet-title';
        titleEl.textContent = this.getFieldTitle();
        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'cs-sheet-close';
        closeBtn.setAttribute('aria-label', 'Fechar');
        closeBtn.innerHTML = '&times;';
        closeBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.close();
        });
        titleRow.appendChild(titleEl);
        titleRow.appendChild(closeBtn);
        sheetHeader.appendChild(handle);
        sheetHeader.appendChild(titleRow);
        this.panel.appendChild(sheetHeader);

        const total = this.select.options.length;
        if (total > SEARCH_THRESHOLD) {
            this.search = document.createElement('input');
            this.search.type = 'text';
            this.search.className = 'cs-search';
            this.search.placeholder = 'Filtrar opções...';
            this.search.addEventListener('input', () => this.renderList());
            this.panel.appendChild(this.search);
        } else {
            this.search = null;
        }
        this.list = document.createElement('div');
        this.list.className = 'cs-list';
        this.panel.appendChild(this.list);

        document.body.appendChild(this.panel);
        this.renderList();
        this.position();

        this.trigger.setAttribute('aria-expanded', 'true');
        this.wrap.classList.add('cs-open');

        const selected = this.list.querySelector('.cs-option.cs-selected');
        if (selected) selected.scrollIntoView({ block: 'nearest' });

        this.panel.tabIndex = -1;
        if (this.search && !isMobileOrTouchSheet()) {
            this.search.focus({ preventScroll: true });
        } else {
            this.panel.focus({ preventScroll: true });
        }
    }

    close() {
        if (!this.isOpen()) return;
        if (this.backdrop && this.backdrop.isConnected) {
            this.backdrop.remove();
        }
        this.panel.remove();
        this.trigger.setAttribute('aria-expanded', 'false');
        this.wrap.classList.remove('cs-open');
        if (activeInstance === this) activeInstance = null;
    }

    renderList() {
        const tokens = normalizeText(this.search?.value || '').trim().split(/\s+/).filter(Boolean);
        this.list.innerHTML = '';
        this.items = [];
        this.focusIndex = -1;

        const appendOption = (opt, parent, groupNorm = '') => {
            if (tokens.length > 0) {
                const hay = groupNorm ? `${normalizeText(opt.text)} ${groupNorm}` : normalizeText(opt.text);
                if (!tokens.every(t => hay.includes(t))) return false;
            }
            const el = document.createElement('div');
            el.className = 'cs-option';
            el.setAttribute('role', 'option');
            el.textContent = opt.text;
            el.title = opt.text;
            if (opt.disabled) el.classList.add('cs-disabled');
            if (opt.selected) {
                el.classList.add('cs-selected');
                el.setAttribute('aria-selected', 'true');
            }
            el.addEventListener('click', () => {
                if (performance.now() - this.openedAt < OPEN_GUARD_MS) return;
                if (!opt.disabled) this.choose(opt.value);
            });
            if (!opt.disabled) {
                const idx = this.items.length;
                el.addEventListener('mousemove', () => {
                    if (this.focusIndex !== idx) this.setFocus(idx, false);
                });
                this.items.push(el);
            }
            parent.appendChild(el);
            return true;
        };

        for (const child of Array.from(this.select.children)) {
            if (child.tagName === 'OPTGROUP') {
                const group = document.createElement('div');
                group.className = 'cs-group';
                const header = document.createElement('div');
                header.className = 'cs-group-label';
                header.textContent = child.label;
                group.appendChild(header);
                const groupNorm = normalizeText(child.label);
                let any = false;
                for (const opt of Array.from(child.children)) {
                    if (opt.tagName === 'OPTION' && appendOption(opt, group, groupNorm)) any = true;
                }
                if (any) this.list.appendChild(group);
            } else if (child.tagName === 'OPTION') {
                appendOption(child, this.list);
            }
        }

        if (!this.list.children.length) {
            const empty = document.createElement('div');
            empty.className = 'cs-empty';
            empty.textContent = 'Nenhuma opção encontrada';
            this.list.appendChild(empty);
        }
    }

    position() {
        if (!this.isOpen()) return;
        const rect = this.trigger.getBoundingClientRect();
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const margin = 8;

        if (vw <= 768) {
            // Mobile (M3 Modal Bottom Sheet de largura total)
            this.panel.classList.add('cs-sheet');
            if (this.backdrop && !this.backdrop.isConnected) {
                document.body.insertBefore(this.backdrop, this.panel);
            }
            Object.assign(this.panel.style, { left: '', top: '', width: '', maxHeight: '' });
            return;
        }
        this.panel.classList.remove('cs-sheet');
        if (this.backdrop && this.backdrop.isConnected) {
            this.backdrop.remove();
        }

        const width = Math.min(Math.max(rect.width, 340), vw - margin * 2);
        let left = rect.left;
        if (left + width > vw - margin) left = vw - margin - width;
        left = Math.max(margin, left);

        const spaceBelow = vh - rect.bottom - margin;
        const spaceAbove = rect.top - margin;
        const openUp = spaceBelow < 220 && spaceAbove > spaceBelow;
        const maxHeight = Math.min(380, openUp ? spaceAbove - 4 : spaceBelow - 4);

        this.panel.style.width = `${width}px`;
        this.panel.style.left = `${left}px`;
        this.panel.style.maxHeight = `${Math.max(maxHeight, 140)}px`;
        if (openUp) {
            this.panel.style.top = `${Math.max(margin, rect.top - 4 - Math.min(this.panel.scrollHeight, Math.max(maxHeight, 140)))}px`;
        } else {
            this.panel.style.top = `${rect.bottom + 4}px`;
        }
    }

    setFocus(idx, scroll = true) {
        if (idx < 0 || idx >= this.items.length) return;
        if (this.focusIndex >= 0 && this.items[this.focusIndex]) {
            this.items[this.focusIndex].classList.remove('cs-focus');
        }
        this.focusIndex = idx;
        const el = this.items[idx];
        el.classList.add('cs-focus');
        if (scroll) el.scrollIntoView({ block: 'nearest' });
    }

    onPanelKey(e) {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            this.setFocus(Math.min(this.focusIndex + 1, this.items.length - 1));
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            this.setFocus(Math.max(this.focusIndex - 1, 0));
        } else if (e.key === 'Enter') {
            e.preventDefault();
            const el = this.items[this.focusIndex] || (this.items.length === 1 ? this.items[0] : null);
            if (el) el.click();
        } else if (e.key === 'Escape' || e.key === 'Tab') {
            this.close();
            this.trigger.focus();
        }
    }

    choose(value) {
        this.close();
        this.trigger.focus({ preventScroll: true });
        if (valueDesc.get.call(this.select) === value) return;
        valueDesc.set.call(this.select, value);
        this.refreshLabel();
        this.select.dispatchEvent(new Event('input', { bubbles: true }));
        this.select.dispatchEvent(new Event('change', { bubbles: true }));
    }
}

/** Converte todos os `select.form-input` dentro de `root` (idempotente). */
export function enhanceSelects(root = document) {
    if (!root) return;
    root.querySelectorAll('select.form-input:not([data-cs-enhanced])').forEach(sel => {
        sel.dataset.csEnhanced = '1';
        new CustomSelect(sel);
    });
}

export function closeCustomSelects() {
    closeActive();
}

if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => enhanceSelects(document));
    } else {
        enhanceSelects(document);
    }
}

