# ComfyUI-QIBO

ComfyUI 魔塔 ModelScope API 增强版自定义节点，在原版基础上**新增登录魔塔自动获取 API Token** 功能。

## ✨ 新增功能

### 🔑 登录获取 Token（核心新增）
- **QIBO 登录获取Token** 节点：通过 Playwright 浏览器自动化登录魔塔，自动获取 Access Token
  - 浏览器自动登录：自动填入账号密码，处理验证码后自动抓取 Token
  - 验证已保存的 Token：批量验证 Token 有效性，自动清理失效 Token
  - 打开 Token 页面手动获取：用系统浏览器打开魔塔 Token 页面
- **QIBO Token管理** 节点：管理多个 Token（查看/添加/删除/清空/验证）

### 🖼️ 原有功能（完整保留）
- 生图节点（文生图，支持 LoRA）
- 图像编辑节点（图生图/图像编辑，支持多图输入与 LoRA）
- 文本生成节点（大语言模型对话）
- 图生文节点（图像描述分析）
- 图像描述生成节点（Qwen3-VL 反推）
- LoRA 预设管理 / 单 LoRA 加载 / 多 LoRA 加载

## 📦 安装

将本目录放入 ComfyUI 的 `custom_nodes` 目录下，然后安装依赖：

```bash
pip install -r requirements.txt
playwright install chromium
```

> Playwright 用于浏览器自动化登录获取 Token。如不使用自动登录功能，可跳过 Playwright 安装，手动输入 Token。

## 🚀 使用方法

### 自动登录获取 Token（推荐）

1. 添加 **QIBO 登录获取Token** 节点
2. 选择操作 `浏览器自动登录获取Token`
3. 填入魔塔账号（邮箱/手机号）和密码
4. 设置 `显示浏览器` = True（首次登录建议显示浏览器以处理验证码）
5. 执行节点，浏览器自动打开魔塔登录页
6. 如有验证码，在浏览器中手动完成验证
7. 登录成功后自动导航到 Token 页面抓取 Token
8. Token 自动保存到配置文件，后续节点可直接使用

### 手动获取 Token

1. 添加 **QIBO 登录获取Token** 节点
2. 选择操作 `打开Token页面手动获取`
3. 在浏览器中登录魔塔，复制 Access Token（`ms-` 开头）
4. 添加 **QIBO Token管理** 节点，选择 `添加Token`，粘贴 Token

### 使用 Token 生成图像

1. 添加 **QIBO-Image 生图节点**
2. `api_tokens` 字段留空（自动使用已保存的 Token）
3. 输入提示词，执行生成

## 🔑 如何获取 ModelScope Access Token

### 方式一：自动登录获取（本项目新增）
使用 **QIBO 登录获取Token** 节点，自动完成。

### 方式二：网页手动获取
1. 访问 https://modelscope.cn 并登录
2. 进入 https://modelscope.cn/my/myaccesstoken
3. 创建或查看 Access Token（`ms-` 开头）

## 📋 节点列表

| 节点 | 类别 | 功能 |
|------|------|------|
| QIBO 登录获取Token | QIBO_API/登录 | 浏览器自动化登录获取 Token |
| QIBO Token管理 | QIBO_API/登录 | 管理多个 Token |
| QIBO-Image 生图节点 | QIBO_API | 文生图 |
| QIBO-Image 图像编辑节点 | QIBO_API | 图生图/图像编辑（支持多图输入，最多4张） |
| QIBO-Text 文本生成节点 | QIBO_API | 大语言模型对话 |
| QIBO-Text 推理文本节点 | QIBO_API | 推理模型对话，分离输出推理过程与最终回答 |
| QIBO 故事分镜生成 | QIBO_API | 故事要求→生成故事→拆分分镜→逐镜生成画面（人物一致性保持） |
| QIBO 文本显示 | QIBO_API | 显示文本内容，执行后在节点下方展示 |
| QIBO-Vision 图生文节点 | QIBO_API | 图像描述分析 |
| QIBO 图像描述生成 | QIBO_API | Qwen3-VL 反推 |
| QIBO-LoRA 预设管理 | QIBO_API/LoRA | LoRA 预设增删改查 |
| QIBO-LoRA 单LoRA加载 | QIBO_API/LoRA | 加载单个 LoRA |
| QIBO-LoRA 多LoRA加载 | QIBO_API/LoRA | 加载多个 LoRA |
| QIBO 图片缩放 | QIBO_API | 按长边等比缩放，输出宽高供下游使用 |
| QIBO 分块图片上传 | QIBO_API | 大图片自动分块上传，绕过服务端大小限制 |
| QIBO H3 素材规划台 | QIBO_API/H3 | 时间线编排参考视频/图片/音频，输出素材规划与分段规划 |
| QIBO H3 时间线导演台 | QIBO_API/H3 | 规划台+规划编码器合并的兼容节点 |
| QIBO H3 规划编码器 | QIBO_API/H3 | 将素材规划与提示词编码为 H3 条件与 Latent |
| QIBO H3 Omni 素材包提示词桥 | QIBO_API/H3 | 将素材包送入 Prompt Rewriter Omni，避免工作流循环 |
| QIBO H3 有限分段采样 | QIBO_API/H3/Long Video | 自适应 Drift-Control 续写 + Soft AV 音频连续性，展开并采样全部分段 |
| QIBO H3 有限分段展开 | QIBO_API/H3/Long Video | 旧工作流兼容入口 |
| QIBO H3 Two-Stage Sampler | QIBO_API/H3/SelfLift | SelfLift 渐进分辨率二采（75% 低清 + 25% 高清） |
| QIBO H3 直接 Latent Guide | QIBO_API/H3/Experimental | 从 H3 AV Latent 直接复制合法时间块（实验） |
| QIBO H3 视频差异指标 | QIBO_API/H3/Experimental | 比较两批 RGB 视频帧并报告差异（实验） |

## 🎬 MiniMax H3 时间线导演台

本插件已合并 [ComfyUI-MiniMaxH3-TimelineDirector](https://github.com/Songssx/ComfyUI-MiniMaxH3-TimelineDirector) 的全部节点，统一改用 `QIBO` 前缀注册，分类归入 `QIBO_API/H3`。

### 核心能力：轻量级无限时长视频生成

把任意目标时长拆成多个连续片段，在一次 ComfyUI 执行中自动完成逐段生成、同种子续接、自适应 Drift-Control 视频遮罩、Soft AV 音频连续性、重叠帧去除与最终音画合并。

### 主工作流节点链路

```
素材规划台 ──Omni素材包──> Omni提示词桥 ──rewritten_prompt──> 规划编码器
     └────────────────分段规划──────────────────────────────> 有限分段采样
```

长视频生成只需连接 **素材规划台「分段规划」→ 有限分段采样「有限分段规划」**。

### 依赖

- ComfyUI 原生 MiniMax H3 节点（MiniMaxH3AddGuide 等）与 MiniMax H3 Ref2VA 模型
- 使用 Omni 提示词桥需另装 [MiniMax-H3-Prompt-Rewriter-ComfyUI](https://github.com/pytraveler/MiniMax-H3-Prompt-Rewriter-ComfyUI)
- 二采需自行把 H3 Latent Upscaler 放入 `ComfyUI/models/latent_upscale_models/`

### 示例工作流

- `example_workflows/MiniMaxH3全功能合一完全体导演台工作流.json` — 全任务合一主工作流
- `example_workflows/MiniMax_H3时间规划+Prompt提示词生成.json` — 时间规划 + Omni 提示词扩写

## 🎯 支持的模型

### 生图模型
- Qwen/Qwen-Image, Qwen/Qwen-Image-2512
- MusePublic/489_ckpt_FLUX_1, MusePublic/flux-high-res
- black-forest-labs/FLUX.1-Krea-dev
- MAILAND/majicflus_v1, Tongyi-MAI/Z-Image-Turbo

### 图像编辑模型
- Qwen/Qwen-Image-Edit, Qwen/Qwen-Image-Edit-2511
- MusePublic/FLUX.1-Kontext-Dev, black-forest-labs/FLUX.1-Kontext-dev

### 文本模型
- deepseek-ai/DeepSeek-V4.1-Flash（推荐，可用）
- deepseek-ai/DeepSeek-V3.1, deepseek-ai/DeepSeek-R1-0528
- Qwen/Qwen3-Coder-480B-A35B-Instruct
- ZhipuAI/GLM-4.5

### 视觉模型
- stepfun-ai/step3
- Qwen/Qwen2.5-VL-7B/72B/3B/32B-Instruct
- Qwen/QVQ-72B-Preview

## 📄 许可证
MIT License