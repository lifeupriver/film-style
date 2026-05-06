// markdown.js — small, safe markdown → DOM renderer.
//
// Built deliberately small. Produces real DOM nodes (no innerHTML), so any
// pasted content can't smuggle script tags. Supported features cover what
// the style-guide.md actually emits: headings, paragraphs, lists, blockquotes,
// fenced code, inline `code` / **bold** / *italic* / [links], horizontal rules,
// pipe-tables. Anything fancier degrades to plain prose.

const INLINE_TOKENS = [
  // order matters: longer / more specific first
  { re: /^\*\*(.+?)\*\*/, tag: "strong" },
  { re: /^__(.+?)__/, tag: "strong" },
  { re: /^\*(.+?)\*/, tag: "em" },
  { re: /^_(.+?)_/, tag: "em" },
  { re: /^`([^`]+)`/, tag: "code" },
  { re: /^\[([^\]]+)\]\(([^)]+)\)/, tag: "a" },
];

function parseInline(text) {
  const frag = document.createDocumentFragment();
  let rest = text;
  while (rest.length) {
    let matched = false;
    for (const tok of INLINE_TOKENS) {
      const m = rest.match(tok.re);
      if (!m) continue;
      const before = rest.slice(0, rest.indexOf(m[0]));
      // We use ^ anchor → before is always empty, but keep guard for safety.
      if (before) frag.appendChild(document.createTextNode(before));
      const node = document.createElement(tok.tag);
      if (tok.tag === "a") {
        const href = m[2] || "";
        if (/^https?:|^\/|^#/.test(href)) {
          node.setAttribute("href", href);
          if (/^https?:/.test(href)) node.setAttribute("rel", "noopener noreferrer");
        }
        node.appendChild(parseInline(m[1]));
      } else if (tok.tag === "code") {
        node.textContent = m[1];
      } else {
        node.appendChild(parseInline(m[1]));
      }
      frag.appendChild(node);
      rest = rest.slice(m[0].length);
      matched = true;
      break;
    }
    if (!matched) {
      // Consume one character of plain text and continue scanning.
      frag.appendChild(document.createTextNode(rest[0]));
      rest = rest.slice(1);
    }
  }
  return frag;
}

function slugify(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .slice(0, 60);
}

function parseTable(lines) {
  // Expects lines like:
  //   | h1 | h2 |
  //   |----|----|
  //   | a  | b  |
  if (lines.length < 2) return null;
  const splitRow = (l) =>
    l
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map((c) => c.trim());

  const headers = splitRow(lines[0]);
  const sep = lines[1];
  if (!/^\|?[-: |]+\|?$/.test(sep.trim())) return null;
  const rows = lines.slice(2).map(splitRow);

  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const tr = document.createElement("tr");
  for (const h of headers) {
    const th = document.createElement("th");
    th.appendChild(parseInline(h));
    tr.appendChild(th);
  }
  thead.appendChild(tr);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (const r of rows) {
    const row = document.createElement("tr");
    for (const cell of r) {
      const td = document.createElement("td");
      td.appendChild(parseInline(cell));
      row.appendChild(td);
    }
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  return table;
}

export function renderMarkdown(text) {
  const root = document.createElement("div");
  const tocEntries = [];

  const lines = text.split(/\r?\n/);
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // skip blank
    if (!line.trim()) {
      i++;
      continue;
    }

    // fenced code
    if (line.startsWith("```")) {
      i++;
      const buf = [];
      while (i < lines.length && !lines[i].startsWith("```")) {
        buf.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++; // closing fence
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = buf.join("\n");
      pre.appendChild(code);
      root.appendChild(pre);
      continue;
    }

    // hr
    if (/^\s*(---|\*\*\*|___)\s*$/.test(line)) {
      root.appendChild(document.createElement("hr"));
      i++;
      continue;
    }

    // headings
    const heading = line.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      const level = heading[1].length;
      const text = heading[2];
      const h = document.createElement(`h${level}`);
      const id = slugify(text);
      h.id = id;
      h.appendChild(parseInline(text));
      root.appendChild(h);
      if (level <= 3) tocEntries.push({ level, text, id });
      i++;
      continue;
    }

    // table
    if (line.trim().startsWith("|") && lines[i + 1] && lines[i + 1].trim().startsWith("|")) {
      const buf = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        buf.push(lines[i]);
        i++;
      }
      const tbl = parseTable(buf);
      if (tbl) root.appendChild(tbl);
      else {
        // fallback: treat as paragraph
        const p = document.createElement("p");
        p.appendChild(parseInline(buf.join(" ")));
        root.appendChild(p);
      }
      continue;
    }

    // blockquote
    if (line.startsWith(">")) {
      const buf = [];
      while (i < lines.length && lines[i].startsWith(">")) {
        buf.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      const bq = document.createElement("blockquote");
      const p = document.createElement("p");
      p.appendChild(parseInline(buf.join(" ")));
      bq.appendChild(p);
      root.appendChild(bq);
      continue;
    }

    // unordered list
    if (/^\s*[-*+]\s+/.test(line)) {
      const ul = document.createElement("ul");
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        const li = document.createElement("li");
        li.appendChild(parseInline(lines[i].replace(/^\s*[-*+]\s+/, "")));
        ul.appendChild(li);
        i++;
      }
      root.appendChild(ul);
      continue;
    }

    // ordered list
    if (/^\s*\d+\.\s+/.test(line)) {
      const ol = document.createElement("ol");
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        const li = document.createElement("li");
        li.appendChild(parseInline(lines[i].replace(/^\s*\d+\.\s+/, "")));
        ol.appendChild(li);
        i++;
      }
      root.appendChild(ol);
      continue;
    }

    // paragraph (collect contiguous non-empty lines)
    const buf = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^#{1,6}\s/.test(lines[i]) &&
      !lines[i].startsWith("```") &&
      !lines[i].startsWith(">") &&
      !/^\s*[-*+]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !/^\s*(---|\*\*\*|___)\s*$/.test(lines[i])
    ) {
      buf.push(lines[i]);
      i++;
    }
    const p = document.createElement("p");
    p.appendChild(parseInline(buf.join(" ")));
    root.appendChild(p);
  }

  return { node: root, toc: tocEntries };
}
