import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const STYLE_ID = "qibo-pano-gallery-style";
const SUBFOLDER = "qibo_changtu";
const NODE_NAME = "QIBOPanoramaGalleryNode";

function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
.qibo-pano {
    overflow: hidden;
    width: 100%;
    height: 100%;
    margin: 0;
    padding: 0;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
}

.qibo-pano-list {
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
.qibo-pano-tag {
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
.qibo-pano-tag.hide {
    display: none;
}
.qibo-pano-tag:hover {
    filter: brightness(1.2);
    border-color: var(--theme-color-light, #4c8cff);
}
.qibo-pano-tag.qibo-pano-tag-selected {
    border: 2px solid var(--theme-color-light, #4CAF50);
}
.qibo-pano-tag img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
    border-radius: 4px;
    pointer-events: none;
}
.qibo-pano-tag-index {
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
.qibo-pano-tag-delete {
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
.qibo-pano-tag:hover .qibo-pano-tag-delete {
    opacity: 1;
}
.qibo-pano-tag-delete:hover {
    background: rgba(255, 40, 40, 1);
}
.qibo-pano-tag-cb {
    position: absolute;
    top: 4px;
    left: 4px;
    width: 22px;
    height: 22px;
    border-radius: 4px;
    border: 2px solid var(--border-color);
    background: rgba(0, 0, 0, 0.5);
    cursor: pointer;
    z-index: 3;
    padding: 0;
    margin: 0;
    appearance: none;
    -webkit-appearance: none;
    opacity: 0;
    transition: opacity 0.15s;
    display: flex;
    align-items: center;
    justify-content: center;
}
.qibo-pano-tag:hover .qibo-pano-tag-cb {
    opacity: 1;
}
.qibo-pano-tag-cb:checked {
    border-color: var(--theme-color-light, #4CAF50);
    background: var(--theme-color-light, #4CAF50);
    opacity: 1;
}
.qibo-pano-tag-cb:checked::after {
    content: "✓";
    color: #fff;
    font-size: 14px;
    font-weight: bold;
    line-height: 1;
}
.qibo-pano-empty {
    text-align: center;
    color: var(--descrip-text);
    font-size: 11px;
    padding: 20px 0;
    grid-column: 1 / -1;
}
#qibo-pano-show-image {
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
.qibo-pano-tip-row { margin: 2px 0; }
.qibo-pano-tip-label { color: var(--descrip-text); margin-right: 4px; }
.qibo-pano-tip-prompt {
    color: var(--input-text);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 120px;
    overflow-y: auto;
    margin-top: 2px;
}
.qibo-pano-tip-model { color: var(--theme-color-light, #80d0ff); }
.qibo-pano-tip-time { color: var(--descrip-text); font-size: 10px; }

.qibo-pano-lightbox {
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
.qibo-pano-lightbox.dragging { cursor: grabbing; }
.qibo-pano-lightbox img {
    max-width: 90vw;
    max-height: 90vh;
    object-fit: contain;
    transform-origin: center center;
    will-change: transform;
    pointer-events: none;
}
.qibo-pano-lightbox-hint {
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
.qibo-pano-lightbox-close {
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
.qibo-pano-lightbox-close:hover { opacity: 1; }

.qibo-pano-toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 8px;
    border-bottom: 1px solid var(--border-color);
    background: var(--comfy-input-bg);
    flex: 0 0 auto;
    box-sizing: border-box;
}
.qibo-pano-btn {
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
.qibo-pano-btn:hover { filter: brightness(1.2); }
.qibo-pano-btn:active { filter: brightness(0.9); }
.qibo-pano-btn.disabled {
    opacity: 0.5;
    cursor: not-allowed;
    pointer-events: none;
}
.qibo-pano-status {
    flex: 1 1 auto;
    font-size: 11px;
    color: var(--descrip-text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.qibo-pano-status.error { color: #ff6b6b; }
.qibo-pano-status.success { color: #51cf66; }

`;
    document.head.appendChild(style);
}

let _tipEl = null;
function getTipEl() {
    if (!_tipEl) {
        _tipEl = document.createElement("div");
        _tipEl.id = "qibo-pano-show-image";
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
    const prompt = item.prompt || item.seg_prompt || "（无提示词）";
    const model = item.model || "（未知模型）";
    const ts = item.timestamp || "";
    const size = (item.width && item.height) ? `${item.width}x${item.height}` : "";
    const ratio = item.ratio || "";
    const segDesc = item.seg_desc || "";
    const negPrompt = item.negative_prompt || "";
    let descHtml = "";
    if (segDesc) {
        let descText = segDesc;
        if (descText.startsWith("{")) {
            try {
                const obj = JSON.parse(descText);
                if (obj && obj.title) descText = obj.title;
            } catch (_) {}
        }
        if (descText.length > 200) descText = descText.substring(0, 200) + "...";
        descHtml = `<div class="qibo-pano-tip-row"><span class="qibo-pano-tip-label">描述:</span> ${escapeHtml(descText)}</div>`;
    }
    tip.innerHTML = `
        <div class="qibo-pano-tip-row"><span class="qibo-pano-tip-label">模型:</span><span class="qibo-pano-tip-model">${escapeHtml(model)}</span></div>
        ${descHtml}
        <div class="qibo-pano-tip-row"><span class="qibo-pano-tip-label">提示词:</span></div>
        <div class="qibo-pano-tip-prompt">${escapeHtml(prompt)}</div>
        ${negPrompt ? `<div class="qibo-pano-tip-row"><span class="qibo-pano-tip-label">负面:</span> ${escapeHtml(negPrompt)}</div>` : ''}
        ${ts ? `<div class="qibo-pano-tip-row qibo-pano-tip-time">${escapeHtml(ts)}${size ? ' · ' + escapeHtml(size) : ''}${ratio ? ' · ' + escapeHtml(ratio) : ''}</div>` : ''}
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
    box.className = "qibo-pano-lightbox";
    box.innerHTML = `
        <span class="qibo-pano-lightbox-close">&times;</span>
        <img src="${url}" alt="preview" />
        <div class="qibo-pano-lightbox-hint">滚轮缩放 · 拖动平移 · 双击关闭 · ESC 退出</div>
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
        if (e.target.classList.contains("qibo-pano-lightbox-close")) return;
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
    box.querySelector(".qibo-pano-lightbox-close").addEventListener("click", closeBox);
    box.addEventListener("dblclick", (e) => { e.stopPropagation(); closeBox(); });
    const onKey = (e) => {
        if (e.key === "Escape") { closeBox(); document.removeEventListener("keydown", onKey); }
    };
    document.addEventListener("keydown", onKey);
}

async function fetchGalleryItems(limit, offset) {
    try {
        let url = `/qibo/panorama_gallery/list`;
        const params = [];
        if (limit != null) params.push(`limit=${limit}`);
        if (offset != null) params.push(`offset=${offset}`);
        if (params.length) url += `?${params.join("&")}`;
        const resp = await api.fetchApi(url);
        if (resp.status === 200) {
            const data = await resp.json();
            return { items: data.items || [], total: data.total || 0 };
        }
    } catch (e) {
        console.warn("[QIBO 超长图画廊] 列表加载失败", e);
    }
    return { items: [], total: 0 };
}

function buildGalleryDOM(node) {
    const root = document.createElement("div");
    root.className = "qibo-pano";
    root.innerHTML = `
        <ul class="qibo-pano-list"></ul>
    `;

    const stopHost = (e) => { e.stopPropagation(); };
    ["pointerdown", "mousedown", "mouseup", "click", "dblclick", "pointerup"].forEach((evt) => {
        root.addEventListener(evt, stopHost);
    });

    const list = root.querySelector(".qibo-pano-list");
    const selectedOrder = [];


    const toolbar = document.createElement("div");
    toolbar.className = "qibo-pano-toolbar";

    const refreshBtn = document.createElement("button");
    refreshBtn.type = "button";
    refreshBtn.className = "qibo-pano-btn";
    refreshBtn.textContent = "🔄 刷新";

    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.className = "qibo-pano-btn";
    clearBtn.textContent = "🗑️ 清空";
    clearBtn.title = "清空 output/qibo_changtu 目录下所有图片";

    const regenBtn = document.createElement("button");
    regenBtn.type = "button";
    regenBtn.className = "qibo-pano-btn";
    regenBtn.textContent = "🔁 选中生成";
    regenBtn.title = "把选中的图片依次重新生成，新图片不覆盖原图";

    const stitchBtn = document.createElement("button");
    stitchBtn.type = "button";
    stitchBtn.className = "qibo-pano-btn";
    stitchBtn.textContent = "📐 选中拼接";
    stitchBtn.title = "按选中顺序把首图+选中图片直接拼成超长图，保存到画廊";

    const statusEl = document.createElement("span");
    statusEl.className = "qibo-pano-status";

    toolbar.appendChild(refreshBtn);
    toolbar.appendChild(clearBtn);
    toolbar.appendChild(regenBtn);
    toolbar.appendChild(stitchBtn);

    toolbar.appendChild(statusEl);
    root.insertBefore(toolbar, list);

    const setStatus = (text, kind) => {
        statusEl.textContent = text || "";
        statusEl.classList.remove("error", "success");
        if (kind) statusEl.classList.add(kind);
    };

    const PAGE_SIZE = 8;
    let currentOffset = 0;
    let totalCount = 0;
    let isLoadingMore = false;
    let loadingEl = null;

    const createTagElement = (item) => {
        const tag = document.createElement("div");
        tag.className = "qibo-pano-tag";
        tag.dataset.tag = item.prompt || "";
        tag.dataset.name = item.model || "";
        tag.dataset.filename = item.filename || "";
        tag.dataset.index = String(item.index);

        const img = document.createElement("img");
        const imgUrl = `/view?filename=${encodeURIComponent(item.filename)}&type=output&subfolder=${SUBFOLDER}&preview=1`;
        img.src = imgUrl;
        img.loading = "lazy";
        img.onerror = () => { img.style.opacity = "0.3"; };
        tag.appendChild(img);

        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.className = "qibo-pano-tag-cb";
        cb.title = "选中此图片";
        tag.appendChild(cb);

        const idxLabel = document.createElement("span");
        idxLabel.className = "qibo-pano-tag-index";
        idxLabel.textContent = String(item.index);
        tag.appendChild(idxLabel);

        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "qibo-pano-tag-delete";
        delBtn.textContent = "×";
        delBtn.title = "删除此图片";
        delBtn.onclick = async (e) => {
            e.stopPropagation();
            e.preventDefault();
            if (!confirm(`确认删除 图${item.index} (${item.filename})？`)) return;
            delBtn.style.opacity = "0.4";
            try {
                const resp = await api.fetchApi("/qibo/panorama_gallery/delete", {
                    method: "POST",
                    body: JSON.stringify({ filename: item.filename }),
                    headers: { "Content-Type": "application/json" },
                });
                if (resp.ok) {
                    if (node._qiboPanoRefresh) await node._qiboPanoRefresh();
                } else {
                    console.warn("[QIBO 超长图画廊] 删除失败", resp.status);
                }
            } catch (err) {
                console.warn("[QIBO 超长图画廊] 删除请求异常", err);
            }
        };
        tag.appendChild(delBtn);

        const updateSelection = (checked) => {
            if (checked) {
                if (!selectedOrder.includes(item.filename)) selectedOrder.push(item.filename);
            } else {
                const idx = selectedOrder.indexOf(item.filename);
                if (idx >= 0) selectedOrder.splice(idx, 1);
            }
        };

        tag.onclick = () => {
            if (tag._clickTimer) {
                clearTimeout(tag._clickTimer);
                tag._clickTimer = null;
                return;
            }
            tag._clickTimer = setTimeout(() => {
                tag._clickTimer = null;
                cb.checked = !cb.checked;
                tag.classList.toggle("qibo-pano-tag-selected", cb.checked);
                updateSelection(cb.checked);
            }, 250);
        };
        cb.onclick = (e) => {
            e.stopPropagation();
            tag.classList.toggle("qibo-pano-tag-selected", cb.checked);
            updateSelection(cb.checked);
        };
        tag.onmousemove = (e) => {
            showTip(item, e.clientX, e.clientY);
        };
        tag.onmouseleave = () => { hideTip(); };
        tag.ondblclick = (e) => {
            e.stopPropagation();
            e.preventDefault();
            if (tag._clickTimer) {
                clearTimeout(tag._clickTimer);
                tag._clickTimer = null;
            }
            if (!item.filename) return;
            const imgUrl = `/view?filename=${encodeURIComponent(item.filename)}&type=output&subfolder=${SUBFOLDER}`;
            showLightbox(imgUrl);
        };

        return tag;
    };

    const showEmpty = () => {
        list.innerHTML = "";
        const empty = document.createElement("li");
        empty.className = "qibo-pano-empty";
        empty.textContent = "（暂无图片）请将超长图生成结果保存到 output/qibo_changtu 目录";
        list.appendChild(empty);
    };

    const showLoadingIndicator = () => {
        if (!loadingEl) {
            loadingEl = document.createElement("li");
            loadingEl.className = "qibo-pano-empty";
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
            const { items, total } = await fetchGalleryItems(PAGE_SIZE, 0);
            currentOffset = items.length;
            totalCount = total;
            list.innerHTML = "";
            selectedOrder.length = 0;
            if (!items.length) {
                showEmpty();
                setStatus(`共 0 张图片 (output/${SUBFOLDER})`);
                return;
            }
            items.forEach((item) => list.appendChild(createTagElement(item)));
            setStatus(`共 ${total} 张图片 (output/${SUBFOLDER})`);
        } catch (e) {
            console.warn("[QIBO 超长图画廊] 刷新失败", e);
            setStatus(`加载失败: ${e.message}`, "error");
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
            const { items, total } = await fetchGalleryItems(PAGE_SIZE, currentOffset);
            totalCount = total;
            hideLoadingIndicator();
            items.forEach((item) => list.appendChild(createTagElement(item)));
            currentOffset += items.length;
        } catch (e) {
            console.warn("[QIBO 超长图画廊] 加载更多失败", e);
            hideLoadingIndicator();
        }
        isLoadingMore = false;
    };

    list.addEventListener("scroll", () => {
        if (list.scrollTop + list.clientHeight >= list.scrollHeight - 50) {
            loadMore();
        }
    });


    refreshBtn.onclick = () => debouncedRefresh();

    clearBtn.onclick = async () => {
        if (clearBtn.classList.contains("disabled")) return;
        if (!confirm("确认清空 output/qibo_changtu 目录下所有图片？此操作不可恢复。")) return;
        clearBtn.classList.add("disabled");
        setStatus("清空中...");
        try {
            const resp = await api.fetchApi("/qibo/panorama_gallery/clear", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
            });
            if (resp.ok) {
                const data = await resp.json().catch(() => ({}));
                setStatus(`✅ 已清空 ${data.removed ?? ""} 张图片`, "success");
                if (node._qiboPanoRefresh) await node._qiboPanoRefresh();
            } else {
                setStatus(`❌ 清空失败 HTTP ${resp.status}`, "error");
            }
        } catch (err) {
            setStatus(`❌ 清空异常: ${err.message}`, "error");
        }
        clearBtn.classList.remove("disabled");
        setTimeout(() => setStatus(""), 4000);
    };

    regenBtn.onclick = async () => {
        if (regenBtn.classList.contains("disabled")) return;
        const selectedTags = list.querySelectorAll(".qibo-pano-tag.qibo-pano-tag-selected");
        let filenames = [];
        selectedTags.forEach((tag) => {
            const fname = tag.dataset.filename;
            if (fname) filenames.push(fname);
        });
        if (!filenames.length) {
            setStatus("❌ 请先点击选中要重新生成的图片", "error");
            setTimeout(() => setStatus(""), 3000);
            return;
        }
        const _pjCnt = filenames.filter(f => f.startsWith("pj_")).length;
        filenames = filenames.filter(f => !f.startsWith("pj_"));
        if (!filenames.length) {
            setStatus("❌ 选中的全是拼接图(pj_)，不能对拼接图重新生成", "error");
            setTimeout(() => setStatus(""), 4000);
            return;
        }
        if (!confirm(`确认重新生成选中的 ${filenames.length} 张图片？${_pjCnt ? `（已自动过滤 ${_pjCnt} 张拼接图）` : ""}\n新图片不会覆盖原图，文件名后加时间戳。`)) return;
        regenBtn.classList.add("disabled");
        setStatus(`重新生成中 (0/${filenames.length})...`);
        try {
            const resp = await api.fetchApi("/qibo/panorama_gallery/regenerate", {
                method: "POST",
                body: JSON.stringify({ filenames }),
                headers: { "Content-Type": "application/json" },
            });
            if (resp.ok) {
                const data = await resp.json().catch(() => ({}));
                const saved = data.saved || 0;
                const failed = filenames.length - saved;
                if (failed === 0) {
                    setStatus(`✅ 已重新生成 ${saved} 张图片`, "success");
                } else {
                    setStatus(`⚠️ 成功 ${saved} 失败 ${failed} / 共 ${filenames.length}`, "error");
                }
                if (node._qiboPanoRefresh) await node._qiboPanoRefresh();
            } else {
                const errData = await resp.json().catch(() => ({}));
                setStatus(`❌ 生成失败: ${errData.error || resp.status}`, "error");
            }
        } catch (err) {
            setStatus(`❌ 生成异常: ${err.message}`, "error");
        }
        regenBtn.classList.remove("disabled");
        setTimeout(() => setStatus(""), 6000);
    };

    stitchBtn.onclick = async () => {
        if (!selectedOrder.length) {
            setStatus("❌ 请先点击选中要拼接的图片（按点击顺序排列）", "error");
            setTimeout(() => setStatus(""), 3000);
            return;
        }
        const _pjCnt = selectedOrder.filter(f => f.startsWith("pj_")).length;
        const stitchNames = selectedOrder.filter(f => !f.startsWith("pj_"));
        if (!stitchNames.length) {
            setStatus("❌ 选中的全是拼接图(pj_)，不能对拼接图再拼接", "error");
            setTimeout(() => setStatus(""), 4000);
            return;
        }
        if (!confirm(`确认把首图 + 选中的 ${stitchNames.length} 张图片按选中顺序拼成超长图？${_pjCnt ? `（已自动过滤 ${_pjCnt} 张拼接图）` : ""}`)) return;
        stitchBtn.classList.add("disabled");
        setStatus("拼接中...");
        try {
            const resp = await api.fetchApi("/qibo/panorama_gallery/stitch_selected", {
                method: "POST",
                body: JSON.stringify({ filenames: stitchNames, crop_top: 0, cache_id: "default" }),
                headers: { "Content-Type": "application/json" },
            });
            const data = await resp.json().catch(() => ({}));
            if (resp.ok && data.ok) {
                setStatus(`✅ 拼接完成：首图+${data.count}张选中图，${data.width}x${data.height}，已保存到画廊`, "success");
                if (node._qiboPanoRefresh) await node._qiboPanoRefresh();
            } else {
                setStatus(`❌ 拼接失败: ${data.error || resp.status}`, "error");
            }
        } catch (err) {
            setStatus(`❌ 拼接异常: ${err.message}`, "error");
        }
        stitchBtn.classList.remove("disabled");
        setTimeout(() => setStatus(""), 8000);
    };

    node._qiboPanoRefresh = debouncedRefresh;
    debouncedRefresh();

    return root;
}

app.registerExtension({
    name: "QIBO.PanoramaGalleryUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            ensureStyle();

            const root = buildGalleryDOM(this);
            this.addDOMWidget("qibo_pano_gallery_ui", "div", root, {
                serialize: false,
                hideOnZoom: false,
            });

            this.widgets?.forEach((w) => {
                if (w.name === "info" || w.name === "selected_files") {
                    w.hidden = true;
                    w.computeSize = () => [0, -4];
                    if (w.element) w.element.style.display = "none";
                    if (w.inputEl) w.inputEl.style.display = "none";
                    if (w.lastElement) w.lastElement.style.display = "none";
                }
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
            if (this._qiboPanoRefresh) {
                setTimeout(() => this._qiboPanoRefresh(), 300);
            }
            return result;
        };
    },
});
api.addEventListener("executing", (e) => {
    if (e?.detail?.node_id === null || e?.detail === null) {
        app.graph?.nodes?.forEach((node) => {
            if (node._qiboPanoRefresh) {
                setTimeout(() => node._qiboPanoRefresh(), 600);
            }
        });
    }
});
api.addEventListener("qibo_panorama_gallery_update", (e) => {
    app.graph?.nodes?.forEach((node) => {
        if (node.type === NODE_NAME && node._qiboPanoRefresh) {
            setTimeout(() => node._qiboPanoRefresh(), 200);
        }
    });
});
