import { app } from "/scripts/app.js";

const NODE_TYPE = "QIBODownloadExtractNode";

function fmtSize(bytes) {
    if (!bytes) return "0B";
    if (bytes < 1024) return bytes + "B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + "KB";
    return (bytes / 1048576).toFixed(1) + "MB";
}

app.registerExtension({
    name: "QIBO.DownloadExtract",
    async beforeRegisterNodeDef(nodeType, nodeData, appInstance) {
        if (nodeData?.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            const self = this;

            let downloadedFilename = "";
            let downloading = false;

            const urlWidget = self.widgets?.find((w) => w.name === "url");
            const overwriteWidget = self.widgets?.find((w) => w.name === "overwrite");

            const dlBtn = self.addWidget("button", "下载文件", null, async () => {
                if (downloading) return;
                const url = urlWidget?.value?.trim() || "";
                if (!url) {
                    dlBtn.name = "请先输入网址";
                    self.setDirtyCanvas(true, true);
                    setTimeout(() => { dlBtn.name = "下载文件"; self.setDirtyCanvas(true, true); }, 2000);
                    return;
                }
                downloading = true;
                dlBtn.name = "下载中...";
                self.setDirtyCanvas(true, true);
                try {
                    const res = await fetch("/qibo/download_url_file", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ url }),
                    });
                    const j = await res.json();
                    if (j.error) {
                        dlBtn.name = "下载失败: " + j.error.slice(0, 40);
                        self.setDirtyCanvas(true, true);
                        downloading = false;
                        return;
                    }
                    const taskId = j.task_id;
                    downloadedFilename = j.filename;

                    const pollProgress = async () => {
                        try {
                            const pr = await fetch("/qibo/download_progress", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ task_id: taskId }),
                            });
                            const pj = await pr.json();
                            if (pj.error) {
                                dlBtn.name = "下载失败: " + pj.error.slice(0, 40);
                                self.setDirtyCanvas(true, true);
                                downloading = false;
                                return;
                            }
                            if (pj.status === "done") {
                                const sizeStr = pj.size ? fmtSize(pj.size) : "";
                                dlBtn.name = "已下载: " + downloadedFilename + (sizeStr ? " (" + sizeStr + ")" : "");
                                self.setDirtyCanvas(true, true);
                                downloading = false;
                                return;
                            }
                            if (pj.status === "error") {
                                dlBtn.name = "下载失败: " + (pj.error || "").slice(0, 40);
                                self.setDirtyCanvas(true, true);
                                downloading = false;
                                return;
                            }
                            if (pj.status === "downloading") {
                                const pct = pj.total > 0 ? ((pj.downloaded / pj.total) * 100).toFixed(1) + "%" : "";
                                const dlStr = fmtSize(pj.downloaded);
                                const totalStr = pj.total > 0 ? "/" + fmtSize(pj.total) : "";
                                dlBtn.name = "下载中 " + dlStr + totalStr + (pct ? " " + pct : "");
                                self.setDirtyCanvas(true, true);
                            }
                        } catch (e) {}
                        if (downloading) {
                            setTimeout(pollProgress, 1000);
                        }
                    };
                    setTimeout(pollProgress, 500);
                } catch (e) {
                    dlBtn.name = "下载失败: " + e;
                    self.setDirtyCanvas(true, true);
                    downloading = false;
                }
            });

            const exBtn = self.addWidget("button", "解压到 custom_nodes", null, async () => {

                const overwrite = overwriteWidget?.value || false;
                exBtn.name = "解压中...";
                self.setDirtyCanvas(true, true);
                try {
                    const res = await fetch("/qibo/extract_to_custom_nodes", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ filename: downloadedFilename, overwrite }),
                    });
                    const j = await res.json();
                    if (j.error) {
                        exBtn.name = "解压失败: " + j.error.slice(0, 40);
                        self.setDirtyCanvas(true, true);
                        return;
                    }
                    const msg = "解压" + j.moved_count + "个" + (j.skipped_count > 0 ? ",跳过" + j.skipped_count + "个" : "");
                    exBtn.name = msg;
                    self.setDirtyCanvas(true, true);
                } catch (e) {
                    exBtn.name = "解压失败: " + e;
                    self.setDirtyCanvas(true, true);
                }
            });

            return result;
        };
    },
});