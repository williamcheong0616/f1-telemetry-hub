// The user guide (GUIDE.md, shipped with the app) rendered as a page with a table of contents. A small
// Markdown reader for the subset the guide uses: headings, paragraphs, lists, tables, quotes, code, links.
// It builds elements, never HTML from the text, and only follows http(s) links and in-guide anchors.
import { h } from '../util.js';

// the same ids GitHub gives headings, so links inside the guide work in both places
export const slug = t => t.toLowerCase().trim().replace(/[^\p{L}\p{N}\s-]/gu, '').replace(/\s/g, '-');

function inline(text) {
  const out = [];
  const re = /(`[^`]+`)|(\*\*(.+?)\*\*)|(\*([^*\s][^*]*?)\*)|(\[([^\]]+)\]\(([^)\s]+)\))/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1]) out.push(h('code', { class: 'inline' }, m[1].slice(1, -1)));
    else if (m[2]) out.push(h('b', {}, ...inline(m[3])));
    else if (m[4]) out.push(h('em', {}, ...inline(m[5])));
    else if (m[6]) {
      const url = m[8];
      if (/^https?:\/\//.test(url)) out.push(h('a', { href: url, target: '_blank', rel: 'noopener noreferrer' }, ...inline(m[7])));
      else if (url.startsWith('#') && !url.startsWith('#/')) out.push(h('a', { href: '#/guide?s=' + url.slice(1), 'data-anchor': url.slice(1) }, ...inline(m[7])));
      else out.push(...inline(m[7]));
    }
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const cells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
const LIST = /^(\s*)([-*]|\d+\.)\s+(.*)$/;

export function render(md) {
  const lines = md.replace(/\r/g, '').split('\n');
  const blocks = [], toc = [];
  let i = 0;
  const isBlockStart = l => /^(#{1,4}\s|```|>|\||---+\s*$)/.test(l) || LIST.test(l);
  while (i < lines.length) {
    const l = lines[i];
    if (!l.trim() || /^<!--.*-->$/.test(l.trim())) { i++; continue; }
    let m;
    if (l.startsWith('```')) {
      const code = [];
      for (i++; i < lines.length && !lines[i].startsWith('```'); i++) code.push(lines[i]);
      i++;
      blocks.push(h('pre', { class: 'guide-pre' }, h('code', {}, code.join('\n'))));
    } else if ((m = /^(#{1,4})\s+(.*)$/.exec(l))) {
      const level = m[1].length, text = m[2].trim(), id = slug(text);
      blocks.push(h('h' + level, { id }, ...inline(text)));
      if (level === 2 || level === 3) toc.push({ level, text, id });
      i++;
    } else if (/^---+\s*$/.test(l)) {
      blocks.push(h('hr')); i++;
    } else if (l.startsWith('|') && i + 1 < lines.length && /^\|?\s*:?-{3,}/.test(lines[i + 1])) {
      const head = cells(l);
      const rows = [];
      for (i += 2; i < lines.length && lines[i].startsWith('|'); i++) rows.push(cells(lines[i]));
      blocks.push(h('div', { class: 'table-wrap' }, h('table', { class: 'data guide-table' },
        h('thead', {}, h('tr', {}, ...head.map(c => h('th', {}, ...inline(c))))),
        h('tbody', {}, ...rows.map(r => h('tr', {}, ...r.map(c => h('td', {}, ...inline(c)))))))));
    } else if (l.startsWith('>')) {
      const text = [];
      for (; i < lines.length && lines[i].startsWith('>'); i++) text.push(lines[i].replace(/^>\s?/, ''));
      blocks.push(h('blockquote', { class: 'guide-note' }, ...text.join('\n').split(/\n\s*\n/).map(p => h('p', {}, ...inline(p.replace(/\n/g, ' '))))));
    } else if (LIST.test(l)) {
      const root = { ordered: /\d/.test(LIST.exec(l)[2]), items: [] };
      let item = null;
      for (; i < lines.length; i++) {
        const x = lines[i];
        const lm = LIST.exec(x);
        if (lm) {
          const deep = lm[1].length >= 2 && item;
          if (deep) {
            item.sub = item.sub || { ordered: /\d/.test(lm[2]), items: [] };
            item.sub.items.push({ text: lm[3] });
          } else root.items.push(item = { text: lm[3] });
        } else if (x.trim() && /^\s+/.test(x) && item) {
          const target = item.sub ? item.sub.items[item.sub.items.length - 1] : item;
          target.text += ' ' + x.trim();
        } else break;
      }
      const build = list => h(list.ordered ? 'ol' : 'ul', {}, ...list.items.map(it => h('li', {}, ...inline(it.text), it.sub ? build(it.sub) : null)));
      blocks.push(build(root));
    } else {
      const text = [];
      for (; i < lines.length && lines[i].trim() && !(text.length && isBlockStart(lines[i])); i++) text.push(lines[i].trim());
      blocks.push(h('p', {}, ...inline(text.join(' '))));
    }
  }
  return { blocks, toc };
}

export async function mount(root, arg, query) {
  let md;
  try {
    const r = await fetch('/api/guide');
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
    md = await r.text();
  } catch (e) {
    root.append(h('div', { class: 'card empty' }, h('h3', {}, 'The guide is not available'), String(e.message || e)));
    return;
  }
  const { blocks, toc } = render(md);
  const article = h('article', { class: 'guide-body card' }, ...blocks);
  const go = (id, smooth = true) => {
    const el = article.querySelector('#' + CSS.escape(id));
    if (!el) return;
    el.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' });
    history.replaceState(null, '', '#/guide?s=' + id);
  };
  const nav = h('nav', { class: 'guide-toc', 'aria-label': 'Guide contents' },
    h('div', { class: 'small muted', style: { marginBottom: '6px' } }, 'Contents'),
    ...toc.map(t => h('a', { href: '#/guide?s=' + t.id, class: 'lvl' + t.level, onclick: e => { e.preventDefault(); go(t.id); } }, t.text.replace(/\*\*/g, ''))));
  article.addEventListener('click', e => {
    const a = e.target.closest('a[data-anchor]');
    if (a) { e.preventDefault(); go(a.dataset.anchor); }
  });
  root.append(h('div', { class: 'guide' }, nav, article));
  if (query.s) requestAnimationFrame(() => go(query.s, false));
}
