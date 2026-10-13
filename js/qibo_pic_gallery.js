import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const STYLE_ID = "qibo-pic-gallery-style";
const QIBODATA_COLOR = "#39d0c8";

const NODE_GALLERY_TYPE = {
    "QIBOOutputPicGalleryNode": "output",
    "QIBOInputPicGalleryNode": "input",
};

function ensureLinkTypeColor() {
    try {
        const canvas = app.canvas;
        if (canvas && canvas.getLinkColor && !canvas._qiboLinkColorHooked) {
            const orig = canvas.getLinkColor.bind(canvas);
            canvas.getLinkColor = function (link) {
                try {
                    const node = app.graph?.getNodeById?.(link[1]);
                    if (node) {
                        const slot = node.outputs?.[link[2]];
                        if (slot && slot.type === "QIBODATA") return QIBODATA_COLOR;
                    }
                } catch (_) {}
                return orig(link);
            };
            canvas._qiboLinkColorHooked = true;
        }
    } catch (_) {}
}

function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
.qibo-pg {
    overflow: hidden;
    width: 100%;
    height: 100%;
    margin: 0;
    padding: 0;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
}

.qibo-pg-list {
    list-style: none;
    padding: 0;
    margin: 8px 0 0 0;
    flex: 1 1 auto;
    min-height: 0;
    width: 100%;
    overflow-y: auto;
    overflow-x: hidden;
    display: grid;
    grid-template-columns: 1fr 1fr;
    justify-items: center;
    gap: 8px;
    box-sizing: border-box;
}
.qibo-pg-tag {
    position: relative;
    display: block;
    margin: 0;
    padding: 4px;
    width: 180px;
    height: 180px;
    color: var(--input-text);
    background-color: var(--comfy-input-bg);
    border-radius: 8px;
    border: 2px solid var(--border-color);
    font-size: 11px;
    cursor: pointer;
    box-sizing: border-box;
    overflow: hidden;
}
.qibo-pg-tag.hide {
    display: none;
}
.qibo-pg-tag:hover {
    filter: brightness(1.2);
    border-color: var(--theme-color-light, #4c8cff);
}
.qibo-pg-tag.qibo-pg-tag-selected {
    border: 2px solid var(--theme-color-light, #4CAF50);
}
.qibo-pg-tag img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    border-radius: 4px;
    pointer-events: none;
}
.qibo-pg-tag input[type=checkbox] {
    color-adjust: exact;
    display: inline-block;
    flex-shrink: 0;
    vertical-align: middle;
    appearance: none;
    border: 2px solid var(--border-color);
    background-origin: border-box;
    padding: 0;
    width: 1rem;
    height: 1rem;
    border-radius: 4px;
    color: var(--theme-color-light);
    user-select: none;
    position: absolute;
    top: 4px;
    left: 4px;
    z-index: 2;
    margin: 0;
    cursor: pointer;
}
.qibo-pg-tag input[type=checkbox]:checked {
    border: 1px solid var(--theme-color-light);
    background-color: var(--theme-color-light);
    background-image: url("data:image/svg+xml,%3csvg viewBox='0 0 16 16' fill='white' xmlns='http://www.w3.org/2000/svg'%3e%3cpath d='M12.207 4.793a1 1 0 010 1.414l-5 5a1 1 0 01-1.414 0l-2-2a1 1 0 011.414-1.414L6.5 9.086l4.293-4.293a1 1 0 011.414 0z'/%3e%3c/svg%3e");
}
.qibo-pg-tag-index {
    position: absolute;
    top: 4px;
    right: 6px;
    font-size: 10px;
    color: #ffd;
    background: rgba(0, 0, 0, 0.65);
    padding: 0 4px;
    border-radius: 3px;
    pointer-events: none;
    z-index: 2;
}
.qibo-pg-tag-delete {
    position: absolute;
    bottom: 4px;
    right: 4px;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: rgba(255, 70, 70, 0.9);
    color: #fff;
    font-size: 15px;
    line-height: 20px;
    text-align: center;
    cursor: pointer;
    z-index: 3;
    border: none;
    padding: 0;
    opacity: 0;
    transition: opacity 0.15s;
}
.qibo-pg-tag:hover .qibo-pg-tag-delete {
    opacity: 1;
}
.qibo-pg-tag-delete:hover {
    background: rgba(255, 40, 40, 1);
}
.qibo-pg-empty {
    text-align: center;
    color: var(--descrip-text);
    font-size: 11px;
    padding: 20px 0;
    grid-column: 1 / -1;
}
#qibo-pg-show-image {
    position: fixed;
    z-index: 99999;
    max-width: 320px;
    min-width: 180px;
    background: var(--comfy-menu-bg, #1a1a2e);
    border: 1px solid var(--theme-color-light, #4c8cff);
    border-radius: 10px;
    padding: 8px 10px;
    font-size: 11px;
    color: var(--input-text);
    pointer-events: none;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.6);
    line-height: 1.5;
    display: none;
}
.qibo-pg-tip-row { margin: 2px 0; }
.qibo-pg-tip-label { color: var(--descrip-text); margin-right: 4px; }
.qibo-pg-tip-prompt {
    color: var(--input-text);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 120px;
    overflow-y: auto;
    margin-top: 2px;
}
.qibo-pg-tip-model { color: var(--theme-color-light, #80d0ff); }
.qibo-pg-tip-time { color: var(--descrip-text); font-size: 10px; }

.qibo-pg-lightbox {
    position: fixed;
    inset: 0;
    z-index: 100000;
    background: rgba(0, 0, 0, 0.92);
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: grab;
    user-select: none;
}
.qibo-pg-lightbox.dragging { cursor: grabbing; }
.qibo-pg-lightbox img {
    max-width: 90vw;
    max-height: 90vh;
    object-fit: contain;
    transform-origin: center center;
    will-change: transform;
    pointer-events: none;
}
.qibo-pg-lightbox-hint {
    position: absolute;
    bottom: 16px;
    left: 50%;
    transform: translateX(-50%);
    color: #c3cad5;
    font-size: 12px;
    background: rgba(0, 0, 0, 0.5);
    padding: 4px 12px;
    border-radius: 4px;
    pointer-events: none;
}
.qibo-pg-lightbox-close {
    position: absolute;
    top: 16px;
    right: 24px;
    color: #fff;
    font-size: 28px;
    cursor: pointer;
    pointer-events: auto;
    line-height: 1;
    opacity: 0.7;
}
.qibo-pg-lightbox-close:hover { opacity: 1; }

.qibo-pg-toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 8px;
    border-bottom: 1px solid var(--border-color);
    background: var(--comfy-input-bg);
    flex: 0 0 auto;
    box-sizing: border-box;
}
.qibo-pg-upload-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 12px;
    font-size: 12px;
    color: var(--input-text);
    background: var(--comfy-button-bg, #2a2a3e);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    cursor: pointer;
    user-select: none;
    line-height: 1.4;
    transition: filter 0.15s;
}
.qibo-pg-upload-btn:hover { filter: brightness(1.2); }
.qibo-pg-upload-btn:active { filter: brightness(0.9); }
.qibo-pg-upload-btn.disabled {
    opacity: 0.5;
    cursor: not-allowed;
    pointer-events: none;
}
.qibo-pg-upload-status {
    flex: 1 1 auto;
    font-size: 11px;
    color: var(--descrip-text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.qibo-pg-upload-status.error { color: #ff6b6b; }
.qibo-pg-upload-status.success { color: #51cf66; }
`;
    document.head.appendChild(style);
}

let _tipEl = null;
function getTipEl() {
    if (!_tipEl) {
        _tipEl = document.createElement("div");
        _tipEl.id = "qibo-pg-show-image";
        document.body.appendChild(_tipEl);
    }
    return _tipEl;
}

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function showTip(item, x, y) {
    const tip = getTipEl();
    const prompt = item.prompt || "（无提示词）";
    const model = item.model || "（未知模型）";
    const ts = item.timestamp || "";
    const size = (item.width && item.height) ? `${item.width}x${item.height}` : "";
    const ratio = item.ratio || "";
    tip.innerHTML = `
        <div class="qibo-pg-tip-row"><span class="qibo-pg-tip-label">模型:</span><span class="qibo-pg-tip-model">${escapeHtml(model)}</span></div>
        <div class="qibo-pg-tip-row"><span class="qibo-pg-tip-label">提示词:</span></div>
        <div class="qibo-pg-tip-prompt">${escapeHtml(prompt)}</div>
        ${ts ? `<div class="qibo-pg-tip-row qibo-pg-tip-time">${escapeHtml(ts)}${size ? ' · ' + escapeHtml(size) : ''}${ratio ? ' · ' + escapeHtml(ratio) : ''}</div>` : ''}
    `;
    tip.style.display = "block";
    positionTip(x, y);
}

function positionTip(x, y) {
    if (!_tipEl || _tipEl.style.display === "none") return;
    const tip = _tipEl;
    const rect = tip.getBoundingClientRect();
    let left = x + 14;
    let top = y + 14;
    if (left + rect.width > window.innerWidth - 8) left = x - rect.width - 14;
    if (top + rect.height > window.innerHeight - 8) top = y - rect.height - 14;
    if (left < 8) left = 8;
    if (top < 8) top = 8;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
}

function hideTip() {
    const tip = getTipEl();
    tip.style.display = "none";
}

let _lightboxEl = null;
function showLightbox(url) {
    if (_lightboxEl) _lightboxEl.remove();
    const box = document.createElement("div");
    box.className = "qibo-pg-lightbox";
    box.innerHTML = `
        <span class="qibo-pg-lightbox-close">&times;</span>
        <img src="${url}" alt="preview" />
        <div class="qibo-pg-lightbox-hint">滚轮缩放 · 拖动平移 · 双击关闭 · ESC 退出</div>
    `;
    document.body.appendChild(box);
    _lightboxEl = box;

    const img = box.querySelector("img");
    let scale = 1;
    let tx = 0, ty = 0;
    let dragging = false;
    let lastX = 0, lastY = 0;

    const applyTransform = () => {
        img.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
    };

    box.addEventListener("wheel", (e) => {
        e.preventDefault();
        const delta = e.deltaY < 0 ? 1.15 : 1 / 1.15;
        scale = Math.min(8, Math.max(0.2, scale * delta));
        applyTransform();
    }, { passive: false });

    box.addEventListener("pointerdown", (e) => {
        if (e.target.classList.contains("qibo-pg-lightbox-close")) return;
        dragging = true;
        lastX = e.clientX;
        lastY = e.clientY;
        box.classList.add("dragging");
        box.setPointerCapture(e.pointerId);
    });
    box.addEventListener("pointermove", (e) => {
        if (!dragging) return;
        tx += e.clientX - lastX;
        ty += e.clientY - lastY;
        lastX = e.clientX;
        lastY = e.clientY;
        applyTransform();
    });
    const endDrag = (e) => {
        dragging = false;
        box.classList.remove("dragging");
        try { box.releasePointerCapture(e.pointerId); } catch (_) {}
    };
    box.addEventListener("pointerup", endDrag);
    box.addEventListener("pointercancel", endDrag);

    const closeBox = () => {
        box.remove();
        if (_lightboxEl === box) _lightboxEl = null;
    };
    box.querySelector(".qibo-pg-lightbox-close").addEventListener("click", closeBox);
    box.addEventListener("dblclick", (e) => { e.stopPropagation(); closeBox(); });
    const onKey = (e) => {
        if (e.key === "Escape") { closeBox(); document.removeEventListener("keydown", onKey); }
    };
    document.addEventListener("keydown", onKey);
}

async function fetchGalleryItems(galleryType, limit, offset) {
    try {
        let url = `/qibo/pic_gallery/list?type=${galleryType}`;
        if (limit != null) url += `&limit=${limit}`;
        if (offset != null) url += `&offset=${offset}`;
        const resp = await api.fetchApi(url);
        if (resp.status === 200) {
            const data = await resp.json();
            return { items: data.items || [], total: data.total || 0 };
        }
    } catch (e) {
        console.warn("[QIBO] 画廊列表加载失败", e);
    }
    return { items: [], total: 0 };
}

async function uploadGalleryImage(file, subfolder) {
    const serverName = `qibo_${Date.now()}_${Math.random().toString(36).slice(2, 7)}_${file.name.replace(/[^\w.()\-\u4e00-\u9fff]+/gu, "_")}`;
    const data = new FormData();
    data.append("image", file, serverName);
    data.append("type", "input");
    data.append("subfolder", subfolder);
    data.append("overwrite", "true");
    const resp = await api.fetchApi("/upload/image", { method: "POST", body: data });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${resp.status}`);
    }
    return await resp.json();
}

function buildGalleryDOM(node, galleryType) {
    const root = document.createElement("div");
    root.className = "qibo-pg";
    root.innerHTML = `
        <ul class="qibo-pg-list"></ul>
    `;

    const stopHost = (e) => { e.stopPropagation(); };
    ["pointerdown", "mousedown", "mouseup", "click", "dblclick", "pointerup"].forEach((evt) => {
        root.addEventListener(evt, stopHost);
    });

    const list = root.querySelector(".qibo-pg-list");

    let toolbar = null;
    let uploadBtn = null;
    let clearBtn = null;
    let uploadStatus = null;
    let fileInput = null;

    if (galleryType === "input") {
        toolbar = document.createElement("div");
        toolbar.className = "qibo-pg-toolbar";

        uploadBtn = document.createElement("button");
        uploadBtn.type = "button";
        uploadBtn.className = "qibo-pg-upload-btn";
        uploadBtn.textContent = "📁 上传图片";

        clearBtn = document.createElement("button");
        clearBtn.type = "button";
        clearBtn.className = "qibo-pg-upload-btn";
        clearBtn.textContent = "🗑️ 清空";
        clearBtn.title = "清空所有图片与映射文件";

        uploadStatus = document.createElement("span");
        uploadStatus.className = "qibo-pg-upload-status";

        fileInput = document.createElement("input");
        fileInput.type = "file";
        fileInput.accept = "image/*";
        fileInput.multiple = true;
        fileInput.style.display = "none";

        toolbar.appendChild(uploadBtn);
        toolbar.appendChild(clearBtn);
        toolbar.appendChild(uploadStatus);
        toolbar.appendChild(fileInput);
        root.insertBefore(toolbar, list);

        const setUploadStatus = (text, kind) => {
            uploadStatus.textContent = text || "";
            uploadStatus.classList.remove("error", "success");
            if (kind) uploadStatus.classList.add(kind);
        };

        const handleBatchUpload = async (files) => {
            if (!files || !files.length) return;
            uploadBtn.classList.add("disabled");
            const total = files.length;
            let ok = 0;
            let fail = 0;
            for (let i = 0; i < total; i++) {
                const file = files[i];
                setUploadStatus(`上传中 (${i + 1}/${total}): ${file.name}`);
                try {
                    await uploadGalleryImage(file, "qibo_in_pic");
                    ok++;
                } catch (e) {
                    fail++;
                    console.warn(`[QIBO] 上传失败 ${file.name}:`, e.message);
                }
            }
            uploadBtn.classList.remove("disabled");
            if (fail === 0) {
                setUploadStatus(`✅ 已上传 ${ok} 张图片`, "success");
            } else {
                setUploadStatus(`⚠️ 成功 ${ok} 失败 ${fail} / 共 ${total}`, fail === total ? "error" : "success");
            }
            if (node._qiboPgRefresh) {
                await node._qiboPgRefresh();
            }
            setTimeout(() => setUploadStatus(""), 4000);
        };

        uploadBtn.onclick = () => {
            if (uploadBtn.classList.contains("disabled")) return;
            fileInput.value = "";
            fileInput.click();
        };
        fileInput.onchange = () => {
            if (fileInput.files && fileInput.files.length) {
                handleBatchUpload(Array.from(fileInput.files));
            }
        };
        clearBtn.onclick = async () => {
            if (clearBtn.classList.contains("disabled")) return;
            if (!confirm("确认清空所有图片与映射文件？此操作不可恢复。")) return;
            clearBtn.classList.add("disabled");
            setUploadStatus("清空中...");
            try {
                const resp = await api.fetchApi("/qibo/pic_gallery/clear", {
                    method: "POST",
                    body: JSON.stringify({ type: galleryType }),
                    headers: { "Content-Type": "application/json" },
                });
                if (resp.ok) {
                    const data = await resp.json().catch(() => ({}));
                    setUploadStatus(`✅ 已清空 ${data.removed ?? ""} 张图片`, "success");
                    if (node._qiboPgRefresh) await node._qiboPgRefresh();
                } else {
                    setUploadStatus(`❌ 清空失败 HTTP ${resp.status}`, "error");
                }
            } catch (err) {
                setUploadStatus(`❌ 清空异常: ${err.message}`, "error");
            }
            clearBtn.classList.remove("disabled");
            setTimeout(() => setUploadStatus(""), 4000);
        };
    }

    const PAGE_SIZE = 8;
    let currentOffset = 0;
    let totalCount = 0;
    let isLoadingMore = false;
    let loadingEl = null;

    const createTagElement = (item) => {
        const tag = document.createElement("label");
        tag.className = "qibo-pg-tag";
        tag.dataset.tag = item.prompt || "";
        tag.dataset.name = item.model || "";
        tag.dataset.filename = item.filename || "";
        tag.dataset.index = String(item.index);

        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.name = item.filename || "";
        tag.appendChild(cb);

        const img = document.createElement("img");
        const imgUrl = `/view?filename=${encodeURIComponent(item.filename)}&type=${galleryType}&subfolder=${galleryType === "output" ? "qibo_out_pic" : "qibo_in_pic"}&preview=1`;
        img.src = imgUrl;
        img.loading = "lazy";
        img.onerror = () => { img.style.opacity = "0.3"; };
        tag.appendChild(img);

        const idxLabel = document.createElement("span");
        idxLabel.className = "qibo-pg-tag-index";
        idxLabel.textContent = String(item.index);
        tag.appendChild(idxLabel);

        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "qibo-pg-tag-delete";
        delBtn.textContent = "×";
        delBtn.title = "删除此图片";
        delBtn.onclick = async (e) => {
            e.stopPropagation();
            e.preventDefault();
            if (!confirm(`确认删除 图${item.index} (${item.filename})？`)) return;
            delBtn.style.opacity = "0.4";
            try {
                const resp = await api.fetchApi("/qibo/pic_gallery/delete", {
                    method: "POST",
                    body: JSON.stringify({ type: galleryType, filename: item.filename }),
                    headers: { "Content-Type": "application/json" },
                });
                if (resp.ok) {
                    if (node._qiboPgRefresh) await node._qiboPgRefresh();
                } else {
                    console.warn("[QIBO] 删除失败", resp.status);
                }
            } catch (err) {
                console.warn("[QIBO] 删除请求异常", err);
            }
        };
        tag.appendChild(delBtn);

        cb.onclick = () => {
            tag.classList.toggle("qibo-pg-tag-selected");
        };
        tag.onmousemove = (e) => {
            if (tag.classList.contains("qibo-pg-tag-selected")) {
                showTip(item, e.clientX, e.clientY);
            }
        };
        tag.onmouseleave = () => { hideTip(); };
        tag.ondblclick = (e) => {
            e.stopPropagation();
            e.preventDefault();
            if (!item.filename) return;
            const imgUrl = `/view?filename=${encodeURIComponent(item.filename)}&type=${galleryType}&subfolder=${galleryType === "output" ? "qibo_out_pic" : "qibo_in_pic"}`;
            showLightbox(imgUrl);
        };

        return tag;
    };

    const showEmpty = () => {
        list.innerHTML = "";
        const empty = document.createElement("li");
        empty.className = "qibo-pg-empty";
        empty.textContent = "（暂无图片）";
        list.appendChild(empty);
    };

    const showLoadingIndicator = () => {
        if (!loadingEl) {
            loadingEl = document.createElement("li");
            loadingEl.className = "qibo-pg-empty";
            loadingEl.textContent = "加载中...";
            loadingEl.style.gridColumn = "1 / -1";
        }
        list.appendChild(loadingEl);
    };

    const hideLoadingIndicator = () => {
        if (loadingEl && loadingEl.parentElement) {
            loadingEl.remove();
        }
    };

    const refresh = async () => {
        try {
            const { items, total } = await fetchGalleryItems(galleryType, PAGE_SIZE, 0);
            currentOffset = items.length;
            totalCount = total;
            list.innerHTML = "";
            if (!items.length) {
                showEmpty();
                return;
            }
            items.forEach((item) => list.appendChild(createTagElement(item)));
        } catch (e) {
            console.warn("[QIBO] 画廊刷新失败", e);
        }
    };

    const debouncedRefresh = (() => {
        let timer = null;
        let pending = false;
        return async () => {
            if (timer) {
                pending = true;
                return;
            }
            await refresh();
            timer = setTimeout(async () => {
                timer = null;
                if (pending) {
                    pending = false;
                    await debouncedRefresh();
                }
            }, 300);
        };
    })();

    const loadMore = async () => {
        if (isLoadingMore || currentOffset >= totalCount) return;
        isLoadingMore = true;
        showLoadingIndicator();
        try {
            const { items, total } = await fetchGalleryItems(galleryType, PAGE_SIZE, currentOffset);
            totalCount = total;
            hideLoadingIndicator();
            items.forEach((item) => list.appendChild(createTagElement(item)));
            currentOffset += items.length;
        } catch (e) {
            console.warn("[QIBO] 加载更多失败", e);
            hideLoadingIndicator();
        }
        isLoadingMore = false;
    };

    list.addEventListener("scroll", () => {
        if (list.scrollTop + list.clientHeight >= list.scrollHeight - 50) {
            loadMore();
        }
    });

    node._qiboPgRefresh = debouncedRefresh;
    refresh();

    return root;
}

app.registerExtension({
    name: "QIBO.PicGalleryUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const galleryType = NODE_GALLERY_TYPE[nodeData.name];
        if (!galleryType) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            ensureStyle();
            ensureLinkTypeColor();

            const root = buildGalleryDOM(this, galleryType);
            this.addDOMWidget("qibo_pg_ui", "div", root, {
                serialize: false,
                hideOnZoom: false,
            });

            if (this.size?.[0] < 400) {
                this.setSize([(this.size?.[0] || 210) * 3, 520]);
            }
            if (root.parentElement) {
                const p = root.parentElement;
                p.style.width = "100%";
                p.style.height = "100%";
                p.style.margin = "0";
                p.style.padding = "0";
                p.style.boxSizing = "border-box";
            }


            return result;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function () {
            const result = onExecuted?.apply(this, arguments);
            if (this._qiboPgRefresh) {
                setTimeout(() => this._qiboPgRefresh(), 300);
            }
            return result;
        };
    },
});
api.addEventListener("executing", (e) => {
    if (e?.detail?.node_id === null || e?.detail === null) {
        app.graph?.nodes?.forEach((node) => {
            if (node._qiboPgRefresh) {
                setTimeout(() => node._qiboPgRefresh(), 600);
            }
        });
    }
});
api.addEventListener("qibo_pic_gallery_update", (e) => {
    const data = e?.detail;
    if (!data) return;
    const updateType = data.type;
    app.graph?.nodes?.forEach((node) => {
        const nodeType = NODE_GALLERY_TYPE[node.type];
        if (nodeType === updateType && node._qiboPgRefresh) {
            setTimeout(() => node._qiboPgRefresh(), 200);
        }
    });
});
api.addEventListener("qibo_batch_progress", (e) => {
    const data = e?.detail;
    if (!data) return;
    const status = data.status;
    if (status !== "done" && status !== "error") return;
    app.graph?.nodes?.forEach((node) => {
        if (NODE_GALLERY_TYPE[node.type] === "output" && node._qiboPgRefresh) {
            setTimeout(() => node._qiboPgRefresh(), 300);
        }
    });
});
