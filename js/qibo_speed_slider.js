import { app } from "/scripts/app.js";

const NODE_NAME = "QIBOSpeedSliderNode";
const MIN = -10;
const MAX = 10;
const STEP = 0.1;
const COL_BG = "#2e364a";
const COL_YELLOW = "#ffd700";
const COL_TRACK_DARK = "#0a0a0a";

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
                if (!w || w.__qiboSliderInstalled) return;
                if (typeof self.addDOMWidget !== "function") return;

                w.__qiboSliderInstalled = true;
                const hideDefaultWidget = () => {
                    const candidates = [];
                    if (w.element) candidates.push(w.element);
                    if (w.inputEl) {
                        candidates.push(w.inputEl.parentElement);
                        candidates.push(w.inputEl.closest(".vue-widget, .propertywidget, .widget, .widget-row, .item"));
                    }
                    if (w.domEl) candidates.push(w.domEl);
                    for (const el of candidates) {
                        if (el && el !== container && !el.contains(container)) {
                            el.style.display = "none";
                            el.style.visibility = "hidden";
                            el.style.height = "0";
                            el.style.margin = "0";
                            el.style.padding = "0";
                        }
                    }
                };
                hideDefaultWidget();
                for (const d of [50, 200, 500, 1000, 1500]) setTimeout(hideDefaultWidget, d);

                const container = document.createElement("div");
                container.style.cssText = `position:relative;width:100%;background:${COL_BG};border:1px solid #6b7280;border-radius:14px;padding:8px 10px 10px;box-sizing:border-box;font-family:inherit;user-select:none;overflow:hidden;`;

                const titleBar = document.createElement("div");
                titleBar.style.cssText = "color:#ffffff;font-size:12px;font-weight:600;margin-bottom:6px;text-align:center;";
                titleBar.textContent = "速度滑块 (-10 - +10)";
                container.appendChild(titleBar);

                const valueRow = document.createElement("div");
                valueRow.style.cssText = "display:flex;justify-content:center;align-items:baseline;gap:6px;margin-bottom:8px;";
                const valueLabel = document.createElement("span");
                valueLabel.style.cssText = "color:#8a93a8;font-size:12px;";
                valueLabel.textContent = "值";
                const valueNum = document.createElement("span");
                valueNum.style.cssText = `color:${COL_YELLOW};font-size:22px;font-weight:700;line-height:1;`;
                valueNum.textContent = "0";
                valueRow.appendChild(valueLabel);
                valueRow.appendChild(valueNum);
                container.appendChild(valueRow);

                const track = document.createElement("div");
                track.style.cssText = `position:relative;width:100%;height:10px;background:${COL_TRACK_DARK};border-radius:5px;cursor:pointer;touch-action:none;box-shadow:inset 0 1px 2px rgba(0,0,0,0.6);`;

                const fill = document.createElement("div");
                fill.style.cssText = `position:absolute;left:0;top:0;bottom:0;background:${COL_YELLOW};border-radius:5px 0 0 5px;pointer-events:none;`;
                track.appendChild(fill);

                const handle = document.createElement("div");
                handle.style.cssText = `position:absolute;top:50%;width:18px;height:18px;background:#ffffff;border:3px solid ${COL_YELLOW};border-radius:50%;transform:translate(-50%,-50%);pointer-events:none;box-shadow:0 1px 4px rgba(0,0,0,0.5);`;
                track.appendChild(handle);

                container.appendChild(track);

                const tickRow = document.createElement("div");
                tickRow.style.cssText = "display:flex;justify-content:space-between;font-size:9px;color:#8a93a8;margin-top:5px;padding:0 1px;";
                for (let i = MIN; i <= MAX; i += 5) {
                    const t = document.createElement("span");
                    t.textContent = i;
                    tickRow.appendChild(t);
                }
                container.appendChild(tickRow);

                const badge = document.createElement("div");
                badge.style.cssText = "position:absolute;top:6px;right:8px;display:flex;align-items:center;gap:3px;font-size:11px;color:#ffffff;";
                const dot = document.createElement("span");
                dot.style.cssText = "display:inline-block;width:7px;height:7px;background:#39d353;border-radius:50%;";
                const star = document.createElement("span");
                star.textContent = "*";
                badge.appendChild(dot);
                badge.appendChild(star);
                container.appendChild(badge);

                const arcSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
                arcSvg.setAttribute("width", "26");
                arcSvg.setAttribute("height", "60");
                arcSvg.style.cssText = "position:absolute;right:-6px;top:10px;pointer-events:none;opacity:0.55;";
                const arcPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
                arcPath.setAttribute("d", "M 24 0 Q -6 30 24 60");
                arcPath.setAttribute("stroke", "#ffffff");
                arcPath.setAttribute("stroke-width", "1.5");
                arcPath.setAttribute("fill", "none");
                arcSvg.appendChild(arcPath);
                container.appendChild(arcSvg);

                const domW = self.addDOMWidget("qibo_speed_ui", "div", container, {
                    serialize: false,
                    getValue: () => String(w.value ?? 0),
                    setValue: (v) => { w.value = parseFloat(v) || 0; },
                });
                domW.options.getHeight = () => 96;

                const valToPct = (v) => (v - MIN) / (MAX - MIN);
                const pctToVal = (p) => Math.round((MIN + p * (MAX - MIN)) / STEP) * STEP;

                const render = (v) => {
                    const pct = valToPct(v);
                    handle.style.left = (pct * 100) + "%";
                    fill.style.width = (pct * 100) + "%";
                    valueNum.textContent = v.toFixed(1);
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
                if (w.inputEl) {
                    w.inputEl.addEventListener("input", syncFromWidget);
                    w.inputEl.addEventListener("change", syncFromWidget);
                }
                w.__qiboSyncSlider = syncFromWidget;
                syncFromWidget();
            };

            requestAnimationFrame(install);
            setTimeout(install, 50);
            setTimeout(install, 200);
            setTimeout(install, 500);
            setTimeout(install, 1000);

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