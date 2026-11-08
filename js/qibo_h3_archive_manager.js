// QIBO H3 接力存档管理器
// 「QIBO H3 存档管理」节点上出现「🗂 存档管理」按钮，点击弹出面板：
//   - 列出 output/qibo_h3/ 全部存档（文件名 / 大小 / 保存时间）
//   - 勾选批量删除
//   - 每行可一键「设为二采」：把当前图里所有 QIBO H3 接力存档·加载 节点
//     的 filename 切到该存档
// 服务端 API：GET/POST /qibo/h3_archives（见 qibo_h3_archive_api.py）
import { app } from "/scripts/app.js";

const MANAGER_NODE = "QIBO_H3_ARCHIVE_MANAGER";
const LOAD_NODE = "QIBO_H3_SELFLIFT_RELAY_LOAD";

function loadNodes() {
    const g = app.graph;
    const nodes = (g && g._nodes) || [];
    return nodes.filter((n) => n.type === LOAD_NODE);
}

function loadFilenameWidget(node) {
    return (node.widgets || []).find((w) => w.name === "filename");
}

function syncLoadCombos(removeNames, preferred) {
    // 删除后同步 LOAD 节点下拉：移除被删项；值被删的节点切到 preferred 或第一项
    for (const node of loadNodes()) {
        const w = loadFilenameWidget(node);
        if (!w) continue;
        if (w.options && Array.isArray(w.options.values)) {
            w.options.values = w.options.values.filter((v) => !removeNames.includes(v));
        }
        if (removeNames.includes(w.value)) {
            const opts = (w.options && w.options.values) || [];
            w.value = preferred && opts.includes(preferred) ? preferred
                : (opts.length ? opts[0] : w.value);
        }
        if (preferred) w.value = preferred;
        node.setDirtyCanvas?.(true, true);
    }
}

async function fetchArchives() {
    const res = await fetch("/qibo/h3_archives");
    if (!res.ok) throw new Error("HTTP " + res.status);
    return await res.json();
}

export function openArchiveManager() {
    // 遮罩
    const overlay = document.createElement("div");
    overlay.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:99999;" +
        "display:flex;align-items:center;justify-content:center;";
    // 面板
    const panel = document.createElement("div");
    panel.style.cssText = "background:#1e1e24;color:#e8e8ee;border-radius:10px;min-width:640px;" +
        "max-width:820px;max-height:82vh;display:flex;flex-direction:column;" +
        "box-shadow:0 12px 48px rgba(0,0,0,.6);font-family:sans-serif;";
    overlay.appendChild(panel);

    panel.innerHTML = `
        <div style="padding:12px 16px;border-bottom:1px solid #38383f;display:flex;align-items:center;gap:10px;">
            <b style="font-size:15px;">🗂 QIBO H3 接力存档管理</b>
            <span id="qam-dir" style="font-size:11px;color:#9a9aa5;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"></span>
            <button id="qam-refresh" style="cursor:pointer;">刷新</button>
            <button id="qam-close" style="cursor:pointer;">关闭</button>
        </div>
        <div id="qam-list" style="flex:1;overflow:auto;padding:6px 12px;"></div>
        <div style="padding:10px 16px;border-top:1px solid #38383f;display:flex;gap:10px;align-items:center;">
            <button id="qam-all">全选 / 全不选</button>
            <button id="qam-del" style="color:#ff8080;">删除选中</button>
            <span id="qam-status" style="flex:1;font-size:12px;color:#9a9aa5;"></span>
        </div>`;
    document.body.appendChild(overlay);

    const $ = (id) => panel.querySelector(id);
    const listEl = $("#qam-list"), statusEl = $("#qam-status"), dirEl = $("#qam-dir");
    let archives = [];
    const checked = new Set();

    const setStatus = (t, warn) => {
        statusEl.textContent = t;
        statusEl.style.color = warn ? "#ff9a9a" : "#9a9aa5";
    };

    async function reload() {
        setStatus("加载中…");
        try {
            const data = await fetchArchives();
            archives = data.archives || [];
            dirEl.textContent = data.dir || "";
            dirEl.title = data.dir || "";
            render();
            setStatus(archives.length ? `共 ${archives.length} 个存档` : "目录为空：先在存档工作流跑一次一采");
        } catch (e) {
            setStatus("读取失败: " + e.message, true);
        }
    }

    function render() {
        checked.clear();
        if (!archives.length) {
            listEl.innerHTML = `<div style="padding:24px;text-align:center;color:#777;">（没有存档）</div>`;
            return;
        }
        const rows = archives.map((a) => `
            <label style="display:flex;align-items:center;gap:10px;padding:7px 8px;border-radius:6px;cursor:pointer;" class="qam-row">
                <input type="checkbox" data-name="${a.name}" style="cursor:pointer;">
                <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${a.name}">${a.name}</span>
                <span style="color:#9a9aa5;font-size:12px;width:70px;text-align:right;">${a.size_mb} MB</span>
                <span style="color:#9a9aa5;font-size:12px;width:140px;">${a.mtime}</span>
                <button data-use="${a.name}" style="cursor:pointer;font-size:12px;">设为二采</button>
            </label>`).join("");
        listEl.innerHTML = rows;
        listEl.querySelectorAll("input[type=checkbox]").forEach((cb) => {
            cb.onchange = () => {
                if (cb.checked) checked.add(cb.dataset.name);
                else checked.delete(cb.dataset.name);
            };
        });
        listEl.querySelectorAll("button[data-use]").forEach((b) => {
            b.onclick = (ev) => {
                ev.preventDefault();
                useArchive(b.dataset.use);
            };
        });
    }

    function useArchive(name) {
        const nodes = loadNodes();
        if (!nodes.length) {
            setStatus("当前图里没有「QIBO H3 接力存档·加载」节点", true);
            return;
        }
        let n = 0;
        for (const node of nodes) {
            const w = loadFilenameWidget(node);
            if (w) { w.value = name; n += 1; }
            node.setDirtyCanvas?.(true, true);
        }
        setStatus(`✅ 已把 ${n} 个加载节点切换到存档「${name}」，直接排队即可二采`);
    }

    $("#qam-refresh").onclick = reload;
    $("#qam-close").onclick = () => overlay.remove();
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    $("#qam-all").onclick = () => {
        const cbs = [...listEl.querySelectorAll("input[type=checkbox]")];
        const allOn = cbs.length && cbs.every((c) => c.checked);
        cbs.forEach((c) => { c.checked = !allOn; });
        checked.clear();
        cbs.forEach((c) => { if (c.checked) checked.add(c.dataset.name); });
    };

    $("#qam-del").onclick = async () => {
        if (!checked.size) { setStatus("先勾选要删除的存档", true); return; }
        if (!confirm(`确定删除选中的 ${checked.size} 个存档？此操作不可恢复。`)) return;
        const names = [...checked];
        try {
            const res = await fetch("/qibo/h3_archives/delete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ names }),
            });
            const data = await res.json();
            const removed = (data.deleted || []).map((n) => n);
            if (data.errors?.length) setStatus("部分删除失败: " + data.errors.join("; "), true);
            else setStatus(`已删除 ${removed.length} 个存档`);
            syncLoadCombos(removed);
            reload();
        } catch (e) {
            setStatus("删除请求失败: " + e.message, true);
        }
    };

    reload();
}

app.registerExtension({
    name: "QIBO.H3ArchiveManager",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== MANAGER_NODE) return;
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated?.apply(this, arguments);
            const el = document.createElement("div");
            el.style.cssText = "display:flex;padding:4px;gap:6px;";
            const btn = document.createElement("button");
            btn.textContent = "🗂 存档管理（列表 / 删除 / 选择二采）";
            btn.style.cssText = "flex:1;cursor:pointer;font-size:12px;padding:5px 8px;";
            btn.onclick = () => openArchiveManager();
            el.appendChild(btn);
            this.addDOMWidget("archive_manager", "button", el);
            return r;
        };
    },
});
