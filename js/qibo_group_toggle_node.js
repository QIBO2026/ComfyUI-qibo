import { app } from "/scripts/app.js";

const NODE_TYPE = "QIBOGroupToggleNode";

const THEME = {
    bgColor: "#252729",
    itemBg: "#16181A",
    accentColor: "#D4AF37",
    accentDim: "#6B7280",
    offTrack: "#2F3238",
    knob: "#FFFFFF",
};

const PAD = 12;
const ROW_H = 34;
const ROW_GAP = 6;
const TOP_GAP = 10;
const NAME_MAX = 10;
const SWITCH_W = 52;
const SWITCH_H = 28;
const KNOB_R = 12;
const SCAN_MS = 300;
const MIN_W = 320;

function modeAlways() {
    return (typeof LiteGraph !== "undefined" && LiteGraph.ALWAYS != null) ? LiteGraph.ALWAYS : 0;
}

function modeIgnore() {
    return (typeof LiteGraph !== "undefined" && LiteGraph.BYPASS != null) ? LiteGraph.BYPASS : 4;
}

function allGroups() {
    try {
        return (app.graph && app.graph._groups) || [];
    } catch (e) {
        return [];
    }
}

function nodesInGroup(group) {
    if (!Array.isArray(group._nodes) || group._nodes.length === 0) {
        try {
            if (typeof group.recomputeInsideNodes === "function") group.recomputeInsideNodes();
        } catch (e) {}
    }
    if (Array.isArray(group._nodes) && group._nodes.length > 0) return group._nodes;
    const b = group.bounding || [0, 0, 0, 0];
    try {
        return (app.graph && app.graph._nodes ? app.graph._nodes : []).filter((n) => {
            if (!n.pos) return false;
            const x = n.pos[0];
            const y = n.pos[1];
            return x >= b[0] && x <= b[0] + b[2] && y >= b[1] && y <= b[1] + b[3];
        });
    } catch (e) {
        return [];
    }
}

function groupEnabled(group) {
    const ns = nodesInGroup(group);
    if (!ns.length) return true;
    return ns.every((n) => n.mode === modeAlways());
}

function setGroupEnabled(group, enabled) {
    const target = enabled ? modeAlways() : modeIgnore();
    for (const n of nodesInGroup(group)) {
        if (n.type === NODE_TYPE) continue;
        try { n.mode = target; } catch (e) {}
    }
    try { group.mode = target; } catch (e) {}
}

function clipName(t) {
    const s = String(t == null ? "" : t).trim() || "未命名分组";
    const chars = [...s];
    return chars.length > NAME_MAX ? chars.slice(0, NAME_MAX).join("") + "…" : s;
}

function titleHeight() {
    return (typeof LiteGraph !== "undefined" && LiteGraph.NODE_TITLE_HEIGHT) || 30;
}

function rowTop() {
    return titleHeight() + TOP_GAP;
}

function layoutRows(node) {
    const rows = node.__qiboRows || [];
    const h = rowTop() + rows.length * (ROW_H + ROW_GAP) + TOP_GAP;
    const w = Math.max((node.size && node.size[0]) || 0, MIN_W);
    if (!node.size || Math.abs(node.size[0] - w) > 0.5 || Math.abs(node.size[1] - h) > 0.5) {
        try { node.setSize([w, h]); } catch (e) {}
    }
}

function refreshRows(node) {
    const groups = allGroups();
    node.__qiboRows = groups.map((g) => {
        const cnt = nodesInGroup(g).length;
        const name = cnt ? clipName(g.title) : clipName(g.title) + "（空组）";
        return { group: g, name, enabled: groupEnabled(g) };
    });
    layoutRows(node);
}

function scanSignature() {
    return allGroups().map((g) => `${g.title || ""}:${groupEnabled(g) ? 1 : 0}:${nodesInGroup(g).length}`).join("|");
}

function rowAt(node, localPos) {
    const rows = node.__qiboRows || [];
    if (!rows.length) return -1;
    const top = rowTop();
    if (localPos[1] < top) return -1;
    const idx = Math.floor((localPos[1] - top) / (ROW_H + ROW_GAP));
    if (idx < 0 || idx >= rows.length) return -1;
    const rowY = top + idx * (ROW_H + ROW_GAP);
    if (localPos[1] > rowY + ROW_H) return -1;
    const switchX = node.size[0] - SWITCH_W - PAD - 4;
    if (localPos[0] > switchX - 20 && localPos[0] < node.size[0] - PAD + 6) return idx;
    return -1;
}

function rr(ctx, x, y, w, h, r) {
    if (typeof ctx.roundRect === "function") {
        ctx.beginPath();
        ctx.roundRect(x, y, w, h, r);
        return;
    }
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
}

app.registerExtension({
    name: "QIBO.GroupToggleNode",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        const onDrawForeground = nodeType.prototype.onDrawForeground;
        const onMouseDown = nodeType.prototype.onMouseDown;

        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            try {
                this.bgcolor = THEME.bgColor;
                this.__qiboRows = [];
                this.__qiboSig = null;
                this.__qiboLastScan = 0;
                refreshRows(this);
            } catch (e) {
                console.warn("[QIBO.GroupToggle] 初始化失败:", e);
            }
            return result;
        };

        nodeType.prototype.onDrawForeground = function (ctx) {
            const result = onDrawForeground?.apply(this, arguments);
            if (this.flags?.collapsed) return result;

            const now = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
            if (!this.__qiboLastScan || now - this.__qiboLastScan > SCAN_MS) {
                this.__qiboLastScan = now;
                try {
                    const sig = scanSignature();
                    if (sig !== this.__qiboSig) {
                        this.__qiboSig = sig;
                        refreshRows(this);
                    }
                } catch (e) {}
            }

            const rows = this.__qiboRows || [];
            const top = rowTop();
            const rowW = this.size[0] - PAD * 2;

            ctx.imageSmoothingEnabled = true;
            ctx.imageSmoothingQuality = "high";

            if (!rows.length) {
                ctx.fillStyle = THEME.accentDim;
                ctx.font = "13px 'Segoe UI', Arial, sans-serif";
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillText("画布暂无分组", this.size[0] / 2, top + ROW_H / 2);
                return result;
            }

            for (let i = 0; i < rows.length; i++) {
                const row = rows[i];
                const rowY = top + i * (ROW_H + ROW_GAP);
                const switchX = this.size[0] - SWITCH_W - PAD - 4;
                const switchY = rowY + (ROW_H - SWITCH_H) / 2;
                const isOn = row.enabled;

                rr(ctx, PAD, rowY, rowW, ROW_H, 8);
                ctx.fillStyle = THEME.itemBg;
                ctx.fill();
                ctx.strokeStyle = "rgba(255,255,255,0.05)";
                ctx.lineWidth = 1;
                ctx.stroke();

                ctx.fillStyle = isOn ? THEME.accentColor : THEME.accentDim;
                ctx.font = "bold 14px 'Segoe UI', Arial, sans-serif";
                ctx.textAlign = "left";
                ctx.textBaseline = "middle";
                ctx.shadowColor = "rgba(0,0,0,0.5)";
                ctx.shadowBlur = 2;
                ctx.shadowOffsetY = 1;
                ctx.fillText(row.name, PAD + 12, rowY + ROW_H / 2 + 1);
                ctx.shadowColor = "transparent";

                rr(ctx, switchX, switchY, SWITCH_W, SWITCH_H, SWITCH_H / 2);
                if (isOn) {
                    const grad = ctx.createLinearGradient(switchX, switchY, switchX + SWITCH_W, switchY);
                    grad.addColorStop(0, "#C49B2D");
                    grad.addColorStop(1, "#F1C40F");
                    ctx.fillStyle = grad;
                } else {
                    ctx.fillStyle = THEME.offTrack;
                }
                ctx.fill();
                if (!isOn) {
                    ctx.strokeStyle = "rgba(0,0,0,0.4)";
                    ctx.lineWidth = 2;
                    ctx.stroke();
                }

                ctx.font = "bold 10px 'Segoe UI', Arial, sans-serif";
                ctx.textBaseline = "middle";
                if (isOn) {
                    ctx.fillStyle = "rgba(60,40,0,0.9)";
                    ctx.textAlign = "left";
                    ctx.fillText("开", switchX + 7, switchY + SWITCH_H / 2);
                } else {
                    ctx.fillStyle = "rgba(255,255,255,0.55)";
                    ctx.textAlign = "right";
                    ctx.fillText("关", switchX + SWITCH_W - 7, switchY + SWITCH_H / 2);
                }

                const knobX = isOn ? (switchX + SWITCH_W - KNOB_R * 2 - 2) : (switchX + 2);
                const knobY = switchY + 2;
                ctx.shadowColor = "rgba(0,0,0,0.4)";
                ctx.shadowBlur = 6;
                ctx.shadowOffsetY = 2;
                ctx.beginPath();
                ctx.arc(knobX + KNOB_R, knobY + KNOB_R, KNOB_R, 0, Math.PI * 2);
                ctx.fillStyle = THEME.knob;
                ctx.fill();
                ctx.shadowColor = "transparent";
                ctx.beginPath();
                ctx.arc(knobX + KNOB_R, knobY + KNOB_R - 2, KNOB_R - 2, Math.PI, Math.PI * 2);
                ctx.fillStyle = "rgba(255,255,255,0.8)";
                ctx.fill();
            }
            return result;
        };

        nodeType.prototype.onMouseDown = function (e, localPos, graphCanvas) {
            const result = onMouseDown?.apply(this, arguments);
            if (this.flags?.collapsed) return result;
            try {
                const idx = rowAt(this, localPos);
                if (idx >= 0) {
                    const row = this.__qiboRows[idx];
                    const next = !row.enabled;
                    setGroupEnabled(row.group, next);
                    row.enabled = next;
                    try { app.graph.setDirtyCanvas(true, true); } catch (e2) {}
                    return true;
                }
            } catch (err) {}
            return result;
        };
    },
});