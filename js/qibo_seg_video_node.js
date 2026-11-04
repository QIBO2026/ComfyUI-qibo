import { app } from "/scripts/app.js";

const NODE_TYPE = "QIBOSegVideoManagerNode";

const COL_BG = "#1e1e22";
const COL_PANEL = "#25252b";
const COL_BORDER = "#3c3c44";
const COL_FG = "#e6e6e6";
const COL_DIM = "#9a9aa2";
const COL_ACCENT = "#4caf50";
const COL_BTN = "#2d2d34";
const COL_BTN_HOVER = "#3a3a44";
const COL_DANGER = "#e05555";
const FONT_CSS = "12px/1.5 ui-monospace, Consolas, 'Segoe UI', sans-serif";

function fmtSize(n) {
    n = Number(n) || 0;
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " MB";
    return (n / 1024 / 1024 / 1024).toFixed(2) + " GB";
}

function cssText(obj) {
    return Object.entries(obj).map(([k, v]) => `${k}:${v}`).join(";");
}

app.registerExtension({
    name: "QIBO.SegVideoManager",
    async beforeRegisterNodeDef(nodeType, nodeData, appInstance) {
        if (nodeData?.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            const self = this;

            const selected = new Set(); // key: folder + "/" + filename

            const container = document.createElement("div");
            container.style.cssText = cssText({
                width: "100%", height: "100%", background: COL_BG,
                color: COL_FG, "font-family": FONT_CSS, "font-size": "12px",
                display: "flex", "flex-direction": "column", "box-sizing": "border-box",
                "border-radius": "4px", overflow: "hidden",
            });

            const toolbar = document.createElement("div");
            toolbar.style.cssText = cssText({
                "flex": "0 0 auto", display: "flex", gap: "6px", padding: "6px 8px",
                "background": COL_PANEL, "border-bottom": `1px solid ${COL_BORDER}`,
                "align-items": "center", "flex-wrap": "wrap",
            });
            container.appendChild(toolbar);

            function makeBtn(text, onClick, opts) {
                opts = opts || {};
                const b = document.createElement("button");
                b.textContent = text;
                b.style.cssText = cssText({
                    background: opts.danger ? COL_DANGER : COL_BTN,
                    color: opts.danger ? "#fff" : COL_FG,
                    border: `1px solid ${COL_BORDER}`, "border-radius": "3px",
                    padding: "3px 10px", "font-size": "12px", cursor: "pointer",
                    "font-family": "inherit",
                });
                b.addEventListener("mouseenter", () => { if (!b.disabled) b.style.background = opts.danger ? "#c44" : COL_BTN_HOVER; });
                b.addEventListener("mouseleave", () => { if (!b.disabled) b.style.background = opts.danger ? COL_DANGER : COL_BTN; });
                b.addEventListener("click", () => { if (!b.disabled) onClick(); });
                toolbar.appendChild(b);
                return b;
            }

            const statusSpan = document.createElement("span");
            statusSpan.style.cssText = cssText({ color: COL_DIM, "font-size": "11px", "margin-left": "auto" });
            toolbar.appendChild(statusSpan);

            const btnRefresh = makeBtn("🔄 刷新", () => loadList());
            const btnDelete = makeBtn("🗑 删除选中", () => doDelete(), { danger: true });
            const btnConcat = makeBtn("🎬 合成视频", () => doConcat());

            const resultBox = document.createElement("div");
            resultBox.style.cssText = cssText({
                "flex": "0 0 auto", padding: "6px 8px", background: "#1a2a1a",
                "border-bottom": `1px solid ${COL_BORDER}`, display: "none",
                "font-size": "12px", color: COL_FG, "word-break": "break-all",
            });
            container.appendChild(resultBox);

            const listWrap = document.createElement("div");
            listWrap.style.cssText = cssText({
                "flex": "1 1 auto", overflow: "auto", padding: "4px 0",
                "min-height": "0",
            });
            container.appendChild(listWrap);

            function setStatus(text) { statusSpan.textContent = text; }

            function renderEmpty(msg) {
                listWrap.innerHTML = "";
                const d = document.createElement("div");
                d.style.cssText = cssText({ padding: "20px", color: COL_DIM, "text-align": "center" });
                d.textContent = msg;
                listWrap.appendChild(d);
            }

            function makeCheckbox(checked, onChange) {
                const cb = document.createElement("input");
                cb.type = "checkbox";
                cb.checked = !!checked;
                cb.style.cssText = cssText({ margin: "0 6px 0 0", cursor: "pointer", "vertical-align": "middle" });
                cb.addEventListener("change", () => onChange(cb.checked));
                return cb;
            }

            function renderList(folders) {
                listWrap.innerHTML = "";
                if (!folders || folders.length === 0) {
                    renderEmpty("暂无分段视频目录。\n分段视频导出在 output/minimax_seg_export/<时间戳>/ 下。");
                    return;
                }
                for (const fd of folders) {
                    const section = document.createElement("div");
                    section.style.cssText = cssText({
                        "border-bottom": `1px solid ${COL_BORDER}`, padding: "4px 8px",
                    });

                    const header = document.createElement("div");
                    header.style.cssText = cssText({
                        display: "flex", "align-items": "center", padding: "4px 0",
                        "border-radius": "3px",
                    });

                    const allChecked = fd.files.length > 0 && fd.files.every(f => selected.has(fd.folder + "/" + f.filename));
                    const someChecked = fd.files.some(f => selected.has(fd.folder + "/" + f.filename));
                    const cbFolder = makeCheckbox(allChecked, (checked) => {
                        for (const f of fd.files) {
                            const k = fd.folder + "/" + f.filename;
                            if (checked) selected.add(k); else selected.delete(k);
                        }
                        renderList(folders);
                    });
                    cbFolder.indeterminate = !allChecked && someChecked;
                    header.appendChild(cbFolder);

                    const folderLabel = document.createElement("span");
                    folderLabel.style.cssText = cssText({ "font-weight": "600", "margin-right": "8px" });
                    folderLabel.textContent = "📁 " + fd.folder;
                    header.appendChild(folderLabel);

                    const countLabel = document.createElement("span");
                    countLabel.style.cssText = cssText({ color: COL_DIM, "font-size": "11px" });
                    countLabel.textContent = `${fd.file_count} 个视频 · ${fmtSize(fd.total_size)}`;
                    header.appendChild(countLabel);

                    const selCount = fd.files.filter(f => selected.has(fd.folder + "/" + f.filename)).length;
                    if (selCount > 0) {
                        const selLabel = document.createElement("span");
                        selLabel.style.cssText = cssText({ color: COL_ACCENT, "font-size": "11px", "margin-left": "8px" });
                        selLabel.textContent = `(选中 ${selCount})`;
                        header.appendChild(selLabel);
                    }

                    section.appendChild(header);

                    const fileList = document.createElement("div");
                    fileList.style.cssText = cssText({ "padding-left": "20px" });
                    for (const f of fd.files) {
                        const row = document.createElement("div");
                        row.style.cssText = cssText({
                            display: "flex", "align-items": "center", padding: "2px 0",
                            "border-radius": "2px",
                        });
                        const key = fd.folder + "/" + f.filename;
                        const cb = makeCheckbox(selected.has(key), (checked) => {
                            if (checked) selected.add(key); else selected.delete(key);
                            renderList(folders);
                        });
                        row.appendChild(cb);

                        const name = document.createElement("span");
                        name.style.cssText = cssText({ "flex": "1 1 auto", "white-space": "nowrap", "overflow": "hidden", "text-overflow": "ellipsis", "margin-right": "8px" });
                        name.textContent = "🎬 " + f.filename;
                        name.title = f.filename;
                        row.appendChild(name);

                        const sz = document.createElement("span");
                        sz.style.cssText = cssText({ color: COL_DIM, "font-size": "11px", "flex-shrink": "0", "width": "80px", "text-align": "right" });
                        sz.textContent = fmtSize(f.size);
                        row.appendChild(sz);

                        fileList.appendChild(row);
                    }
                    section.appendChild(fileList);
                    listWrap.appendChild(section);
                }
                updateBtnStates();
            }

            function updateBtnStates() {
                const n = selected.size;
                btnDelete.disabled = n === 0;
                btnConcat.disabled = n === 0;
                btnDelete.style.opacity = n === 0 ? "0.5" : "1";
                btnConcat.style.opacity = n === 0 ? "0.5" : "1";
            }

            async function loadList() {
                setStatus("⏳ 加载中...");
                resultBox.style.display = "none";
                try {
                    const r = await fetch("/qibo/seg_video/list", { cache: "no-store" });
                    if (!r.ok) { setStatus(`❌ HTTP ${r.status}`); renderEmpty("加载失败"); return; }
                    const j = await r.json();
                    const folders = j.folders || [];
                    const totalFiles = folders.reduce((s, f) => s + f.file_count, 0);
                    setStatus(`共 ${folders.length} 个目录 · ${totalFiles} 个视频 · 选中 ${selected.size}`);
                    renderList(folders);
                } catch (e) {
                    setStatus(`❌ ${e}`);
                    renderEmpty("加载失败: " + e);
                }
            }

            function getSelectedItems() {
                const items = [];
                for (const k of selected) {
                    const i = k.indexOf("/");
                    if (i > 0) items.push({ folder: k.substring(0, i), filename: k.substring(i + 1) });
                }
                return items;
            }

            async function doDelete() {
                const items = getSelectedItems();
                if (items.length === 0) return;
                if (!confirm(`确认删除选中的 ${items.length} 个视频文件？此操作不可恢复。`)) return;
                setStatus("⏳ 删除中...");
                btnDelete.disabled = true;
                btnConcat.disabled = true;
                try {
                    const r = await fetch("/qibo/seg_video/delete", {
                        method: "POST", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ items }),
                    });
                    const j = await r.json();
                    if (j.ok) {
                        for (const it of items) selected.delete(it.folder + "/" + it.filename);
                        const errs = (j.errors || []).join("; ");
                        setStatus(`✅ 已删除 ${j.removed} 个${errs ? " · ⚠ " + errs : ""}`);
                        await loadList();
                    } else {
                        setStatus(`❌ ${j.error || "删除失败"}`);
                    }
                } catch (e) {
                    setStatus(`❌ ${e}`);
                }
            }

            async function doConcat() {
                const items = getSelectedItems();
                if (items.length === 0) return;
                if (!confirm(`将选中的 ${items.length} 个视频合成为一个视频？`)) return;
                setStatus("⏳ 合成中（可能耗时较长）...");
                btnDelete.disabled = true;
                btnConcat.disabled = true;
                try {
                    const r = await fetch("/qibo/seg_video/concat", {
                        method: "POST", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ items }),
                    });
                    const j = await r.json();
                    if (j.ok) {
                        setStatus(`✅ 合成完成: ${j.filename} (${fmtSize(j.size)})`);
                        resultBox.style.display = "block";
                        resultBox.innerHTML = "";
                        const label = document.createElement("div");
                        label.textContent = `✅ 合成成功: ${j.filename} (${fmtSize(j.size)})`;
                        label.style.cssText = cssText({ color: COL_ACCENT, "margin-bottom": "6px" });
                        resultBox.appendChild(label);

                        const preview = document.createElement("video");
                        preview.src = j.url;
                        preview.controls = true;
                        preview.style.cssText = cssText({ width: "100%", "max-height": "160px", "border-radius": "3px", "margin-bottom": "6px", background: "#000" });
                        resultBox.appendChild(preview);

                        const linkRow = document.createElement("div");
                        linkRow.style.cssText = cssText({ display: "flex", gap: "8px", "align-items": "center" });

                        const dl = document.createElement("a");
                        dl.href = j.url;
                        dl.download = j.filename;
                        dl.textContent = "⬇ 下载视频";
                        dl.style.cssText = cssText({
                            background: COL_ACCENT, color: "#fff", "text-decoration": "none",
                            padding: "4px 12px", "border-radius": "3px", "font-size": "12px",
                        });
                        linkRow.appendChild(dl);

                        const open = document.createElement("a");
                        open.href = j.url;
                        open.target = "_blank";
                        open.textContent = "🔗 新窗口打开";
                        open.style.cssText = cssText({
                            background: COL_BTN, color: COL_FG, "text-decoration": "none",
                            padding: "4px 12px", "border-radius": "3px", "font-size": "12px",
                            border: `1px solid ${COL_BORDER}`,
                        });
                        linkRow.appendChild(open);

                        resultBox.appendChild(linkRow);
                    } else {
                        setStatus(`❌ ${j.error || "合成失败"}`);
                        resultBox.style.display = "block";
                        resultBox.innerHTML = "";
                        const errDiv = document.createElement("div");
                        errDiv.textContent = "❌ " + (j.error || "合成失败");
                        errDiv.style.cssText = cssText({ color: COL_DANGER });
                        resultBox.appendChild(errDiv);
                    }
                } catch (e) {
                    setStatus(`❌ ${e}`);
                } finally {
                    btnDelete.disabled = false;
                    btnConcat.disabled = false;
                    updateBtnStates();
                }
            }

            const w = this.addDOMWidget("qibo_seg_video", "div", container, { serialize: false });
            const HEADER_OFFSET = 60;
            w.options.getHeight = () => Math.max(160, self.size[1] - HEADER_OFFSET);
            if (!this.size || this.size[0] < 480) this.size = [520, 560];

            const origResize = this.onResize || function () {};
            this.onResize = function () {
                origResize.apply(this, arguments);
                const h = Math.max(160, self.size[1] - HEADER_OFFSET);
                container.style.height = h + "px";
                if (self.graph) self.setDirtyCanvas(true, true);
            };
            container.style.height = Math.max(160, this.size[1] - HEADER_OFFSET) + "px";

            loadList();
            return result;
        };
    },
});