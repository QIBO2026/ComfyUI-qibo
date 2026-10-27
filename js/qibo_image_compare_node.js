import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const NODE_TYPE = "QIBOImageCompareNode";

app.registerExtension({
    name: "QIBO.ImageCompare",
    async beforeRegisterNodeDef(nodeType, nodeData, appInstance) {
        if (nodeData?.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            const self = this;

            const container = document.createElement("div");
            container.style.cssText = "position:relative;width:100%;height:100%;overflow:hidden;background:#222;";

            const imgA = document.createElement("img");
            const imgB = document.createElement("img");
            for (const img of [imgA, imgB]) {
                img.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;object-fit:contain;user-select:none;-webkit-user-drag:none;";
            }
            imgA.style.zIndex = "1";
            imgB.style.zIndex = "2";
            imgB.style.clipPath = "inset(0 0 0 50%)";
            container.appendChild(imgA);
            container.appendChild(imgB);

            const divider = document.createElement("div");
            divider.style.cssText = "position:absolute;top:0;left:50%;width:2px;height:100%;background:#fff;box-shadow:0 0 4px rgba(0,0,0,0.8);pointer-events:none;z-index:3;";
            container.appendChild(divider);

            const label = document.createElement("div");
            label.style.cssText = "position:absolute;top:4px;left:6px;font:11px monospace;color:#fff;background:rgba(0,0,0,0.55);padding:2px 6px;border-radius:3px;z-index:4;pointer-events:none;";
            label.textContent = "A \u25C0 | \u25B6 B";
            container.appendChild(label);

            const hint = document.createElement("div");
            hint.style.cssText = "position:absolute;bottom:4px;right:6px;font:11px monospace;color:#aaa;background:rgba(0,0,0,0.55);padding:2px 6px;border-radius:3px;z-index:4;pointer-events:none;";
            hint.textContent = "slide";
            container.appendChild(hint);

            const w = this.addDOMWidget("qibo_compare", "div", container, { serialize: false });
            const HEADER_OFFSET = 110;
            w.options.getHeight = () => Math.max(120, self.size[1] - HEADER_OFFSET);
            w.options.onResize = () => { w.options.getHeight && (w.last_y != null); };
            if (!this.size || this.size[0] < 400) this.size = [420, 460];

            const origResize = this.onResize || function () {};
            this.onResize = function () {
                origResize.apply(this, arguments);
                const h = Math.max(120, self.size[1] - HEADER_OFFSET);
                container.style.height = h + "px";
                if (self.graph) self.setDirtyCanvas(true, true);
            };
            container.style.height = Math.max(120, self.size[1] - HEADER_OFFSET) + "px";

            let mode = "slide";
            let splitX = 50;

            function updateSplit(x) {
                splitX = Math.max(0, Math.min(100, x));
                imgB.style.clipPath = `inset(0 0 0 ${splitX}%)`;
                divider.style.left = `${splitX}%`;
            }

            container.addEventListener("mousemove", (e) => {
                if (mode !== "slide") return;
                const rect = container.getBoundingClientRect();
                updateSplit(((e.clientX - rect.left) / rect.width) * 100);
            });

            container.addEventListener("click", (e) => {
                if (mode !== "click") return;
                const rect = container.getBoundingClientRect();
                const x = ((e.clientX - rect.left) / rect.width) * 100;
                if (x < 50) { updateSplit(100); } else { updateSplit(0); }
            });

            self._qiboCompare = {
                imgA, imgB, divider, container,
                setMode: (m) => { mode = m; hint.textContent = m; },
            };

            return result;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (result) {
            const r = onExecuted?.apply(this, arguments);
            try {
                if (this._qiboCompare && result?.a_images?.length && result?.b_images?.length) {
                    const a = result.a_images[0];
                    const b = result.b_images[0];
                    this._qiboCompare.imgA.src = api.apiURL(`/view?filename=${encodeURIComponent(a.filename)}&subfolder=${encodeURIComponent(a.subfolder || "")}&type=${a.type}`);
                    this._qiboCompare.imgB.src = api.apiURL(`/view?filename=${encodeURIComponent(b.filename)}&subfolder=${encodeURIComponent(b.subfolder || "")}&type=${b.type}`);
                    if (result.mode) this._qiboCompare.setMode(result.mode);
                }
            } catch (e) {
                console.warn("[QIBO.ImageCompare] onExecuted:", e);
            }
            return r;
        };
    },
});