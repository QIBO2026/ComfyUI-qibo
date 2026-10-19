import { app } from "/scripts/app.js";

const NODE_TYPE = "QIBORestartNode";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitComfyUIBack(maxWaitMs = 300000) {
    const start = Date.now();
    await sleep(5000);
    while (Date.now() - start < maxWaitMs) {
        try {
            const r = await fetch("/system_stats", { cache: "no-store" });
            if (r.ok) {
                const j = await r.json().catch(() => null);
                if (j) return true;
            }
        } catch (e) {}
        await sleep(3000);
    }
    return false;
}

app.registerExtension({
    name: "QIBO.RestartComfyUI",
    async beforeRegisterNodeDef(nodeType, nodeData, appInstance) {
        if (nodeData?.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            try {
                const self = this;
                let restarting = false;
                const btn = self.addWidget("button", "重启 ComfyUI", null, async () => {
                    if (restarting) return;
                    restarting = true;
                    btn.name = "⏳ 重启中，等待服务恢复...";
                    self.setDirtyCanvas(true, true);
                    try {
                        const res = await fetch("/qibo/restart_comfyui", { method: "POST" });
                        let ok = res.ok;
                        let msg = "";
                        try {
                            const j = await res.json();
                            if (j.error) { ok = false; msg = j.error; }
                            else if (j.msg) msg = j.msg;
                        } catch (e) {}
                        if (!ok) {
                            btn.name = `❌ 重启失败: ${msg || res.status}`;
                            self.setDirtyCanvas(true, true);
                            restarting = false;
                            return;
                        }
                        const back = await waitComfyUIBack();
                        if (back) {
                            btn.name = "✅ 重启完成，正在刷新页面...";
                            self.setDirtyCanvas(true, true);
                            await sleep(1000);
                            location.reload();
                        } else {
                            btn.name = "⚠ 等待超时，请手动刷新页面";
                            self.setDirtyCanvas(true, true);
                            restarting = false;
                        }
                    } catch (e) {
                        const back = await waitComfyUIBack();
                        if (back) {
                            location.reload();
                        } else {
                            btn.name = "⚠ " + e + "（可手动刷新查看）";
                            self.setDirtyCanvas(true, true);
                            restarting = false;
                        }
                    }
                });
            } catch (e) {
                console.warn("[QIBO.RestartComfyUI] 按钮添加失败:", e);
            }
            return result;
        };
    },
});