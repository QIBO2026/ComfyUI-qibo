import { app } from "/scripts/app.js";

const NODE_TYPE = "QIBOGroupToggleNode";

function modeAlways() {
    return (typeof LiteGraph !== "undefined" && LiteGraph.ALWAYS != null) ? LiteGraph.ALWAYS : 0;
}

function modeIgnore() {
    return (typeof LiteGraph !== "undefined" && LiteGraph.NEVER != null) ? LiteGraph.NEVER : 2;
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
    try { app.graph.setDirtyCanvas(true, true); } catch (e) {}
    try {
        if (app.canvas && typeof app.canvas.draw === "function") app.canvas.draw();
    } catch (e) {}
}

app.registerExtension({
    name: "QIBO.GroupToggleNode",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        const onConfigure = nodeType.prototype.onConfigure;

        function rebuild(node) {
            try {
                node.widgets = (node.widgets || []).filter((w) => !w.__qiboGroupToggle && !w.__qiboGroupRefresh);
                const groups = allGroups();
                const refreshBtn = node.addWidget(
                    "button",
                    groups.length ? `🔄 刷新分组列表（${groups.length} 组）` : "🔄 刷新分组列表（画布无分组）",
                    null,
                    () => rebuild(node)
                );
                refreshBtn.__qiboGroupRefresh = true;
                for (const group of groups) {
                    const title = (group.title || "未命名分组").trim() || "未命名分组";
                    const ns = nodesInGroup(group);
                    const label = ns.length ? `${title}（${ns.length}节点）` : `${title}（空组）`;
                    const w = node.addWidget("button", "", null, () => {
                        setGroupEnabled(group, !groupEnabled(group));
                        w.name = (groupEnabled(group) ? "【开】" : "【关】") + label;
                        try { node.setDirtyCanvas(true, true); } catch (e) {}
                    });
                    w.__qiboGroupToggle = true;
                    w.name = (groupEnabled(group) ? "【开】" : "【关】") + label;
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
                setTimeout(() => { try { rebuild(self); } catch (e) {} }, 60);
            } catch (e) {
                console.warn("[QIBO.GroupToggle] 初始化失败:", e);
            }
            return result;
        };

        nodeType.prototype.onConfigure = function () {
            const result = onConfigure?.apply(this, arguments);
            try {
                const self = this;
                setTimeout(() => { try { rebuild(self); } catch (e) {} }, 120);
            } catch (e) {}
            return result;
        };
    },
});