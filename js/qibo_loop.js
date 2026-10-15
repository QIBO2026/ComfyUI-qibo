import { app } from "/scripts/app.js";

const MACRO = "QIBOLoopContainer";
const OPEN = "TensorLoopOpen";
const CLOSE = "TensorLoopClose";

app.registerExtension({
    name: "QIBO.LoopVisualMerge",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== MACRO) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            const macro = this;
            requestAnimationFrame(() => {
                try {
                    const canvas = app.canvas;
                    const graph = canvas.getCurrentGraph?.() || canvas.graph || app.graph;
                    const [x, y] = macro.pos;

                    const openNode = LiteGraph.createNode(OPEN);
                    openNode.pos = [x, y];
                    graph.add(openNode);

                    const closeNode = LiteGraph.createNode(CLOSE);
                    closeNode.pos = [x + 440, y];
                    graph.add(closeNode);

                    openNode.connect(0, closeNode, 0);

                    try {
                        const GroupCtor = LiteGraph.LGraphGroup ||
                            (typeof LGraphGroup !== "undefined" ? LGraphGroup : null);
                        if (GroupCtor) {
                            const group = new GroupCtor("QIBO 循环");
                            group.pos = [x - 24, y - 60];
                            group.size = [720, 240];
                            graph.add(group);
                            group.recomputeInsideNodes?.();
                        }
                    } catch (ge) {
                        console.warn("[QIBO.LoopVisualMerge] group 创建失败:", ge);
                    }

                    graph.remove(macro);
                    graph.setDirtyCanvas?.(true, true);
                } catch (e) {
                    console.warn("[QIBO.LoopVisualMerge] 展开失败:", e);
                }
            });
            return result;
        };
    },
});