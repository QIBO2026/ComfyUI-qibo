# ComfyUI-ModelScope-API-Pro

ComfyUI 魔塔 ModelScope API 增强版自定义节点，在原版基础上**新增登录魔塔自动获取 API Token** 功能。

## ✨ 新增功能

### 🔑 登录获取 Token（核心新增）
- **ModelScope 登录获取Token** 节点：通过 Playwright 浏览器自动化登录魔塔，自动获取 Access Token
  - 浏览器自动登录：自动填入账号密码，处理验证码后自动抓取 Token
  - 验证已保存的 Token：批量验证 Token 有效性，自动清理失效 Token
  - 打开 Token 页面手动获取：用系统浏览器打开魔塔 Token 页面
- **ModelScope Token管理** 节点：管理多个 Token（查看/添加/删除/清空/验证）

### 🖼️ 原有功能（完整保留）
- 生图节点（文生图，支持 LoRA）
- 图像编辑节点（图生图/图像编辑，支持 LoRA）
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

1. 添加 **ModelScope 登录获取Token** 节点
2. 选择操作 `浏览器自动登录获取Token`
3. 填入魔塔账号（邮箱/手机号）和密码
4. 设置 `显示浏览器` = True（首次登录建议显示浏览器以处理验证码）
5. 执行节点，浏览器自动打开魔塔登录页
6. 如有验证码，在浏览器中手动完成验证
7. 登录成功后自动导航到 Token 页面抓取 Token
8. Token 自动保存到配置文件，后续节点可直接使用

### 手动获取 Token

1. 添加 **ModelScope 登录获取Token** 节点
2. 选择操作 `打开Token页面手动获取`
3. 在浏览器中登录魔塔，复制 Access Token（`ms-` 开头）
4. 添加 **ModelScope Token管理** 节点，选择 `添加Token`，粘贴 Token

### 使用 Token 生成图像

1. 添加 **ModelScope-Image 生图节点**
2. `api_tokens` 字段留空（自动使用已保存的 Token）
3. 输入提示词，执行生成

## 🔑 如何获取 ModelScope Access Token

### 方式一：自动登录获取（本项目新增）
使用 **ModelScope 登录获取Token** 节点，自动完成。

### 方式二：网页手动获取
1. 访问 https://modelscope.cn 并登录
2. 进入 https://modelscope.cn/my/myaccesstoken
3. 创建或查看 Access Token（`ms-` 开头）

## 📋 节点列表

| 节点 | 类别 | 功能 |
|------|------|------|
| ModelScope 登录获取Token | ModelScopeAPI/登录 | 浏览器自动化登录获取 Token |
| ModelScope Token管理 | ModelScopeAPI/登录 | 管理多个 Token |
| ModelScope-Image 生图节点 | ModelScopeAPI | 文生图 |
| ModelScope-Image 图像编辑节点 | ModelScopeAPI | 图生图/图像编辑 |
| ModelScope-Text 文本生成节点 | ModelScopeAPI | 大语言模型对话 |
| ModelScope-Vision 图生文节点 | ModelScopeAPI | 图像描述分析 |
| ModelScope 图像描述生成 | ModelScopeAPI | Qwen3-VL 反推 |
| ModelScope-LoRA 预设管理 | ModelScopeAPI/LoRA | LoRA 预设增删改查 |
| ModelScope-LoRA 单LoRA加载 | ModelScopeAPI/LoRA | 加载单个 LoRA |
| ModelScope-LoRA 多LoRA加载 | ModelScopeAPI/LoRA | 加载多个 LoRA |

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
- Qwen/Qwen3-Coder-480B-A35B-Instruct
- deepseek-ai/DeepSeek-V3.1, deepseek-ai/DeepSeek-R1-0528
- ZhipuAI/GLM-4.5

### 视觉模型
- stepfun-ai/step3
- Qwen/Qwen2.5-VL-7B/72B/3B/32B-Instruct
- Qwen/QVQ-72B-Preview

## 📄 许可证
MIT License