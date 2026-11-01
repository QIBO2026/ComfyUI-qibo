import { app } from "/scripts/app.js";

const NODE_NAME = "QIBOSpeedSliderNode";
const MIN = -10;
const MAX = 10;
const STEP = 0.1;

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
                wrap.style.cssText = "width:100%;padding:8px 6px 4px;box-sizing:border-box;font-family:inherit;user-select:none;";

                const labelRow = document.createElement("div");
                labelRow.style.cssText = "display:flex;justify-content:space-between;align-items:center;font-size:11px;color:#858585;margin-bottom:6px;";
                const minLabel = document.createElement("span");
                minLabel.textContent = String(MIN);
                const valBox = document.createElement("span");
                valBox.style.cssText = "color:#4caf50;font-weight:600;font-size:14px;min-width:52px;text-align:center;background:#2d2d30;border-radius:4px;padding:2px 8px;border:1px solid #3e3e42;";
                valBox.textContent = "0.0";
                const maxLabel = document.createElement("span");
                maxLabel.textContent = "+" + String(MAX);
                labelRow.appendChild(minLabel);
                labelRow.appendChild(valBox);
                labelRow.appendChild(maxLabel);
                wrap.appendChild(labelRow);

                const track = document.createElement("div");
                track.style.cssText = "position:relative;width:100%;height:28px;background:#2d2d30;border-radius:6px;border:1px solid #3e3e42;cursor:pointer;touch-action:none;";

                const centerMark = document.createElement("div");
                centerMark.style.cssText = "position:absolute;left:50%;top:0;bottom:0;width:2px;background:#555;transform:translateX(-50%);pointer-events:none;";
                track.appendChild(centerMark);

                const fill = document.createElement("div");
                fill.style.cssText = "position:absolute;top:3px;bottom:3px;border-radius:3px;pointer-events:none;transition:none;";
                track.appendChild(fill);

                const handle = document.createElement("div");
                handle.style.cssText = "position:absolute;top:50%;width:14px;height:22px;background:#007acc;border:2px solid #fff;border-radius:4px;transform:translate(-50%,-50%);pointer-events:none;box-shadow:0 1px 3px rgba(0,0,0,0.5);";
                track.appendChild(handle);

                const tickRow = document.createElement("div");
                tickRow.style.cssText = "display:flex;justify-content:space-between;font-size:9px;color:#555;margin-top:4px;padding:0 2px;";
                for (let i = MIN; i <= MAX; i += 5) {
                    const t = document.createElement("span");
                    t.textContent = i;
                    tickRow.appendChild(t);
                }

                wrap.appendChild(track);
                wrap.appendChild(tickRow);

                const host = w.inputEl.parentElement?.parentElement || w.inputEl.parentElement;
                if (host) host.appendChild(wrap);

                const valToPct = (v) => (v - MIN) / (MAX - MIN);
                const pctToVal = (p) => Math.round((MIN + p * (MAX - MIN)) / STEP) * STEP;

                const render = (v) => {
                    const pct = valToPct(v);
                    handle.style.left = (pct * 100) + "%";
                    const centerPct = valToPct(0);
                    if (v >= 0) {
                        fill.style.left = (centerPct * 100) + "%";
                        fill.style.width = ((pct - centerPct) * 100) + "%";
                        fill.style.background = "linear-gradient(90deg,#2e7d32,#4caf50)";
                    } else {
                        fill.style.left = (pct * 100) + "%";
                        fill.style.width = ((centerPct - pct) * 100) + "%";
                        fill.style.background = "linear-gradient(90deg,#d13438,#f48789)";
                    }
                    valBox.textContent = v.toFixed(1);
                    valBox.style.color = v > 0 ? "#4caf50" : (v < 0 ? "#f48789" : "#cccccc");
                };

                let dragging = false;
                let activePointerId = null;
                const setFromX = (clientX) => {
                    const rect = track.getBoundingClientRect();
                    let p = (clientX - rect.left) / rect.width;
                    p = Math.max(0, Math.min(1, p));
                    const v = pctToVal(p);
                    w.value = v;
                    if (w.inputEl) w.inputEl.value = String(v);
                    render(v);
                    self.setDirtyCanvas(true, true);
                };
                track.addEventListener("pointerdown", (ev) => {
                    if (dragging) return;
                    dragging = true;
                    activePointerId = ev.pointerId;
                    try { track.setPointerCapture(ev.pointerId); } catch (e) {}
                    setFromX(ev.clientX);
                    ev.preventDefault();
                    ev.stopPropagation();
                });
                track.addEventListener("pointermove", (ev) => {
                    if (!dragging || ev.pointerId !== activePointerId) return;
                    setFromX(ev.clientX);
                    ev.preventDefault();
                });
                const endDrag = (ev) => {
                    if (!dragging || ev.pointerId !== activePointerId) return;
                    dragging = false;
                    activePointerId = null;
                    try { track.releasePointerCapture(ev.pointerId); } catch (e) {}
                };
                track.addEventListener("pointerup", endDrag);
                track.addEventListener("pointercancel", endDrag);

                const syncFromWidget = () => {
                    const v = Math.max(MIN, Math.min(MAX, parseFloat(w.value) || 0));
                    render(v);
                };
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