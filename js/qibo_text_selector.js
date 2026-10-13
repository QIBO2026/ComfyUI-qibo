import { app } from "/scripts/app.js";

const STYLE_ID = "qibo-text-selector-style";

function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
.qibo-ts { display:flex; flex-direction:column; gap:5px; padding:8px;
    width:100%; margin:0; box-sizing:border-box;
    background:#161620; border:1px solid #4c5565; border-radius:6px; }
.qibo-ts-label { font-size:10px; color:#8e9bb0; margin:0; }
.qibo-ts-input { width:100%; max-width:100%; min-height:60px; resize:none; background:#1e1e2e; color:#c3cad5;
    border:1px solid #4c5565; border-radius:4px; padding:4px 6px; font-size:12px;
    font-family:inherit; box-sizing:border-box; }
.qibo-ts-btn { padding:3px 12px; border:1px solid #4c5565; border-radius:4px;
    background:#282d36; color:#c3cad5; cursor:pointer; font-size:12px; box-sizing:border-box; }
.qibo-ts-btn:hover { background:#34505b; color:#fff; }
.qibo-ts-btn.danger { border-color:#6b3a3a; flex:0 0 auto; }
.qibo-ts-btn.danger:hover { background:#4a2020; color:#ff8080; }
.qibo-ts-btn[data-act="add"] { flex:1; }
.qibo-ts-btn[data-act="edit"] { flex:1; border-color:#3a5a6b; }
.qibo-ts-btn[data-act="edit"]:hover { background:#204a5b; color:#80d0ff; }
.qibo-ts-btn[data-act="clear-input"] { flex:0 0 auto; border-color:#6b5a3a; }
.qibo-ts-btn[data-act="clear-input"]:hover { background:#4a4020; color:#ffc080; }
.qibo-ts-btn[data-act="clear-all"] { width:100%; border-color:#6b5a3a; }
.qibo-ts-btn[data-act="clear-all"]:hover { background:#4a4020; color:#ffc080; }
.qibo-ts-row { display:flex; gap:6px; align-items:center; width:100%; }
.qibo-ts-select { flex:1 1 auto; min-width:0; background:#1e1e2e; color:#c3cad5;
    border:1px solid #4c5565; border-radius:4px; padding:3px 6px; font-size:12px; }
.qibo-ts-preview { background:#121220; border:1px solid #3a3f4b; border-radius:4px;
    padding:4px 6px; font-size:11px; color:#8e9bb0; min-height:22px; max-height:56px;
    overflow:auto; white-space:pre-wrap; word-break:break-all; box-sizing:border-box; }
.qibo-ts-preview.active { border:2px solid #4CAF50; color:#4CAF50; background:#1a2e1a; }
.qibo-ts-count { font-size:10px; color:#6b7a8f; text-align:right; margin:0; }
`;
    document.head.appendChild(style);
}

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

app.registerExtension({
    name: "QIBO.TextSelectorUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "QIBOTextSelectorNode") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            ensureStyle();

            const dataWidget = this.widgets?.find(w => w.name === "text_data");
            if (!dataWidget) return result;

            let savedData = dataWidget.value || '{"items":["这个是一只猫"],"selected":0}';

            const root = document.createElement("div");
            root.className = "qibo-ts";
            root.innerHTML = `
                <div class="qibo-ts-label">📝 输入文本：</div>
                <textarea class="qibo-ts-input" placeholder="输入文本，点添加加入列表..."></textarea>
                <div class="qibo-ts-row">
                    <button class="qibo-ts-btn" data-act="add">＋ 添加</button>
                    <button class="qibo-ts-btn" data-act="edit">✎ 编辑</button>
                    <button class="qibo-ts-btn" data-act="clear-input">✕ 清空</button>
                </div>
                <div class="qibo-ts-label">📋 选择输出：</div>
                <div class="qibo-ts-row">
                    <select class="qibo-ts-select"><option value="">（空）</option></select>
                    <button class="qibo-ts-btn danger" data-act="delete">删除</button>
                </div>
                <button class="qibo-ts-btn" data-act="clear-all">清空列表</button>
                <div class="qibo-ts-label">✅ 当前输出：</div>
                <div class="qibo-ts-preview">暂无选中内容</div>
                <p class="qibo-ts-count">共 0 项</p>
            `;
            const domWidget = this.addDOMWidget("qibo_ts_ui", "div", root, {
                serialize: false,
                hideOnZoom: false,
                getHeight: () => root.offsetHeight,
            });

            const stopHost = (e) => { e.stopPropagation(); };
            ["pointerdown", "mousedown", "mouseup", "click", "dblclick", "pointerup", "wheel"].forEach((evt) => {
                root.addEventListener(evt, stopHost);
            });

            root.addEventListener("focusin", () => {
                const w = this.size[0];
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        if (this.size[0] > w) this.setSize([w, this.size[1]]);
                    });
                });
            });

            const inputEl = root.querySelector(".qibo-ts-input");
            const selectEl = root.querySelector(".qibo-ts-select");
            const previewEl = root.querySelector(".qibo-ts-preview");
            const countEl = root.querySelector(".qibo-ts-count");

            const getData = () => {
                try { return JSON.parse(savedData || '{"items":[],"selected":0}') || {}; }
                catch (_) { return { items: [], selected: 0 }; }
            };
            const saveData = (data) => {
                savedData = JSON.stringify(data);
                dataWidget.value = savedData;
            };

            const refreshUI = () => {
                const data = getData();
                const items = Array.isArray(data.items) ? data.items : [];
                const sel = Math.max(0, Math.min(items.length - 1, data.selected || 0));
                if (items.length) {
                    selectEl.innerHTML = items.map((t, i) => {
                        const label = `[${i + 1}] ${t.slice(0, 50)}${t.length > 50 ? "…" : ""}`;
                        return `<option value="${i}">${escapeHtml(label)}</option>`;
                    }).join("");
                    selectEl.value = String(sel);
                    previewEl.textContent = items[sel];
                    previewEl.classList.add("active");
                } else {
                    selectEl.innerHTML = `<option value="">（空）</option>`;
                    selectEl.value = "";
                    previewEl.textContent = "暂无选中内容";
                    previewEl.classList.remove("active");
                }
                countEl.textContent = `共 ${items.length} 项`;
            };

            const syncInputFromSelected = () => {
                const data = getData();
                const items = Array.isArray(data.items) ? data.items : [];
                if (!items.length) return;
                let idx = parseInt(selectEl.value);
                if (isNaN(idx) || idx < 0 || idx >= items.length) idx = data.selected || 0;
                idx = Math.max(0, Math.min(items.length - 1, idx));
                inputEl.value = items[idx];
            };

            root.querySelector('[data-act="add"]').onclick = () => {
                const text = inputEl.value.trim();
                if (!text) return;
                const data = getData();
                if (!Array.isArray(data.items)) data.items = [];
                data.items.push(text);
                data.selected = data.items.length - 1;
                saveData(data);
                inputEl.value = "";
                refreshUI();
            };

            root.querySelector('[data-act="edit"]').onclick = () => {
                const data = getData();
                if (!Array.isArray(data.items) || !data.items.length) return;
                const text = inputEl.value.trim();
                if (!text) return;
                let idx = parseInt(selectEl.value);
                if (isNaN(idx) || idx < 0 || idx >= data.items.length) idx = data.selected || 0;
                idx = Math.max(0, Math.min(data.items.length - 1, idx));
                data.items[idx] = text;
                data.selected = idx;
                saveData(data);
                refreshUI();
            };

            root.querySelector('[data-act="clear-input"]').onclick = () => {
                inputEl.value = "";
            };

            root.querySelector('[data-act="delete"]').onclick = () => {
                const data = getData();
                if (!Array.isArray(data.items) || !data.items.length) return;
                let idx = parseInt(selectEl.value);
                if (isNaN(idx) || idx < 0 || idx >= data.items.length) idx = data.selected || 0;
                data.items.splice(idx, 1);
                data.selected = Math.max(0, Math.min(data.items.length - 1, idx));
                saveData(data);
                refreshUI();
                syncInputFromSelected();
            };

            root.querySelector('[data-act="clear-all"]').onclick = () => {
                const data = getData();
                if (!Array.isArray(data.items) || !data.items.length) return;
                data.items = [];
                data.selected = 0;
                saveData(data);
                inputEl.value = "";
                refreshUI();
            };

            selectEl.onchange = () => {
                const data = getData();
                data.selected = parseInt(selectEl.value) || 0;
                saveData(data);
                refreshUI();
                syncInputFromSelected();
            };

            const purgeOriginal = () => {
                if (!this.domNode) return false;
                let removed = false;
                this.domNode.querySelectorAll("textarea, input[type='text']").forEach(el => {
                    if (el === inputEl) return;
                    let c = el.parentElement;
                    while (c && c !== this.domNode) {
                        if (c.parentElement === this.domNode || c.parentElement?.parentElement === this.domNode) {
                            c.remove();
                            removed = true;
                            break;
                        }
                        c = c.parentElement;
                    }
                    if (!removed && el.parentElement) {
                        el.parentElement.remove();
                        removed = true;
                    }
                });
                this.domNode.querySelectorAll("label, span, .widget-label").forEach(el => {
                    if (el.textContent?.includes("text_data")) {
                        const c = el.parentElement;
                        if (c && c !== this.domNode) { c.remove(); removed = true; }
                    }
                });
                return removed;
            };

            const onSerialize = this.onSerialize;
            this.onSerialize = function (o) {
                dataWidget.value = savedData;
                const r = onSerialize?.apply(this, arguments);
                if (o) o._qibo_text_data = savedData;
                return r;
            };

            let sizeFixed = false;
            const onConfigure = this.onConfigure;
            this.onConfigure = function (o) {
                const r = onConfigure?.apply(this, arguments);
                if (o && typeof o._qibo_text_data === "string") savedData = o._qibo_text_data;
                else if (dataWidget.value) savedData = dataWidget.value;
                dataWidget.value = savedData;
                refreshUI();
                syncInputFromSelected();
                sizeFixed = false;
                requestAnimationFrame(() => {
                    if (root.parentElement) {
                        const p = root.parentElement;
                        p.style.width = "100%";
                        p.style.margin = "0";
                        p.style.padding = "0";
                        p.style.boxSizing = "border-box";
                    }
                    const domH = root.offsetHeight;
                    if (domH > 0) {
                        this.setSize([460, domH + 40]);
                        this.graph?.setDirtyCanvas?.(true, true);
                        sizeFixed = true;
                    }
                });
                return r;
            };

            const fixSizeOnce = () => {
                if (sizeFixed) return;
                requestAnimationFrame(() => {
                    const domH = root.offsetHeight;
                    if (domH > 0) {
                        this.setSize([460, domH + 40]);
                        this.graph?.setDirtyCanvas?.(true, true);
                        sizeFixed = true;
                    }
                });
            };
            const onSelected = this.onSelected;
            this.onSelected = function () {
                const r = onSelected?.apply(this, arguments);
                fixSizeOnce();
                return r;
            };

            const finalize = () => {
                if (root.parentElement) {
                    const p = root.parentElement;
                    p.style.width = "100%";
                    p.style.margin = "0";
                    p.style.padding = "0";
                    p.style.boxSizing = "border-box";
                }
                purgeOriginal();
                refreshUI();
                syncInputFromSelected();
                const domH = root.offsetHeight;
                if (domH > 0) {
                    this.setSize([460, domH + 40]);
                    this.graph?.setDirtyCanvas?.(true, true);
                    sizeFixed = true;
                }
            };
            finalize();
            requestAnimationFrame(finalize);
            requestAnimationFrame(() => requestAnimationFrame(finalize));
            setTimeout(finalize, 100);

            return result;
        };
    }
});
