import { app } from "/scripts/app.js";

const NODE_TYPE = "QIBOModelMoveNode";

const COL_BG = "#1e1e1e";
const COL_FG = "#cccccc";
const COL_BORDER = "#3e3e42";
const COL_DIM = "#858585";
const FONT_CSS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif";

function fmtSize(bytes) {
    if (bytes == null || isNaN(bytes)) return "?";
    if (bytes < 1024) return bytes + "B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + "KB";
    if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + "MB";
    return (bytes / 1073741824).toFixed(2) + "GB";
}

let foldersCache = null;
async function fetchFolders() {
    if (foldersCache) return foldersCache;
    try {
        const r = await fetch("/qibo/model_folders");
        if (r.ok) {
            const j = await r.json();
            if (j.folders && j.folders.length > 0) {
                foldersCache = j.folders;
                return foldersCache;
            }
        }
    } catch (e) {}
    foldersCache = ["checkpoints", "diffusion_models", "loras", "text_encoders", "vae", "controlnet", "upscale_models"];
    return foldersCache;
}

async function fetchLocalModels() {
    const r = await fetch("/qibo/modelscope/list_local");
    const raw = await r.text();
    if (!r.ok) {
        const hint = r.status === 404 ? "（后端路由未注册，请重启 ComfyUI）" : "";
        return { __error: `HTTP ${r.status}: ${raw.slice(0, 200)}${hint}` };
    }
    try {
        return JSON.parse(raw);
    } catch (e) {
        return { __error: "响应不是 JSON: " + raw.slice(0, 200) };
    }
}

function showMoveDialog(node) {
    document.querySelectorAll(".qibo-move-overlay").forEach((el) => el.remove());
    const overlay = document.createElement("div");
    overlay.className = "qibo-move-overlay";
    overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:100000;display:flex;align-items:center;justify-content:center;font-family:" + FONT_CSS + ";";
    const dlg = document.createElement("div");
    dlg.style.cssText = `background:${COL_BG};color:${COL_FG};border:1px solid ${COL_BORDER};border-radius:8px;min-width:560px;max-width:860px;width:90%;max-height:82vh;display:flex;flex-direction:column;font-size:13px;box-shadow:0 8px 32px rgba(0,0,0,0.5);`;

    const title = document.createElement("div");
    title.textContent = "📁 本地模型管理 — 勾选模型，右键选目标目录，点「移动选中」";
    title.style.cssText = `padding:10px 14px;font-weight:bold;border-bottom:1px solid ${COL_BORDER};`;
    dlg.appendChild(title);

    const topRow = document.createElement("div");
    topRow.style.cssText = `padding:8px 14px;border-bottom:1px solid ${COL_BORDER};display:flex;align-items:center;gap:10px;`;
    const selAllCb = document.createElement("input");
    selAllCb.type = "checkbox";
    const selAllLabel = document.createElement("span");
    selAllLabel.textContent = "全选 / 取消全选";
    selAllLabel.style.cursor = "pointer";
    const refreshBtn = document.createElement("button");
    refreshBtn.textContent = "↻ 刷新";
    refreshBtn.style.cssText = `padding:3px 12px;border-radius:4px;border:1px solid ${COL_BORDER};background:${COL_BG};color:${COL_FG};cursor:pointer;font-size:12px;`;
    const hintSpan = document.createElement("span");
    hintSpan.style.cssText = `color:${COL_DIM};font-size:12px;flex:1;text-align:right;`;
    hintSpan.textContent = "";
    topRow.appendChild(selAllCb);
    topRow.appendChild(selAllLabel);
    topRow.appendChild(refreshBtn);
    topRow.appendChild(hintSpan);
    dlg.appendChild(topRow);

    const listEl = document.createElement("div");
    listEl.style.cssText = "overflow-y:auto;overflow-x:auto;padding:8px 14px;flex:1;";
    dlg.appendChild(listEl);

    const btnRow = document.createElement("div");
    btnRow.style.cssText = `padding:10px 14px;border-top:1px solid ${COL_BORDER};display:flex;gap:10px;justify-content:flex-end;align-items:center;`;
    const statusSpan = document.createElement("span");
    statusSpan.style.cssText = `flex:1;color:${COL_DIM};max-width:60%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;`;
    const cancelBtn = document.createElement("button");
    cancelBtn.textContent = "关闭";
    cancelBtn.style.cssText = `padding:6px 16px;border-radius:4px;border:1px solid ${COL_BORDER};background:${COL_BG};color:${COL_FG};cursor:pointer;font-size:13px;`;
    const moveBtn = document.createElement("button");
    moveBtn.textContent = "移动选中";
    moveBtn.style.cssText = "padding:6px 16px;border-radius:4px;border:1px solid #2e6da4;background:#337ab7;color:#fff;cursor:pointer;font-size:13px;";
    btnRow.appendChild(statusSpan);
    btnRow.appendChild(cancelBtn);
    btnRow.appendChild(moveBtn);
    dlg.appendChild(btnRow);

    overlay.appendChild(dlg);
    document.body.appendChild(overlay);

    let busy = false;
    const close = () => overlay.remove();
    cancelBtn.onclick = close;
    refreshBtn.onclick = () => { if (!busy) loadModels(); };
    overlay.addEventListener("mousedown", (ev) => { if (ev.target === overlay && !busy) close(); });

    let items = [];

    const renderList = (models) => {
        listEl.innerHTML = "";
        items = [];
        let lastFolder = null;
        let folderGroup = null;
        let count = 0;
        for (const m of models) {
            if (m.folder !== lastFolder) {
                lastFolder = m.folder;
                const h = document.createElement("div");
                h.textContent = `📦 ${m.folder}`;
                h.style.cssText = `padding:6px 0 3px;font-weight:bold;color:#4ec9b0;border-bottom:1px solid ${COL_BORDER};margin-top:6px;`;
                listEl.appendChild(h);
                folderGroup = document.createElement("div");
                listEl.appendChild(folderGroup);
            }
            const row = document.createElement("div");
            row.style.cssText = "display:flex;align-items:center;gap:8px;padding:3px 0;white-space:nowrap;cursor:context-menu;";
            const cb = document.createElement("input");
            cb.type = "checkbox";
            const nameSpan = document.createElement("span");
            const rel = (m.subpath ? m.subpath + "/" : "") + m.name;
            nameSpan.textContent = rel;
            nameSpan.title = "models/" + m.folder + "/" + rel;
            const sizeSpan = document.createElement("span");
            sizeSpan.style.cssText = `color:${COL_DIM};font-size:12px;`;
            sizeSpan.textContent = fmtSize(m.size);
            const targetSpan = document.createElement("span");
            targetSpan.style.cssText = "color:#569cd6;font-size:12px;";
            row.appendChild(cb);
            row.appendChild(nameSpan);
            row.appendChild(sizeSpan);
            row.appendChild(targetSpan);
            folderGroup.appendChild(row);
            items.push({ m, cb, row, targetSpan, target: null });
            count++;

            row.oncontextmenu = async (e) => {
                e.preventDefault();
                e.stopPropagation();
                const oldm = document.getElementById("qibo-move-folder-menu");
                if (oldm) oldm.remove();
                const targets = items.filter((it) => it.cb.checked);
                const scope = targets.length > 0 ? targets : [items.find((it) => it.row === row)].filter(Boolean);
                if (scope.length === 0) return;
                const scopeFolders = new Set(scope.map((it) => it.m.folder));

                const folders = await fetchFolders();
                const rootParts = [...new Set(folders.map((f) => f.split("/")[0]))];
                const expanded = new Set(rootParts);
                const renderFolderItems = (parentPrefix) => {
                    const directChildren = [];
                    const seen = new Set();
                    for (const fd of folders) {
                        const parts = fd.split("/");
                        if (parentPrefix === "") {
                            if (parts.length === 1 && !seen.has(parts[0])) {
                                seen.add(parts[0]); directChildren.push({ name: parts[0], full: parts[0], isLeaf: true });
                            }
                        } else {
                            const prefix = parentPrefix + "/";
                            if (fd.startsWith(prefix)) {
                                const rest = fd.slice(prefix.length);
                                const first = rest.split("/")[0];
                                const full = parentPrefix + "/" + first;
                                if (!seen.has(first)) {
                                    seen.add(first);
                                    const isLeaf = folders.includes(full);
                                    directChildren.push({ name: first, full, isLeaf });
                                }
                            }
                        }
                    }
                    directChildren.sort((a, b) => a.name.localeCompare(b.name));
                    return directChildren;
                };
                const buildItem = (entry, depth) => {
                    const fd = entry.full;
                    const isDir = !entry.isLeaf || folders.some((f) => f.startsWith(fd + "/") && f !== fd);
                    const hasChildren = folders.some((f) => f.startsWith(fd + "/"));
                    const allSame = scopeFolders.size === 1 && scopeFolders.has(fd);
                    const opt = document.createElement("div");
                    opt.style.cssText = `padding:5px 12px;cursor:pointer;display:flex;align-items:center;gap:6px;color:${COL_FG};${allSame ? "opacity:0.4;" : ""}`;
                    if (depth > 0) opt.style.paddingLeft = (12 + depth * 14) + "px";
                    opt.onmouseover = () => { if (!allSame) { opt.style.background = "#337ab7"; opt.style.color = "#fff"; } };
                    opt.onmouseout = () => { opt.style.background = "transparent"; opt.style.color = COL_FG; };
                    if (hasChildren) {
                        const toggle = document.createElement("span");
                        toggle.style.cssText = `color:${COL_DIM};width:12px;display:inline-block;`;
                        toggle.textContent = expanded.has(fd) ? "▾" : "▸";
                        opt.appendChild(toggle);
                        const txt = document.createElement("span");
                        txt.textContent = entry.name + "/";
                        txt.title = "models/" + fd;
                        opt.appendChild(txt);
                        if (!allSame) {
                            opt.onclick = (ev) => {
                                ev.stopPropagation();
                                if (expanded.has(fd)) expanded.delete(fd); else expanded.add(fd);
                                menu.remove();
                                rebuildMenu();
                            };
                        }
                    } else {
                        const spacer = document.createElement("span");
                        spacer.style.cssText = `width:12px;display:inline-block;`;
                        opt.appendChild(spacer);
                        const txt = document.createElement("span");
                        txt.textContent = entry.name;
                        txt.title = "models/" + fd;
                        opt.appendChild(txt);
                        if (allSame) {
                            const same = document.createElement("span");
                            same.style.cssText = `color:${COL_DIM};font-size:11px;margin-left:auto;`;
                            same.textContent = "(同目录)";
                            opt.appendChild(same);
                        } else {
                            opt.onclick = (ev) => {
                                ev.stopPropagation();
                                for (const it of scope) {
                                    it.target = fd;
                                    it.targetSpan.textContent = "→ " + fd;
                                    if (!it.cb.checked) it.cb.checked = true;
                                }
                                syncSelAll();
                                menu.remove();
                                statusSpan.textContent = `已指定 ${scope.length} 个模型移动到 ${fd}，点「移动选中」执行`;
                            };
                        }
                    }
                    return opt;
                };
                const rebuildMenu = () => {
                    const oldm = document.getElementById("qibo-move-folder-menu");
                    if (oldm) oldm.remove();
                    const m = document.createElement("div");
                    m.id = "qibo-move-folder-menu";
                    const mx2 = Math.min(e.clientX, Math.max(10, window.innerWidth - 240));
                    const my2 = Math.min(e.clientY, Math.max(10, window.innerHeight - 480));
                    m.style.cssText = `position:fixed;left:${mx2}px;top:${my2}px;z-index:100002;background:${COL_BG};border:1px solid ${COL_BORDER};border-radius:4px;padding:4px 0;box-shadow:0 4px 12px rgba(0,0,0,0.5);font-size:12px;min-width:220px;max-height:460px;overflow-y:auto;`;
                    const mt2 = document.createElement("div");
                    mt2.style.cssText = `color:${COL_DIM};padding:4px 12px;border-bottom:1px solid ${COL_BORDER};margin-bottom:2px;position:sticky;top:0;background:${COL_BG};`;
                    mt2.textContent = scopeFolders.size > 1 ? `移动 ${scope.length} 个模型到目录` : `移动 ${scope.length} 个模型到目录（当前: ${[...scopeFolders][0]}）`;
                    m.appendChild(mt2);
                    const renderLevel = (parentPrefix, depth) => {
                        const children = renderFolderItems(parentPrefix);
                        for (const entry of children) {
                            m.appendChild(buildItem(entry, depth));
                            if (expanded.has(entry.full) && folders.some((f) => f.startsWith(entry.full + "/"))) {
                                renderLevel(entry.full, depth + 1);
                            }
                        }
                    };
                    renderLevel("", 0);
                    document.body.appendChild(m);
                    const closeMenu2 = (ev) => { if (!m.contains(ev.target)) { m.remove(); document.removeEventListener("mousedown", closeMenu2); } };
                    setTimeout(() => document.addEventListener("mousedown", closeMenu2), 0);
                    menu = m;
                };
                let menu = null;
                rebuildMenu();
            };
        }
        if (count === 0) {
            const empty = document.createElement("div");
            empty.style.cssText = `color:${COL_DIM};padding:24px;text-align:center;`;
            empty.textContent = "models 目录下没有模型文件";
            listEl.appendChild(empty);
        }
        const enabled = () => items;
        const syncSelAll = () => {
            selAllCb.checked = items.length > 0 && items.every((it) => it.cb.checked);
            selAllCb.indeterminate = items.length > 0 && items.some((it) => it.cb.checked) && !selAllCb.checked;
        };
        selAllCb.onchange = () => { for (const it of items) it.cb.checked = selAllCb.checked; };
        for (const it of items) it.cb.onchange = syncSelAll;
        syncSelAll();
    };

    const loadModels = async () => {
        listEl.innerHTML = "";
        const loading = document.createElement("div");
        loading.style.cssText = `color:${COL_DIM};padding:24px;text-align:center;`;
        loading.textContent = "扫描 models 目录中...";
        listEl.appendChild(loading);
        hintSpan.textContent = "";
        try {
            const res = await fetchLocalModels();
            if (res.__error) {
                loading.textContent = "❌ " + res.__error;
                return;
            }
            if (res.error) {
                loading.textContent = "❌ " + res.error;
                return;
            }
            const models = res.models || [];
            renderList(models);
            hintSpan.textContent = `共 ${models.length} 个模型`;
        } catch (e) {
            loading.textContent = "❌ " + e;
        }
    };

    moveBtn.onclick = async () => {
        if (busy) return;
        const picked = items.filter((it) => it.cb.checked && it.target);
        const noTarget = items.filter((it) => it.cb.checked && !it.target);
        if (picked.length === 0) {
            statusSpan.textContent = noTarget.length > 0 ? "⚠ 勾选的模型还没有右键指定目标目录" : "⚠ 请先勾选模型并右键指定目标目录";
            return;
        }
        busy = true;
        moveBtn.disabled = true;
        refreshBtn.disabled = true;
        cancelBtn.disabled = true;
        selAllCb.disabled = true;
        for (const it of items) it.cb.disabled = true;
        moveBtn.textContent = "移动中...";
        const byTarget = new Map();
        for (const it of picked) {
            if (!byTarget.has(it.target)) byTarget.set(it.target, []);
            byTarget.get(it.target).push(it);
        }
        const logLines = [];
        let okCount = 0;
        try {
            for (const [target, group] of byTarget) {
                const body = {
                    dest_folder: target,
                    models: group.map((it) => ({ folder: it.m.folder, subpath: it.m.subpath || "", filename: it.m.name })),
                };
                let res;
                try {
                    const r = await fetch("/qibo/modelscope/move", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(body),
                    });
                    const raw = await r.text();
                    try { res = JSON.parse(raw); } catch (e) { res = { __error: `HTTP ${r.status}: ${raw.slice(0, 200)}` }; }
                } catch (e) {
                    res = { __error: String(e) };
                }
                if (res.__error || res.error) {
                    logLines.push(`❌ 移动到 ${target} 失败: ${res.__error || res.error}`);
                    continue;
                }
                const results = res.results || [];
                okCount += res.ok_count || results.filter((x) => x.ok).length;
                for (const rr of results) {
                    if (rr.ok) logLines.push(`✓ ${rr.filename}  ${rr.folder} → ${target}`);
                    else logLines.push(`❌ ${rr.filename}  ${rr.folder} → ${target}: ${rr.error}`);
                }
            }
        } finally {
            busy = false;
            moveBtn.disabled = false;
            refreshBtn.disabled = false;
            cancelBtn.disabled = false;
            selAllCb.disabled = false;
            moveBtn.textContent = "移动选中";
        }
        statusSpan.textContent = `移动完成: ${okCount}/${picked.length} 成功`;
        if (okCount < picked.length) console.warn("[QIBO.ModelMove]\n" + logLines.join("\n"));
        setTimeout(() => { if (!busy) loadModels(); }, 600);
    };

    loadModels();
}

app.registerExtension({
    name: "QIBO.ModelMove",
    async beforeRegisterNodeDef(nodeType, nodeData, appInstance) {
        if (nodeData?.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            try {
                const self = this;
                const btn = self.addWidget("button", "列举本地模型", null, async () => {
                    btn.name = "⏳ 扫描中...";
                    self.setDirtyCanvas(true, true);
                    try {
                        showMoveDialog(self);
                    } finally {
                        btn.name = "📋 列举本地模型";
                        self.setDirtyCanvas(true, true);
                    }
                });
            } catch (e) {
                console.warn("[QIBO.ModelMove] 按钮添加失败:", e);
            }
            return result;
        };
    },
});