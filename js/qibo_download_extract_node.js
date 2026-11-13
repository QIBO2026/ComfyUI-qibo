import { app } from "/scripts/app.js";

const NODE_TYPE = "QIBODownloadExtractNode";

app.registerExtension({
    name: "QIBO.DownloadExtract",
    async beforeRegisterNodeDef(nodeType, nodeData, appInstance) {
        if (nodeData?.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            const self = this;

            let downloadedFilename = "";

            const urlWidget = self.widgets?.find((w) => w.name === "url");
            const overwriteWidget = self.widgets?.find((w) => w.name === "overwrite");

            const dlBtn = self.addWidget("button", "下载文件", null, async () => {
                const url = urlWidget?.value?.trim() || "";
                if (!url) {
                    dlBtn.name = "请先输入网址";
                    self.setDirtyCanvas(true, true);
                    setTimeout(() => { dlBtn.name = "下载文件"; self.setDirtyCanvas(true, true); }, 2000);
                    return;
                }
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
                        return;
                    }
                    downloadedFilename = j.filename;
                    const sizeKB = j.size ? (j.size / 1024).toFixed(1) + "KB" : "";
                    dlBtn.name = "已下载: " + j.filename + (sizeKB ? " (" + sizeKB + ")" : "");
                    self.setDirtyCanvas(true, true);
                } catch (e) {
                    dlBtn.name = "下载失败: " + e;
                    self.setDirtyCanvas(true, true);
                }
            });

            const exBtn = self.addWidget("button", "解压到 custom_nodes", null, async () => {
                if (!downloadedFilename) {
                    exBtn.name = "请先下载文件";
                    self.setDirtyCanvas(true, true);
                    setTimeout(() => { exBtn.name = "解压到 custom_nodes"; self.setDirtyCanvas(true, true); }, 2000);
                    return;
                }
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
                    const msg = "解压" + j.extracted_count + "个" + (j.skipped_count > 0 ? ",跳过" + j.skipped_count + "个" : "");
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