/**
 * QIBO 多图载入节点 - DOM 面板
 *
 * 移植自 TaiYang_MultiImage 的 multi_image_dom.js。
 * 网格展示、拖拽排序、上传、删除、缩放参数控件。
 * 新增：支持从 output 目录浏览和上传图片。
 */
import { app } from "/scripts/app.js";
import {
  MAX_IMAGES,
  MODE_OPTIONS,
  UPSCALE_METHODS,
  DEFAULT_STEPS,
  getWidget,
  getImageFiles,
  setImages,
  getMode,
  getMegapixels,
  setMegapixels,
  getUpscaleMethod,
  setUpscaleMethod,
  getResolutionSteps,
  setResolutionSteps,
  uploadOne,
  syncConnections,
  reorderList,
  scaledSize,
  viewUrl,
} from "./qibo_multi_image.js";

const NODE_NAME = "QIBOMultiImageLoader";

const CELL = 130;
const GAP = 10;
const COLS = 4;
const MIN_NODE_W = 560;
const TOP_H = 24;
const CTRL_H = 56;
const PAD = 12;
const VGAP = 8;

const STYLE_ID = "qibo-mi-style";
const POLL_MS = 600;

function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const s = document.createElement("style");
  s.id = STYLE_ID;
  s.textContent = `
.qibo-mi {
  display: flex; flex-direction: column; gap: ${VGAP}px;
  width: 100%; height: 100%; box-sizing: border-box; padding: 6px;
  border-radius: 8px; background: #17181c;
  box-shadow: inset 0 0 0 1px #2c2e36;
  user-select: none; -webkit-user-select: none;
  font-family: inherit;
}
.qibo-mi-top { display: flex; align-items: center; gap: 8px; height: ${TOP_H}px; flex: 0 0 ${TOP_H}px; }
.qibo-mi-title { font-size: 12px; font-weight: 600; color: #8fd0ff; letter-spacing: .2px; }
.qibo-mi-link { font-size: 11.5px; color: #9aa0ab; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.qibo-mi-link.ok { color: #8fe08f; }
.qibo-mi-link.warn { color: #ffd479; }
.qibo-mi-spacer { flex: 1 1 auto; min-width: 0; }

.qibo-mi-grid {
  display: grid; grid-template-columns: repeat(${COLS}, ${CELL}px);
  gap: ${GAP}px; justify-content: center; align-content: start;
  flex: 0 0 auto;
}
.qibo-mi-cell {
  position: relative; width: ${CELL}px; height: ${CELL}px;
  border-radius: 6px; background: #0f1013; overflow: hidden;
  box-shadow: inset 0 0 0 1px #2b2e35;
}
.qibo-mi-cell img { width: 100%; height: 100%; object-fit: cover; display: block; }
.qibo-mi-cell.has { cursor: grab; }
.qibo-mi-cell.has:active { cursor: grabbing; }
.qibo-mi-cell.empty { background: #121316; box-shadow: inset 0 0 0 1px #24262c; }
.qibo-mi-cell.add {
  display: flex; align-items: center; justify-content: center; cursor: pointer;
  background: #141519; box-shadow: inset 0 0 0 1px #30333b;
  color: #5c636e; font-size: 26px; font-weight: 300; line-height: 1;
}
.qibo-mi-cell.add:hover { background: #17202a; color: #8fd0ff; box-shadow: inset 0 0 0 1px #3f6f95; }
.qibo-mi-cell.add.off { cursor: not-allowed; opacity: .45; }
.qibo-mi-cell.dragging { opacity: .4; }
.qibo-mi-cell.over { box-shadow: inset 0 0 0 2px #8fd0ff; }
.qibo-mi-idx {
  position: absolute; left: 6px; top: 5px; padding: 1px 5px; border-radius: 4px;
  font-size: 10.5px; line-height: 14px; color: #cfd3db;
  background: rgba(8,9,12,.72);
}
.qibo-mi-size {
  position: absolute; left: 5px; bottom: 4px; padding: 1px 5px; border-radius: 4px;
  font-size: 10px; line-height: 13px; color: #d6e4f0;
  background: rgba(8,9,12,.72); font-variant-numeric: tabular-nums;
}
.qibo-mi-src {
  position: absolute; right: 4px; bottom: 4px; padding: 1px 4px; border-radius: 3px;
  font-size: 9px; line-height: 12px; color: #8fd0ff;
  background: rgba(8,9,12,.72);
}
.qibo-mi-src.out { color: #ffd479; }
.qibo-mi-del {
  position: absolute; right: 4px; top: 4px; width: 18px; height: 18px;
  padding: 0; border: none; border-radius: 50%; cursor: pointer;
  background: rgba(8,9,12,.78); color: #dfe2e8;
  font-size: 13px; line-height: 18px; text-align: center;
  opacity: 0; transition: opacity .12s;
}
.qibo-mi-cell.has:hover .qibo-mi-del { opacity: 1; }
.qibo-mi-del:hover { background: #a33; color: #fff; }

.qibo-mi-ctrl { display: flex; flex-direction: column; gap: 6px; flex: 0 0 auto; }
.qibo-mi-line { display: flex; align-items: center; gap: 6px; height: 24px; }
.qibo-mi-lb { font-size: 11px; color: #b7bcc7; white-space: nowrap; }
.qibo-mi-num {
  width: 54px; height: 22px; box-sizing: border-box; padding: 0 5px;
  border-radius: 4px; background: #1c1e24; color: #dfe2e8;
  font-size: 11px; font-family: inherit; text-align: right;
  border: 1px solid #2f323a; outline: none;
  -moz-appearance: textfield;
}
.qibo-mi-num::-webkit-outer-spin-button,
.qibo-mi-num::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.qibo-mi-num:focus { border-color: #6b7ce0; background: #22252d; color: #fff; box-shadow: 0 0 0 2px rgba(107,124,224,.18); }
.qibo-mi-unit { font-size: 10.5px; color: #6b7079; }
.qibo-mi-sel {
  flex: 1 1 0; min-width: 0; height: 24px; padding: 0 4px;
  border-radius: 4px; background: #23252c; color: #dfe2e8;
  font-size: 11px; font-family: inherit; border: 1px solid #34373f;
  outline: none; cursor: pointer;
}
.qibo-mi-sel:hover { border-color: #4a4e59; }
.qibo-mi-btn {
  flex: 0 0 auto; height: 24px; padding: 0 8px; box-sizing: border-box;
  border-radius: 4px; cursor: pointer; white-space: nowrap;
  font-size: 11px; font-family: inherit; line-height: 1;
  background: #262931; color: #cfd3db; border: 1px solid #353941;
}
.qibo-mi-btn:hover { background: #2e323b; border-color: #454a55; color: #fff; }
.qibo-mi-btn:active { transform: translateY(1px); }
.qibo-mi-btn.pri { border-color: #35506a; color: #b9ddf6; }
.qibo-mi-btn.pri:hover { border-color: #3f6f95; background: #1d2a36; color: #d7ecff; }
.qibo-mi-btn.danger:hover { border-color: #7a3d47; color: #f2c3c9; }
.qibo-mi-btn.toggle { min-width: 60px; text-align: center; }
.qibo-mi-btn.toggle.on { border-color: #3f6f95; background: #1d2a36; color: #d7ecff; }
`;
  document.head.appendChild(s);
}

function panelHeight(count) {
  const slots = Math.min(MAX_IMAGES, Math.max(COLS, count + 1));
  const rows = Math.ceil(slots / COLS);
  return PAD + TOP_H + VGAP + (rows * CELL + (rows - 1) * GAP) + VGAP + CTRL_H;
}

function linkedCount(node) {
  let n = 0;
  for (const out of node.outputs || []) {
    if ((out.links || []).length) n++;
  }
  return n;
}

function fitNode(node) {
  try {
    const w = Math.max(MIN_NODE_W, node.size?.[0] || 0);
    const h = node.computeSize ? node.computeSize(w)[1] : node.size?.[1];
    if (!h) return;
    if (Math.abs((node.size?.[0] || 0) - w) > 1 || Math.abs((node.size?.[1] || 0) - h) > 2) {
      node.setSize([w, h]);
    }
  } catch (_) { }
}

function build(node) {
  ensureStyle();

  const root = document.createElement("div");
  root.className = "qibo-mi";
  root.innerHTML = `
    <div class="qibo-mi-top">
      <span class="qibo-mi-title">参考图</span>
      <span class="qibo-mi-link"></span>
      <span class="qibo-mi-spacer"></span>
      <button type="button" class="qibo-mi-btn toggle qibo-mi-upsrc" title="切换上传目录">→ input</button>
      <button type="button" class="qibo-mi-btn danger qibo-mi-clear">清空</button>
    </div>
    <div class="qibo-mi-grid"></div>
    <div class="qibo-mi-ctrl">
      <div class="qibo-mi-line">
        <span class="qibo-mi-lb">缩放</span>
        <input type="number" class="qibo-mi-num qibo-mi-mp" step="0.1" min="0" max="16" title="目标总像素 = 数值 × 1024²，0 = 不缩放">
        <span class="qibo-mi-unit">MP</span>
        <span class="qibo-mi-lb">对齐</span>
        <input type="number" class="qibo-mi-num qibo-mi-steps" step="1" min="1" max="256" title="宽高对齐到该数字的整数倍">
      </div>
      <div class="qibo-mi-line">
        <select class="qibo-mi-sel qibo-mi-method" title="缩放插值算法"></select>
        <select class="qibo-mi-sel qibo-mi-mode" title="自动连线目标"></select>
        <button type="button" class="qibo-mi-btn pri qibo-mi-add">添加</button>
      </div>
    </div>`;

  const el = {
    root,
    title: root.querySelector(".qibo-mi-title"),
    link: root.querySelector(".qibo-mi-link"),
    clear: root.querySelector(".qibo-mi-clear"),
    upsrc: root.querySelector(".qibo-mi-upsrc"),
    grid: root.querySelector(".qibo-mi-grid"),
    mp: root.querySelector(".qibo-mi-mp"),
    steps: root.querySelector(".qibo-mi-steps"),
    method: root.querySelector(".qibo-mi-method"),
    mode: root.querySelector(".qibo-mi-mode"),
    add: root.querySelector(".qibo-mi-add"),
  };

  for (const m of UPSCALE_METHODS) {
    const o = document.createElement("option");
    o.value = m;
    o.textContent = m;
    el.method.appendChild(o);
  }
  for (let i = 0; i < MODE_OPTIONS.length; i++) {
    const o = document.createElement("option");
    o.value = String(i);
    o.textContent = MODE_OPTIONS[i];
    el.mode.appendChild(o);
  }

  const swallow = (e) => e.stopPropagation();
  for (const t of [root.querySelector(".qibo-mi-top"), root.querySelector(".qibo-mi-ctrl")]) {
    t.addEventListener("pointerdown", swallow);
    t.addEventListener("wheel", swallow, { passive: true });
  }
  el.grid.addEventListener("wheel", swallow, { passive: true });

  let uploadSource = "input";

  el.upsrc.addEventListener("click", () => {
    uploadSource = uploadSource === "input" ? "output" : "input";
    el.upsrc.textContent = `→ ${uploadSource}`;
    el.upsrc.classList.toggle("on", uploadSource === "output");
  });

  const pickFiles = () => {
    const files = getImageFiles(node);
    if (files.length >= MAX_IMAGES) return;
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.multiple = true;
    input.onchange = async () => {
      const picked = Array.from(input.files || []);
      if (!picked.length) return;
      const uploaded = [];
      for (const f of picked) {
        try {
          uploaded.push(await uploadOne(f, uploadSource));
        } catch (err) {
          console.error("[QIBOMultiImage] 上传失败:", f.name, err);
        }
      }
      if (!uploaded.length) return;
      const next = getImageFiles(node).concat(uploaded).slice(0, MAX_IMAGES);
      setImages(node, next);
      syncConnections(node);
      refresh(node, true);
    };
    input.click();
  };

  const insertAt = async (at, files) => {
    const uploaded = [];
    for (const f of files) {
      if (!/^image\//i.test(f.type) && !/\.(png|jpe?g|webp|bmp|gif|tiff?)$/i.test(f.name)) continue;
      try {
        uploaded.push(await uploadOne(f, uploadSource));
      } catch (err) {
        console.error("[QIBOMultiImage] 上传失败:", f.name, err);
      }
    }
    if (!uploaded.length) return;
    const list = getImageFiles(node).slice();
    const pos = Math.max(0, Math.min(at, list.length));
    list.splice(pos, 0, ...uploaded);
    setImages(node, list.slice(0, MAX_IMAGES));
    syncConnections(node);
    refresh(node, true);
  };

  el.add.addEventListener("click", () => {
    if (getImageFiles(node).length >= MAX_IMAGES) return;
    pickFiles();
  });
  el.clear.addEventListener("click", () => {
    if (!getImageFiles(node).length) return;
    setImages(node, []);
    syncConnections(node);
    refresh(node, true);
  });

  let dragFrom = -1;

  const cellAt = (e) => {
    const c = e.target?.closest?.(".qibo-mi-cell");
    if (!c) return -1;
    const i = Number(c.dataset.i);
    return Number.isFinite(i) ? i : -1;
  };

  el.grid.addEventListener("pointerdown", (e) => e.stopPropagation());

  el.grid.addEventListener("dragstart", (e) => {
    const i = cellAt(e);
    const files = getImageFiles(node);
    if (i < 0 || i >= files.length) {
      e.preventDefault();
      return;
    }
    dragFrom = i;
    e.dataTransfer.setData("text/plain", String(i));
    e.dataTransfer.effectAllowed = "move";
    e.target.classList.add("dragging");
  });

  el.grid.addEventListener("dragend", (e) => {
    dragFrom = -1;
    for (const c of el.grid.querySelectorAll(".dragging, .over")) {
      c.classList.remove("dragging", "over");
    }
  });

  el.grid.addEventListener("dragover", (e) => {
    e.preventDefault();
    const cell = e.target?.closest?.(".qibo-mi-cell");
    for (const c of el.grid.querySelectorAll(".over")) c.classList.remove("over");
    if (cell && !cell.classList.contains("empty")) cell.classList.add("over");
    e.dataTransfer.dropEffect = "move";
  });

  el.grid.addEventListener("dragleave", (e) => {
    const cell = e.target?.closest?.(".qibo-mi-cell");
    if (cell) cell.classList.remove("over");
  });

  el.grid.addEventListener("drop", async (e) => {
    e.preventDefault();
    for (const c of el.grid.querySelectorAll(".over, .dragging")) c.classList.remove("over", "dragging");

    const dropped = e.dataTransfer?.files;
    if (dropped && dropped.length) {
      const at = Math.max(0, Math.min(cellAt(e), getImageFiles(node).length));
      await insertAt(at, Array.from(dropped));
      return;
    }

    const files = getImageFiles(node);
    const from = dragFrom >= 0 ? dragFrom : Number(e.dataTransfer?.getData("text/plain"));
    const to = cellAt(e);
    dragFrom = -1;
    if (!Number.isFinite(from) || from < 0 || from >= files.length) return;
    if (to < 0 || to >= files.length || to === from) return;
    setImages(node, reorderList(files, from, to));
    syncConnections(node);
    refresh(node, true);
  });

  el.grid.addEventListener("click", (e) => {
    const i = cellAt(e);
    const files = getImageFiles(node);
    if (i < 0) return;

    if (e.target?.classList?.contains("qibo-mi-del")) {
      e.stopPropagation();
      const next = files.slice();
      next.splice(i, 1);
      setImages(node, next);
      syncConnections(node);
      refresh(node, true);
      return;
    }
    if (i === files.length) pickFiles();
  });

  el.grid.addEventListener("dblclick", (e) => {
    const i = cellAt(e);
    const files = getImageFiles(node);
    if (i < 0 || i >= files.length) return;
    window.open(viewUrl(files[i]), "_blank");
  });

  el.mp.addEventListener("change", () => {
    const v = Number(el.mp.value);
    setMegapixels(node, Number.isFinite(v) ? Math.max(0, Math.min(16, v)) : 0);
    refresh(node, false);
  });
  el.steps.addEventListener("change", () => {
    const v = Number(el.steps.value);
    setResolutionSteps(node, Number.isFinite(v) ? Math.max(1, Math.min(256, Math.round(v))) : DEFAULT_STEPS);
    refresh(node, false);
  });
  el.method.addEventListener("change", () => {
    setUpscaleMethod(node, el.method.value);
  });
  el.mode.addEventListener("change", () => {
    if (node._qiboManualTarget) {
      node._qiboManualTarget = null;
      if (node.properties) delete node.properties.auto_link_target;
    }
    const w = getWidget(node, "auto_link");
    if (w) w.value = MODE_OPTIONS[Number(el.mode.value)] ?? MODE_OPTIONS[0];
    syncConnections(node);
    refresh(node, false);
  });

  node.__qiboMiEl = el;
  return el;
}

function refresh(node, full = true) {
  const el = node.__qiboMiEl;
  if (!el) return;
  const files = getImageFiles(node);
  const linked = linkedCount(node);

  el.title.textContent = `参考图 ${files.length}/${MAX_IMAGES}`;
  el.link.textContent = files.length === 0
    ? "还没有图片，点「添加」或把图片拖进来"
    : linked >= files.length
      ? `✓ 已连接${node._qiboManualTarget ? " " + node._qiboManualTarget : ""}`
      : `还有 ${files.length - linked} 张未连接`;
  el.link.className = "qibo-mi-link"
    + (files.length === 0 ? "" : linked >= files.length ? " ok" : " warn");

  if (full) {
    const slots = Math.min(MAX_IMAGES, Math.max(COLS, Math.ceil((files.length + 1) / COLS) * COLS));
    el.grid.textContent = "";
    for (let i = 0; i < slots; i++) {
      const cell = document.createElement("div");
      cell.className = "qibo-mi-cell";
      cell.dataset.i = String(i);

      if (i < files.length) {
        cell.classList.add("has");
        cell.draggable = true;
        const isOutput = files[i].startsWith("output/");
        cell.title = `${files[i]}\n拖动可调顺序，双击看大图`;
        const img = document.createElement("img");
        img.src = viewUrl(files[i]);
        img.alt = files[i];
        img.draggable = false;
        const idx = document.createElement("span");
        idx.className = "qibo-mi-idx";
        idx.textContent = String(i + 1);
        const size = document.createElement("span");
        size.className = "qibo-mi-size";
        const src = document.createElement("span");
        src.className = "qibo-mi-src" + (isOutput ? " out" : "");
        src.textContent = isOutput ? "OUT" : "IN";
        const del = document.createElement("button");
        del.type = "button";
        del.className = "qibo-mi-del";
        del.textContent = "×";
        del.title = "移除这张";
        img.addEventListener("load", () => updateSizes(node));
        cell.append(img, idx, size, src, del);
      } else if (i === files.length) {
        cell.classList.add("add");
        if (files.length >= MAX_IMAGES) {
          cell.classList.add("off");
          cell.textContent = "满";
          cell.title = `最多 ${MAX_IMAGES} 张`;
        } else {
          cell.textContent = "＋";
          cell.title = "添加图片（可多选）";
        }
      } else {
        cell.classList.add("empty");
      }
      el.grid.appendChild(cell);
    }
    fitNode(node);
  }

  const mp = getMegapixels(node);
  if (document.activeElement !== el.mp) el.mp.value = mp > 0 ? String(mp) : "0";
  const steps = getResolutionSteps(node);
  if (document.activeElement !== el.steps) el.steps.value = String(steps);
  el.method.value = getUpscaleMethod(node);
  el.mode.value = String(getMode(node));
  el.add.disabled = files.length >= MAX_IMAGES;
  updateSizes(node);
}

function updateSizes(node) {
  const el = node.__qiboMiEl;
  if (!el) return;
  const mp = getMegapixels(node);
  const steps = getResolutionSteps(node);
  for (const cell of el.grid.querySelectorAll(".qibo-mi-cell.has")) {
    const img = cell.querySelector("img");
    const tag = cell.querySelector(".qibo-mi-size");
    if (!img || !tag) continue;
    const w0 = img.naturalWidth;
    const h0 = img.naturalHeight;
    if (!w0 || !h0) continue;
    const [w, h] = scaledSize(w0, h0, mp, steps);
    tag.textContent = `${w} × ${h}`;
  }
}

function signature(node) {
  return JSON.stringify([
    getImageFiles(node),
    linkedCount(node),
    node._qiboManualTarget || "",
    getMegapixels(node),
    getResolutionSteps(node),
    getUpscaleMethod(node),
    getMode(node),
    MAX_IMAGES,
  ]);
}

function watch(node) {
  if (node.__qiboMiTimer) clearInterval(node.__qiboMiTimer);
  node.__qiboMiSig = signature(node);
  node.__qiboMiFiles = JSON.stringify(getImageFiles(node));
  node.__qiboMiTimer = setInterval(() => {
    if (!node.__qiboMiEl) {
      clearInterval(node.__qiboMiTimer);
      node.__qiboMiTimer = 0;
      return;
    }
    const sig = signature(node);
    if (sig === node.__qiboMiSig) return;
    node.__qiboMiSig = sig;
    const filesSig = JSON.stringify(getImageFiles(node));
    const layoutChanged = filesSig !== node.__qiboMiFiles;
    node.__qiboMiFiles = filesSig;
    refresh(node, layoutChanged);
  }, POLL_MS);
}

app.registerExtension({
  name: "QIBO.MultiImage.DomPanel",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) return;

    const origCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = origCreated?.apply(this, arguments);
      const node = this;
      node.__qiboDomPanel = true;

      setTimeout(() => {
        if (node.__qiboMiEl) return;
        try {
          const el = build(node);
          node.addDOMWidget("multi_image_panel", "QIBO_MULTI_IMAGE", el.root, {
            serialize: false,
            hideOnZoom: false,
            getHeight: () => panelHeight(getImageFiles(node).length),
            getMinHeight: () => panelHeight(0),
            getMaxHeight: () => panelHeight(MAX_IMAGES),
          });
          refresh(node, true);
          watch(node);
        } catch (e) {
          node.__qiboDomPanel = false;
          console.error("[QIBOMultiImage] DOM 面板创建失败", e);
        }
      }, 0);

      return r;
    };

    const origConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r = origConfigure?.apply(this, arguments);
      const node = this;
      requestAnimationFrame(() => {
        if (!node.__qiboMiEl) return;
        refresh(node, true);
        node.__qiboMiSig = signature(node);
      });
      return r;
    };

    const origRemoved = nodeType.prototype.onRemoved;
    nodeType.prototype.onRemoved = function () {
      if (this.__qiboMiTimer) clearInterval(this.__qiboMiTimer);
      this.__qiboMiTimer = 0;
      this.__qiboMiEl = null;
      return origRemoved?.apply(this, arguments);
    };
  },
});