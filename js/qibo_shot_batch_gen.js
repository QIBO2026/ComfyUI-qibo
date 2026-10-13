import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const STYLE_ID = "qibo-shot-batch-gen-style";
const NODE_NAMES = ["QIBOBatchImageEditNode"];
const CANCEL_ENDPOINTS = {
    "QIBOBatchImageEditNode": "/qibo/batch_edit/cancel",
};

function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
.qibo-sbg {
    width: 100%;
    box-sizing: border-box;
    padding: 6px 8px;
    display: flex;
    flex-direction: column;
    gap: 6px;
}
.qibo-sbg-row { display: flex; align-items: center; gap: 8px; }
.qibo-sbg-progress {
    flex: 1 1 auto; font-size: 12px; color: var(--input-text);
    background: var(--comfy-input-bg, #1e1e2e); border: 1px solid var(--border-color);
    border-radius: 4px; padding: 4px 8px; min-height: 22px; line-height: 1.4;
    overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
}
.qibo-sbg-progress .qibo-sbg-shot { color: #4CAF50; font-weight: bold; }
.qibo-sbg-progress .qibo-sbg-title { color: var(--input-text); margin-left: 6px; }
.qibo-sbg-progress .qibo-sbg-count { color: var(--descrip-text); margin-left: 6px; font-size: 11px; }
.qibo-sbg-progress.idle .qibo-sbg-shot { color: var(--descrip-text); font-weight: normal; }
.qibo-sbg-progress.error .qibo-sbg-shot { color: #ff6b6b; }
.qibo-sbg-progress.done .qibo-sbg-shot { color: #51cf66; }
.qibo-sbg-cancel-btn {
    flex: 0 0 auto; padding: 4px 14px; font-size: 12px; color: #ff6b6b;
    background: var(--comfy-button-bg, #2a2a3e); border: 1px solid #6b3a3a;
    border-radius: 4px; cursor: pointer; user-select: none; line-height: 1.4;
}
.qibo-sbg-cancel-btn:hover { background: #4a2020; color: #ff8080; }
.qibo-sbg-cancel-btn.disabled { opacity: 0.4; cursor: not-allowed; pointer-events: none; }
.qibo-sbg-recover-btn {
    flex: 0 0 auto; padding: 4px 14px; font-size: 12px; color: #4CAF50;
    background: var(--comfy-button-bg, #2a2a3e); border: 1px solid #3a6b3a;
    border-radius: 4px; cursor: pointer; user-select: none; line-height: 1.4;
}
.qibo-sbg-recover-btn:hover { background: #1a3a1a; color: #80ff80; }
.qibo-sbg-recover-btn.disabled { opacity: 0.4; cursor: not-allowed; pointer-events: none; }
.qibo-sbg-clear-btn {
    flex: 0 0 auto; padding: 4px 10px; font-size: 11px; color: var(--descrip-text);
    background: var(--comfy-button-bg, #2a2a3e); border: 1px solid var(--border-color);
    border-radius: 4px; cursor: pointer; user-select: none; line-height: 1.4;
}
.qibo-sbg-clear-btn:hover { filter: brightness(1.2); }
.qibo-sbg-bar { width: 100%; height: 4px; background: var(--border-color); border-radius: 2px; overflow: hidden; }
.qibo-sbg-bar-fill { height: 100%; background: #4CAF50; border-radius: 2px; transition: width 0.3s; width: 0%; }
`;
    document.head.appendChild(style);
}

function buildProgressDOM(node, cancelEndpoint) {
    const root = document.createElement("div");
    root.className = "qibo-sbg";

    const row = document.createElement("div");
    row.className = "qibo-sbg-row";

    const progress = document.createElement("div");
    progress.className = "qibo-sbg-progress idle";
    progress.innerHTML = `<span class="qibo-sbg-shot">待生成</span>`;

    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "qibo-sbg-cancel-btn disabled";
    cancelBtn.textContent = "取消";

    const recoverBtn = document.createElement("button");
    recoverBtn.type = "button";
    recoverBtn.className = "qibo-sbg-recover-btn";
    recoverBtn.textContent = "恢复";
    recoverBtn.title = "用已保存的 task_id 恢复未完成的任务";

    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.className = "qibo-sbg-clear-btn";
    clearBtn.textContent = "清空";
    clearBtn.title = "清空任务记录";

    row.appendChild(progress);
    row.appendChild(cancelBtn);
    row.appendChild(recoverBtn);
    row.appendChild(clearBtn);

    const bar = document.createElement("div");
    bar.className = "qibo-sbg-bar";
    const barFill = document.createElement("div");
    barFill.className = "qibo-sbg-bar-fill";
    bar.appendChild(barFill);

    root.appendChild(row);
    root.appendChild(bar);

    const stopHost = (e) => { e.stopPropagation(); };
    ["pointerdown", "mousedown", "mouseup", "click", "dblclick", "pointerup"].forEach((evt) => {
        root.addEventListener(evt, stopHost);
    });

    cancelBtn.onclick = async () => {
        if (cancelBtn.classList.contains("disabled")) return;
        try {
            await api.fetchApi(cancelEndpoint, { method: "POST" });
            cancelBtn.classList.add("disabled");
            cancelBtn.textContent = "取消中...";
        } catch (e) {
            console.warn("[QIBO] 取消请求失败", e);
        }
    };

    const getApiTokens = () => {
        const w = node.widgets?.find((w) => w.name === "api_tokens");
        return w?.value || "";
    };

    recoverBtn.onclick = async () => {
        if (recoverBtn.classList.contains("disabled")) return;
        if (!confirm("确认恢复未完成的任务？将用已保存的 task_id 重新轮询获取结果。")) return;
        recoverBtn.classList.add("disabled");
        recoverBtn.textContent = "恢复中...";
        cancelBtn.classList.remove("disabled");
        cancelBtn.textContent = "停止";
        try {
            const resp = await api.fetchApi("/qibo/batch_edit/recover", {
                method: "POST",
                body: JSON.stringify({ api_tokens: getApiTokens() }),
                headers: { "Content-Type": "application/json" },
            });
            const data = await resp.json();
            if (!data.ok) {
                alert(data.error || "恢复失败");
                recoverBtn.classList.remove("disabled");
                recoverBtn.textContent = "恢复";
                cancelBtn.classList.add("disabled");
                cancelBtn.textContent = "取消";
            }
        } catch (e) {
            console.warn("[QIBO] 恢复请求失败", e);
            recoverBtn.classList.remove("disabled");
            recoverBtn.textContent = "恢复";
            cancelBtn.classList.add("disabled");
            cancelBtn.textContent = "取消";
        }
    };


    cancelBtn.onclick = async () => {
        if (cancelBtn.textContent === "停止") {
            try {
                await api.fetchApi("/qibo/batch_edit/recover_cancel", { method: "POST" });
            } catch (e) { console.warn("[QIBO] 停止恢复失败", e); }
            cancelBtn.classList.add("disabled");
            cancelBtn.textContent = "取消";
            recoverBtn.classList.remove("disabled");
            recoverBtn.textContent = "恢复";
            return;
        }
        if (cancelBtn.classList.contains("disabled")) return;
        try {
            await api.fetchApi(cancelEndpoint, { method: "POST" });
            cancelBtn.classList.add("disabled");
            cancelBtn.textContent = "取消中...";
        } catch (e) {
            console.warn("[QIBO] 取消请求失败", e);
        }
    };

    clearBtn.onclick = async () => {
        if (!confirm("确认清空所有任务记录？")) return;
        try {
            await api.fetchApi("/qibo/batch_edit/clear_tasks", { method: "POST" });
            clearBtn.textContent = "已清空";
            setTimeout(() => { clearBtn.textContent = "清空"; }, 2000);
        } catch (e) {
            console.warn("[QIBO] 清空任务记录失败", e);
        }
    };

    node._qiboSbgUpdate = (data) => {
        const { shot_id, title, current, total, status } = data;
        progress.classList.remove("idle", "error", "done");
        if (status === "generating") {
            progress.innerHTML = `<span class="qibo-sbg-shot">${shot_id}</span><span class="qibo-sbg-title">${title}</span><span class="qibo-sbg-count">[${current}/${total}]</span>`;
            cancelBtn.classList.remove("disabled");
            cancelBtn.textContent = "取消";
            if (total > 0) barFill.style.width = `${((current - 1) / total) * 100}%`;
        } else if (status === "done") {
            progress.innerHTML = `<span class="qibo-sbg-shot">${shot_id}</span><span class="qibo-sbg-title">${title}</span><span class="qibo-sbg-count">[${current}/${total}] ✅</span>`;
            if (total > 0) barFill.style.width = `${(current / total) * 100}%`;
        } else if (status === "error") {
            progress.classList.add("error");
            progress.innerHTML = `<span class="qibo-sbg-shot">${shot_id}</span><span class="qibo-sbg-title">${title}</span><span class="qibo-sbg-count">[${current}/${total}] ❌</span>`;
        } else if (status === "cancelled") {
            progress.classList.add("error");
            progress.innerHTML = `<span class="qibo-sbg-shot">已取消</span><span class="qibo-sbg-count">[${current}/${total}]</span>`;
            cancelBtn.classList.add("disabled");
            cancelBtn.textContent = "取消";
            recoverBtn.classList.remove("disabled");
            recoverBtn.textContent = "恢复";
        } else if (status === "finished") {
            progress.classList.add("done");
            progress.innerHTML = `<span class="qibo-sbg-shot">完成</span><span class="qibo-sbg-count">共 ${current} 张</span>`;
            cancelBtn.classList.add("disabled");
            cancelBtn.textContent = "取消";
            recoverBtn.classList.remove("disabled");
            recoverBtn.textContent = "恢复";
            barFill.style.width = "100%";
        }
    };

    return root;
}

app.registerExtension({
    name: "QIBO.ShotBatchGenUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!NODE_NAMES.includes(nodeData.name)) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            ensureStyle();

            const cancelEp = CANCEL_ENDPOINTS[nodeData.name] || "/qibo/batch_edit/cancel";
            const root = buildProgressDOM(this, cancelEp);
            this.addDOMWidget("qibo_sbg_ui", "div", root, {
                serialize: false,
                hideOnZoom: false,
                getHeight: () => 48,
            });

            if (root.parentElement) {
                const p = root.parentElement;
                p.style.width = "100%";
                p.style.margin = "0";
                p.style.padding = "0";
                p.style.boxSizing = "border-box";
            }

            const fixSize = () => {
                if (this.size?.[0] < 400) this.size[0] = 420;
                const h = this.computeSize()[1];
                if (this.size[1] > h) this.size[1] = h;
                this.setDirtyCanvas(true, true);
            };
            fixSize();
            requestAnimationFrame(fixSize);

            return result;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = onConfigure?.apply(this, arguments);
            requestAnimationFrame(() => {
                if (this.size?.[0] < 400) this.size[0] = 420;
                const h = this.computeSize()[1];
                if (this.size[1] > h) this.size[1] = h;
                this.setDirtyCanvas(true, true);
            });
            return r;
        };

        const onSelected = nodeType.prototype.onSelected;
        nodeType.prototype.onSelected = function () {
            const r = onSelected?.apply(this, arguments);
            if (!this._qiboSizeFixed) {
                this._qiboSizeFixed = true;
                if (this.size?.[0] < 400) this.size[0] = 420;
                const h = this.computeSize()[1];
                if (this.size[1] > h) this.size[1] = h;
                this.setDirtyCanvas(true, true);
            }
            return r;
        };
    },
});

function _dispatchProgress(e) {
    const data = e?.detail;
    if (!data) return;
    app.graph?.nodes?.forEach((node) => {
        if (NODE_NAMES.includes(node.type) && node._qiboSbgUpdate) {
            node._qiboSbgUpdate(data);
        }
    });
}

api.addEventListener("qibo_shot_progress", _dispatchProgress);
api.addEventListener("qibo_batch_progress", _dispatchProgress);
