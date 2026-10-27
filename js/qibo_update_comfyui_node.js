import { app } from "/scripts/app.js";

const NODE_TYPE = "QIBOUpdateComfyUINode";

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
    name: "QIBO.UpdateComfyUI",
    async beforeRegisterNodeDef(nodeType, nodeData, appInstance) {
        if (nodeData?.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            try {
                const self = this;
                let polling = false;
                const btn = self.addWidget("button", "一键更新 ComfyUI", null, async () => {
                    if (polling) return;
                    polling = true;
                    btn.name = "⏳ 更新中...";
                    self.setDirtyCanvas(true, true);
                    try {
                        const res = await fetch("/qibo/update_comfyui", { method: "POST" });
                        const j = await res.json().catch(() => ({}));
                        if (!res.ok || j.error) {
                            btn.name = `❌ 启动失败: ${j.error || res.status}`;
                            self.setDirtyCanvas(true, true);
                            polling = false;
                            return;
                        }
                        if (j.status === "busy") {
                            btn.name = "⚠ 已有更新任务在运行，继续等待...";
                            self.setDirtyCanvas(true, true);
                        }
                        let lastLogLen = 0;
                        let stable = 0;
                        while (true) {
                            await sleep(1500);
                            const pr = await fetch("/qibo/update_comfyui_progress", { cache: "no-store" });
                            const ps = await pr.json().catch(() => null);
                            if (!ps) continue;
                            const stepTxt = ps.step ? `【${ps.step}】` : "";
                            const logTail = (ps.log || "").slice(-200);
                            if (ps.status === "running") {
                                btn.name = `⏳ ${stepTxt} ${logTail.slice(-60)}`;
                                self.setDirtyCanvas(true, true);
                                continue;
                            }
                            if (ps.status === "done") {
                                btn.name = "✅ 更新完成，3 秒后自动重启 ComfyUI...";
                                self.setDirtyCanvas(true, true);
                                await sleep(3000);
                                try {
                                    await fetch("/qibo/restart_comfyui", { method: "POST" });
                                } catch (e) {}
                                const back = await waitComfyUIBack();
                                if (back) {
                                    btn.name = "✅ 重启完成，正在刷新...";
                                    self.setDirtyCanvas(true, true);
                                    await sleep(1000);
                                    location.reload();
                                } else {
                                    btn.name = "⚠ 等待超时，请手动刷新页面";
                                    self.setDirtyCanvas(true, true);
                                    polling = false;
                                }
                                return;
                            }
                            if (ps.status === "error") {
                                btn.name = `❌ 更新失败: ${ps.error || "未知错误"}`;
                                self.setDirtyCanvas(true, true);
                                polling = false;
                                return;
                            }
                            stable++;
                            if (stable > 3) {
                                btn.name = "⚠ 状态异常，请查看控制台";
                                self.setDirtyCanvas(true, true);
                                polling = false;
                                return;
                            }
                        }
                    } catch (e) {
                        btn.name = "⚠ " + e;
                        self.setDirtyCanvas(true, true);
                        polling = false;
                    }
                });
            } catch (e) {
                console.warn("[QIBO.UpdateComfyUI] 按钮添加失败:", e);
            }
            return result;
        };
    },
});