"""Browser-side extraction payload for agent observations."""

SENSITIVE_ELEMENT_PREDICATE = r"""(el) => {
  const attr = (key) => el.getAttribute(key) || '';
  const tag = el.tagName.toLowerCase();
  const inputType = attr('type').toLowerCase() || (tag === 'input' ? 'text' : '');
  return ['password','file'].includes(inputType) ||
    /(cc-number|cvc|ssn|otp|token|secret|password|credit.?card)/i.test(
      [attr('name'), el.id || '', attr('autocomplete')].join(' ')
    );
}"""

ROLE_OF_ELEMENT = r"""(el) => {
  const attr = (key) => el.getAttribute(key) || '';
  const explicit = attr('role').split(/\s+/)[0];
  if (explicit) return explicit;
  const tag = el.tagName.toLowerCase();
  const type = attr('type').toLowerCase();
  if (tag === 'a' && el.hasAttribute('href')) return 'link';
  if (tag === 'button' || (tag === 'input' && ['button','submit','reset','image'].includes(type))) return 'button';
  if (tag === 'textarea') return 'textbox';
  if (tag === 'select') return el.multiple ? 'listbox' : 'combobox';
  if (tag === 'input') {
    if (type === 'checkbox') return 'checkbox';
    if (type === 'radio') return 'radio';
    if (type === 'range') return 'slider';
    return 'textbox';
  }
  if (tag === 'summary') return 'button';
  return 'generic';
}"""

OBSERVATION_SCRIPT = r"""
({maxTextLength, contentMode, scopeElement}) => {
  const clip = (value, n = 160) => (value || '').replace(/\s+/g, ' ').trim().slice(0, n);
  const attr = (el, key) => el.getAttribute(key) || '';
  const cssString = (value) => JSON.stringify(String(value));
  const hidden = (el) => {
    if (!(el instanceof Element)) return false;
    if (el.hidden || el.getAttribute('aria-hidden') === 'true') return true;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return true;
    return el.parentElement ? hidden(el.parentElement) : false;
  };
  const visible = (el) => {
    if (hidden(el)) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const roleOf = __SURF_ROLE_OF_ELEMENT__;
  const nameOf = (el) => {
    const labelledby = attr(el, 'aria-labelledby');
    if (labelledby) {
      const value = labelledby.split(/\s+/).map(id => document.getElementById(id)).filter(Boolean).map(node => node.innerText || '').join(' ');
      if (clip(value)) return clip(value);
    }
    if (attr(el, 'aria-label')) return clip(attr(el, 'aria-label'));
    if (el.labels && el.labels.length) return clip(Array.from(el.labels).map(label => label.innerText || '').join(' '));
    const tag = el.tagName.toLowerCase(), type = attr(el, 'type').toLowerCase();
    const controlValue = tag === 'input' && ['button','submit','reset','image'].includes(type) ? attr(el, 'value') : '';
    return clip(el.innerText || controlValue || attr(el, 'placeholder') || attr(el, 'title'));
  };
  const unique = (selector) => {
    try { return document.querySelectorAll(selector).length === 1; } catch (_) { return false; }
  };
  const structural = (el) => {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.documentElement) {
      let part = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter(child => child.tagName === node.tagName);
        if (same.length > 1) part += `:nth-of-type(${same.indexOf(node) + 1})`;
      }
      parts.unshift(part);
      const candidate = parts.join(' > ');
      if (unique(candidate)) return candidate;
      node = parent;
    }
    return `html > ${parts.join(' > ')}`;
  };
  const locatorCandidates = (el, role, name) => {
    const candidates = [];
    for (const key of ['data-testid','data-test','data-qa']) if (attr(el,key)) candidates.push(`[${key}=${cssString(attr(el,key))}]`);
    if (el.id) candidates.push(`#${CSS.escape(el.id)}`);
    if (el.labels && el.labels.length && el.labels[0].contains(el)) {
      const labelScoped = `${structural(el.labels[0])} ${el.tagName.toLowerCase()}`;
      if (unique(labelScoped) && document.querySelector(labelScoped) === el) candidates.push(labelScoped);
    }
    if (attr(el,'aria-label')) candidates.push(`[aria-label=${cssString(attr(el,'aria-label'))}]`);
    const rendered = clip(el.innerText, 160);
    if (role !== 'generic' && name && rendered === name) {
      const sameName = Array.from(document.querySelectorAll(el.tagName.toLowerCase())).filter(node => clip(node.innerText,160).includes(name));
      if (sameName.length === 1 && sameName[0] === el) candidates.push(`${el.tagName.toLowerCase()}:has-text(${cssString(name)})`);
    }
    if (attr(el,'name')) {
      let stable = `${el.tagName.toLowerCase()}[name=${cssString(attr(el,'name'))}]`;
      if (attr(el,'type')) stable += `[type=${cssString(attr(el,'type'))}]`;
      candidates.push(stable);
    }
    if (attr(el,'role')) candidates.push(`[role=${cssString(attr(el,'role'))}]`);
    candidates.push(structural(el));
    return [...new Set(candidates)].filter(candidate => candidate.includes(':has-text(') || unique(candidate));
  };
  const actionList = (el, role) => {
    const tag = el.tagName.toLowerCase();
    const type = attr(el,'type').toLowerCase();
    const actions = [];
    if (tag === 'a' || tag === 'button' || ['button','submit','reset','checkbox','radio'].includes(type) || role === 'button' || el.onclick || el.hasAttribute('data-surf-listener')) actions.push('click');
    if (tag === 'textarea' || (tag === 'input' && !['button','submit','reset','checkbox','radio','file'].includes(type)) || el.isContentEditable) actions.push('type');
    if (tag === 'select') actions.push('select');
    if (!actions.length) actions.push('hover');
    return [...new Set(actions)];
  };
  const discoveryOf = (el) => {
    const tag = el.tagName.toLowerCase();
    if (['a','button','input','textarea','select','summary','details'].includes(tag) || el.isContentEditable) return 'native';
    if (attr(el,'role')) return 'aria';
    if (el.tabIndex >= 0) return 'focusable';
    if (el.onclick || el.hasAttribute('data-surf-listener')) return 'listener';
    return 'heuristic';
  };
  const root = scopeElement || document.body;
  const selector = 'a[href],button,input,textarea,select,summary,details,[contenteditable]:not([contenteditable="false"]),[role],[tabindex]:not([tabindex="-1"]),[onclick],[data-surf-listener]';
  const found = new Set(Array.from(root.querySelectorAll(selector)));
  for (const el of root.querySelectorAll('*')) {
    if (!found.has(el) && getComputedStyle(el).cursor === 'pointer') found.add(el);
  }
  const elements = Array.from(found).map((el) => {
    const tag = el.tagName.toLowerCase();
    const inputType = attr(el,'type').toLowerCase() || (tag === 'input' ? 'text' : '');
    const role = roleOf(el);
    const name = nameOf(el);
    const renderedText = clip(el.innerText, 160);
    const state = {visible: visible(el), enabled: !(el.disabled || attr(el,'aria-disabled') === 'true')};
    if ((tag === 'input' && ['checkbox','radio'].includes(inputType)) || role === 'checkbox' || role === 'radio' || role === 'switch') {
      state.checked = attr(el,'aria-checked') ? attr(el,'aria-checked') === 'true' : Boolean(el.checked);
    }
    if (tag === 'option' || role === 'option' || el.hasAttribute('aria-selected')) {
      state.selected = attr(el,'aria-selected') ? attr(el,'aria-selected') === 'true' : Boolean(el.selected);
    }
    if (el.required || el.hasAttribute('aria-required')) state.required = el.required || attr(el,'aria-required') === 'true';
    if (el.readOnly || el.hasAttribute('aria-readonly')) state.readonly = el.readOnly || attr(el,'aria-readonly') === 'true';
    if (el.hasAttribute('aria-expanded')) state.expanded = attr(el,'aria-expanded') === 'true';
    const sensitive = (__SURF_SENSITIVE_ELEMENT_PREDICATE__)(el);
    const entry = {
      role, name, tag, actions: actionList(el, role), state,
      discovery: discoveryOf(el), locator_candidates: locatorCandidates(el, role, name),
      fingerprint: {tag, role, type: inputType, name, id: el.id || '', testid: attr(el,'data-testid') || attr(el,'data-test') || attr(el,'data-qa')}
    };
    if (inputType) entry.input_type = inputType;
    if (renderedText && renderedText !== name) entry.text = renderedText;
    if (attr(el,'placeholder')) entry.placeholder = clip(attr(el,'placeholder'));
    if ('value' in el) {
      if (sensitive) entry.value_redacted = true;
      else entry.value = String(el.value ?? '');
    }
    if (tag === 'select') entry.options = Array.from(el.options).slice(0,100).map(option => ({label: clip(option.text), value: option.value, selected: option.selected, disabled: option.disabled}));
    if (tag === 'a') entry.link = {href: attr(el,'href'), resolved: el.href, visible: state.visible};
    if (el.form) entry.form = {id: el.form.id || '', action: el.form.action || '', method: (el.form.method || 'get').toUpperCase()};
    entry.legacy = {id: el.id || '', name: attr(el,'name')};
    return entry;
  });

  const noiseSelector = '[class*="ad-"],[class*="ads"],[id*="ad-"],[id*="ads"],[class*="cookie"],[id*="cookie"],[class*="newsletter"],[class*="subscribe"],[aria-label*="advertisement" i],aside,footer';
  const boundaryTags = new Set(['ADDRESS','ARTICLE','ASIDE','BLOCKQUOTE','BR','BUTTON','DD','DIV','DL','DT','FIELDSET','FIGCAPTION','FIGURE','FOOTER','FORM','H1','H2','H3','H4','H5','H6','HEADER','HR','INPUT','LABEL','LEGEND','LI','MAIN','NAV','OL','OPTION','P','PRE','SECTION','SELECT','SUMMARY','TABLE','TD','TEXTAREA','TH','TR','UL']);
  const renderedText = (container, mode) => {
    if (!container) return '';
    const pieces = [];
    const excluded = (el) => {
      if (hidden(el) || ['SCRIPT','STYLE','NOSCRIPT','SVG'].includes(el.tagName)) return true;
      if (mode !== 'full' && mode !== 'ui' && el.matches(noiseSelector)) return true;
      if (mode === 'reader' && el.matches('nav,header,footer,aside,form,button,input,textarea,select')) return true;
      if (mode === 'compact' && el.matches('nav,header,footer,aside,form,button,input,textarea,select')) return true;
      if (mode === 'data' && el.matches('nav,header,footer,aside,form,button')) return true;
      return false;
    };
    const walk = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        if (!node.parentElement || excluded(node.parentElement)) return;
        const value = node.nodeValue.replace(/\s+/g, ' ').trim();
        if (value) pieces.push(value);
        return;
      }
      if (!(node instanceof Element) || excluded(node)) return;
      if (node.tagName === 'IMG' && node.getAttribute('alt')) {
        pieces.push(node.getAttribute('alt').replace(/\s+/g, ' ').trim());
        return;
      }
      const boundary = boundaryTags.has(node.tagName);
      if (boundary && pieces.length && pieces[pieces.length - 1] !== '\n') pieces.push('\n');
      for (const child of node.childNodes) walk(child);
      if (boundary && pieces.length && pieces[pieces.length - 1] !== '\n') pieces.push('\n');
    };
    walk(container);
    return pieces.join(' ').replace(/ *\n */g, '\n').replace(/\n{3,}/g, '\n\n').trim();
  };
  const sourceText = renderedText(root, 'full');
  let textRoot = root;
  if (contentMode === 'reader') {
    const candidates = Array.from(root.querySelectorAll('.entry-content,.post-content,.article-content,.article-body,.story-body,article,main,[role=main],.article,.story,.post'));
    textRoot = candidates.sort((a,b) => renderedText(b,'reader').length - renderedText(a,'reader').length)[0] || root;
  }
  const selectedText = renderedText(textRoot, contentMode);
  const visibleText = selectedText.slice(0, maxTextLength);
  const ratio = sourceText.length ? 1 - (selectedText.length / sourceText.length) : 0;
  return {
    elements,
    visible_text: visibleText,
    visible_text_length: visibleText.length,
    token_estimate: Math.ceil(visibleText.length / 4),
    source_text_length: sourceText.length,
    selected_text_length: selectedText.length,
    truncated: visibleText.length < selectedText.length,
    reduction_ratio: Math.round(Math.max(0, Math.min(1, ratio)) * 10000) / 10000,
    tables: Array.from(root.querySelectorAll('table')).slice(0,20).map((table,index) => ({index, rows: table.rows.length, columns: table.rows[0] ? table.rows[0].cells.length : 0, preview: Array.from(table.rows).slice(0,5).map(row => Array.from(row.cells).slice(0,8).map(cell => clip(cell.innerText,120))) }))
  };
}
"""

OBSERVATION_SCRIPT = OBSERVATION_SCRIPT.replace(
    "__SURF_SENSITIVE_ELEMENT_PREDICATE__", SENSITIVE_ELEMENT_PREDICATE
).replace("__SURF_ROLE_OF_ELEMENT__", ROLE_OF_ELEMENT)


LISTENER_INIT_SCRIPT = r"""
(() => {
  if (window.__surfListenerPatched) return;
  window.__surfListenerPatched = true;
  const original = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function(type, listener, options) {
    if (this instanceof Element && ['click','dblclick','input','change','keydown','pointerdown'].includes(type)) {
      this.setAttribute('data-surf-listener', '');
    }
    return original.call(this, type, listener, options);
  };
})();
"""
