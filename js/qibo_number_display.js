import { app } from "/scripts/app.js";
import { ComfyWidgets } from "/scripts/widgets.js";

const NODE_NAME = "QIBONumberDisplayNode";
const EXT_NAME = "QIBO.AnyValueDisplayUI";
const WIDGET_NAME = "display";

app.registerExtension({
    name: EXT_NAME,
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated?.apply(this, arguments);
            if (this.widgets?.find(w => w.name === WIDGET_NAME)) return result;

            const widget = ComfyWidgets.STRING(
                this,
                WIDGET_NAME,
                ["STRING", { multiline: true, default: "" }],
                app
            ).widget;
            widget.inputEl.readOnly = true;
            widget.inputEl.placeholder = "(等待执行后显示文本)";
            widget.serializeValue = async () => "";
            this.__qiboValueWidget = widget;

            return result;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            const result = onExecuted?.apply(this, arguments);
            try {
                const raw = message?.text;
                const text = Array.isArray(raw) ? raw[0] : raw;
                if (typeof text === "string" && this.__qiboValueWidget) {
                    this.__qiboValueWidget.value = text;
                    this.setDirtyCanvas(true, true);
                }
            } catch (e) {
                console.warn("[QIBO.AnyValueDisplayUI] 回填失败:", e);
            }
            return result;
        };
    },
});