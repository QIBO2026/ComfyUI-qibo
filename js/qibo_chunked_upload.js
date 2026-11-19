/**
 * QIBO 分块上传前端扩展
 *
 * 自动拦截所有发往 /upload/image 的请求，当文件超过阈值时
 * 自动切分成多个小 chunk 逐块上传，服务端合并后返回。
 * 用户点击任意节点的"上传图片"按钮即可自动生效，无需额外操作。
 *
 * 开关控制：默认关闭，需通过右下角开关按钮手动开启。
 * 开关状态持久化在 qibo_config.json 中。
 * 代码级默认值由 CHUNKED_UPLOAD_ENABLED 常量控制，API 读取失败时回退到此值。
 */
import { app } from "/scripts/app.js";

// ========== 分块上传开关（代码级默认值，改 true 即开启） ==========
const CHUNKED_UPLOAD_ENABLED = false;
// ==================================================================

const CHUNK_SIZE = 512 * 1024;
const THRESHOLD = 1024 * 1024;

let _progressEl = null;
let _interceptorsInstalled = false;
let _toggleBtn = null;

function _showProgress(received, total, filename) {
    if (!_progressEl) {
        _progressEl = document.createElement("div");
        _progressEl.style.cssText = `
            position: fixed; bottom: 20px; right: 20px; z-index: 99999;
            background: #1e1e1e; color: #4CAF50; border: 1px solid #4CAF50;
            border-radius: 8px; padding: 12px 20px; font-size: 14px;
            font-family: monospace; box-shadow: 0 4px 12px rgba(0,0,0,0.5);
            min-width: 280px; transition: opacity 0.3s;
        `;
        document.body.appendChild(_progressEl);
    }
    const pct = (received / total * 100).toFixed(1);
    const bar = "█".repeat(Math.floor(pct / 5)).padEnd(20, "░");
    _progressEl.innerHTML = `
        <div style="margin-bottom:4px">📦 QIBO 分块上传: ${filename || ""}</div>
        <div style="font-size:12px;color:#aaa">${bar} ${pct}% (${received}/${total})</div>
    `;
    _progressEl.style.opacity = "1";
}

function _hideProgress() {
    if (_progressEl) {
        _progressEl.style.opacity = "0";
        setTimeout(() => {
            if (_progressEl) { _progressEl.remove(); _progressEl = null; }
        }, 500);
    }
}

async function chunkedUploadFile(file, uploadType = "input", subfolder = "") {
    const totalSize = file.size;
    const totalChunks = Math.ceil(totalSize / CHUNK_SIZE);

    console.log(`[QIBO] 分块上传: ${file.name} (${(totalSize/1024/1024).toFixed(2)}MB) → ${totalChunks} 块 × 512KB`);
    _showProgress(0, totalChunks, file.name);

    const initResp = await fetch("/qibo/chunked_upload/init", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            filename: file.name,
            total_chunks: totalChunks,
            total_size: totalSize,
            type: uploadType,
            subfolder: subfolder,
        }),
    });
    if (!initResp.ok) throw new Error(`初始化失败: ${initResp.status}`);
    const { upload_id } = await initResp.json();

    for (let idx = 0; idx < totalChunks; idx++) {
        const offset = idx * CHUNK_SIZE;
        const chunk = file.slice(offset, offset + CHUNK_SIZE);

        const formData = new FormData();
        formData.append("upload_id", upload_id);
        formData.append("chunk_index", String(idx));
        formData.append("data", chunk, `chunk_${idx}`);

        const chunkResp = await fetch("/qibo/chunked_upload/chunk", {
            method: "POST",
            body: formData,
        });
        if (!chunkResp.ok) throw new Error(`块 ${idx}/${totalChunks} 失败: ${chunkResp.status}`);

        _showProgress(idx + 1, totalChunks, file.name);
    }

    const mergeResp = await fetch("/qibo/chunked_upload/merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ upload_id, filename: file.name, type: uploadType }),
    });
    if (!mergeResp.ok) throw new Error(`合并失败: ${mergeResp.status}`);

    const result = await mergeResp.json();
    console.log(`[QIBO] 上传完成:`, result);
    _hideProgress();
    return result;
}

function _installFetchInterceptor() {
    const _originalFetch = window.fetch;

    window.fetch = async function (input, init) {
        let url = typeof input === "string" ? input : input?.url;
        const isUploadImage = url && url.includes("/upload/image");

        if (isUploadImage && init?.body instanceof FormData) {
            const formData = init.body;
            const file = formData.get("image");

            if (file && file instanceof File && file.size > THRESHOLD) {
                const uploadType = formData.get("type") || "input";
                const subfolder = formData.get("subfolder") || "";

                console.log(`[QIBO] 拦截大文件上传: ${file.name} (${(file.size/1024/1024).toFixed(2)}MB) → 分块模式`);

                try {
                    const result = await chunkedUploadFile(file, uploadType, subfolder);
                    return new Response(JSON.stringify(result), {
                        status: 200,
                        statusText: "OK",
                        headers: { "Content-Type": "application/json" },
                    });
                } catch (err) {
                    console.warn("[QIBO] 分块上传失败，降级为普通上传:", err.message);
                    _hideProgress();
                }
            }
        }

        return _originalFetch.call(this, input, init);
    };

    console.log("[QIBO] fetch 拦截器已安装，大文件自动分块上传");
}

function _installXHRInterceptor() {
    const _originalOpen = XMLHttpRequest.prototype.open;
    const _originalSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
        this._qiboUrl = url;
        this._qiboMethod = method;
        return _originalOpen.call(this, method, url, ...rest);
    };

    XMLHttpRequest.prototype.send = function (body) {
        if (this._qiboUrl && this._qiboUrl.includes("/upload/image") && body instanceof FormData) {
            const file = body.get("image");
            if (file && file instanceof File && file.size > THRESHOLD) {
                const uploadType = body.get("type") || "input";
                const subfolder = body.get("subfolder") || "";
                const xhr = this;

                console.log(`[QIBO] XHR 拦截大文件: ${file.name} (${(file.size/1024/1024).toFixed(2)}MB)`);

                chunkedUploadFile(file, uploadType, subfolder).then(result => {
                    const json = JSON.stringify(result);
                    Object.defineProperty(xhr, "readyState", { value: 4, configurable: true });
                    Object.defineProperty(xhr, "status", { value: 200, configurable: true });
                    Object.defineProperty(xhr, "responseText", { value: json, configurable: true });
                    Object.defineProperty(xhr, "response", { value: json, configurable: true });
                    if (typeof xhr.onreadystatechange === "function") xhr.onreadystatechange();
                    if (typeof xhr.onload === "function") xhr.onload();
                }).catch(err => {
                    console.warn("[QIBO] XHR 分块上传失败，降级:", err.message);
                    _hideProgress();
                    _originalSend.call(this, body);
                });
                return;
            }
        }
        return _originalSend.call(this, body);
    };

    console.log("[QIBO] XHR 拦截器已安装");
}

function _createToggleBtn(enabled) {
    if (_toggleBtn) _toggleBtn.remove();
    _toggleBtn = document.createElement("div");
    _toggleBtn.style.cssText = `
        position: fixed; bottom: 20px; left: 20px; z-index: 99998;
        background: ${enabled ? "#1b3a1b" : "#1e1e1e"}; color: ${enabled ? "#4CAF50" : "#888"};
        border: 1px solid ${enabled ? "#4CAF50" : "#555"}; border-radius: 8px;
        padding: 8px 14px; font-size: 12px; font-family: monospace;
        cursor: pointer; user-select: none; box-shadow: 0 2px 8px rgba(0,0,0,0.3);
        transition: all 0.2s;
    `;
    _toggleBtn.innerHTML = enabled
        ? "📦 分块上传: <b style='color:#4CAF50'>ON</b>"
        : "📦 分块上传: <b style='color:#888'>OFF</b>";
    _toggleBtn.title = "点击切换大图片分块上传功能";
    _toggleBtn.addEventListener("click", async () => {
        const newEnabled = !enabled;
        try {
            const resp = await fetch("/qibo/chunked_upload/toggle", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ enabled: newEnabled }),
            });
            if (resp.ok) {
                enabled = newEnabled;
                _toggleBtn.style.background = newEnabled ? "#1b3a1b" : "#1e1e1e";
                _toggleBtn.style.color = newEnabled ? "#4CAF50" : "#888";
                _toggleBtn.style.borderColor = newEnabled ? "#4CAF50" : "#555";
                _toggleBtn.innerHTML = newEnabled
                    ? "📦 分块上传: <b style='color:#4CAF50'>ON</b>"
                    : "📦 分块上传: <b style='color:#888'>OFF</b>";
                if (newEnabled && !_interceptorsInstalled) {
                    _installFetchInterceptor();
                    _installXHRInterceptor();
                    _interceptorsInstalled = true;
                }
                console.log(`[QIBO] 分块上传已${newEnabled ? "开启" : "关闭"}`);
            }
        } catch (err) {
            console.warn("[QIBO] 切换开关失败:", err.message);
        }
    });
    document.body.appendChild(_toggleBtn);
}

app.registerExtension({
    name: "ComfyUI-qibo.ChunkedUpload",

    async setup() {
        let enabled = CHUNKED_UPLOAD_ENABLED;
        try {
            const resp = await fetch("/qibo/chunked_upload/toggle");
            if (resp.ok) {
                const data = await resp.json();
                enabled = !!data.enabled;
            }
        } catch (err) {
            console.warn("[QIBO] 读取分块上传配置失败，使用代码默认值:", CHUNKED_UPLOAD_ENABLED, err.message);
        }

        if (enabled) {
            _installFetchInterceptor();
            _installXHRInterceptor();
            _interceptorsInstalled = true;
        }

        _createToggleBtn(enabled);
        console.log(`[QIBO] 分块上传扩展已加载（当前: ${enabled ? "开启" : "关闭"}）`);
    },
});
