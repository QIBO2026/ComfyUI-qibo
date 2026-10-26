# Copyright (C) 2026 wuwukasi (wuwukaka)
# SPDX-License-Identifier: GPL-3.0-only

"""
BodyRatioMapper nodes - Main entry point.
QIBOPoseCorrect: 中文包装节点，复用 ProportionTransfer 校正算法。
渲染使用 ComfyUI 核心 SDPoseDrawKeypoints。
"""

from .core import BodyRatioMapperProportionTransfer


class QIBOPoseCorrect:
    """QIBO 骨骼比例校正（中文包装节点）"""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "目标姿态": ("POSE_KEYPOINT", {"tooltip": "目标姿态关键点（SDPose/OpenPose 格式）"}),
            },
            "optional": {
                "参考姿态": ("POSE_KEYPOINT", {"tooltip": "参考姿态关键点（比例来源）"}),
                "手动锚点姿态": ("POSE_KEYPOINT", {"tooltip": "（可选）覆盖 WSCS，提供正面直立姿态作为比例基准"}),
                "手动首帧": ("POSE_KEYPOINT", {"tooltip": "（可选）覆盖首帧参考，用于首帧偏移基准模式"}),
                "启用RPCA降噪": ("BOOLEAN", {"default": False, "label_on": "RPCA 开", "label_off": "RPCA 关", "tooltip": "启用全局 RPCA 乘数（锚点 vs 首帧比例校正）"}),
                "手部缩放": ("BOOLEAN", {"default": True, "label_on": "开", "label_off": "关"}),
                "脚部缩放": ("BOOLEAN", {"default": True, "label_on": "开", "label_off": "关"}),
                "Y轴防抖": ("BOOLEAN", {"default": True, "label_on": "开", "label_off": "关"}),
                "X轴防抖": ("BOOLEAN", {"default": False, "label_on": "开", "label_off": "关"}),
                "最佳手部搜索": ("BOOLEAN", {"default": True, "label_on": "开", "label_off": "关"}),
                "肩部FK修正手": ("BOOLEAN", {"default": False, "label_on": "开", "label_off": "关", "tooltip": "用肩部 FK 替换手部 FK"}),
                "躯干FK修正手臂": ("BOOLEAN", {"default": False, "label_on": "开", "label_off": "关", "tooltip": "用躯干 FK 替换上/下臂 FK"}),
                "躯干FK修正脚": ("BOOLEAN", {"default": False, "label_on": "开", "label_off": "关", "tooltip": "用躯干 FK 替换脚部 FK"}),
                "最佳颈部搜索": ("BOOLEAN", {"default": False, "label_on": "开", "label_off": "关"}),
                "最终偏移对齐": ("BOOLEAN", {"default": True, "label_on": "开", "label_off": "关"}),
                "首帧偏移基准": ("BOOLEAN", {"default": False, "label_on": "首帧基准", "label_off": "锚点基准", "tooltip": "开：按参考 vs 首帧对齐全局偏移；关：按参考 vs 锚点帧对齐"}),
                "头部固定": ("BOOLEAN", {"default": False, "label_on": "开", "label_off": "关", "tooltip": "开：每帧鼻尖对齐参考鼻尖，保持头部稳定"}),
                "匹配原始耳部比例": ("BOOLEAN", {"default": False, "label_on": "开", "label_off": "关", "tooltip": "开：计算锚点与首个有效头部帧的耳宽比，作为 RPCA 乘数匹配原始耳部尺寸"}),
                "锚点输出模式": (["单帧多人", "多帧单人"], {"default": "单帧多人", "tooltip": "锚点输出布局模式"}),
                "详细日志": ("BOOLEAN", {"default": False, "label_on": "开", "label_off": "关", "tooltip": "启用详细内部日志"}),
                "置信度阈值": ("FLOAT", {"default": 0.30, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "WSCS 和参考门控的统一置信度阈值"}),
                "输出绝对坐标": ("BOOLEAN", {"default": True, "label_on": "绝对像素", "label_off": "归一化(0-1)"}),
                "签名": ("BOOLEAN", {"default": True, "label_on": "by wuwukasi(bilibili)", "label_off": "by wuwukasi(bilibili)"}),
            },
        }

    RETURN_TYPES = ("POSE_KEYPOINT", "POSE_KEYPOINT", "POSE_KEYPOINT")
    RETURN_NAMES = ("校正后姿态", "锚点姿态", "首帧输出")
    FUNCTION = "process"
    CATEGORY = "QIBO 姿态"

    _KEY_MAP = {
        "目标姿态": "pose_keypoint",
        "参考姿态": "ref_pose_keypoint",
        "手动锚点姿态": "manual_anchor_pose",
        "手动首帧": "manual_first_frame",
        "启用RPCA降噪": "enable_rpca",
        "手部缩放": "hand_scaling",
        "脚部缩放": "foot_scaling",
        "Y轴防抖": "offset_stabilizer_y",
        "X轴防抖": "offset_stabilizer_x",
        "最佳手部搜索": "best_hand_search",
        "肩部FK修正手": "use_shoulder_fk_for_hand",
        "躯干FK修正手臂": "use_torso_fk_for_arm",
        "躯干FK修正脚": "use_torso_fk_for_foot",
        "最佳颈部搜索": "best_neck_search",
        "最终偏移对齐": "final_offset_alignment",
        "首帧偏移基准": "base_offset_mode",
        "头部固定": "head_fixed_mode",
        "匹配原始耳部比例": "match_original_ear_scale",
        "锚点输出模式": "anchor_output_mode",
        "详细日志": "print_detailed_logs",
        "置信度阈值": "confidence_threshold",
        "输出绝对坐标": "output_absolute_coordinates",
        "签名": "signature",
    }

    _MODE_MAP = {
        "单帧多人": "single_frame_multi_person",
        "多帧单人": "multi_frame_single_person",
    }

    def process(self, **kwargs):
        inner = BodyRatioMapperProportionTransfer()
        english = {}
        for zh, en in self._KEY_MAP.items():
            if zh in kwargs:
                v = kwargs[zh]
                if zh == "锚点输出模式" and v in self._MODE_MAP:
                    v = self._MODE_MAP[v]
                english[en] = v
        return inner.process(**english)


NODE_CLASS_MAPPINGS = {
    "QIBOPoseCorrect": QIBOPoseCorrect,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOPoseCorrect": "QIBO 骨骼比例校正",
}
