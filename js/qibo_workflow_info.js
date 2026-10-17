import { app } from "/scripts/app.js";
import { ComfyWidgets } from "/scripts/widgets.js";

const NODE_NAME = "QIBOWorkflowInfoNode";
const EXT_NAME = "QIBO.WorkflowInfoUI";

const FOLDERS = [
    "checkpoints",
    "diffusion_models",
    "loras",
    "text_encoders",
    "vae",
    "controlnet",
    "upscale_models",
    "gligen",
    "hypernetworks",
    "style_models",
];

const DEFAULT_REPO_URL = "https://www.modelscope.cn/models/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/tree/master/split_files";

const FONT_CSS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif";
const COL_BG = "#1e1e1e";
const COL_FG = "#cccccc";
const COL_BORDER = "#3e3e42";
const COL_DIM = "#858585";

function fmtSize(bytes) {
    if (!bytes) return "?";
    if (bytes < 1024) return bytes + "B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + "KB";
    if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + "MB";
    return (bytes / 1073741824).toFixed(2) + "GB";
}

function collectGraphNodes() {
    const out = {};
    const types = [];
    const probe = [];
    const candidates = [];
    const g1 = app.graph;
    candidates.push(["app.graph.nodes", g1 && g1.nodes]);
    candidates.push(["app.graph._nodes", g1 && g1._nodes]);
    const c = app.canvas;
    const g2 = c && c.graph;
    candidates.push(["app.canvas.graph.nodes", g2 && g2.nodes]);
    candidates.push(["app.canvas.graph._nodes", g2 && g2._nodes]);

    let nodes = null;
    let usedPath = null;
    for (const [path, arr] of candidates) {
        const desc = arr === undefined ? "undefined" : (Array.isArray(arr) ? `Array len=${arr.length}` : typeof arr);
        probe.push(`${path} = ${desc}`);
        if (Array.isArray(arr) && arr.length > 0 && !nodes) {
            nodes = arr;
            usedPath = path;
        }
    }
    if (!nodes) nodes = [];

    let skippedNoType = 0;
    let skippedBypass = 0;
    for (const node of nodes) {
        if (!node) continue;
        if (!node.type) { skippedNoType++; continue; }
        if (node.mode === 2) { skippedBypass++; continue; }
        const inputs = {};
        if (node.widgets) {
            for (const w of node.widgets) {
                if (!w || !w.name) continue;
                if (w.type === "button") continue;
                inputs[w.name] = w.value;
            }
        }
        out[node.id] = { class_type: node.type, inputs };
        types.push(node.type);
    }
    return { out, types, usedPath, probe, total: nodes.length, skippedNoType, skippedBypass };
}

function formatResult(res) {
    const lines = [];
    lines.push("=== 工作流需求清单 ===");
    if (res.error) { lines.push("❌ 检测出错: " + res.error); return lines.join("\n"); }

    const rns = res.required_nodes || [];
    const rms = res.required_models || [];
    const nodeTotal = rns.reduce((s, n) => s + (n.count || 1), 0);
    lines.push(`\n【需要的节点】${rns.length} 种 / ${nodeTotal} 个`);
    for (const n of rns) {
        const mark = n.registered ? "✓" : "✗";
        const tag = n.registered ? "" : "  [未安装]";
        lines.push(`  ${mark} ${n.class_type} (×${n.count})${tag}`);
        if (!n.registered && n.install_url) {
            lines.push(`       安装: ${n.install_url}`);
        }
    }

    lines.push(`\n【需要的模型】${rms.length} 个`);
    if (rms.length === 0) {
        lines.push("  (未识别到模型加载字段，若工作流含加载器但未列出，需补充字段映射)");
    }
    for (const m of rms) {
        let mark = "✓", tag = "已就位";
        if (m.status === "missing") { mark = "✗"; tag = "缺失"; }
        else if (m.status === "folder_unknown") { mark = "⚠"; tag = "目录未注册"; }
        lines.push(`  ${mark} [节点${m.node_id}] ${m.class_type}.${m.field} = ${m.value}`);
        lines.push(`       目录: ${m.folder}  ${tag}`);
        if (m.status === "missing" && m.available && m.available.length) {
            const shown = m.available.slice(0, 15).join(", ");
            lines.push(`       该目录已有: ${shown}${m.available.length > 15 ? " ..." : ""}`);
        } else if (m.status === "missing") {
            lines.push(`       该目录为空`);
        }
    }

    const missNode = (res.missing_node_types || []).length;
    const missModel = (res.missing_models || []).length;
    lines.push("");
    if (missNode === 0 && missModel === 0) {
        lines.push("✅ 需要的节点与模型均已就位，可尝试运行。");
    } else {
        lines.push(`❌ 缺失: ${missNode} 种节点 + ${missModel} 个模型，需补齐后再运行。`);
    }
    return lines.join("\n");
}

function parseRepoUrls(text) {
    if (!text) return [];
    const regex = /https?:\/\//g;
    const indices = [];
    let m;
    while ((m = regex.exec(text)) !== null) {
        indices.push(m.index);
    }
    const urls = [];
    for (let i = 0; i < indices.length; i++) {
        const start = indices[i];
        const end = i + 1 < indices.length ? indices[i + 1] : text.length;
        let url = text.substring(start, end).trim();
        url = url.replace(/[.,。，,、;；\s]+$/, "");
        if (url.length > 0) urls.push(url);
    }
    return urls;
}

function wrapTextarea(el, autoScroll) {
    const w = {};
    Object.defineProperty(w, "value", {
        get() { return el.value; },
        set(v) {
            el.value = v;
            if (autoScroll) { el.scrollTop = el.scrollHeight; }
        },
    });
    return w;
}

function wrapSelect(el) {
    const w = { options: {} };
    Object.defineProperty(w, "value", {
        get() { return el.value; },
        set(v) { el.value = v; },
    });
    Object.defineProperty(w.options, "values", {
        get() { return Array.from(el.options).map(o => o.value); },
        set(arr) {
            el.innerHTML = "";
            for (const v of arr) {
                const o = document.createElement("option");
                o.value = v;
                o.textContent = v;
                el.appendChild(o);
            }
        },
    });
    return w;
}

const QIBO_STYLE_ID = "qibo-workflow-info-style";
function ensureQiboStyles() {
    if (document.getElementById(QIBO_STYLE_ID)) return;
    const s = document.createElement("style");
    s.id = QIBO_STYLE_ID;
    s.textContent = `
.qibo-main { width:100% !important; min-width:942px !important; height:100%; display:flex !important; flex-direction:row; gap:6px; font-family:${FONT_CSS}; font-size:12px; background:transparent; overflow:hidden; }
.qibo-left { flex:0 0 270px !important; width:270px !important; min-width:270px !important; max-width:270px !important; height:100%; display:flex; flex-direction:column; gap:4px; overflow:hidden; }
.qibo-mid { flex:0 0 220px !important; width:220px !important; min-width:220px !important; max-width:220px !important; height:100%; display:flex; flex-direction:column; gap:4px; overflow:hidden; }
.qibo-right { flex:0 0 440px !important; width:440px !important; min-width:440px !important; max-width:440px !important; height:100%; display:flex; flex-direction:column; gap:4px; overflow:hidden; }
.qibo-label { color:${COL_DIM}; font-size:11px; font-weight:500; flex-shrink:0; }
.qibo-textarea { background:${COL_BG}; color:${COL_FG}; border:1px solid ${COL_BORDER}; border-radius:4px; padding:6px 8px; font-size:12px; font-family:inherit; outline:none; line-height:1.4; }
.qibo-select { background:${COL_BG}; color:${COL_FG}; border:1px solid ${COL_BORDER}; border-radius:4px; padding:4px 6px; font-size:12px; flex-shrink:0; outline:none; }
.qibo-btn { background:#2d2d30; color:${COL_FG}; border:1px solid ${COL_BORDER}; border-radius:4px; padding:6px 8px; font-size:12px; cursor:pointer; text-align:left; flex-shrink:0; font-family:inherit; transition:background 0.15s; }
.qibo-btn:hover { background:#3e3e42; }
.qibo-filelist { flex:1 1 0; overflow-y:auto; overflow-x:auto; border:1px solid ${COL_BORDER}; border-radius:4px; padding:0; background:${COL_BG}; color:${COL_FG}; font-size:12px; min-height:0; }
`;
    document.head.appendChild(s);
}

app.registerExtension({
    name: EXT_NAME,
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            if (this.__qibo3ColInit) return result;
            this.__qibo3ColInit = true;

            ensureQiboStyles();

            const self = this;
            self.__qiboSelectedIdxs = new Set();
            if (typeof this.setSize === "function") {
                this.setSize([942, 560]);
            } else {
                this.size = [942, 560];
            }

            // === Build three-column DOM ===
            const mainContainer = document.createElement("div");
            mainContainer.className = "qibo-main";

            // --- Left column: repo URL + selects + buttons ---
            const leftCol = document.createElement("div");
            leftCol.className = "qibo-left";

            function makeLabel(text) {
                const el = document.createElement("div");
                el.textContent = text;
                el.className = "qibo-label";
                return el;
            }

            leftCol.appendChild(makeLabel("模型地址或者节点地址 (可多行多地址)"));

            const repoTextarea = document.createElement("textarea");
            repoTextarea.value = DEFAULT_REPO_URL;
            repoTextarea.className = "qibo-textarea";
            repoTextarea.style.cssText = "flex:1 1 90px;min-height:70px;resize:vertical;width:100%;";
            leftCol.appendChild(repoTextarea);

            leftCol.appendChild(makeLabel("目标目录"));
            const folderSelect = document.createElement("select");
            folderSelect.className = "qibo-select";
            folderSelect.style.width = "100%";
            for (const f of FOLDERS) {
                const o = document.createElement("option");
                o.value = f;
                o.textContent = f;
                folderSelect.appendChild(o);
            }
            folderSelect.value = "checkpoints";
            leftCol.appendChild(folderSelect);

            leftCol.appendChild(makeLabel("缺失模型名 / 模型ID"));
            const fnSelect = document.createElement("select");
            fnSelect.className = "qibo-select";
            fnSelect.style.width = "100%";
            const fnPlaceholder = document.createElement("option");
            fnPlaceholder.value = "(先检测缺失)";
            fnPlaceholder.textContent = "(先检测缺失)";
            fnSelect.appendChild(fnPlaceholder);
            leftCol.appendChild(fnSelect);

            const idSelect = document.createElement("select");
            idSelect.className = "qibo-select";
            idSelect.style.width = "100%";
            const idPlaceholder = document.createElement("option");
            idPlaceholder.value = "";
            idPlaceholder.textContent = "(搜索后自动填)";
            idSelect.appendChild(idPlaceholder);
            leftCol.appendChild(idSelect);

            function makeBtn(text, fn, parent) {
                const btn = document.createElement("button");
                btn.textContent = text;
                btn.className = "qibo-btn";
                if (parent) {
                    btn.style.flex = "1 1 0";
                    btn.style.width = "auto";
                } else {
                    btn.style.width = "100%";
                }
                btn.onclick = fn;
                (parent || leftCol).appendChild(btn);
                return btn;
            }

            function makeBtnRow(btns) {
                const row = document.createElement("div");
                row.style.cssText = "display:flex;flex-direction:row;gap:4px;flex-shrink:0;";
                for (const [text, fn] of btns) makeBtn(text, fn, row);
                leftCol.appendChild(row);
            }

            // --- Middle column: info / log ---
            const midCol = document.createElement("div");
            midCol.className = "qibo-mid";

            midCol.appendChild(makeLabel("检测信息 / 下载进度"));

            const midTextarea = document.createElement("textarea");
            midTextarea.readOnly = true;
            midTextarea.placeholder = "(点击左侧按钮检测工作流缺失的节点与模型)";
            midTextarea.className = "qibo-textarea";
            midTextarea.style.cssText = "flex:1 1 0;resize:none;white-space:pre-wrap;min-height:0;width:100%;";
            midCol.appendChild(midTextarea);

            // --- Right column: file list ---
            const rightCol = document.createElement("div");
            rightCol.className = "qibo-right";

            rightCol.appendChild(makeLabel("文件列表 (勾选后点 ⬇批量下载)"));

            const fileListContainer = document.createElement("div");
            fileListContainer.className = "qibo-filelist";
            const fileListHint = document.createElement("div");
            fileListHint.style.cssText = `color:${COL_DIM};padding:10px 15px;font-size:12px;`;
            fileListHint.textContent = "(点 📋列文件 后在此勾选，或点 🔍一键检测下载缺失)";
            fileListContainer.appendChild(fileListHint);
            rightCol.appendChild(fileListContainer);

            mainContainer.appendChild(leftCol);
            mainContainer.appendChild(midCol);
            mainContainer.appendChild(rightCol);

            try {
                const domWidget = this.addDOMWidget("qibo_main", "div", mainContainer, { serialize: false });
                if (domWidget) {
                    domWidget.computeSize = () => [942, 620];
                    console.log("[QIBO] addDOMWidget ok, computeSize set");
                } else {
                    console.warn("[QIBO] addDOMWidget returned undefined/null");
                }
            } catch (e) {
                console.warn("[QIBO] addDOMWidget failed:", e);
            }

            let manifestWidget = null;
            try {
                manifestWidget = this.addWidget("text", "model_manifest", "", () => {}, { multiline: true });
                if (manifestWidget) {
                    if (manifestWidget.inputEl) {
                        manifestWidget.inputEl.style.display = "none";
                        manifestWidget.inputEl.placeholder = "(模型清单 JSON，不可见，随工作流保存)";
                    }
                    if (manifestWidget.element) manifestWidget.element.style.display = "none";
                    manifestWidget.options = manifestWidget.options || {};
                    manifestWidget.options.hidden = true;
                    manifestWidget.hidden = true;
                    manifestWidget.computeSize = () => [0, 0];
                    manifestWidget.h = 0;
                    manifestWidget.w = 0;
                }
            } catch (e) {
                console.warn("[QIBO] manifest widget add failed:", e);
            }

            // === Persistent cache for repo textarea (saves with workflow) ===
            let repoUrlCacheWidget = null;
            try {
                repoUrlCacheWidget = this.addWidget("text", "repo_url_cache", (repoTextarea.value || DEFAULT_REPO_URL), () => {}, { multiline: true });
                if (repoUrlCacheWidget) {
                    if (repoUrlCacheWidget.inputEl) repoUrlCacheWidget.inputEl.style.display = "none";
                    if (repoUrlCacheWidget.element) repoUrlCacheWidget.element.style.display = "none";
                    repoUrlCacheWidget.options = repoUrlCacheWidget.options || {};
                    repoUrlCacheWidget.options.hidden = true;
                    repoUrlCacheWidget.hidden = true;
                    repoUrlCacheWidget.computeSize = () => [0, 0];
                    repoUrlCacheWidget.h = 0;
                    repoUrlCacheWidget.w = 0;
                }
            } catch (e) {
                console.warn("[QIBO] repo_url_cache widget add failed:", e);
            }
            repoTextarea.addEventListener("input", () => {
                if (repoUrlCacheWidget) repoUrlCacheWidget.value = repoTextarea.value;
            });
            const _origConfigure = this.onConfigure;
            this.onConfigure = function (o) {
                if (_origConfigure) _origConfigure.call(this, o);
                try {
                    if (repoUrlCacheWidget && repoUrlCacheWidget.value) {
                        repoTextarea.value = repoUrlCacheWidget.value;
                    }
                } catch (e) {}
            };

            // === Create widget wrappers (same interface as before) ===
            const widget = wrapTextarea(midTextarea, true);
            const msRepoWidget = wrapTextarea(repoTextarea, false);
            const msFolderWidget = wrapSelect(folderSelect);
            const msFnWidget = wrapSelect(fnSelect);
            const msIdWidget = wrapSelect(idSelect);
            const msSelectWidget = { value: "all", options: { values: ["all"] } };

            self.__qiboWorkflowInfoWidget = widget;

            // When filename dropdown changes, auto-update folder from __qiboMissingModels
            fnSelect.onchange = () => {
                const list = self.__qiboMissingModels;
                if (!list) return;
                const m = list.find(x => x.value === fnSelect.value);
                if (m && m.folder) {
                    msFolderWidget.value = m.folder;
                    self.setDirtyCanvas(true, true);
                }
            };

            // === Functions ===
            const renderFilesInRightPanel = (allFiles, emptyText) => {
                const content = fileListContainer;
                content.innerHTML = "";
                if (!allFiles || allFiles.length === 0) {
                    const empty = document.createElement("div");
                    empty.style.cssText = `color:${COL_DIM};padding:16px;font-size:13px;`;
                    empty.textContent = emptyText || "(无文件)";
                    content.appendChild(empty);
                    return;
                }
                let existCount = 0;
                for (const f of allFiles) if (f.local_exists) existCount++;
                const headerRow = document.createElement("div");
                headerRow.style.cssText = `display:flex;align-items:center;gap:10px;padding:8px 15px;border-bottom:1px solid ${COL_BORDER};background:#252526;`;
                const selectAllCb = document.createElement("input");
                selectAllCb.type = "checkbox";
                selectAllCb.style.cssText = "appearance:none;width:14px;height:14px;border:1px solid #555;border-radius:3px;cursor:pointer;position:relative;flex-shrink:0;";
                if (self.__qiboSelectedIdxs && allFiles.length > 0 && allFiles.every((_, idx) => self.__qiboSelectedIdxs.has(idx))) {
                    selectAllCb.checked = true;
                    selectAllCb.style.background = "#007acc";
                }
                selectAllCb.onchange = () => {
                    selectAllCb.style.background = selectAllCb.checked ? "#007acc" : "transparent";
                    content.querySelectorAll(".qibo-file-cb").forEach(cb => { cb.checked = selectAllCb.checked; cb.style.background = cb.checked ? "#007acc" : "transparent"; });
                    if (self.__qiboSelectedIdxs) {
                        self.__qiboSelectedIdxs.clear();
                        if (selectAllCb.checked) { for (let idx = 0; idx < allFiles.length; idx++) self.__qiboSelectedIdxs.add(idx); }
                    }
                };
                const selectAllLabel = document.createElement("label");
                selectAllLabel.style.cssText = `cursor:pointer;color:${COL_FG};flex:1;font-size:13px;`;
                selectAllLabel.textContent = `全选/取消 (${allFiles.length} 个文件)`;
                const existBadge = document.createElement("span");
                existBadge.style.cssText = `color:#4caf50;font-size:12px;${existCount ? "" : "display:none;"}`;
                existBadge.textContent = `${existCount} 个已存在`;
                headerRow.appendChild(selectAllCb);
                headerRow.appendChild(selectAllLabel);
                headerRow.appendChild(existBadge);
                content.appendChild(headerRow);
                let byFolder = {};
                for (let i = 0; i < allFiles.length; i++) {
                    const f = allFiles[i];
                    const folder = f.local_folder || "(未匹配)";
                    if (!byFolder[folder]) byFolder[folder] = [];
                    byFolder[folder].push(i);
                }
                for (const folder of Object.keys(byFolder)) {
                    const folderEl = document.createElement("div");
                    folderEl.style.cssText = "margin-bottom:2px;";
                    const folderHeader = document.createElement("div");
                    folderHeader.style.cssText = "display:flex;align-items:center;gap:8px;padding:8px 15px;cursor:pointer;user-select:none;font-weight:500;font-size:13px;";
                    const folderIcon = document.createElement("span");
                    folderIcon.style.cssText = "color:#dcb67a;font-size:12px;";
                    folderIcon.textContent = "▼";
                    const groupCb = document.createElement("input");
                    groupCb.type = "checkbox";
                    groupCb.style.cssText = "appearance:none;width:14px;height:14px;border:1px solid #555;border-radius:3px;cursor:pointer;position:relative;flex-shrink:0;";
                    groupCb.onclick = (e) => e.stopPropagation();
                    const folderContent = document.createElement("div");
                    folderContent.style.cssText = "display:flex;flex-direction:column;min-width:100%;width:max-content;";
                    groupCb.onchange = () => {
                        groupCb.style.background = groupCb.checked ? "#007acc" : "transparent";
                        for (const idx of byFolder[folder]) { const cb = content.querySelector(`.qibo-file-cb[data-idx="${idx}"]`); if (cb) { cb.checked = groupCb.checked; cb.style.background = cb.checked ? "#007acc" : "transparent"; } }
                    };
                    const folderLabel = document.createElement("span");
                    folderLabel.style.cssText = "color:#dcb67a;";
                    const folderExist = byFolder[folder].filter(i => allFiles[i].local_exists).length;
                    folderLabel.textContent = `${folder} (${byFolder[folder].length}${folderExist ? `, ${folderExist} 已存在` : ""})`;
                    folderHeader.appendChild(folderIcon);
                    folderHeader.appendChild(groupCb);
                    folderHeader.appendChild(folderLabel);
                    folderHeader.onmouseover = () => { folderHeader.style.background = "#2a2d2e"; };
                    folderHeader.onmouseout = () => { folderHeader.style.background = "transparent"; };
                    let collapsed = false;
                    folderHeader.onclick = (e) => { if (e.target.tagName === "INPUT") return; collapsed = !collapsed; folderIcon.textContent = collapsed ? "▶" : "▼"; folderContent.style.display = collapsed ? "none" : "flex"; };
                    folderEl.appendChild(folderHeader);
                    for (const i of byFolder[folder]) {
                        const f = allFiles[i];
                        const itemEl = document.createElement("div");
                        itemEl.style.cssText = "display:flex;align-items:center;justify-content:space-between;padding:6px 15px 6px 35px;font-size:13px;cursor:pointer;";
                        itemEl.onmouseover = () => { itemEl.style.background = "#2a2d2e"; };
                        itemEl.onmouseout = () => { itemEl.style.background = "transparent"; };
                        const itemInfo = document.createElement("div");
                        itemInfo.style.cssText = "display:flex;align-items:center;gap:8px;white-space:nowrap;";
                        const cb = document.createElement("input");
                        cb.type = "checkbox";
                        cb.className = "qibo-file-cb";
                        cb.dataset.idx = String(i);
                        cb.style.cssText = "appearance:none;width:14px;height:14px;border:1px solid #555;border-radius:3px;cursor:pointer;position:relative;flex-shrink:0;";
                        if (self.__qiboSelectedIdxs && self.__qiboSelectedIdxs.has(i)) { cb.checked = true; cb.style.background = "#007acc"; }
                        cb.onclick = (e) => e.stopPropagation();
                        cb.onchange = () => {
                            cb.style.background = cb.checked ? "#007acc" : "transparent";
                            if (self.__qiboSelectedIdxs) { if (cb.checked) self.__qiboSelectedIdxs.add(i); else self.__qiboSelectedIdxs.delete(i); }
                        };
                        const nameSpan = document.createElement("span");
                        nameSpan.style.cssText = `white-space:nowrap;color:${f.local_exists ? "#858585" : "#cccccc"};`;
                        nameSpan.textContent = f.name;
                        itemInfo.appendChild(cb);
                        itemInfo.appendChild(nameSpan);
                        const itemRight = document.createElement("div");
                        itemRight.style.cssText = "display:flex;align-items:center;gap:6px;flex-shrink:0;margin-left:10px;";
                        const sizeSpan = document.createElement("span");
                        sizeSpan.style.cssText = `color:${COL_DIM};font-size:12px;`;
                        sizeSpan.textContent = fmtSize(f.size);
                        itemRight.appendChild(sizeSpan);
                        if (f.local_exists) { const checkIcon = document.createElement("span"); checkIcon.style.cssText = "color:#4caf50;font-size:14px;"; checkIcon.textContent = "✓"; itemRight.appendChild(checkIcon); }
                        itemEl.appendChild(itemInfo);
                        itemEl.appendChild(itemRight);
                        itemEl.onclick = (e) => { if (e.target.tagName === "INPUT") return; cb.checked = !cb.checked; cb.style.background = cb.checked ? "#007acc" : "transparent"; };
                        itemEl.oncontextmenu = (e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            const oldm = document.getElementById("qibo-folder-menu");
                            if (oldm) oldm.remove();
                            const menu = document.createElement("div");
                            menu.id = "qibo-folder-menu";
                            menu.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;z-index:99999;background:${COL_BG};border:1px solid ${COL_BORDER};border-radius:4px;padding:4px 0;box-shadow:0 4px 12px rgba(0,0,0,0.5);font-size:12px;min-width:160px;`;
                            const title = document.createElement("div");
                            title.style.cssText = `color:${COL_DIM};padding:4px 12px;border-bottom:1px solid ${COL_BORDER};margin-bottom:2px;`;
                            title.textContent = "下载到目录";
                            menu.appendChild(title);
                            const curFolder = f.local_folder || "checkpoints";
                            for (const fd of FOLDERS) {
                                const opt = document.createElement("div");
                                opt.style.cssText = `padding:5px 12px;cursor:pointer;display:flex;align-items:center;gap:6px;color:${COL_FG};`;
                                opt.onmouseover = () => { opt.style.background = "#007acc"; opt.style.color = "#fff"; };
                                opt.onmouseout = () => { opt.style.background = "transparent"; opt.style.color = COL_FG; };
                                const mark = document.createElement("span");
                                mark.style.cssText = "width:14px;color:#4caf50;";
                                mark.textContent = (fd === curFolder) ? "✓" : "";
                                const txt = document.createElement("span");
                                txt.textContent = fd;
                                opt.appendChild(mark);
                                opt.appendChild(txt);
                                opt.onclick = (ev) => {
                                    ev.stopPropagation();
                                    f.local_folder = fd;
                                    menu.remove();
                                    renderFilesInRightPanel(allFiles, emptyText);
                                };
                                menu.appendChild(opt);
                            }
                            document.body.appendChild(menu);
                            const closeMenu = (ev) => { if (!menu.contains(ev.target)) { menu.remove(); document.removeEventListener("mousedown", closeMenu); } };
                            setTimeout(() => document.addEventListener("mousedown", closeMenu), 0);
                        };
                        folderContent.appendChild(itemEl);
                    }
                    folderEl.appendChild(folderContent);
                    content.appendChild(folderEl);
                }
            };

            const detectAndMatch = async () => {
                const collected = collectGraphNodes();
                const r = await fetch("/qibo/workflow_check", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ nodes: collected.out }),
                });
                if (!r.ok) return { error: `检测失败: HTTP ${r.status}` };
                const res = await r.json();
                const missModels = (res.missing_models || []).filter(m => m.status === "missing");
                const seen = new Set();
                const uniqMiss = [];
                for (const m of missModels) { if (!seen.has(m.value)) { seen.add(m.value); uniqMiss.push(m); } }
                if (uniqMiss.length > 0) {
                    msFnWidget.options.values = uniqMiss.map(m => m.value);
                    self.__qiboMissingModels = uniqMiss.map(m => ({ value: m.value, folder: m.folder }));
                    msFnWidget.value = uniqMiss[0].value;
                    if (uniqMiss[0].folder) msFolderWidget.value = uniqMiss[0].folder;
                }
                const rawUrls = parseRepoUrls(msRepoWidget.value || "");
                let allFiles = [];
                let repoErrors = [];
                for (const repoUrl of rawUrls) {
                    try {
                        const lr = await fetch("/qibo/modelscope/list_files", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ url: repoUrl }),
                        });
                        if (!lr.ok) { repoErrors.push(`${repoUrl}: HTTP ${lr.status}`); continue; }
                        const lres = await lr.json();
                        if (lres.error) { repoErrors.push(`${repoUrl}: ${lres.error}`); continue; }
                        for (const f of (lres.files || [])) f._repo = lres.model_id || repoUrl;
                        allFiles = allFiles.concat(lres.files || []);
                    } catch (e) { repoErrors.push(`${repoUrl}: ${e}`); }
                }
                let matched = [];
                let unmatched = [];
                for (const m of uniqMiss) {
                    let f = allFiles.find(x => x.name === m.value);
                    if (!f) f = allFiles.find(x => x.name.includes(m.value) || m.value.includes(x.name));
                    if (f) { if (!f.local_folder && m.folder) f.local_folder = m.folder; matched.push(f); }
                    else unmatched.push(m.value);
                }
                self.__qiboMatchedFiles = matched;
                if (self.__qiboSelectedIdxs) {
                    self.__qiboSelectedIdxs.clear();
                    matched.forEach((f, idx) => { if (!f.local_exists) self.__qiboSelectedIdxs.add(idx); });
                }
                self.__qiboRepoFiles = matched;
                renderFilesInRightPanel(matched, "(未匹配到任何缺失模型)");
                return { res, uniqMiss, matched, unmatched, repoErrors, allFiles };
            };

            self.__qiboDetect = async () => {
                const diag = [];
                try {
                    diag.push("=== 检测缺失并匹配 ===");
                    widget.value = diag.join("\n") + "\n\n检测中...";
                    self.setDirtyCanvas(true, true);
                    const result = await detectAndMatch();
                    if (result.error) {
                        widget.value = diag.join("\n") + "\n\n❌ " + result.error;
                        self.setDirtyCanvas(true, true);
                        return;
                    }
                    const { uniqMiss, matched, unmatched, repoErrors } = result;
                    diag.push(`缺失模型 ${uniqMiss.length} 个:`);
                    for (const m of uniqMiss) diag.push(`  ❓ ${m.value} [${m.folder || "?"}]`);
                    diag.push("");
                    diag.push(`从仓库地址列文件匹配 ${matched.length}/${uniqMiss.length}:`);
                    for (const f of matched) diag.push(`  ✓ ${f.name}  [${f.local_folder || "?"}]  ${fmtSize(f.size)}`);
                    for (const u of unmatched) diag.push(`  ❌ ${u}  未找到`);
                    if (repoErrors.length) { diag.push("", "列文件错误:"); for (const e of repoErrors) diag.push("  " + e); }
                    diag.push("");
                    if (matched.length > 0) diag.push(`✅ 右栏已显示 ${matched.length} 个匹配文件，点"2、一键下载缺少"开始下载`);
                    else diag.push("⚠ 未匹配到，请检查左栏仓库地址");
                    widget.value = diag.join("\n");
                } catch (e) {
                    widget.value = (diag.length ? diag.join("\n") + "\n\n" : "") + "❌ 异常: " + e;
                }
                self.setDirtyCanvas(true, true);
            };

            self.__qiboMsSearch = async () => {
                const fn = (msFnWidget.value || "").trim();
                if (!fn || fn === "(先检测缺失)") {
                    widget.value = "❌ 请在缺失模型名下拉选模型名";
                    self.setDirtyCanvas(true, true);
                    return;
                }
                const searchBody = { filename: fn };
                widget.value = `🔍 搜索魔搭: ${fn}\n搜索中...`;
                self.setDirtyCanvas(true, true);
                try {
                    const r = await fetch("/qibo/modelscope/search", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(searchBody),
                    });
                    if (!r.ok) {
                        widget.value = `❌ 搜索失败: ${r.status}`;
                        self.setDirtyCanvas(true, true);
                        return;
                    }
                    const res = await r.json();
                    if (res.error) {
                        widget.value = `❌ ${res.error}`;
                        self.setDirtyCanvas(true, true);
                        return;
                    }
                    const cands = res.candidates || [];
                    const lines = [`🔍 搜索: ${fn}  (query: ${res.query || ""})`];

                    if (cands.length === 0) {
                        lines.push(`Bing 搜索无结果，从仓库地址逐个列文件匹配...`);
                        widget.value = lines.join("\n");
                        self.setDirtyCanvas(true, true);

                        const repoUrls = parseRepoUrls(msRepoWidget.value || "");
                        let matchedFiles = [];
                        for (let u = 0; u < repoUrls.length; u++) {
                            const repoUrl = repoUrls[u];
                            lines.push(`\n[${u + 1}/${repoUrls.length}] ${repoUrl}`);
                            widget.value = lines.join("\n");
                            self.setDirtyCanvas(true, true);
                            try {
                                const lr = await fetch("/qibo/modelscope/list_files", {
                                    method: "POST",
                                    headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ url: repoUrl }),
                                });
                                if (!lr.ok) { lines.push(`  ❌ HTTP ${lr.status}`); continue; }
                                const lres = await lr.json();
                                if (lres.error) { lines.push(`  ❌ ${lres.error}`); continue; }
                                const files = lres.files || [];
                                for (const f of files) {
                                    if (f.name && f.name.toLowerCase().includes(fn.toLowerCase())) {
                                        matchedFiles.push({
                                            model_id: lres.model_id || repoUrl,
                                            page_url: repoUrl,
                                            direct_file_url: f.direct_url,
                                            files: [f.name],
                                            local_folder: f.local_folder,
                                        });
                                        lines.push(`  ✓ ${f.name}  ${fmtSize(f.size)}  [${f.local_folder || "?"}]`);
                                    }
                                }
                            } catch (e) {
                                lines.push(`  ❌ ${e}`);
                            }
                        }

                        lines.push(`\n共匹配 ${matchedFiles.length} 个文件`);
                        let pick = null;
                        const idOpts = [];
                        for (let i = 0; i < matchedFiles.length; i++) {
                            const c = matchedFiles[i];
                            idOpts.push(c.model_id);
                            if (c.direct_file_url && !pick) pick = c;
                        }
                        if (idOpts.length > 0) msIdWidget.options.values = idOpts;
                        if (pick) {
                            self.__qiboMsPick = pick;
                            msIdWidget.value = pick.model_id;
                            lines.push(`\n✅ 已自动选中: ${pick.model_id}`);
                            if (pick.direct_file_url) lines.push(`   直链: ${pick.direct_file_url}`);
                            if (pick.local_folder) {
                                msFolderWidget.value = pick.local_folder;
                                lines.push(`   目录: ${pick.local_folder}`);
                            }
                            lines.push(`   点"⬇ 下载到目录"即可下载`);
                        } else {
                            lines.push("\n⚠ 未匹配到文件，请检查仓库地址");
                        }
                        widget.value = lines.join("\n");
                        self.setDirtyCanvas(true, true);
                        return;
                    }

                    lines.push(`找到 ${cands.length} 个候选:`);
                    let pick = null;
                    const idOpts = [];
                    for (let i = 0; i < cands.length; i++) {
                        const c = cands[i];
                        idOpts.push(c.model_id);
                        const hasDirect = c.direct_file_url ? " [有直链]" : "";
                        lines.push(`\n[${i + 1}] ${c.model_id}${hasDirect}`);
                        lines.push(`    ${c.page_url}`);
                        if (c.direct_file_url) {
                            lines.push(`    直链: ${c.direct_file_url}`);
                            if (!pick) pick = c;
                        }
                        if (c.files && c.files.length) {
                            lines.push(`    文件: ${c.files.join(", ")}`);
                        }
                    }
                    if (idOpts.length > 0) msIdWidget.options.values = idOpts;
                    if (pick) {
                        self.__qiboMsPick = pick;
                        msIdWidget.value = pick.model_id;
                        lines.push(`\n✅ 已自动选中: ${pick.model_id}`);
                        if (pick.direct_file_url) lines.push(`   下载直链已就绪，点"⬇ 下载到目录"即可`);
                    } else {
                        lines.push("\n⚠ 未找到带直链的候选，可从模型ID下拉选后点下载（走 SDK）");
                    }
                    widget.value = lines.join("\n");
                } catch (e) {
                    widget.value = `❌ 搜索异常: ${e}`;
                }
                self.setDirtyCanvas(true, true);
            };

            self.__qiboMsDownload = async () => {
                const folder = msFolderWidget.value || "checkpoints";
                const pick = self.__qiboMsPick || {};
                const fnRaw = (msFnWidget.value || "").trim();
                const filename = (fnRaw && fnRaw !== "(先检测缺失)") ? fnRaw : undefined;
                const directUrl = pick.direct_file_url || undefined;
                const modelId = (msIdWidget.value || "").trim() || pick.model_id || undefined;
                if (!directUrl && !modelId) {
                    widget.value = "❌ 无下载来源：请先搜魔搭选中候选";
                    self.setDirtyCanvas(true, true);
                    return;
                }
                const body = { folder };
                if (filename) body.filename = filename;
                if (directUrl) body.direct_url = directUrl;
                if (modelId) body.model_id = modelId;
                widget.value = `⬇ 下载到 ${folder}\n${directUrl ? "直链: " + directUrl : "模型: " + modelId}\n下载中...`;
                self.setDirtyCanvas(true, true);
                try {
                    const r = await fetch("/qibo/modelscope/download", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(body),
                    });
                    if (!r.ok) {
                        widget.value = `❌ 下载失败: ${r.status}`;
                        self.setDirtyCanvas(true, true);
                        return;
                    }
                    const res = await r.json();
                    if (res.error) {
                        widget.value = `❌ ${res.error}`;
                        self.setDirtyCanvas(true, true);
                        return;
                    }
                    const lines = ["✅ 下载完成"];
                    if (res.full_path) lines.push(`文件路径: ${res.full_path}`);
                    else if (res.path) lines.push(`文件路径: ${res.path}`);
                    if (res.size) lines.push(`大小: ${res.size} bytes`);
                    if (res.folder) lines.push(`模型目录: ${res.folder}`);
                    if (res.dest_dir) lines.push(`保存到: ${res.dest_dir}`);
                    if (res.files && res.files.length) lines.push(`文件列表: ${res.files.join(", ")}`);
                    widget.value = lines.join("\n");
                    appendToManifest({
                        name: filename || res.filename || (res.files && res.files[0]) || "(unknown)",
                        direct_url: directUrl || res.direct_url || "",
                        folder: res.folder || folder,
                        size: res.size || 0,
                    });
                } catch (e) {
                    widget.value = `❌ 下载异常: ${e}`;
                }
                self.setDirtyCanvas(true, true);
            };

            self.__qiboListFiles = async () => {
                const rawUrls = (msRepoWidget.value || "").trim();
                if (!rawUrls) {
                    widget.value = "❌ 请先在左栏填入魔搭仓库地址（可多行多地址）";
                    self.setDirtyCanvas(true, true);
                    return;
                }
                const urls = parseRepoUrls(rawUrls);

                let allFiles = [];
                let repoNames = [];
                let errors = [];
                for (let u = 0; u < urls.length; u++) {
                    const repoUrl = urls[u];
                    try {
                        const r = await fetch("/qibo/modelscope/list_files", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ url: repoUrl }),
                        });
                        if (!r.ok) { errors.push(`${repoUrl}: HTTP ${r.status}`); continue; }
                        const res = await r.json();
                        if (res.error) { errors.push(`${repoUrl}: ${res.error}`); continue; }
                        const files = res.files || [];
                        for (const f of files) f._repo = res.model_id || repoUrl;
                        allFiles = allFiles.concat(files);
                        repoNames.push(res.model_id || repoUrl);
                    } catch (e) {
                        errors.push(`${repoUrl}: ${e}`);
                    }
                }

                if (self.__qiboSelectedIdxs) self.__qiboSelectedIdxs.clear();
                self.__qiboRepoFiles = allFiles;
                renderFilesInRightPanel(allFiles, errors.length ? errors.join("\n") : "(无文件)");

                const lines = [`📋 解析 ${urls.length} 个地址，共 ${allFiles.length} 个文件:`];
                for (const rn of repoNames) lines.push(`  ✓ ${rn}`);
                for (const er of errors) lines.push(`  ❌ ${er}`);
                lines.push(`请在右栏列表勾选要下载的文件，然后点"⬇ 批量下载"`);
                widget.value = lines.join("\n");
                self.setDirtyCanvas(true, true);
            };

            const qiboConfirmDownloadList = (items) => new Promise((resolve) => {
                const overlay = document.createElement("div");
                overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:100000;display:flex;align-items:center;justify-content:center;font-family:" + FONT_CSS + ";";
                const card = document.createElement("div");
                card.style.cssText = "background:" + COL_BG + ";border:1px solid " + COL_BORDER + ";border-radius:8px;width:600px;max-width:90vw;max-height:80vh;display:flex;flex-direction:column;box-shadow:0 8px 32px rgba(0,0,0,0.5);";
                const title = document.createElement("div");
                title.style.cssText = "padding:14px 18px;border-bottom:1px solid " + COL_BORDER + ";font-size:14px;font-weight:600;color:" + COL_FG + ";";
                title.textContent = "确认下载 " + items.length + " 个文件";
                card.appendChild(title);
                const listWrap = document.createElement("div");
                listWrap.style.cssText = "flex:1 1 auto;overflow-y:auto;padding:4px 0;min-height:0;";
                const totalSize = items.reduce((s, it) => s + (it.size || 0), 0);
                items.forEach((it, i) => {
                    const row = document.createElement("div");
                    row.style.cssText = "display:flex;gap:10px;padding:6px 18px;font-size:12px;color:" + COL_FG + ";align-items:center;";
                    const idx = document.createElement("span");
                    idx.style.cssText = "color:" + COL_DIM + ";width:36px;flex-shrink:0;text-align:right;";
                    idx.textContent = (i + 1) + ".";
                    const name = document.createElement("span");
                    name.style.cssText = "flex:1 1 auto;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
                    name.textContent = it.name;
                    name.title = it.name;
                    const size = document.createElement("span");
                    size.style.cssText = "color:" + COL_DIM + ";width:72px;flex-shrink:0;text-align:right;";
                    size.textContent = fmtSize(it.size || 0);
                    const path = document.createElement("span");
                    path.style.cssText = "color:#4caf50;width:220px;flex-shrink:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
                    const pathText = "models/" + it.folder + "/" + it.name;
                    path.textContent = pathText;
                    path.title = pathText;
                    row.appendChild(idx); row.appendChild(name); row.appendChild(size); row.appendChild(path);
                    listWrap.appendChild(row);
                });
                card.appendChild(listWrap);
                const summary = document.createElement("div");
                summary.style.cssText = "padding:8px 18px;color:" + COL_DIM + ";font-size:12px;border-top:1px solid " + COL_BORDER + ";";
                summary.textContent = "总计 " + items.length + " 个文件，合计 " + fmtSize(totalSize);
                card.appendChild(summary);
                const btnRow = document.createElement("div");
                btnRow.style.cssText = "padding:12px 18px;border-top:1px solid " + COL_BORDER + ";display:flex;justify-content:flex-end;gap:10px;";
                const cancelBtn = document.createElement("button");
                cancelBtn.style.cssText = "background:#3e3e42;color:" + COL_FG + ";border:1px solid " + COL_BORDER + ";border-radius:4px;padding:7px 18px;font-size:13px;cursor:pointer;font-family:inherit;";
                cancelBtn.textContent = "取消";
                const okBtn = document.createElement("button");
                okBtn.style.cssText = "background:#007acc;color:#fff;border:none;border-radius:4px;padding:7px 18px;font-size:13px;cursor:pointer;font-family:inherit;";
                okBtn.textContent = "确定下载";
                btnRow.appendChild(cancelBtn); btnRow.appendChild(okBtn);
                card.appendChild(btnRow);
                overlay.appendChild(card);
                document.body.appendChild(overlay);
                const close = (val) => { overlay.remove(); resolve(val); };
                cancelBtn.onclick = () => close(false);
                okBtn.onclick = () => close(true);
                overlay.onclick = (e) => { if (e.target === overlay) close(false); };
            });

            self.__qiboBatchDownload = async () => {
                const files = self.__qiboRepoFiles || [];
                if (files.length === 0) {
                    widget.value = "❌ 请先点 📋列文件 获取文件列表";
                    self.setDirtyCanvas(true, true);
                    return;
                }

                const content = fileListContainer;
                const checkboxes = content ? content.querySelectorAll(".qibo-file-cb:checked") : [];
                let selected = [];
                for (const cb of checkboxes) {
                    const idx = parseInt(cb.dataset.idx);
                    if (!isNaN(idx) && files[idx]) selected.push(files[idx]);
                }

                if (selected.length === 0) {
                    const sel = (msSelectWidget.value || "all").trim();
                    if (sel === "all") {
                        selected = files.slice();
                    } else {
                        const indices = new Set();
                        for (const part of sel.split(/[,\s]+/)) {
                            const range = part.match(/^(\d+)-(\d+)$/);
                            if (range) {
                                for (let n = parseInt(range[1]); n <= parseInt(range[2]); n++) indices.add(n - 1);
                            } else if (/^\d+$/.test(part)) {
                                indices.add(parseInt(part) - 1);
                            }
                        }
                        selected = files.filter((_, i) => indices.has(i));
                    }
                }

                if (selected.length === 0) {
                    widget.value = "❌ 未选中任何文件，请在右栏列表勾选";
                    self.setDirtyCanvas(true, true);
                    return;
                }

                const dlItems = selected.map(f => ({ name: f.name, size: f.size || 0, folder: f.local_folder || "checkpoints" }));
                const confirmed = await qiboConfirmDownloadList(dlItems);
                if (!confirmed) {
                    widget.value = `已取消：未下载 ${selected.length} 个文件`;
                    self.setDirtyCanvas(true, true);
                    return;
                }

                const dlFiles = selected.map(f => ({
                    direct_url: f.direct_url,
                    name: f.name,
                    local_folder: f.local_folder,
                }));

                let logLines = [`⬇ 批量下载 ${dlFiles.length} 个文件`, ""];
                let okCount = 0;
                const updateWidget = () => { widget.value = logLines.join("\n"); self.setDirtyCanvas(true, true); };

                for (let i = 0; i < dlFiles.length; i++) {
                    const f = dlFiles[i];
                    const folder = f.local_folder || "checkpoints";
                    let destPath = "";

                    try {
                        const r = await fetch("/qibo/modelscope/download", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ direct_url: f.direct_url, filename: f.name, folder }),
                        });
                        const res = await r.json();
                        if (res.error) {
                            logLines.push(`❌ [${i + 1}/${dlFiles.length}] ${f.name}: ${res.error}`);
                            updateWidget();
                            continue;
                        }
                        if (!res.task_id) {
                            logLines.push(`❌ [${i + 1}/${dlFiles.length}] ${f.name}: 未返回 task_id`);
                            updateWidget();
                            continue;
                        }
                        destPath = res.dest_path || "";
                        const taskId = res.task_id;
                        const lineIdx = logLines.length;
                        logLines.push(`⏳ [${i + 1}/${dlFiles.length}] ${f.name}  准备下载...`);
                        if (destPath) logLines.push(`  保存到: ${destPath}`);
                        updateWidget();

                        while (true) {
                            await new Promise(resolve => setTimeout(resolve, 800));
                            try {
                                const pr = await fetch("/qibo/modelscope/download_progress", {
                                    method: "POST",
                                    headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ task_id: taskId }),
                                });
                                const pres = await pr.json();
                                if (pres.error) {
                                    logLines[lineIdx] = `❌ [${i + 1}/${dlFiles.length}] ${f.name}: ${pres.error}`;
                                    updateWidget();
                                    break;
                                }
                                if (pres.status === "done") {
                                    okCount++;
                                    logLines[lineIdx] = `✓ [${i + 1}/${dlFiles.length}] ${f.name}  ${fmtSize(pres.downloaded)}  [${pres.folder || folder}]`;
                                    updateWidget();
                                    appendToManifest({ name: f.name, direct_url: f.direct_url, folder: pres.folder || folder, size: pres.downloaded || f.size || 0 });
                                    break;
                                }
                                if (pres.status === "error") {
                                    logLines[lineIdx] = `❌ [${i + 1}/${dlFiles.length}] ${f.name}: ${pres.error || "下载失败"}`;
                                    updateWidget();
                                    break;
                                }
                                const pct = pres.total > 0 ? pres.percent.toFixed(1) : "?";
                                const dl = fmtSize(pres.downloaded);
                                const tot = pres.total > 0 ? fmtSize(pres.total) : "?";
                                const spd = fmtSize(pres.speed);
                                logLines[lineIdx] = `⏳ [${i + 1}/${dlFiles.length}] ${f.name}  ${dl}/${tot}  ${pct}%  ${spd}/s`;
                                updateWidget();
                            } catch (e2) {
                                logLines[lineIdx] = `❌ [${i + 1}/${dlFiles.length}] ${f.name}: 轮询失败 ${e2}`;
                                updateWidget();
                                break;
                            }
                        }
                    } catch (e) {
                        logLines.push(`❌ [${i + 1}/${dlFiles.length}] ${f.name}: ${e}`);
                        updateWidget();
                    }
                }

                logLines.push("", `✅ 下载完成: ${okCount}/${dlFiles.length} 成功`);
                updateWidget();
            };

            self.__qiboAutoDownload = async () => {
                widget.value = "🔍 一键检测下载缺失\n\n准备中...";
                self.setDirtyCanvas(true, true);
                let logLines = ["🔍 一键检测下载缺失", ""];
                const updateWidget = () => { widget.value = logLines.join("\n"); self.setDirtyCanvas(true, true); };
                try {
                    let matched = (self.__qiboMatchedFiles && self.__qiboMatchedFiles.length > 0) ? self.__qiboMatchedFiles : null;
                    if (matched) {
                        logLines.push(`使用上次检测匹配的 ${matched.length} 个模型`);
                        updateWidget();
                    } else {
                        logLines.push("检测工作流缺失模型中...");
                        updateWidget();
                        const result = await detectAndMatch();
                        if (result.error) { logLines.push("❌ " + result.error); updateWidget(); return; }
                        matched = result.matched;
                        logLines.push(`检测到 ${result.uniqMiss.length} 个缺失模型，匹配 ${matched.length} 个:`);
                        for (const f of matched) logLines.push(`  ✓ ${f.name}  [${f.local_folder || "?"}]  ${fmtSize(f.size)}`);
                        for (const u of result.unmatched) logLines.push(`  ❌ ${u}  未找到`);
                        updateWidget();
                    }
                    if (matched.length === 0) {
                        logLines.push("", "❌ 无匹配模型，请先点\"1、当前流检测缺少\"");
                        updateWidget();
                        return;
                    }
                    const localMissing = matched.filter(f => !f.local_exists);
                    const localExist = matched.filter(f => f.local_exists);
                    if (localExist.length > 0) {
                        logLines.push("", `ℹ️ ${localExist.length} 个已存在本地，跳过下载，加入清单:`);
                        for (const f of localExist) {
                            logLines.push(`  ✓ ${f.name}`);
                            appendToManifest({ name: f.name, direct_url: f.direct_url, folder: f.local_folder || "checkpoints", size: f.size || 0 });
                        }
                    }
                    if (localMissing.length === 0) {
                        logLines.push("", "✅ 所有匹配模型已存在本地，无需下载");
                        updateWidget();
                        return;
                    }
                    logLines.push("", `⬇ 开始下载 ${localMissing.length} 个缺失模型...`, "");
                    updateWidget();
                    let okCount = 0;
                    for (let i = 0; i < localMissing.length; i++) {
                        const f = localMissing[i];
                        const folder = f.local_folder || "checkpoints";
                        try {
                            const dr = await fetch("/qibo/modelscope/download", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ direct_url: f.direct_url, filename: f.name, folder }),
                            });
                            const dres = await dr.json();
                            if (dres.error) { logLines.push(`❌ [${i + 1}/${localMissing.length}] ${f.name}: ${dres.error}`); updateWidget(); continue; }
                            if (!dres.task_id) { logLines.push(`❌ [${i + 1}/${localMissing.length}] ${f.name}: 未返回 task_id`); updateWidget(); continue; }
                            const taskId = dres.task_id;
                            const destPath = dres.dest_path || "";
                            const lineIdx = logLines.length;
                            logLines.push(`⏳ [${i + 1}/${localMissing.length}] ${f.name}  准备下载...`);
                            if (destPath) logLines.push(`  保存到: ${destPath}`);
                            updateWidget();
                            while (true) {
                                await new Promise(resolve => setTimeout(resolve, 800));
                                try {
                                    const pr = await fetch("/qibo/modelscope/download_progress", {
                                        method: "POST",
                                        headers: { "Content-Type": "application/json" },
                                        body: JSON.stringify({ task_id: taskId }),
                                    });
                                    const pres = await pr.json();
                                    if (pres.error || pres.status === "error") { logLines[lineIdx] = `❌ [${i + 1}/${localMissing.length}] ${f.name}: ${pres.error || "失败"}`; updateWidget(); break; }
                                    if (pres.status === "done") { okCount++; logLines[lineIdx] = `✓ [${i + 1}/${localMissing.length}] ${f.name}  ${fmtSize(pres.downloaded)}  [${pres.folder || folder}]`; updateWidget(); appendToManifest({ name: f.name, direct_url: f.direct_url, folder: pres.folder || folder, size: pres.downloaded || f.size || 0 }); break; }
                                    const pct = pres.total > 0 ? pres.percent.toFixed(1) : "?";
                                    const dl = fmtSize(pres.downloaded);
                                    const tot = pres.total > 0 ? fmtSize(pres.total) : "?";
                                    const spd = fmtSize(pres.speed);
                                    logLines[lineIdx] = `⏳ [${i + 1}/${localMissing.length}] ${f.name}  ${dl}/${tot}  ${pct}%  ${spd}/s`;
                                    updateWidget();
                                } catch (e2) { logLines[lineIdx] = `❌ [${i + 1}/${localMissing.length}] ${f.name}: 轮询失败`; updateWidget(); break; }
                            }
                        } catch (e) { logLines.push(`❌ [${i + 1}/${localMissing.length}] ${f.name}: ${e}`); updateWidget(); }
                    }
                    logLines.push("", `✅ 下载完成: ${okCount}/${localMissing.length} 成功`);
                    updateWidget();
                } catch (e) {
                    logLines.push(``, `❌ 异常: ${e}`);
                    widget.value = logLines.join("\n");
                    self.setDirtyCanvas(true, true);
                }
            };

            const fetchJson = async (url, opts) => {
                const r = await fetch(url, opts);
                const raw = await r.text();
                if (!r.ok) {
                    const hint = r.status === 404 ? "\n⚠ 后端路由未注册，请重启 ComfyUI 使新路由生效" : "";
                    return { __error: `HTTP ${r.status}: ${raw.slice(0, 300)}${hint}` };
                }
                try {
                    return JSON.parse(raw);
                } catch (e) {
                    return { __error: `响应非 JSON: ${raw.slice(0, 300)}\n⚠ 请重启 ComfyUI 使新后端路由生效` };
                }
            };

            const appendToManifest = async (modelInfo) => {
                try {
                    let manifest = null;
                    const raw = manifestWidget ? (manifestWidget.value || "").trim() : "";
                    if (raw) { try { manifest = JSON.parse(raw); } catch (e) { manifest = null; } }
                    if (!manifest || !Array.isArray(manifest.models)) {
                        manifest = { models: [], saved_at: new Date().toISOString() };
                    }
                    const folder = modelInfo.folder || "checkpoints";
                    const exists = manifest.models.find(m => m.name === modelInfo.name && (m.folder || "checkpoints") === folder);
                    if (!exists) {
                        manifest.models.push({
                            name: modelInfo.name,
                            direct_url: modelInfo.direct_url || "",
                            folder: folder,
                            size: modelInfo.size || 0,
                        });
                        manifest.saved_at = new Date().toISOString();
                        if (manifestWidget) {
                            manifestWidget.value = JSON.stringify(manifest);
                            self.setDirtyCanvas(true, true);
                        }
                        await fetchJson("/qibo/save_model_manifest", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify(manifest),
                        });
                    }
                } catch (e) {
                    console.warn("[QIBO] appendToManifest failed:", e);
                }
            };

            const pollInstallProgress = async (title) => {
                let logLines = [`${title}`, ""];
                const updateWidget = () => { widget.value = logLines.join("\n"); self.setDirtyCanvas(true, true); };
                while (true) {
                    await new Promise(resolve => setTimeout(resolve, 1000));
                    try {
                        const pres = await fetchJson("/qibo/install_progress");
                        if (pres.__error) {
                            logLines.push(`❌ 轮询失败: ${pres.__error}`);
                            updateWidget();
                            break;
                        }
                        const total = pres.total || 0;
                        const done = pres.done || 0;
                        const failed = pres.failed || 0;
                        const results = pres.results || [];
                        logLines = [`${title}  [${done + failed}/${total}]  ✓${done} ✗${failed}`, ""];
                        for (let i = 0; i < results.length; i++) {
                            const r2 = results[i];
                            const mark = r2.status === "ok" ? "✓" : (r2.status === "skip" ? "ℹ" : "❌");
                            logLines.push(`${mark} [${i + 1}] ${r2.class_type}`);
                            logLines.push(`    ${r2.msg || r2.status}`);
                        }
                        if (pres.status === "running" && pres.current) {
                            logLines.push("", `⏳ 正在安装: ${pres.current}`);
                        }
                        updateWidget();
                        if (pres.status === "done") {
                            logLines.push("", `✅ 安装完成: ${done} 成功, ${failed} 失败`);
                            logLines.push("⚠ 请重启 ComfyUI 后刷新浏览器使新节点生效");
                            updateWidget();
                            break;
                        }
                    } catch (e2) {
                        logLines.push(`❌ 轮询异常: ${e2}`);
                        updateWidget();
                        break;
                    }
                }
            };

            self.__qiboInstallMissingNodes = async () => {
                let logLines = ["🔧 安装缺少节点", ""];
                const updateWidget = () => { widget.value = logLines.join("\n"); self.setDirtyCanvas(true, true); };
                updateWidget();
                try {
                    const collected = collectGraphNodes();
                    logLines.push("检测工作流缺失节点中...");
                    updateWidget();
                    const res = await fetchJson("/qibo/workflow_check", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ nodes: collected.out }),
                    });
                    if (res.__error) { logLines.push(`❌ 检测失败: ${res.__error}`); updateWidget(); return; }
                    const rns = res.required_nodes || [];
                    const missing = rns.filter(n => !n.registered && n.install_url);
                    const noUrl = rns.filter(n => !n.registered && !n.install_url);
                    if (missing.length === 0) {
                        logLines.push("✅ 未检测到可安装的缺失节点");
                        if (noUrl.length > 0) {
                            logLines.push(`\n⚠ ${noUrl.length} 种节点缺 install_url（extension-node-map 未收录）:`);
                            for (const n of noUrl) logLines.push(`  ✗ ${n.class_type}`);
                        }
                        updateWidget();
                        return;
                    }
                    const seenUrl = new Set();
                    const deduped = [];
                    const merged = {};
                    for (const n of missing) {
                        if (seenUrl.has(n.install_url)) {
                            (merged[n.install_url] = merged[n.install_url] || []).push(n.class_type);
                            continue;
                        }
                        seenUrl.add(n.install_url);
                        deduped.push(n);
                    }
                    const mergedCount = missing.length - deduped.length;
                    logLines.push(`检测到 ${missing.length} 个缺失节点类型，对应 ${deduped.length} 个仓库:`);
                    for (const n of deduped) {
                        logLines.push(`  ✗ ${n.class_type}  <- ${n.install_url}`);
                        if (merged[n.install_url]) {
                            logLines.push(`       (同仓库另含: ${merged[n.install_url].join(", ")})`);
                        }
                    }
                    if (noUrl.length > 0) {
                        logLines.push(`\n⚠ 另有 ${noUrl.length} 种节点缺 install_url，无法自动安装:`);
                        for (const n of noUrl) logLines.push(`  ✗ ${n.class_type}`);
                    }
                    logLines.push("", "提交安装请求中...");
                    updateWidget();

                    const ires = await fetchJson("/qibo/install_missing_nodes", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ nodes: deduped.map(n => ({ class_type: n.class_type, install_url: n.install_url })) }),
                    });
                    if (ires.__error) { logLines.push(`❌ ${ires.__error}`); updateWidget(); return; }
                    if (ires.error) { logLines.push(`❌ ${ires.error}`); updateWidget(); return; }
                    logLines.push(`✅ 安装任务已启动 (共 ${ires.total} 个仓库)`, "");
                    updateWidget();
                    await pollInstallProgress("🔧 安装缺少节点");
                } catch (e) {
                    logLines.push(``, `❌ 异常: ${e}`);
                    updateWidget();
                }
            };

            self.__qiboInstallFromLink = async () => {
                let logLines = ["🔗 从链接安装节点", ""];
                const updateWidget = () => { widget.value = logLines.join("\n"); self.setDirtyCanvas(true, true); };
                updateWidget();
                try {
                    const rawUrls = parseRepoUrls(msRepoWidget.value || "");
                    if (rawUrls.length === 0) {
                        widget.value = "❌ 请先在左栏“魔搭仓库地址”文本框填入节点仓库链接（可多行）\n如: https://github.com/kijai/ComfyUI-KLNodePack";
                        self.setDirtyCanvas(true, true);
                        return;
                    }
                    const looksLikeNodeRepo = (u) => {
                        const l = u.toLowerCase();
                        if (l.includes("modelscope.cn")) return false;
                        if (l.includes("/resolve/") || l.includes("/blob/") || l.includes("/raw/") || l.includes("/tree/")) return false;
                        if (l.endsWith(".git")) return true;
                        if (/(github\.com|gitee\.com|gitlab\.com|bitbucket\.org|codeberg\.org)/.test(l)) return true;
                        return false;
                    };
                    const nodeUrls = rawUrls.filter(looksLikeNodeRepo);
                    const skipped = rawUrls.filter(u => !looksLikeNodeRepo(u));
                    logLines.push(`文本框共 ${rawUrls.length} 个链接:`);
                    if (nodeUrls.length === 0) {
                        logLines.push("  ❌ 未识别到节点仓库链接（github/gitee/gitlab 等）");
                        if (skipped.length > 0) {
                            logLines.push(`\n⚠ 已跳过 ${skipped.length} 个（疑似模型仓库或文件直链）:`);
                            for (const u of skipped) logLines.push(`  - ${u}`);
                        }
                        logLines.push("\n提示: 节点仓库链接形如 https://github.com/xxx/ComfyUI-xxx");
                        updateWidget();
                        return;
                    }
                    logLines.push(`  识别为节点仓库: ${nodeUrls.length} 个`);
                    for (const u of nodeUrls) logLines.push(`  ✓ ${u}`);
                    if (skipped.length > 0) {
                        logLines.push(`\n  跳过 ${skipped.length} 个非节点链接:`);
                        for (const u of skipped) logLines.push(`  - ${u}`);
                    }
                    logLines.push("", "提交安装请求中...");
                    updateWidget();

                    const nodes = nodeUrls.map(u => {
                        const base = u.replace(/\/+$/, "");
                        const name = base.split("/").pop().replace(/\.git$/i, "");
                        return { class_type: name, install_url: u };
                    });
                    const ires = await fetchJson("/qibo/install_missing_nodes", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ nodes }),
                    });
                    if (ires.__error) { logLines.push(`❌ ${ires.__error}`); updateWidget(); return; }
                    if (ires.error) { logLines.push(`❌ ${ires.error}`); updateWidget(); return; }
                    logLines.push(`✅ 安装任务已启动 (共 ${ires.total} 个仓库)`, "");
                    updateWidget();
                    await pollInstallProgress("🔗 从链接安装节点");
                } catch (e) {
                    logLines.push(``, `❌ 异常: ${e}`);
                    updateWidget();
                }
            };

            self.__qiboUpdateSelf = async () => {
                widget.value = "🔄 更新 ComfyUI-qibo 自己\n\ngit pull 中...";
                self.setDirtyCanvas(true, true);
                try {
                    const res = await fetchJson("/qibo/update_self", { method: "POST" });
                    if (res.__error) { widget.value = `❌ ${res.__error}`; self.setDirtyCanvas(true, true); return; }
                    if (res.error) { widget.value = `❌ ${res.error}`; self.setDirtyCanvas(true, true); return; }
                    const lines = ["🔄 更新 ComfyUI-qibo 自己", ""];
                    if (res.returncode === 0) {
                        lines.push("✅ git pull 成功");
                    } else {
                        lines.push(`❌ git pull 失败 (returncode=${res.returncode})`);
                    }
                    if (res.stdout && res.stdout.trim()) lines.push("", "stdout:", res.stdout.trim());
                    if (res.stderr && res.stderr.trim()) lines.push("", "stderr:", res.stderr.trim());
                    lines.push("", "⚠ 请重启 ComfyUI 使更新生效");
                    widget.value = lines.join("\n");
                } catch (e) {
                    widget.value = `🔄 更新 ComfyUI-qibo 自己\n\n❌ 异常: ${e}`;
                }
                self.setDirtyCanvas(true, true);
            };


            self.__qiboSaveManifest = async () => {
                let logLines = ["💾 保存模型清单（当前工作流用到的所有模型）", ""];
                const updateWidget = () => { widget.value = logLines.join("\n"); self.setDirtyCanvas(true, true); };
                updateWidget();
                try {
                    const collected = collectGraphNodes();
                    logLines.push("检测工作流引用的模型中...");
                    updateWidget();
                    const res = await fetchJson("/qibo/workflow_check", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ nodes: collected.out }),
                    });
                    if (res.__error) { logLines.push(`❌ 检测失败: ${res.__error}`); updateWidget(); return; }
                    const missModels = (res.missing_models || []).filter(m => m.status === "missing");
                    const presentModels = (res.present_models || []);
                    const allRef = [...missModels, ...presentModels];
                    const seen = new Set();
                    const uniqAll = [];
                    for (const m of allRef) { if (!seen.has(m.value)) { seen.add(m.value); uniqAll.push(m); } }
                    if (uniqAll.length === 0) {
                        logLines.push("❌ 未检测到工作流引用的模型");
                        updateWidget();
                        return;
                    }
                    logLines.push(`工作流引用 ${uniqAll.length} 个模型 (缺失 ${missModels.length} / 已存在 ${presentModels.length})，从仓库地址列文件匹配中...`);
                    updateWidget();
                    const rawUrls = parseRepoUrls(msRepoWidget.value || "");
                    let allFiles = [];
                    for (let u = 0; u < rawUrls.length; u++) {
                        try {
                            const lr = await fetchJson("/qibo/modelscope/list_files", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ url: rawUrls[u] }),
                            });
                            if (lr.__error || lr.error) continue;
                            allFiles = allFiles.concat(lr.files || []);
                        } catch (e) {}
                    }
                    let matched = [];
                    let unmatched = [];
                    for (const m of uniqAll) {
                        let f = allFiles.find(f => f.name === m.value);
                        if (!f) f = allFiles.find(f => f.name.includes(m.value) || m.value.includes(f.name));
                        if (f) {
                            if (!f.local_folder && m.folder) f.local_folder = m.folder;
                            matched.push({ name: f.name, direct_url: f.direct_url, folder: f.local_folder || m.folder || "checkpoints", size: f.size || 0 });
                        } else {
                            unmatched.push(m);
                        }
                    }
                    logLines.push(`匹配 ${matched.length}/${uniqAll.length} 个:`);
                    for (const m of matched) logLines.push(`  ✓ ${m.name}  [${m.folder}]  ${fmtSize(m.size)}`);
                    for (const u of unmatched) logLines.push(`  ✗ ${u.value}  未找到下载地址`);
                    updateWidget();
                    if (rawUrls.length === 0 && unmatched.length > 0) {
                        logLines.push("", "⚠ 左栏“模型地址或者节点地址”输入框为空，无法采集下载地址。");
                        logLines.push("  请在其中填入魔搭/仓库链接（可多行）后重新点“保存模型清单”来采集匹配。");
                        updateWidget();
                    }

                    const allEntries = matched.slice();
                    for (const u of unmatched) {
                        allEntries.push({ name: u.value, direct_url: "", folder: u.folder || "checkpoints", size: 0 });
                    }
                    if (allEntries.length === 0) { logLines.push("", "❌ 未识别到任何模型，无法保存清单"); updateWidget(); return; }

                    const manifest = {
                        models: allEntries,
                        saved_at: new Date().toISOString(),
                        repo_urls: rawUrls,
                    };
                    const manifestStr = JSON.stringify(manifest);
                    if (manifestWidget) {
                        manifestWidget.value = manifestStr;
                        self.setDirtyCanvas(true, true);
                    }
                    logLines.push(`\n✅ 清单已写入“恢复模型下载”文本框: 共 ${allEntries.length} 个模型（匹配 ${matched.length} / 未匹配 ${unmatched.length}）`);
                    logLines.push("别人打开此工作流后点“恢复模型下载”即可一键下载");
                    logLines.push("\n========== 保存的完整数据 ==========");
                    logLines.push(JSON.stringify(manifest, null, 2));
                    updateWidget();
                } catch (e) {
                    logLines.push(``, `❌ 异常: ${e}`);
                    updateWidget();
                }
            };

            self.__qiboRestoreDownload = async () => {
                let logLines = ["📥 恢复模型下载", ""];
                const updateWidget = () => { widget.value = logLines.join("\n"); self.setDirtyCanvas(true, true); };
                updateWidget();
                try {
                    let manifest = null;
                    const raw = manifestWidget ? (manifestWidget.value || "").trim() : "";
                    if (raw) {
                        try { manifest = JSON.parse(raw); } catch (e) { logLines.push(`❌ 工作流内清单 JSON 解析失败: ${e}`); updateWidget(); return; }
                    }
                    if (!manifest || !manifest.models || manifest.models.length === 0) {
                        logLines.push("工作流内无清单，尝试从后端文件加载...");
                        updateWidget();
                        const lr = await fetchJson("/qibo/load_model_manifest");
                        if (lr.__error) { logLines.push(`❌ ${lr.__error}`); updateWidget(); return; }
                        manifest = lr;
                    }
                    const models = (manifest && manifest.models) || [];
                    if (models.length === 0) {
                        logLines.push("❌ 无模型清单。请先点“保存模型清单”生成。");
                        updateWidget();
                        return;
                    }
                    const noUrlCount = models.filter(m => !m.direct_url).length;
                    logLines.push(`清单含 ${models.length} 个模型${noUrlCount ? ` (${noUrlCount} 个无地址将跳过)` : ""}:`);
                    for (let i = 0; i < models.length; i++) {
                        const m = models[i];
                        const mark = m.direct_url ? "⬇" : "⚠";
                        logLines.push(`  [${i + 1}] ${mark} ${m.name}`);
                        logLines.push(`      目录: ${m.folder || "checkpoints"}`);
                        logLines.push(`      地址: ${m.direct_url || "(无，需重新保存模型清单采集)"}`);
                        if (m.size) logLines.push(`      大小: ${fmtSize(m.size)}`);
                    }
                    logLines.push("", `⬇ 开始下载 ${models.length} 个模型...`, "");
                    updateWidget();

                    let okCount = 0;
                    let skipCount = 0;
                    for (let i = 0; i < models.length; i++) {
                        const m = models[i];
                        const folder = m.folder || "checkpoints";
                        const lineIdx = logLines.length;
                        if (!m.direct_url) {
                            skipCount++;
                            logLines.push(`⚠ [${i + 1}/${models.length}] ${m.name}  无下载地址，跳过`);
                            logLines.push(`    → ${folder}  (请先点“保存模型清单”采集地址)`);
                            updateWidget();
                            continue;
                        }
                        logLines.push(`⏳ [${i + 1}/${models.length}] ${m.name}`);
                        logLines.push(`    → ${folder}  准备下载...`);
                        updateWidget();
                        try {
                            const dres = await fetchJson("/qibo/modelscope/download", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ direct_url: m.direct_url, filename: m.name, folder }),
                            });
                            if (dres.__error) { logLines[lineIdx] = `❌ [${i + 1}/${models.length}] ${m.name}: ${dres.__error}`; logLines[lineIdx + 1] = ""; updateWidget(); continue; }
                            if (dres.error) { logLines[lineIdx] = `❌ [${i + 1}/${models.length}] ${m.name}: ${dres.error}`; logLines[lineIdx + 1] = ""; updateWidget(); continue; }
                            if (!dres.task_id) { logLines[lineIdx] = `❌ [${i + 1}/${models.length}] ${m.name}: 未返回 task_id`; logLines[lineIdx + 1] = ""; updateWidget(); continue; }
                            const taskId = dres.task_id;
                            const destPath = dres.dest_path || "";
                            while (true) {
                                await new Promise(r => setTimeout(r, 800));
                                const pres = await fetchJson("/qibo/modelscope/download_progress", {
                                    method: "POST",
                                    headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ task_id: taskId }),
                                });
                                if (pres.__error || pres.error || pres.status === "error") {
                                    logLines[lineIdx] = `❌ [${i + 1}/${models.length}] ${m.name}: ${pres.error || pres.__error || "失败"}`;
                                    logLines[lineIdx + 1] = "";
                                    updateWidget();
                                    break;
                                }
                                if (pres.status === "done") {
                                    okCount++;
                                    logLines[lineIdx] = `✓ [${i + 1}/${models.length}] ${m.name}  ${fmtSize(pres.downloaded)}`;
                                    logLines[lineIdx + 1] = `    → ${pres.folder || folder}  ✅ 完成`;
                                    updateWidget();
                                    break;
                                }
                                const pct = pres.total > 0 ? pres.percent.toFixed(1) : "?";
                                const dl = fmtSize(pres.downloaded);
                                const tot = pres.total > 0 ? fmtSize(pres.total) : "?";
                                const spd = fmtSize(pres.speed);
                                logLines[lineIdx] = `⏳ [${i + 1}/${models.length}] ${m.name}  ${dl}/${tot}  ${pct}%`;
                                logLines[lineIdx + 1] = `    → ${folder}  速度: ${spd}/s`;
                                updateWidget();
                            }
                        } catch (e) {
                            logLines[lineIdx] = `❌ [${i + 1}/${models.length}] ${m.name}: ${e}`;
                            logLines[lineIdx + 1] = "";
                            updateWidget();
                        }
                    }
                    logLines.push("", `✅ 下载完成: ${okCount}/${models.length} 成功${skipCount ? `, ${skipCount} 跳过(无地址)` : ""}`);
                    updateWidget();
                } catch (e) {
                    logLines.push(``, `❌ 异常: ${e}`);
                    updateWidget();
                }
            };

            self.__qiboPrintManifest = async () => {
                let logLines = ["📤 终端打印清单", ""];
                const updateWidget = () => { widget.value = logLines.join("\n"); self.setDirtyCanvas(true, true); };
                updateWidget();
                try {
                    let manifest = null;
                    const raw = manifestWidget ? (manifestWidget.value || "").trim() : "";
                    if (raw) { try { manifest = JSON.parse(raw); } catch (e) { manifest = null; } }
                    if (!manifest || !manifest.models || manifest.models.length === 0) {
                        logLines.push("工作流内无清单，从后端文件加载...");
                        updateWidget();
                        const lr = await fetchJson("/qibo/load_model_manifest");
                        if (lr.__error) { logLines.push(`❌ ${lr.__error}`); updateWidget(); return; }
                        manifest = lr;
                    }
                    const models = (manifest && manifest.models) || [];
                    if (models.length === 0) {
                        logLines.push("❌ 无清单可打印。请先保存模型清单或下载模型。");
                        updateWidget();
                        return;
                    }
                    const res = await fetchJson("/qibo/print_manifest", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ models }),
                    });
                    if (res.__error) { logLines.push(`❌ ${res.__error}`); updateWidget(); return; }
                    logLines.push(`✅ 已打印 ${models.length} 个模型到 ComfyUI 启动终端:`);
                    for (let i = 0; i < models.length; i++) {
                        const m = models[i];
                        logLines.push(`  [${i + 1}] ${m.name}  [${m.folder || "?"}]`);
                        logLines.push(`      ${m.direct_url || "(无地址)"}`);
                    }
                    logLines.push("\n请查看 ComfyUI 启动终端（控制台）输出");
                    updateWidget();
                } catch (e) {
                    logLines.push(``, `❌ 异常: ${e}`);
                    updateWidget();
                }
            };

            // === Wire up buttons ===
            makeBtnRow([
                ["1、当前流检测缺少", () => self.__qiboDetect()],
                ["2、一键下载缺少", () => self.__qiboAutoDownload()],
            ]);
            makeBtnRow([
                ["1、链接列举文件", () => self.__qiboListFiles()],
                ["2、选中批量下载", () => self.__qiboBatchDownload()],
            ]);
            makeBtnRow([
                ["1、单模型搜索", () => self.__qiboMsSearch()],
                ["2、单下载到目录", () => self.__qiboMsDownload()],
            ]);
            makeBtnRow([
                ["安装缺少节点", () => self.__qiboInstallMissingNodes()],
                ["从链接安装", () => self.__qiboInstallFromLink()],
                ["更新自己", () => self.__qiboUpdateSelf()],
            ]);
            makeBtnRow([
                ["保存模型清单", () => self.__qiboSaveManifest()],
                ["恢复模型下载", () => self.__qiboRestoreDownload()],
                ["终端打印清单", () => self.__qiboPrintManifest()],
            ]);


            return result;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            const result = onExecuted?.apply(this, arguments);
            try {
                const raw = message?.text;
                const text = Array.isArray(raw) ? raw[0] : raw;
                if (typeof text === "string" && this.__qiboWorkflowInfoWidget) {
                    this.__qiboWorkflowInfoWidget.value = text;
                    this.setDirtyCanvas(true, true);
                }
            } catch (e) {
                console.warn("[QIBO.WorkflowInfoUI] 回填失败:", e);
            }
            return result;
        };
    },
});