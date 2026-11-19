/**
 * QIBO 多图载入节点 - 前端业务逻辑
 *
 * 移植自 TaiYang_MultiImage，去掉画布自绘部分，只保留 DOM 面板模式。
 * 支持从 input 和 output 目录读取图片（output/ 前缀标识）。
 *
 * 自动连线：发现带 images / ref_images autogrow 组的节点时自动连接。
 * 开关控制：auto_link widget（"自动" / "关闭"）。
 */
import { app } from "/scripts/app.js";

const NODE_NAME = "QIBOMultiImageLoader";
const MAX_IMAGES = 16;

const AUTOGROW_GROUPS = ["images", "ref_images"];
const MODE_OPTIONS = ["自动", "关闭"];
const MODE_AUTO = 0;
const MODE_OFF = 1;

const UPSCALE_METHODS = ["nearest-exact", "bilinear", "area", "bicubic", "lanczos"];
const DEFAULT_STEPS = 32;

function staticCfgOf(node) {
  if (!node) return null;
  const names = (node.inputs || []).map((i) => i.name);
  if (names.length < 2) return null;
  return null;
}

function getWidget(node, name) {
  return node?.widgets?.find((w) => w.name === name) || null;
}

function isCollapsed(node) {
  return node?.flags?.collapsed === true || node?.collapsed === true;
}

function getMode(node) {
  const w = getWidget(node, "auto_link");
  if (!w) return MODE_AUTO;
  let val = w.value;
  if (typeof val === "string") {
    val = MODE_OPTIONS.indexOf(val);
    if (val === -1) val = MODE_AUTO;
  }
  return typeof val === "number" && val >= 0 && val < MODE_OPTIONS.length ? val : MODE_AUTO;
}

function getImageFiles(node) {
  const w = getWidget(node, "image_files");
  if (!w) return [];
  try {
    const parsed = JSON.parse(w.value || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x) => typeof x === "string" && x.length > 0);
  } catch {
    return [];
  }
}

function getMegapixels(node) {
  const w = getWidget(node, "megapixels");
  const v = Number(w?.value);
  return Number.isFinite(v) && v > 0 ? v : 0;
}

function setMegapixels(node, mp) {
  const w = getWidget(node, "megapixels");
  if (w) w.value = clampMegapixels(mp);
  node.setDirtyCanvas?.(true, true);
}

function getUpscaleMethod(node) {
  const w = getWidget(node, "upscale_method");
  return w?.value || "bilinear";
}

function setUpscaleMethod(node, m) {
  const w = getWidget(node, "upscale_method");
  if (w) w.value = m;
  node.setDirtyCanvas?.(true, true);
}

function getResolutionSteps(node) {
  const w = getWidget(node, "resolution_steps");
  const v = Math.round(Number(w?.value));
  if (Number.isFinite(v) && v >= 1) return v;
  if (w) w.value = DEFAULT_STEPS;
  return DEFAULT_STEPS;
}

function setResolutionSteps(node, n) {
  const w = getWidget(node, "resolution_steps");
  const v = Math.round(Number(n));
  if (w) w.value = Number.isFinite(v) && v >= 1 ? v : DEFAULT_STEPS;
  node.setDirtyCanvas?.(true, true);
}

function clampMegapixels(mp) {
  const v = Number(mp);
  if (!Number.isFinite(v) || v < 0) return 0;
  return Math.min(v, 16);
}

function trimNum(v) {
  if (!Number.isFinite(v)) return String(v);
  return String(Math.round(v * 1000) / 1000);
}

function scaledSize(natW, natH, megapixels, resolutionSteps = DEFAULT_STEPS) {
  if (!natW || !natH || megapixels <= 0) return [natW, natH];
  const total = megapixels * 1024 * 1024;
  const scaleBy = Math.sqrt(total / (natW * natH));
  const steps = Math.max(1, Math.round(resolutionSteps) || 1);
  const w = Math.max(steps, Math.round((natW * scaleBy) / steps) * steps);
  const h = Math.max(steps, Math.round((natH * scaleBy) / steps) * steps);
  return [w, h];
}

function viewUrl(name) {
  if (name.startsWith("output/")) {
    return `/api/view?filename=${encodeURIComponent(name.slice(7))}&type=output`;
  }
  return `/api/view?filename=${encodeURIComponent(name)}&type=input`;
}

function makeThumb(name) {
  const img = new Image();
  img.src = viewUrl(name);
  return img;
}

function reorderList(list, from, to) {
  const next = list.slice();
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

function setImages(node, files) {
  const list = files.slice(0, MAX_IMAGES);
  const w = getWidget(node, "image_files");
  if (w) w.value = JSON.stringify(list);
  node._qiboImages = list.slice();
  node._qiboImgCache = {};
  list.forEach((name, i) => {
    node._qiboImgCache[i] = makeThumb(name);
  });
  node.setDirtyCanvas(true, true);
}

function growOutputSlots(node, count) {
  if (typeof node.addOutput !== "function") return;
  const target = Math.max(1, Math.min(count, MAX_IMAGES));
  try {
    while (node.outputs.length < target) {
      const idx = node.outputs.length;
      node.addOutput(`image_${idx + 1}`, "IMAGE");
    }
  } catch (e) {
    console.warn("[QIBOMultiImage] 扩展输出槽失败", e);
  }
}

function syncOutputSlots(node, count) {
  if (typeof node.addOutput !== "function" || typeof node.removeOutput !== "function") return;
  const want = Math.max(1, Math.min(count, MAX_IMAGES));
  const linked = (node.outputs || []).filter((o) => (o.links || []).length > 0).length;
  const target = Math.max(want, linked);
  growOutputSlots(node, target);
  try {
    while (node.outputs.length > target) {
      node.removeOutput(node.outputs.length - 1);
    }
  } catch (e) {
    console.warn("[QIBOMultiImage] 调整输出槽失败", e);
  }
  node.setDirtyCanvas?.(true, true);
}

function getLink(graph, id) {
  if (!graph || id == null) return null;
  const links = graph.links;
  if (!links) return null;
  if (typeof links.get === "function") return links.get(id) ?? null;
  return links[id] ?? null;
}

function targetIdOf(link) {
  return link?.target_id ?? link?.targetNode?.id ?? null;
}

function findImageAutogrow(node, onlyGroups = null) {
  const ag = node?.comfyDynamic?.autogrow;
  if (!ag) return null;
  const wanted = onlyGroups && onlyGroups.length ? onlyGroups : AUTOGROW_GROUPS;
  for (const prefix of wanted) {
    const info = ag[prefix];
    if (!info) continue;
    const specs = info?.inputSpecs || [];
    if (!specs.length) continue;
    if (!specs.some((s) => String(s.type).toUpperCase().includes("IMAGE"))) continue;
    return { prefix, info };
  }
  return null;
}

function isGroupSlot(groupPrefix, fullName) {
  return typeof fullName === "string" && fullName.startsWith(groupPrefix + ".");
}

function slotLocalName(groupPrefix, info, ordinal) {
  const names = info?.names;
  if (Array.isArray(names) && names.length) {
    return names[ordinal] ?? `${info?.inputSpecs?.[0]?.name ?? "image"}_${ordinal + 1}`;
  }
  const p = info?.prefix;
  const base = typeof p === "string" && p.length
    ? p
    : `${(info?.inputSpecs?.[0]?.name ?? groupPrefix)}_`;
  const start = (info?.min ?? 0) > 0 ? info.min : 0;
  return `${base}${start + ordinal}`;
}

function slotTailNumber(groupPrefix, fullName) {
  if (!isGroupSlot(groupPrefix, fullName)) return null;
  const m = fullName.slice(groupPrefix.length + 1).match(/(\d+)$/);
  return m ? parseInt(m[1], 10) : null;
}

function findAutogrowSlot(node, groupPrefix, info, ordinal) {
  const want = `${groupPrefix}.${slotLocalName(groupPrefix, info, ordinal)}`;
  for (let i = 0; i < node.inputs.length; i++) {
    if (node.inputs[i].name === want) return i;
  }
  return -1;
}

function findLastAutogrowSlot(node, groupPrefix) {
  for (let i = node.inputs.length - 1; i >= 0; i--) {
    if (isGroupSlot(groupPrefix, node.inputs[i].name)) return i;
  }
  return -1;
}

function ensureAutogrowInput(node, groupPrefix, info, ordinal) {
  return findAutogrowSlot(node, groupPrefix, info, ordinal);
}

function linksIntoSlot(graph, nodeId, slotIndex) {
  const out = [];
  const links = graph?.links;
  if (!links) return out;
  const visit = (l) => {
    if (!l) return;
    const tid = l.target_id ?? l.targetNode?.id;
    const ts = l.target_slot ?? l.targetSlot;
    if (tid === nodeId && ts === slotIndex) out.push(l);
  };
  if (typeof links.forEach === "function") {
    links.forEach((v, k) => visit(v ?? (typeof links.get === "function" ? links.get(k) : null)));
  } else {
    for (const k in links) visit(links[k]);
  }
  return out;
}

function removeLinkHard(graph, link) {
  if (!graph || !link) return false;
  let gone = false;
  try {
    if (typeof link.disconnect === "function") {
      link.disconnect(graph);
      gone = getLink(graph, link.id) == null;
    }
  } catch (e) { }
  if (!gone) {
    try {
      if (typeof graph.removeLink === "function") {
        graph.removeLink(link);
        gone = getLink(graph, link.id) == null;
      }
    } catch (e) { }
  }
  if (!gone) {
    try {
      if (typeof graph.links?.delete === "function") graph.links.delete(link.id);
      else if (graph.links) delete graph.links[link.id];
      graph.incrementVersion?.();
      gone = true;
    } catch (e) {
      console.warn("[QIBOMultiImage] 清理残留连线失败", e);
    }
  }
  if (!gone) return false;
  const origin = graph.getNodeById?.(link.origin_id);
  const target = graph.getNodeById?.(link.target_id);
  const strip = (arr) => {
    if (!Array.isArray(arr)) return;
    const at = arr.indexOf(link.id);
    if (at !== -1) arr.splice(at, 1);
  };
  strip(origin?.outputs?.[link.origin_slot]?.links);
  const tin = target?.inputs?.[link.target_slot];
  if (tin && (tin.link === link.id || tin.link == null)) tin.link = null;
  return true;
}

function disconnectSlot(node, slotIndex) {
  const graph = node.graph || app.graph;
  const inp = node.inputs?.[slotIndex];
  if (!graph || !inp) return;
  const doomed = linksIntoSlot(graph, node.id, slotIndex);
  if (typeof node.disconnectInput === "function") {
    try {
      node.disconnectInput(slotIndex, true);
    } catch (e) {
      console.warn("[QIBOMultiImage] 断开失败", e);
    }
  }
  for (const link of doomed) {
    if (getLink(graph, link.id)) removeLinkHard(graph, link);
  }
  if (inp.link != null && !getLink(graph, inp.link)) inp.link = null;
  node.setDirtyCanvas?.(true, true);
}

function pruneGroupLinks(loader, target, prefix, info) {
  const graph = target.graph || app.graph;
  if (!graph) return 0;
  let removed = 0;
  for (let i = 0; i < target.inputs.length; i++) {
    const inp = target.inputs[i];
    if (!isGroupSlot(prefix, inp.name)) continue;
    const links = linksIntoSlot(graph, target.id, i);
    if (links.length <= 1) continue;
    const ord = ordinalOfSlot(prefix, info, inp.name);
    let keeper = links[links.length - 1];
    if (ord != null) {
      const exact = links.find((l) => l.origin_id === loader.id && l.origin_slot === ord);
      if (exact) keeper = exact;
    }
    for (const l of links) {
      if (l === keeper) continue;
      if (removeLinkHard(graph, l)) removed++;
    }
  }
  if (removed) {
    console.warn(`[QIBOMultiImage] 清理了 ${removed} 条残留连线`);
    target.setDirtyCanvas?.(true, true);
  }
  return removed;
}

function enforceGroupLinks(loader, target, prefix, info, cap) {
  const graph = target.graph || app.graph;
  const links = graph?.links;
  if (!links) return 0;
  const bad = [];
  const visit = (l) => {
    if (!l) return;
    if ((l.origin_id ?? null) !== loader.id) return;
    if ((l.target_id ?? null) !== target.id) return;
    const slot = target.inputs?.[l.target_slot];
    if (!slot || !isGroupSlot(prefix, slot.name)) return;
    const ord = ordinalOfSlot(prefix, info, slot.name);
    if (ord === null) return;
    if (ord >= cap || l.origin_slot !== ord) {
      bad.push({ link: l, ord, out: l.origin_slot, name: slot.name });
    }
  };
  if (typeof links.forEach === "function") {
    links.forEach((v, k) => visit(v ?? links.get?.(k)));
  } else {
    for (const k in links) visit(links[k]);
  }
  let removed = 0;
  for (const it of bad) {
    if (removeLinkHard(graph, it.link)) removed++;
  }
  if (removed) {
    console.warn(`[QIBOMultiImage] 清理了 ${removed} 条错位连线`);
    target.setDirtyCanvas?.(true, true);
  }
  return removed;
}

function pruneDanglingOutputLinks(node) {
  const graph = node.graph || app.graph;
  const links = graph?.links;
  if (!links) return 0;
  const n = (node.outputs || []).length;
  const bad = [];
  const visit = (l) => {
    if (!l) return;
    if ((l.origin_id ?? null) !== node.id) return;
    if ((l.origin_slot ?? 0) >= n) bad.push(l);
  };
  if (typeof links.forEach === "function") {
    links.forEach((v, k) => visit(v ?? links.get?.(k)));
  } else {
    for (const k in links) visit(links[k]);
  }
  let removed = 0;
  for (const l of bad) {
    if (removeLinkHard(graph, l)) removed++;
  }
  if (removed) {
    console.warn(`[QIBOMultiImage] 清理了 ${removed} 条悬空连线`);
  }
  return removed;
}

function ordinalOfSlot(groupPrefix, info, fullName) {
  if (!isGroupSlot(groupPrefix, fullName)) return null;
  const names = info?.names;
  if (Array.isArray(names) && names.length) {
    const local = fullName.slice(groupPrefix.length + 1);
    const i = names.indexOf(local);
    if (i !== -1) return i;
  }
  const local = fullName.slice(groupPrefix.length + 1);
  for (let ord = 0; ord < (info?.max ?? 16) + 1; ord++) {
    if (slotLocalName(groupPrefix, info, ord) === local) return ord;
  }
  return null;
}

function connectSlot(srcNode, outSlot, dstNode, dstSlotIndex) {
  const inp = dstNode.inputs?.[dstSlotIndex];
  if (!inp || !srcNode.outputs?.[outSlot]) return false;
  const graph = srcNode.graph || app.graph;
  const existing = linksIntoSlot(graph, dstNode.id, dstSlotIndex);
  if (existing.length) {
    const sameOrigin =
      existing.length === 1 &&
      (existing[0].origin_id ?? null) === srcNode.id &&
      (existing[0].origin_slot ?? null) === outSlot;
    if (sameOrigin) return true;
    disconnectSlot(dstNode, dstSlotIndex);
  }
  if (typeof srcNode.connect === "function") {
    try {
      srcNode.connect(outSlot, dstNode, dstSlotIndex);
      if (inp.link != null) return true;
    } catch (e) {
      console.warn("[QIBOMultiImage] connect 失败", e);
    }
  }
  if (typeof srcNode.connectSlots === "function") {
    try {
      srcNode.connectSlots(srcNode.outputs[outSlot], inp, dstNode);
      if (inp.link != null) return true;
    } catch (e) {
      console.warn("[QIBOMultiImage] connectSlots 失败", e);
    }
  }
  console.warn("[QIBOMultiImage] 建链未生效", outSlot, "->", dstNode.type, inp.name);
  return false;
}

function growAutogrowByReconnect(loader, target, groupPrefix) {
  const graph = target.graph || app.graph;
  if (!graph) return false;
  const before = findLastAutogrowSlot(target, groupPrefix);
  if (before === -1) return false;
  const links = linksIntoSlot(graph, target.id, before);
  if (!links.length) return false;
  const link = links.find((l) => (l.origin_id ?? null) === loader.id);
  if (!link) return false;
  const src = graph.getNodeById?.(link.origin_id);
  if (!src) return false;
  const outSlot = link.origin_slot;
  disconnectSlot(target, before);
  connectSlot(src, outSlot, target, before);
  return findLastAutogrowSlot(target, groupPrefix) > before;
}

function collectTargets(node) {
  const graph = node.graph || app.graph;
  if (!graph) return [];
  const mode = getMode(node);
  if (mode === MODE_OFF) return [];
  const manual = node._qiboManualTarget || null;
  let candidates;
  if (manual) {
    candidates = (graph._nodes || []).filter((n) => n.type === manual);
  } else if (mode === MODE_AUTO) {
    candidates = (graph._nodes || []).filter(
      (n) => n.type !== NODE_NAME && (findImageAutogrow(n) || staticCfgOf(n))
    );
  } else {
    const type = MODE_OPTIONS[mode];
    candidates = (graph._nodes || []).filter((n) => n.type === type);
  }
  if (candidates.length === 0) return [];
  const linked = new Set();
  for (const out of node.outputs || []) {
    for (const lid of out.links || []) {
      const link = getLink(graph, lid);
      const tid = targetIdOf(link);
      if (tid != null) linked.add(tid);
    }
  }
  return [...candidates].sort((a, b) => Number(linked.has(b.id)) - Number(linked.has(a.id)));
}

function syncOneTarget(node, target, count) {
  const graph = node.graph || app.graph;
  if (!graph) return;
  const ag = findImageAutogrow(target);
  if (!ag) return;
  const { prefix, info } = ag;
  const cap = Math.min(count, info?.max ?? MAX_IMAGES, MAX_IMAGES);
  pruneGroupLinks(node, target, prefix, info);
  let missing = 0;
  for (let i = 0; i < cap; i++) {
    let idx = ensureAutogrowInput(target, prefix, info, i);
    if (idx === -1) {
      if (growAutogrowByReconnect(node, target, prefix)) {
        idx = ensureAutogrowInput(target, prefix, info, i);
      }
      if (idx === -1) {
        missing++;
        continue;
      }
    }
    connectSlot(node, i, target, idx);
  }
  const snapshot = target.inputs.slice();
  for (const inp of snapshot) {
    if (!isGroupSlot(prefix, inp.name)) continue;
    const ord = ordinalOfSlot(prefix, info, inp.name);
    if (ord === null || ord < cap) continue;
    const idx = target.inputs.indexOf(inp);
    if (idx !== -1) disconnectSlot(target, idx);
  }
  if (missing > 0) markRetry(node);
  target.setDirtyCanvas?.(true, true);
}

function syncConnections(node, opts = {}) {
  if (!opts.force && graphBusy()) {
    node.__qiboNeedSettle = true;
    return;
  }
  const files = getImageFiles(node);
  if (files.length === 0) {
    const graph = node.graph || app.graph;
    const targets = collectTargets(node);
    for (const t of targets) {
      const ag = findImageAutogrow(t);
      for (const inp of t.inputs?.slice() || []) {
        const isAutoSlot = ag && isGroupSlot(ag.prefix, inp.name);
        if (!isAutoSlot) continue;
        const idx = t.inputs.indexOf(inp);
        if (idx === -1) continue;
        const mine = linksIntoSlot(graph, t.id, idx).some(
          (l) => (l.origin_id ?? null) === node.id
        );
        if (mine || inp.link != null) disconnectSlot(t, idx);
      }
    }
    syncOutputSlots(node, 1);
    return;
  }
  const targets = collectTargets(node);
  if (targets.length === 0) {
    syncOutputSlots(node, files.length);
    markRetry(node);
    return;
  }
  growOutputSlots(node, files.length);
  const before = node._retryCount || 0;
  for (const t of targets) syncOneTarget(node, t, files.length);
  if ((node._retryCount || 0) === before) clearRetry(node);
  syncOutputSlots(node, files.length);
}

function syncAllLoaders() {
  const graph = app.graph;
  if (!graph) return;
  if (graphBusy()) {
    scheduleSettle();
    return;
  }
  for (const n of graph._nodes || []) {
    if (n.type !== NODE_NAME) continue;
    if (getImageFiles(n).length === 0) continue;
    syncConnections(n);
  }
}

const RETRY_DELAYS = [120, 400, 1000, 2200, 4000];
const RETRY_MAX = RETRY_DELAYS.length;

function markRetry(node) {
  if (!node) return;
  if ((node._retryCount || 0) >= RETRY_MAX) return;
  node._retryCount = (node._retryCount || 0) + 1;
  const n = node._retryCount;
  setTimeout(() => {
    const g = app?.graph;
    if (!g || !(g._nodes || []).includes(node)) return;
    if (getImageFiles(node).length === 0) return;
    if (graphBusy()) {
      node._retryCount = Math.max(0, n - 1);
      scheduleSettle();
      return;
    }
    syncConnections(node);
  }, RETRY_DELAYS[n - 1] || RETRY_DELAYS[RETRY_DELAYS.length - 1]);
}

function clearRetry(node) {
  if (node) node._retryCount = 0;
}

let graphLoadDepth = 0;
let loadWatchdog = null;

function graphBusy() {
  return graphLoadDepth > 0;
}

function beginGraphLoad() {
  graphLoadDepth++;
  if (loadWatchdog) clearTimeout(loadWatchdog);
  loadWatchdog = setTimeout(() => {
    loadWatchdog = null;
    if (graphLoadDepth > 0) {
      console.warn("[QIBOMultiImage] 未收到载入结束信号，强制解除载入保护");
      graphLoadDepth = 0;
    }
    scheduleSettle();
  }, 15000);
}

function endGraphLoad() {
  graphLoadDepth = Math.max(0, graphLoadDepth - 1);
  if (graphLoadDepth === 0) {
    if (loadWatchdog) {
      clearTimeout(loadWatchdog);
      loadWatchdog = null;
    }
    scheduleSettle();
  }
}

let settleTimer = null;
let settlePass = 0;

function scheduleSettle() {
  if (settleTimer) clearTimeout(settleTimer);
  settlePass = 0;
  const NEXT = [260, 900, 2200];
  const step = () => {
    settleTimer = null;
    if (graphBusy()) return;
    const g = app?.graph;
    if (!g) return;
    for (const n of g._nodes || []) {
      if (n.type !== NODE_NAME) continue;
      try {
        settleLoader(n);
      } catch (e) {
        console.warn("[QIBOMultiImage] 载入后收口失败", e);
      }
    }
    settlePass++;
    if (settlePass < NEXT.length + 1) {
      settleTimer = setTimeout(step, NEXT[settlePass - 1] ?? 900);
    }
  };
  settleTimer = setTimeout(step, 50);
}

function settleLoader(node) {
  const graph = node.graph || app.graph;
  if (!graph) return;
  if (!(graph._nodes || []).includes(node)) return;
  const files = getImageFiles(node);
  const sweep = () => {
    for (const t of collectTargets(node)) {
      const ag = findImageAutogrow(t);
      if (!ag) continue;
      const cap = Math.min(files.length, ag.info?.max ?? MAX_IMAGES, MAX_IMAGES);
      enforceGroupLinks(node, t, ag.prefix, ag.info, cap);
    }
    pruneDanglingOutputLinks(node);
  };
  sweep();
  if (files.length === 0) return;
  syncConnections(node, { force: true });
  sweep();
}

async function uploadOne(file, uploadType = "input") {
  const fd = new FormData();
  fd.append("image", file);
  fd.append("type", uploadType);
  const res = await fetch("/upload/image", { method: "POST", body: fd });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  const name = data.subfolder ? `${data.subfolder}/${data.name}` : data.name;
  return uploadType === "output" ? `output/${name}` : name;
}

app.registerExtension({
  name: "ComfyUI.QIBOMultiImageLoader",

  beforeConfigureGraph() {
    beginGraphLoad();
  },

  afterConfigureGraph() {
    endGraphLoad();
  },

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE_NAME) {
      const origTargetCreated = nodeType.prototype.onNodeCreated;
      nodeType.prototype.onNodeCreated = function () {
        const r = origTargetCreated ? origTargetCreated.apply(this, arguments) : undefined;
        setTimeout(() => {
          if (findImageAutogrow(this) || staticCfgOf(this)) syncAllLoaders();
        }, 80);
        return r;
      };
      return;
    }

    const origCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = origCreated ? origCreated.apply(this, arguments) : undefined;
      this._qiboImages = [];
      this._qiboImgCache = {};
      syncOutputSlots(this, getImageFiles(this).length || 1);

      const modeWidget = getWidget(this, "auto_link");
      if (modeWidget && typeof modeWidget.value === "number" && !MODE_OPTIONS[modeWidget.value]) {
        modeWidget.value = MODE_AUTO;
      }

      const hideWidget = (w) => {
        if (!w) return;
        w.dontHide = true;
        w.hidden = true;
        w.computeSize = () => [0, 0];
        w.draw = () => {};
      };
      hideWidget(getWidget(this, "image_files"));
      hideWidget(getWidget(this, "upscale_method"));
      hideWidget(getWidget(this, "megapixels"));
      hideWidget(getWidget(this, "resolution_steps"));
      hideWidget(modeWidget);

      return r;
    };

    const origConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r = origConfigure ? origConfigure.apply(this, arguments) : undefined;
      const w = getWidget(this, "image_files");
      if ((!w || !w.value || w.value === "[]") && this.properties?.image_files) {
        if (w) w.value = this.properties.image_files;
      }
      this._qiboManualTarget = this.properties?.auto_link_target || null;
      const files = getImageFiles(this);
      this._qiboImages = files.slice();
      this._qiboImgCache = {};
      files.forEach((name, i) => {
        this._qiboImgCache[i] = makeThumb(name);
      });
      if (!graphBusy()) {
        const linkedCount = (this.outputs || []).filter((o) => (o.links || []).length > 0).length;
        syncOutputSlots(this, Math.max(files.length, linkedCount));
      }
      this._retryCount = 0;
      if (graphBusy()) {
        this.__qiboNeedSettle = true;
      } else {
        syncConnections(this);
      }
      return r;
    };

    const origSerialize = nodeType.prototype.onSerialize;
    nodeType.prototype.onSerialize = function () {
      if (this.properties) {
        this.properties.image_files = getWidget(this, "image_files")?.value ?? "[]";
        if (this._qiboManualTarget) this.properties.auto_link_target = this._qiboManualTarget;
        else delete this.properties.auto_link_target;
      }
      return origSerialize ? origSerialize.apply(this, arguments) : this;
    };

    const origMenu = nodeType.prototype.getNodeMenuItems;
    nodeType.prototype.getNodeMenuItems = function (opts) {
      const items = origMenu ? origMenu.apply(this, arguments) : [];
      const graph = this.graph || app.graph;
      const present = [...new Set((graph?._nodes || []).map((n) => n.type))].filter(
        (t) => t && t !== NODE_NAME
      );
      const capable = present.filter((t) => {
        const n = (graph._nodes || []).find((x) => x.type === t);
        return n && (findImageAutogrow(n) || staticCfgOf(n));
      });

      items.push({
        content: "🔗 重新自动连线",
        callback: () => {
          syncConnections(this);
          this.setDirtyCanvas(true, true);
        },
      });

      const curMp = getMegapixels(this);
      items.push({
        content: `🔍 缩放：输入百万像素（当前：${curMp > 0 ? `${trimNum(curMp)} MP` : "关闭"}）`,
        callback: () => {
          const v = promptNumber("缩放：输入目标百万像素（0 = 关闭缩放）", curMp, { min: 0, max: 16 });
          if (v == null) return;
          setMegapixels(this, v);
        },
      });
      items.push({
        content: "⏹ 关闭缩放（保持原分辨率）",
        callback: () => setMegapixels(this, 0),
      });

      if (capable.length) {
        const pickTarget = (node, type) => {
          node._qiboManualTarget = type;
          syncConnections(node);
          node.setDirtyCanvas(true, true);
        };
        const backToAuto = (node) => {
          node._qiboManualTarget = null;
          syncConnections(node);
          node.setDirtyCanvas(true, true);
        };
        items.push({
          content: `🎯 指定多图目标${this._qiboManualTarget ? `（当前：${this._qiboManualTarget}）` : ""}`,
          callback: () => items.push(
            ...capable.map((t) => ({
              content: `　→ ${t}${this._qiboManualTarget === t ? "  ✓当前" : ""}`,
              callback: () => pickTarget(this, t),
            })),
            { content: "　↩ 回到自动发现", callback: () => backToAuto(this) }
          ),
        });
      }
      if (this._qiboManualTarget) {
        items.push({
          content: "↩ 目标改回自动发现",
          callback: () => {
            this._qiboManualTarget = null;
            syncConnections(this);
            this.setDirtyCanvas(true, true);
          },
        });
      }
      items.push({
        content: "⛓ 断开本节点的全部连线",
        callback: () => {
          const graph = this.graph || app.graph;
          for (const out of this.outputs || []) {
            for (const lid of [...(out.links || [])]) {
              const link = getLink(graph, lid);
              if (!link) continue;
              const tid = targetIdOf(link);
              const tnode = tid != null ? graph.getNodeById(tid) : null;
              if (tnode && tnode.inputs) {
                const idx = tnode.inputs.findIndex((x) => x.link === lid);
                if (idx !== -1) disconnectSlot(tnode, idx);
              }
            }
          }
          this.setDirtyCanvas(true, true);
        },
      });
      return items;
    };
  },
});

function promptNumber(title, current, { min, max }) {
  const msg = `${title}\n当前：${current}`;
  const raw = window.prompt(msg, String(current));
  if (raw == null) return null;
  const trimmed = String(raw).trim();
  if (trimmed === "") return null;
  let v = Number(trimmed);
  if (!Number.isFinite(v)) {
    window.alert("输入的不是有效数字，已取消修改。");
    return null;
  }
  if (v < min) v = min;
  if (v > max) v = max;
  return v;
}

export {
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
  beginGraphLoad,
  endGraphLoad,
  graphBusy,
  scheduleSettle,
  settleLoader,
  enforceGroupLinks,
  pruneDanglingOutputLinks,
};