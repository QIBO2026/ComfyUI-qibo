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

                if (w.inputEl.parentElement) {
                    w.inputEl.parentElement.style.display = "none";
                }

                const wrap = document.createElement("div");
                wrap.style.cssText = "width:100%;padding:6px 4px 2px;box-sizing:border-box;font-family:inherit;";

                const labelRow = document.createElement("div");
                labelRow.style.cssText = "display:flex;justify-content:space-between;align-items:center;font-size:11px;color:#858585;margin-bottom:4px;";
                const minLabel = document.createElement("span");
                minLabel.textContent = "-10";
                const valBox = document.createElement("span");
                valBox.style.cssText = "color:#4caf50;font-weight:600;font-size:13px;min-width:48px;text-align:center;background:#2d2d30;border-radius:3px;padding:1px 6px;";
                valBox.textContent = "0.0";
                const maxLabel = document.createElement("span");
                maxLabel.textContent = "+10";
                labelRow.appendChild(minLabel);
                labelRow.appendChild(valBox);
                labelRow.appendChild(maxLabel);
                wrap.appendChild(labelRow);

                const slider = document.createElement("input");
                slider.type = "range";
                slider.min = "-10";
                slider.max = "10";
                slider.step = "0.1";
                slider.value = String(w.value ?? 0);
                slider.style.cssText = "width:100%;height:22px;accent-color:#007acc;cursor:pointer;margin:0;";

                const tickRow = document.createElement("div");
                tickRow.style.cssText = "display:flex;justify-content:space-between;font-size:9px;color:#555;margin-top:2px;padding:0 2px;";
                for (let i = -10; i <= 10; i += 5) {
                    const t = document.createElement("span");
                    t.textContent = i;
                    tickRow.appendChild(t);
                }

                wrap.appendChild(slider);
                wrap.appendChild(tickRow);

                const host = w.inputEl.parentElement?.parentElement || w.inputEl.parentElement;
                if (host) host.appendChild(wrap);

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
                syncFromWidget();
            };

            requestAnimationFrame(install);
            setTimeout(install, 50);
            setTimeout(install, 200);

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