import { app } from "/scripts/app.js";

const NODE_NAME = "QIBOSpeedSliderNode";

app.registerExtension({
    name: "QIBO.SpeedSlider",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            const self = this;

            const install = () => {
                const w = self.widgets?.find((x) => x.name === "value");
                if (!w || !w.inputEl || w.__qiboSliderInstalled) return;
                w.__qiboSliderInstalled = true;

                const slider = document.createElement("input");
                slider.type = "range";
                slider.min = "-10";
                slider.max = "10";
                slider.step = "0.1";
                slider.value = String(w.value ?? 0);
                slider.style.cssText = "width:100%;margin:4px 0 2px;accent-color:#007acc;cursor:pointer;";

                const valBox = document.createElement("span");
                valBox.style.cssText = "display:inline-block;min-width:48px;text-align:right;color:#4caf50;font-size:12px;margin-left:8px;";
                valBox.textContent = (parseFloat(slider.value)).toFixed(1);

                const wrap = document.createElement("div");
                wrap.style.cssText = "display:flex;align-items:center;width:100%;";
                wrap.appendChild(slider);
                wrap.appendChild(valBox);

                w.inputEl.parentElement?.appendChild(wrap);

                const syncFromWidget = () => {
                    const v = parseFloat(w.value) || 0;
                    slider.value = String(v);
                    valBox.textContent = v.toFixed(1);
                };
                slider.addEventListener("input", () => {
                    const v = parseFloat(slider.value) || 0;
                    w.value = v;

                    if (w.inputEl) w.inputEl.value = String(v);
                    valBox.textContent = v.toFixed(1);
                    self.setDirtyCanvas(true, true);
                });
                w.inputEl.addEventListener("input", syncFromWidget);
                w.inputEl.addEventListener("change", syncFromWidget);
                w.__qiboSyncSlider = syncFromWidget;
            };

            requestAnimationFrame(install);
            setTimeout(install, 50);

            const onConfigure = self.onConfigure;
            self.onConfigure = function () {
                const r = onConfigure?.apply(this, arguments);
                setTimeout(() => {
                    if (self.widgets) {
                        const w = self.widgets.find((x) => x.name === "value");
                        if (w && w.__qiboSyncSlider) w.__qiboSyncSlider();
                    }
                }, 30);
                return r;
            };

            return result;
        };
    },
});