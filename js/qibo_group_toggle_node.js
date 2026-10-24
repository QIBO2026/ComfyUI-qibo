import { app } from "/scripts/app.js";

const NODE_TYPE = "QIBOGroupToggleNode";

function modeAlways() {
    return (typeof LiteGraph !== "undefined" && LiteGraph.ALWAYS != null) ? LiteGraph.ALWAYS : 0;
}

function modeBypass() {
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
    if (Array.isArray(group._nodes)) return group._nodes;
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
    const target = enabled ? modeAlways() : modeBypass();
    for (const n of nodesInGroup(group)) {
        try { n.mode = target; } catch (e) {}
    }
    try { group.mode = target; } catch (e) {}
    try { if (app.canvas && app.canvas.setDirty) app.canvas.setDirty(true, true); } catch (e) {}
    try { if (app.canvas && app.canvas.draw) app.canvas.draw(); } catch (e) {}
}

app.registerExtension({
    name: "QIBO.GroupToggleNode",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        const onConfigure = nodeType.prototype.onConfigure;

        function rebuild(node) {
            try {
                node.widgets = (node.widgets || []).filter((w) => !w.__qiboGroupToggle);
                const groups = allGroups();
                const refreshBtn = (node.widgets || []).find((w) => w.name && w.name.indexOf("刷新分组") === 0);
                if (refreshBtn) {
                    refreshBtn.name = groups.length ? `🔄 刷新分组列表 (${groups.length} 组)` : "🔄 刷新分组列表 (画布无分组)";
                }
                for (const group of groups) {
                    const title = (group.title || "未命名分组").trim() || "未命名分组";
                    const ns = nodesInGroup(group);
                    const label = ns.length ? `${title} (${ns.length}节点)` : `${title} (空组)`;
                    const w = node.addWidget("toggle", label, groupEnabled(group), (value) => {
                        setGroupEnabled(group, !!value);
                        try { node.setDirtyCanvas(true, true); } catch (e) {}
                    });
                    w.__qiboGroupToggle = true;
                    try {
                        w.options = w.options || {};
                        w.options.serialize = false;
                    } catch (e) {}
                }
                try { node.setSize(node.computeSize()); } catch (e) {}
                try { node.setDirtyCanvas(true, true); } catch (e) {}
            } catch (e) {
                console.warn("[QIBO.GroupToggle] 刷新分组失败:", e);
            }
        }

        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            try {
                const self = this;
                self.addWidget("button", "🔄 刷新分组列表", null, () => rebuild(self));
                setTimeout(() => { try { rebuild(self); } catch (e) {} }, 60);
            } catch (e) {
                console.warn("[QIBO.GroupToggle] 初始化失败:", e);
            }
            return result;
        };

        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            try { rebuild(this); } catch (e) {}
            return result;
        };
    },
});