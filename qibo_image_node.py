import requests
import json
import time
import torch
import numpy as np
from PIL import Image
from io import BytesIO
import os
import base64
import tempfile
import re
from .qibo_auth import (
    load_config, save_config,
    load_api_tokens, save_api_tokens,
    parse_api_tokens
)


def tensor_to_base64_url(image_tensor):
    try:
        if len(image_tensor.shape) == 4:
            image_tensor = image_tensor.squeeze(0)

        if image_tensor.max() <= 1.0:
            image_np = (image_tensor.cpu().numpy() * 255).astype(np.uint8)
        else:
            image_np = image_tensor.cpu().numpy().astype(np.uint8)

        pil_image = Image.fromarray(image_np)
        buffer = BytesIO()
        pil_image.save(buffer, format='JPEG', quality=85)
        img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

        return f"data:image/jpeg;base64,{img_base64}"
    except Exception as e:
        raise Exception(f"图像格式转换失败: {str(e)}")


# -------------------------- LoRA 预设管理节点 --------------------------
class ModelScopeLoraPresetNode:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        config = load_config()
        lora_presets = config.get("lora_presets", [])
        preset_names = [preset.get("name", "无LoRA") for preset in lora_presets]

        return {
            "required": {
                "action": (["查看预设", "添加预设", "删除预设", "保存预设"], {"default": "查看预设"}),
            },
            "optional": {
                "preset_name": ("STRING", {"default": "自定义LoRA", "label": "预设名称"}),
                "lora_model_id": ("STRING", {"default": "", "label": "LoRA模型ID"}),
                "default_weight": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "默认权重"}),
                "target_preset": (preset_names, {"default": preset_names[0] if preset_names else "无LoRA", "label": "目标预设"}),
            }
        }

    RETURN_TYPES = ("STRING", "FLOAT", "STRING")
    RETURN_NAMES = ("lora_model_id", "lora_weight", "preset_info")
    FUNCTION = "manage_lora_presets"
    CATEGORY = "ModelScopeAPI/LoRA"

    def manage_lora_presets(self, action, preset_name="", lora_model_id="", default_weight=0.8, target_preset=""):
        config = load_config()
        lora_presets = config.get("lora_presets", [])
        preset_info = f"当前共有 {len(lora_presets)} 个LoRA预设"

        if action == "查看预设":
            info_lines = ["=== LoRA预设列表 ==="]
            for i, preset in enumerate(lora_presets):
                info_lines.append(f"{i+1}. {preset.get('name')} | ID: {preset.get('model_id')} | 权重: {preset.get('weight')}")
            preset_info = "\n".join(info_lines)
            selected_preset = next((p for p in lora_presets if p.get("name") == target_preset), {"model_id": "", "weight": 0.8})
            return (selected_preset.get("model_id"), selected_preset.get("weight"), preset_info)

        elif action == "添加预设":
            if not preset_name or preset_name.strip() == "":
                raise Exception("预设名称不能为空")
            if any(p.get("name") == preset_name for p in lora_presets):
                raise Exception(f"已存在名为 {preset_name} 的预设")
            new_preset = {"name": preset_name.strip(), "model_id": lora_model_id.strip(), "weight": float(default_weight)}
            lora_presets.append(new_preset)
            config["lora_presets"] = lora_presets
            save_config(config)
            preset_info = f"成功添加预设: {preset_name} | ID: {lora_model_id}"
            return (lora_model_id, default_weight, preset_info)

        elif action == "删除预设":
            if target_preset == "无LoRA":
                raise Exception("不能删除默认的无LoRA预设")
            original_count = len(lora_presets)
            lora_presets = [p for p in lora_presets if p.get("name") != target_preset]
            if len(lora_presets) == original_count:
                raise Exception(f"未找到预设: {target_preset}")
            config["lora_presets"] = lora_presets
            save_config(config)
            preset_info = f"成功删除预设: {target_preset}"
            return ("", 0.8, preset_info)

        elif action == "保存预设":
            updated = False
            for i, preset in enumerate(lora_presets):
                if preset.get("name") == target_preset:
                    lora_presets[i]["model_id"] = lora_model_id.strip()
                    lora_presets[i]["weight"] = float(default_weight)
                    updated = True
                    break
            if not updated:
                raise Exception(f"未找到预设: {target_preset}")
            config["lora_presets"] = lora_presets
            save_config(config)
            preset_info = f"成功更新预设: {target_preset} | 新ID: {lora_model_id} | 新权重: {default_weight}"
            return (lora_model_id, default_weight, preset_info)

        return ("", 0.8, preset_info)


class ModelScopeSingleLoraLoaderNode:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        config = load_config()
        lora_presets = config.get("lora_presets", [])
        preset_options = [preset.get("name", "无LoRA") for preset in lora_presets]

        return {
            "required": {
                "lora_preset": (preset_options, {"default": preset_options[0], "label": "LoRA预设"}),
            },
            "optional": {
                "lora_weight": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "自定义权重"}),
                "use_custom_weight": ("BOOLEAN", {"default": False, "label_on": "使用自定义权重", "label_off": "使用预设权重"}),
            }
        }

    RETURN_TYPES = ("STRING", "FLOAT")
    RETURN_NAMES = ("lora_id", "lora_weight")
    FUNCTION = "load_single_lora"
    CATEGORY = "ModelScopeAPI/LoRA"

    def load_single_lora(self, lora_preset, lora_weight=0.8, use_custom_weight=False):
        config = load_config()
        lora_presets = config.get("lora_presets", [])
        selected_preset = next((p for p in lora_presets if p.get("name") == lora_preset), {"model_id": "", "weight": 0.8})
        lora_id = selected_preset.get("model_id", "")
        final_weight = lora_weight if use_custom_weight else selected_preset.get("weight", 0.8)
        return (lora_id, final_weight)


class ModelScopeMultiLoraLoaderNode:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        config = load_config()
        lora_presets = config.get("lora_presets", [])
        preset_options = [preset.get("name", "无LoRA") for preset in lora_presets]

        return {
            "required": {
                "lora1_preset": (preset_options, {"default": preset_options[0], "label": "LoRA 1 预设"}),
                "lora2_preset": (preset_options, {"default": preset_options[0], "label": "LoRA 2 预设"}),
                "lora3_preset": (preset_options, {"default": preset_options[0], "label": "LoRA 3 预设"}),
            },
            "optional": {
                "lora1_weight": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA 1 权重"}),
                "lora2_weight": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA 2 权重"}),
                "lora3_weight": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA 3 权重"}),
                "lora1_use_custom": ("BOOLEAN", {"default": False, "label_on": "LoRA1用自定义权重", "label_off": "用预设权重"}),
                "lora2_use_custom": ("BOOLEAN", {"default": False, "label_on": "LoRA2用自定义权重", "label_off": "用预设权重"}),
                "lora3_use_custom": ("BOOLEAN", {"default": False, "label_on": "LoRA3用自定义权重", "label_off": "用预设权重"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "FLOAT", "FLOAT", "FLOAT")
    RETURN_NAMES = ("lora1_id", "lora2_id", "lora3_id", "lora1_w", "lora2_w", "lora3_w")
    FUNCTION = "load_multi_lora"
    CATEGORY = "ModelScopeAPI/LoRA"

    def load_multi_lora(self, lora1_preset, lora2_preset, lora3_preset,
                        lora1_weight=0.8, lora2_weight=0.8, lora3_weight=0.8,
                        lora1_use_custom=False, lora2_use_custom=False, lora3_use_custom=False):
        config = load_config()
        lora_presets = config.get("lora_presets", [])

        def get_lora_info(preset_name, custom_weight, use_custom):
            preset = next((p for p in lora_presets if p.get("name") == preset_name), {"model_id": "", "weight": 0.8})
            model_id = preset.get("model_id", "")
            final_weight = custom_weight if use_custom else preset.get("weight", 0.8)
            return model_id, final_weight

        lora1_id, lora1_w = get_lora_info(lora1_preset, lora1_weight, lora1_use_custom)
        lora2_id, lora2_w = get_lora_info(lora2_preset, lora2_weight, lora2_use_custom)
        lora3_id, lora3_w = get_lora_info(lora3_preset, lora3_weight, lora3_use_custom)
        return (lora1_id, lora2_id, lora3_id, lora1_w, lora2_w, lora3_w)


# -------------------------- 生图节点 --------------------------
class ModelScopeImageNode:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        config = load_config()
        saved_tokens = load_api_tokens()

        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": config.get("default_prompt", "A beautiful landscape")
                }),
                "api_tokens": ("STRING", {
                    "default": "***已保存{}个Token***".format(len(saved_tokens)) if saved_tokens else "",
                    "placeholder": "请输入API Token（支持多个，用逗号/换行分隔）" if not saved_tokens else "留空使用已保存的Token",
                    "multiline": True
                }),
            },
            "optional": {
                "model": (config.get("image_models", ["Qwen/Qwen-Image"]), {
                    "default": config.get("default_model", "Qwen/Qwen-Image")
                }),
                "negative_prompt": ("STRING", {
                    "multiline": True,
                    "default": config.get("default_negative_prompt", "")
                }),
                "width": ("INT", {"default": config.get("default_width", 512), "min": 64, "max": 2048, "step": 64}),
                "height": ("INT", {"default": config.get("default_height", 512), "min": 64, "max": 2048, "step": 64}),
                "seed": ("INT", {"default": config.get("default_seed", -1), "min": -1, "max": 2147483647}),
                "steps": ("INT", {"default": config.get("default_steps", 30), "min": 1, "max": 100}),
                "guidance": ("FLOAT", {"default": config.get("default_guidance", 7.5), "min": 1.5, "max": 20.0, "step": 0.1}),
                "lora1_id": ("STRING", {"default": "", "label": "LoRA1 模型ID"}),
                "lora1_w": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA1 权重"}),
                "lora2_id": ("STRING", {"default": "", "label": "LoRA2 模型ID"}),
                "lora2_w": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA2 权重"}),
                "lora3_id": ("STRING", {"default": "", "label": "LoRA3 模型ID"}),
                "lora3_w": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA3 权重"}),
                "simplified_params": ("BOOLEAN", {"default": False, "label_on": "简化参数(LoRA/社区模型)", "label_off": "完整参数"}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "generate_image"
    CATEGORY = "ModelScopeAPI"

    def generate_image(self, prompt, api_tokens, model="Qwen/Qwen-Image", negative_prompt="", width=512, height=512, seed=-1, steps=30, guidance=7.5,
                       lora1_id="", lora1_w=0.8, lora2_id="", lora2_w=0.8, lora3_id="", lora3_w=0.8, simplified_params=False):
        config = load_config()
        tokens = parse_api_tokens(api_tokens)

        if not tokens:
            raise Exception("请提供至少一个有效的API Token\n提示: 使用 ModelScope登录获取Token 节点自动获取Token")

        if api_tokens and api_tokens.strip() not in ["", "***已保存{}个Token***".format(len(load_api_tokens()))]:
            if save_api_tokens(tokens):
                print(f"✅ 已保存 {len(tokens)} 个API Token")

        print(f"🔍 开始生成图像... 模型: {model} 尺寸: {width}x{height} 步数: {steps} 引导: {guidance}")

        lora_dict = {}
        if lora1_id and lora1_id.strip(): lora_dict[lora1_id.strip()] = float(lora1_w)
        if lora2_id and lora2_id.strip(): lora_dict[lora2_id.strip()] = float(lora2_w)
        if lora3_id and lora3_id.strip(): lora_dict[lora3_id.strip()] = float(lora3_w)

        last_exception = None
        for i, token in enumerate(tokens):
            try:
                print(f"🔄 尝试使用第 {i+1}/{len(tokens)} 个Token...")

                url = 'https://api-inference.modelscope.cn/v1/images/generations'
                payload = {'model': model, 'prompt': prompt}
                if not simplified_params:
                    payload['size'] = f"{width}x{height}"
                    payload['steps'] = steps
                    payload['guidance'] = guidance

                if lora_dict:
                    payload['loras'] = lora_dict
                    first_lora_id = next(iter(lora_dict.keys()))
                    first_lora_w = next(iter(lora_dict.values()))
                    payload['lora'] = first_lora_id
                    payload['lora_weight'] = first_lora_w

                if negative_prompt.strip():
                    payload['negative_prompt'] = negative_prompt
                if seed != -1:
                    payload['seed'] = seed
                else:
                    import random
                    payload['seed'] = random.randint(0, 2147483647)

                headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json',
                    'X-ModelScope-Async-Mode': 'true',
                    'X-ModelScope-Task-Type': 'text-to-image-generation',
                    'X-ModelScope-Request-Params': json.dumps({'loras': lora_dict} if lora_dict else {})
                }

                submission_response = requests.post(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), headers=headers, timeout=config.get("timeout", 60))

                if submission_response.status_code in (400, 422):
                    print(f"⚠️ 标准请求参数失败({submission_response.status_code})，尝试简化参数...")
                    minimal_payload = {'model': model, 'prompt': prompt}
                    if lora_dict:
                        minimal_payload['loras'] = lora_dict
                        minimal_payload['lora'] = first_lora_id
                        minimal_payload['lora_weight'] = first_lora_w
                    submission_response = requests.post(url, data=json.dumps(minimal_payload, ensure_ascii=False).encode('utf-8'), headers=headers, timeout=config.get("timeout", 60))

                if submission_response.status_code != 200:
                    raise Exception(f"API请求失败: {submission_response.status_code}, {submission_response.text}")

                submission_json = submission_response.json()
                image_url = None

                if 'task_id' in submission_json:
                    task_id = submission_json['task_id']
                    print(f"📌 获取任务ID: {task_id}, 开始轮询结果...")
                    poll_start = time.time()
                    max_wait_seconds = max(60, config.get('timeout', 720))
                    while True:
                        task_resp = requests.get(
                            f"https://api-inference.modelscope.cn/v1/tasks/{task_id}",
                            headers={'Authorization': f'Bearer {token}', 'X-ModelScope-Task-Type': 'image_generation'},
                            timeout=config.get("image_download_timeout", 120)
                        )
                        if task_resp.status_code != 200:
                            raise Exception(f"任务查询失败: {task_resp.status_code}, {task_resp.text}")
                        task_data = task_resp.json()
                        status = task_data.get('task_status')
                        print(f"⌛ 任务状态: {status} (已等待 {int(time.time() - poll_start)} 秒)")
                        if status == 'SUCCEED':
                            output_images = task_data.get('output_images') or []
                            if not output_images:
                                raise Exception("任务成功但未返回图片URL")
                            image_url = output_images[0]
                            break
                        if status == 'FAILED':
                            raise Exception(f"任务失败: {task_data}")
                        if time.time() - poll_start > max_wait_seconds:
                            raise Exception(f"任务轮询超时 ({max_wait_seconds}秒)")
                        time.sleep(5)
                elif 'images' in submission_json and len(submission_json['images']) > 0:
                    image_url = submission_json['images'][0]['url']
                else:
                    raise Exception(f"未识别的API返回格式: {submission_json}")

                print(f"📥 下载图片...")
                img_response = requests.get(image_url, timeout=config.get("image_download_timeout", 30))
                if img_response.status_code != 200:
                    raise Exception(f"图片下载失败: {img_response.status_code}")

                pil_image = Image.open(BytesIO(img_response.content))
                if pil_image.mode != 'RGB':
                    pil_image = pil_image.convert('RGB')
                image_np = np.array(pil_image).astype(np.float32) / 255.0
                image_tensor = torch.from_numpy(image_np)[None,]

                print(f"✅ 第 {i+1} 个Token调用成功，图像生成完成!")
                return (image_tensor,)

            except Exception as e:
                last_exception = e
                print(f"❌ 第 {i+1} 个Token调用失败: {str(e)}")
                if i < len(tokens) - 1:
                    continue
                else:
                    break

        raise Exception(f"所有 {len(tokens)} 个API Token都失败了。最后的错误: {str(last_exception)}")


# -------------------------- 图像编辑节点 --------------------------
class ModelScopeImageEditNode:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        config = load_config()
        saved_tokens = load_api_tokens()
        edit_models = config.get("image_edit_models", ["Qwen/Qwen-Image-Edit"])
        gen_models = config.get("image_models", ["Qwen/Qwen-Image"])

        return {
            "required": {
                "image": ("IMAGE",),
                "prompt": ("STRING", {"multiline": True, "default": "修改图片中的内容"}),
                "api_tokens": ("STRING", {
                    "default": "***已保存{}个Token***".format(len(saved_tokens)) if saved_tokens else "",
                    "placeholder": "请输入API Token（支持多个，用逗号/换行分隔）" if not saved_tokens else "留空使用已保存的Token",
                    "multiline": True
                }),
                "image_gen_mode": ("BOOLEAN", {"default": False, "label_on": "图生图模式", "label_off": "图像编辑模式"}),
            },
            "optional": {
                "gen_model": (gen_models, {"default": gen_models[0] if gen_models else "Qwen/Qwen-Image"}),
                "edit_model": (edit_models, {"default": edit_models[0] if edit_models else "Qwen/Qwen-Image-Edit"}),
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
                "width": ("INT", {"default": 512, "min": 64, "max": 1664, "step": 8}),
                "height": ("INT", {"default": 512, "min": 64, "max": 1664, "step": 8}),
                "steps": ("INT", {"default": 30, "min": 1, "max": 100, "step": 1}),
                "guidance": ("FLOAT", {"default": 3.5, "min": 1.5, "max": 20.0, "step": 0.1}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2147483647}),
                "lora1_id": ("STRING", {"default": "", "label": "LoRA1 模型ID"}),
                "lora1_w": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA1 权重"}),
                "lora2_id": ("STRING", {"default": "", "label": "LoRA2 模型ID"}),
                "lora2_w": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA2 权重"}),
                "lora3_id": ("STRING", {"default": "", "label": "LoRA3 模型ID"}),
                "lora3_w": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.1, "label": "LoRA3 权重"}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("edited_image",)
    FUNCTION = "edit_image"
    CATEGORY = "ModelScopeAPI"

    def edit_image(self, image, prompt, api_tokens, image_gen_mode=False, gen_model="Qwen/Qwen-Image",
                   edit_model="Qwen/Qwen-Image-Edit", negative_prompt="",
                   width=512, height=512, steps=30, guidance=3.5, seed=-1,
                   lora1_id="", lora1_w=0.8, lora2_id="", lora2_w=0.8, lora3_id="", lora3_w=0.8):
        config = load_config()
        tokens = parse_api_tokens(api_tokens)

        if not tokens:
            raise Exception("请提供至少一个有效的API Token\n提示: 使用 ModelScope登录获取Token 节点自动获取Token")

        if api_tokens and api_tokens.strip() not in ["", "***已保存{}个Token***".format(len(load_api_tokens()))]:
            if save_api_tokens(tokens):
                print(f"✅ 已保存 {len(tokens)} 个API Token")

        model = gen_model if image_gen_mode else edit_model
        mode = "图生图模式" if image_gen_mode else "图像编辑模式"
        print(f"🔍 开始图像编辑... 模型: {model} ({mode})")

        lora_dict = {}
        if lora1_id and lora1_id.strip(): lora_dict[lora1_id.strip()] = float(lora1_w)
        if lora2_id and lora2_id.strip(): lora_dict[lora2_id.strip()] = float(lora2_w)
        if lora3_id and lora3_id.strip(): lora_dict[lora3_id.strip()] = float(lora3_w)

        last_exception = None
        for i, token in enumerate(tokens):
            try:
                print(f"🔄 尝试使用第 {i+1}/{len(tokens)} 个Token...")

                temp_img_path = None
                image_url = None
                try:
                    temp_img_path = os.path.join(tempfile.gettempdir(), f"qwen_edit_temp_{int(time.time())}.jpg")
                    if len(image.shape) == 4:
                        img = image[0]
                    else:
                        img = image
                    img_np = 255. * img.cpu().numpy()
                    img_pil = Image.fromarray(np.clip(img_np, 0, 255).astype(np.uint8))
                    img_pil.save(temp_img_path)

                    upload_url = 'https://ai.kefan.cn/api/upload/local'
                    with open(temp_img_path, 'rb') as img_file:
                        files = {'file': img_file}
                        upload_response = requests.post(upload_url, files=files, timeout=30)
                        if upload_response.status_code == 200:
                            upload_data = upload_response.json()
                            if upload_data.get('success') == True and 'data' in upload_data:
                                image_url = upload_data['data']
                                print(f"📤 图像上传成功")
                except Exception as e:
                    print(f"⚠️ 图像上传失败，将使用base64编码: {str(e)}")

                if not image_url:
                    image_data = tensor_to_base64_url(image)
                    payload = {'model': model, 'prompt': prompt, 'image': image_data}
                else:
                    payload = {'model': model, 'prompt': prompt, 'image_url': image_url}

                if lora_dict:
                    payload['loras'] = lora_dict
                    first_lora_id = next(iter(lora_dict.keys()))
                    first_lora_w = next(iter(lora_dict.values()))
                    payload['lora'] = first_lora_id
                    payload['lora_weight'] = first_lora_w

                if negative_prompt.strip():
                    payload['negative_prompt'] = negative_prompt
                if width != 512 or height != 512:
                    payload['size'] = f"{width}x{height}"
                if steps != 30:
                    payload['steps'] = steps
                if guidance != 3.5:
                    payload['guidance'] = guidance
                if seed != -1:
                    payload['seed'] = seed
                else:
                    import random
                    payload['seed'] = random.randint(0, 2147483647)

                headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json',
                    'X-ModelScope-Async-Mode': 'true',
                    'X-ModelScope-Task-Type': 'image-to-image-generation',
                    'X-ModelScope-Request-Params': json.dumps({'loras': lora_dict} if lora_dict else {})
                }

                url = 'https://api-inference.modelscope.cn/v1/images/generations'
                submission_response = requests.post(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), headers=headers, timeout=config.get("timeout", 60))

                if submission_response.status_code != 200:
                    raise Exception(f"API请求失败: {submission_response.status_code}, {submission_response.text}")

                submission_json = submission_response.json()
                result_image_url = None

                if 'task_id' in submission_json:
                    task_id = submission_json['task_id']
                    print(f"📌 获取任务ID: {task_id}, 开始轮询结果...")
                    poll_start = time.time()
                    max_wait_seconds = max(60, config.get('timeout', 720))

                    while True:
                        task_resp = requests.get(
                            f"https://api-inference.modelscope.cn/v1/tasks/{task_id}",
                            headers={'Authorization': f'Bearer {token}', 'X-ModelScope-Task-Type': 'image_generation'},
                            timeout=config.get("image_download_timeout", 120)
                        )
                        if task_resp.status_code != 200:
                            raise Exception(f"任务查询失败: {task_resp.status_code}, {task_resp.text}")
                        task_data = task_resp.json()
                        status = task_data.get('task_status')
                        print(f"⌛ 任务状态: {status} (已等待 {int(time.time() - poll_start)} 秒)")
                        if status == 'SUCCEED':
                            output_images = task_data.get('output_images') or []
                            if not output_images:
                                raise Exception("任务成功但未返回图片URL")
                            result_image_url = output_images[0]
                            break
                        if status == 'FAILED':
                            error_message = task_data.get('errors', {}).get('message', '未知错误')
                            raise Exception(f"任务失败: {error_message}")
                        if time.time() - poll_start > max_wait_seconds:
                            raise Exception(f"任务轮询超时 ({max_wait_seconds}秒)")
                        time.sleep(5)
                else:
                    raise Exception(f"未识别的API返回格式: {submission_json}")

                print(f"📥 下载编辑后的图片...")
                img_response = requests.get(result_image_url, timeout=config.get("image_download_timeout", 30))
                if img_response.status_code != 200:
                    raise Exception(f"图片下载失败: {img_response.status_code}")

                pil_image = Image.open(BytesIO(img_response.content))
                if pil_image.mode != 'RGB':
                    pil_image = pil_image.convert('RGB')
                image_np = np.array(pil_image).astype(np.float32) / 255.0
                image_tensor = torch.from_numpy(image_np)[None,]

                if temp_img_path and os.path.exists(temp_img_path):
                    try: os.remove(temp_img_path)
                    except: pass

                print(f"✅ 第 {i+1} 个Token调用成功，图像编辑完成!")
                return (image_tensor,)

            except Exception as e:
                last_exception = e
                print(f"❌ 第 {i+1} 个Token调用失败: {str(e)}")
                if temp_img_path and os.path.exists(temp_img_path):
                    try: os.remove(temp_img_path)
                    except: pass
                if i < len(tokens) - 1:
                    continue
                else:
                    break

        raise Exception(f"所有 {len(tokens)} 个API Token都失败了。最后的错误: {str(last_exception)}")


NODE_CLASS_MAPPINGS = {
    "QIBOImageNode": ModelScopeImageNode,
    "QIBOImageEditNode": ModelScopeImageEditNode,
    "QIBOLORAPresetNode": ModelScopeLoraPresetNode,
    "QIBOSingleLoraLoaderNode": ModelScopeSingleLoraLoaderNode,
    "QIBOMultiLoraLoaderNode": ModelScopeMultiLoraLoaderNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOImageNode": "QIBO-Image 生图节点",
    "QIBOImageEditNode": "QIBO-Image 图像编辑节点",
    "QIBOLORAPresetNode": "QIBO-LoRA 预设管理",
    "QIBOSingleLoraLoaderNode": "QIBO-LoRA 单LoRA加载",
    "QIBOMultiLoraLoaderNode": "QIBO-LoRA 多LoRA加载",
}