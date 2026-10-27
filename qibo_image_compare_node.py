"""QIBO 图片比较节点。

继承 PreviewImage，分别保存 image_a / image_b 为临时图片，
通过 ui 字段把两张图的路径返回给前端，前端 Canvas 渲染并处理滑动/点击交互。
"""
import nodes


class QIBOImageCompareNode(nodes.PreviewImage):
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image_a": ("IMAGE",),
                "image_b": ("IMAGE",),
                "mode": (["slide", "click"],),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ()
    FUNCTION = "compare_images"
    OUTPUT_NODE = True
    CATEGORY = "QIBO"

    def compare_images(self, image_a, image_b, mode="slide", prompt=None, extra_pnginfo=None):
        a_res = self.save_images(image_a, filename_prefix="qibo_cmp_a", prompt=prompt, extra_pnginfo=extra_pnginfo)
        b_res = self.save_images(image_b, filename_prefix="qibo_cmp_b", prompt=prompt, extra_pnginfo=extra_pnginfo)
        return {
            "ui": {
                "a_images": a_res["ui"]["images"],
                "b_images": b_res["ui"]["images"],
                "mode": mode,
            },
            "result": (),
        }


NODE_CLASS_MAPPINGS = {
    "QIBOImageCompareNode": QIBOImageCompareNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOImageCompareNode": "QIBO 图片比较",
}