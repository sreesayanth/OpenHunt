"""Read any application form into FormFields, and fill them in.

A script runs inside the page, finds every visible question (text boxes, dropdowns, radio and
checkbox groups, file uploads, custom dropdowns, yes/no button pairs), works out its label the way
a person would read it, and tags each element with `data-oh-id` so we can find it again to fill it.
Site adapters only add what's special about their site (how to open the form, the submit button).
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field

from openhunt.apply.fields import FormField
from openhunt.apply.values import Fill, pick_text

log = logging.getLogger(__name__)

READ_JS = r"""
([scopeSel, buttonGroups]) => {
  const root = (scopeSel && document.querySelector(scopeSel)) || document;
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  const shown = el => {
    if (!el || !el.isConnected) return false;
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (s.display === 'none' || s.visibility === 'hidden') return false;
    }
    return true;
  };
  const boxShown = el => { const r = el.getBoundingClientRect(); return shown(el) && r.width > 0 && r.height > 0; };
  const textOf = el => {
    if (!el) return '';
    const c = el.cloneNode(true);
    c.querySelectorAll('input,select,textarea,button,option,[role=option],[role=listbox],script,style,.visually-hidden,[aria-hidden=true]').forEach(n => n.remove());
    return clean(c.innerText || c.textContent);
  };
  const byIds = ids => clean(ids.split(/\s+/).map(i => document.getElementById(i)).filter(Boolean).map(e => textOf(e)).join(' '));
  let n = Number(document.body.getAttribute('data-oh-next') || 0);
  const tag = el => { if (!el.hasAttribute('data-oh-id')) el.setAttribute('data-oh-id', String(n++)); return el.getAttribute('data-oh-id'); };

  const nearbyText = el => {
    // Text just before the element inside its field container, e.g. <div><span>Phone</span><input></div>
    let node = el;
    for (let depth = 0; depth < 5 && node && node !== root; depth++) {
      let sib = node.previousElementSibling;
      while (sib) {
        if (!sib.matches('input,select,textarea,button')) {
          const t = textOf(sib);
          if (t && t.length < 300) return t;
        }
        sib = sib.previousElementSibling;
      }
      node = node.parentElement;
      if (node && node.matches('label,legend')) return textOf(node);
      const lab = node && node.querySelector(':scope > label, :scope > legend, :scope > .label, :scope > [class*=label i]');
      if (lab && !lab.contains(el)) { const t = textOf(lab); if (t) return t; }
    }
    return '';
  };
  const labelOf = el => {
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = byIds(lb); if (t) return t; }
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) { const t = textOf(l); if (t) return t; }
    }
    const wrap = el.closest('label');
    if (wrap) { const t = textOf(wrap); if (t) return t; }
    if (el.getAttribute('aria-label')) return clean(el.getAttribute('aria-label'));
    const t = nearbyText(el);
    if (t) return t;
    return clean(el.getAttribute('placeholder') || el.getAttribute('title') || (el.name || '').replace(/[_\[\]-]+/g, ' '));
  };
  const groupLabel = (inputs) => {
    const first = inputs[0];
    const group = first.closest('fieldset,[role=radiogroup],[role=group]');
    if (group) {
      const legend = group.querySelector('legend');
      if (legend) { const t = textOf(legend); if (t) return t; }
      const lb = group.getAttribute('aria-labelledby');
      if (lb) { const t = byIds(lb); if (t) return t; }
      if (group.getAttribute('aria-label')) return clean(group.getAttribute('aria-label'));
    }
    // Walk up to the smallest container holding every option, then read the text before the options.
    let box = first.parentElement;
    while (box && box !== root && !inputs.every(i => box.contains(i))) box = box.parentElement;
    for (let depth = 0; box && depth < 3; depth++, box = box.parentElement) {
      const lab = box.querySelector(':scope > label:not(:has(input)), :scope > legend, :scope > .label, :scope > [class*=label i]:not(:has(input))');
      if (lab) { const t = textOf(lab); if (t) return t; }
      let sib = box.previousElementSibling;
      if (sib) { const t = textOf(sib); if (t && t.length < 300) return t; }
    }
    return clean((first.name || '').replace(/[_\[\]-]+/g, ' '));
  };
  const required = (el, label) => !!(el.required || el.getAttribute('aria-required') === 'true' || /[*✱](\s|$)|\(required\)|^[*✱]/i.test(label));
  const invalid = el => {
    if (el.getAttribute('aria-invalid') === 'true') return true;
    const box = el.closest('.field,.form-group,[class*=field i],[class*=question i],li,fieldset') || el.parentElement;
    const err = box && box.querySelector('[class*=error i]:not(input),[role=alert]');
    return !!(err && shown(err) && clean(err.innerText));
  };
  const strip = t => clean(t.replace(/\s*[*✱](\s|$)/g, ' ').replace(/^[*✱]\s*/, '').replace(/\(required\)/i, ''));

  const out = [];
  const seenGroups = new Set();
  const els = Array.from(root.querySelectorAll('input,select,textarea,[role=combobox],[contenteditable=true][role=textbox]'));
  for (const el of els) {
    if (el.closest('[data-oh-skip]')) continue;
    const tagName = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || (tagName === 'input' ? 'text' : tagName)).toLowerCase();
    if (['hidden', 'submit', 'button', 'reset', 'image', 'password', 'search'].includes(type)) continue;
    if (el.disabled || el.readOnly && type !== 'file' && el.getAttribute('role') !== 'combobox') continue;

    if (type === 'radio' || type === 'checkbox') {
      const name = el.name || '';
      const groupEls = name ? Array.from(root.querySelectorAll(`input[type="${type}"][name="${CSS.escape(name)}"]`)) : [el];
      const key = type + ':' + (name || tag(el));
      if (seenGroups.has(key)) continue;
      seenGroups.add(key);
      const visibleOpts = groupEls.filter(i => shown(i) || (i.labels && Array.from(i.labels).some(boxShown)));
      if (!visibleOpts.length) continue;
      if (type === 'checkbox' && visibleOpts.length === 1) {
        const label = labelOf(visibleOpts[0]);
        out.push({ ui: 'checkbox', ids: [tag(visibleOpts[0])], label: strip(label), kind: 'checkbox', options: [],
                   required: required(visibleOpts[0], label), invalid: invalid(visibleOpts[0]), value: visibleOpts[0].checked ? 'true' : '' });
        continue;
      }
      const label = groupLabel(visibleOpts);
      const options = visibleOpts.map(i => {
        const l = (i.labels && i.labels[0]) ? textOf(i.labels[0]) : (i.getAttribute('aria-label') || i.value);
        return clean(l);
      });
      out.push({ ui: type, ids: visibleOpts.map(tag), label: strip(label), kind: type, options,
                 required: visibleOpts.some(i => i.required) || required(visibleOpts[0], label), invalid: invalid(visibleOpts[0]),
                 value: options.filter((_, i) => visibleOpts[i].checked).join(', ') });
      continue;
    }
    if (type === 'file') {
      const label = labelOf(el);
      const box = el.closest('div,section,fieldset');
      if (!shown(el) && !(box && boxShown(box))) continue;
      out.push({ ui: 'file', ids: [tag(el)], label: strip(label), kind: 'file', options: [],
                 required: required(el, label), invalid: invalid(el), value: el.files && el.files.length ? 'set' : '' });
      continue;
    }
    if (!boxShown(el)) continue;
    const label = labelOf(el);
    if (tagName === 'select') {
      const options = Array.from(el.options).map(o => clean(o.textContent));
      out.push({ ui: 'select', ids: [tag(el)], label: strip(label), kind: el.multiple ? 'checkbox' : 'select', options,
                 required: required(el, label), invalid: invalid(el), value: el.selectedIndex > 0 ? clean(el.options[el.selectedIndex].textContent) : '' });
      continue;
    }
    if (el.getAttribute('role') === 'combobox') {
      out.push({ ui: 'combobox', ids: [tag(el)], label: strip(label), kind: 'select', options: [],
                 required: required(el, label), invalid: invalid(el), value: clean(el.value || '') });
      continue;
    }
    const kind = tagName === 'textarea' || el.getAttribute('contenteditable') ? 'textarea'
               : ['email', 'tel', 'url', 'number', 'date'].includes(type) ? type : 'text';
    out.push({ ui: el.getAttribute('contenteditable') ? 'editable' : 'text', ids: [tag(el)], label: strip(label), kind, options: [],
               required: required(el, label), invalid: invalid(el), value: clean(el.value || el.innerText || '') });
  }

  if (buttonGroups) {
    // Yes/No answered with buttons instead of radios (e.g. Ashby).
    for (const box of root.querySelectorAll('div,span')) {
      const kids = Array.from(box.children);
      if (kids.length < 2 || kids.length > 5 || !kids.every(k => k.tagName === 'BUTTON' && k.type === 'button')) continue;
      if (!kids.every(k => clean(k.innerText).length && clean(k.innerText).length <= 30) || !boxShown(box)) continue;
      const label = nearbyText(box);
      if (!label) continue;
      out.push({ ui: 'buttons', ids: kids.map(tag), label: strip(label), kind: 'radio', options: kids.map(k => clean(k.innerText)),
                 required: /[*✱]\s*$/.test(label), invalid: invalid(box),
                 value: clean((kids.find(k => k.getAttribute('aria-pressed') === 'true' || /active|selected/i.test(k.className)) || {}).innerText || '') });
    }
  }
  document.body.setAttribute('data-oh-next', String(n));
  return out;
}
"""


@dataclass
class Raw:
    """One question on the page, plus what we need to fill it."""

    ui: str  # text | editable | select | combobox | radio | checkbox | buttons | file
    ids: list[str]
    label: str
    kind: str
    options: list[str] = field(default_factory=list)
    required: bool = False
    invalid: bool = False
    value: str = ""

    def to_field(self) -> FormField:
        return FormField(label=self.label, kind=self.kind, options=list(self.options), required=self.required or self.invalid,
                         locator=f"{self.ui}:{','.join(self.ids)}")


async def read_form(page, scope: str = "", button_groups: bool = False) -> list[Raw]:
    """Every visible question on the page (or inside `scope`), in page order."""
    rows = await page.evaluate(READ_JS, [scope, button_groups])
    raws = [Raw(**r) for r in rows if (r.get("label") or r.get("ui") == "file")]
    for raw in raws:
        if raw.ui == "combobox":
            raw.options = await _combobox_options(page, raw)
    return raws


def _loc(page, oh_id: str):
    return page.locator(f'[data-oh-id="{oh_id}"]')


async def _combobox_options(page, raw: Raw) -> list[str]:
    """Open a custom dropdown to read its choices. Search boxes with no fixed list return []."""
    box = _loc(page, raw.ids[0])
    try:
        await box.click(timeout=3000)
        await page.wait_for_timeout(300)
        texts = [t.strip() for t in await page.locator("[role=option]:visible").all_inner_texts()]
        await page.keyboard.press("Escape")
        return [t for t in texts if t][:60]
    except Exception as exc:  # noqa: BLE001
        log.debug("combobox options: %s", exc)
        return []


async def _click(loc) -> None:
    try:
        await loc.check(force=True, timeout=3000)
    except Exception:  # noqa: BLE001 - hidden custom radios: click through the DOM
        await loc.evaluate("el => el.click()")


async def fill(page, raw: Raw, value: Fill) -> None:
    """Put `value` (already fitted to this field by answers.resolve) into the page."""
    ui = raw.ui
    if ui in ("text", "editable"):
        loc = _loc(page, raw.ids[0])
        await loc.fill(str(value))
        await loc.dispatch_event("blur")
        return
    if ui == "file":
        await _loc(page, raw.ids[0]).set_input_files(str(value))
        await page.wait_for_timeout(800)  # many sites read the CV right after upload
        return
    if ui == "select":
        loc = _loc(page, raw.ids[0])
        if isinstance(value, list):
            await loc.select_option(label=value)
        else:
            await loc.select_option(label=str(value))
        return
    if ui == "combobox":
        await _fill_combobox(page, raw, str(value))
        return
    if ui == "checkbox" and not raw.options:
        loc = _loc(page, raw.ids[0])
        want = bool(value) if isinstance(value, bool) else str(value).lower() in ("true", "yes", "1")
        if await loc.is_checked() != want:
            await _click(loc)
        return
    if ui in ("radio", "checkbox", "buttons"):
        wanted = value if isinstance(value, list) else [str(value)]
        for w in wanted:
            idx = raw.options.index(w) if w in raw.options else next((i for i, o in enumerate(raw.options) if pick_text(w, [o])), -1)
            if idx < 0:
                raise ValueError(f"'{w}' is not a choice for '{raw.label}'")
            loc = _loc(page, raw.ids[idx])
            if ui == "buttons":
                await loc.click()
            elif not await loc.is_checked():
                await _click(loc)
        return
    raise ValueError(f"Don't know how to fill {ui}")


async def _fill_combobox(page, raw: Raw, value: str) -> None:
    """Custom dropdowns and search boxes: type, then pick the matching suggestion."""
    from openhunt.apply.values import CITY_ALIASES

    box = _loc(page, raw.ids[0])
    tries = [value]
    low = value.lower()
    for old, new in CITY_ALIASES.items():
        if old in low:
            tries.append(re.sub(old, new, value, flags=re.I))
    tries.append(value.split(",")[0].strip())
    for attempt in dict.fromkeys(t for t in tries if t):
        await box.click()
        try:
            await box.fill("")
            await box.type(attempt[:40], delay=20)
        except Exception:  # noqa: BLE001 - some dropdowns aren't typeable
            pass
        await page.wait_for_timeout(700)
        options = page.locator("[role=option]:visible")
        texts = [t.strip() for t in await options.all_inner_texts()]
        if not texts:
            continue
        hit = attempt if attempt in texts else pick_text(attempt, texts)
        if hit is None and not raw.options:
            hit = texts[0]  # search box (e.g. city): the first suggestion is the best match
        if hit is not None:
            await options.nth(texts.index(hit)).click()
            await asyncio.sleep(0.2)
            return
    await page.keyboard.press("Enter")
    await asyncio.sleep(0.2)


async def page_errors(page, scope: str = "") -> list[str]:
    """Visible validation messages, e.g. 'This field is required'."""
    root = scope or "body"
    try:
        texts = await page.locator(f"{root} [role=alert]:visible, {root} [class*=error i]:visible").all_inner_texts()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for t in texts:
        t = re.sub(r"\s+", " ", t).strip()
        if t and len(t) < 200 and t not in out:
            out.append(t)
    return out[:10]
