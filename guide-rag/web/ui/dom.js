// A tiny DOM helper: every string child becomes a text node (textContent), never markup. Nothing
// from the guide, the index or a model reply is ever parsed as HTML.

export function el(tag, attrs = null, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "dataset") Object.assign(node.dataset, v);
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else if (v === true) node.setAttribute(k, "");
      else node.setAttribute(k, String(v));
    }
  }
  append(node, children);
  return node;
}

export function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.appendChild(typeof child === "string" || typeof child === "number" ? document.createTextNode(String(child)) : child);
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function replace(node, ...children) {
  clear(node);
  return append(node, children);
}

/** A key/value definition list. */
export function kv(pairs) {
  const dl = el("dl", { class: "kv" });
  for (const [k, v] of pairs) {
    if (v === null || v === undefined || v === "") continue;
    dl.appendChild(el("dt", null, String(k)));
    dl.appendChild(el("dd", null, typeof v === "string" || typeof v === "number" ? String(v) : v));
  }
  return dl;
}

/** A table from column definitions [{label, cell(row), class}] and rows. */
export function table(columns, rows, opts = {}) {
  const thead = el("thead", null, el("tr", null, columns.map((c) => el("th", { class: c.class || null }, c.label))));
  const tbody = el("tbody");
  for (const row of rows) {
    tbody.appendChild(el("tr", { class: opts.rowClass ? opts.rowClass(row) : null }, columns.map((c) => el("td", { class: c.class || null }, c.cell(row)))));
  }
  return el("div", { class: "table-wrap" }, el("table", { class: "grid" }, thead, tbody));
}

export function pre(value) {
  return el("pre", null, typeof value === "string" ? value : JSON.stringify(value, null, 2));
}
