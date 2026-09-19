import os
import json
from .qibo_auth import (
    load_config, save_config,
    load_api_tokens, save_api_tokens,
    verify_token, login_with_token,
    login_with_playwright, check_playwright_available,
    open_token_page_in_browser
)


class ModelScopeLoginNode:
    """
    魔塔登录节点 - 通过 Playwright 浏览器自动化登录魔塔并获取 API Token
    支持三种模式:
    1. 浏览器自动登录 (需要安装 Playwright)
    2. 手动输入 Token 验证
    3. 打开浏览器手动获取 Token
    """

    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        config = load_config()
        login_config = config.get("login_config", {})
        saved_tokens = load_api_tokens()
        playwright_available = check_playwright_available()

        return {
            "required": {
                "action": (
                    [
                        "浏览器自动登录获取Token",
                        "验证已保存的Token",
                        "打开Token页面手动获取",
                    ],
                    {"default": "浏览器自动登录获取Token"}
                ),
            },
            "optional": {
                "username": ("STRING", {
                    "default": "",
                    "placeholder": "魔塔账号 (邮箱/手机号)",
                    "multiline": False
                }),
                "password": ("STRING", {
                    "default": "",
                    "placeholder": "魔塔密码",
                    "multiline": False
                }),
                "manual_token": ("STRING", {
                    "default": "",
                    "placeholder": "手动输入Token (ms-开头)",
                    "multiline": True
                }),
                "headless": ("BOOLEAN", {
                    "default": False,
                    "label_on": "无头模式",
                    "label_off": "显示浏览器"
                }),
                "auto_fill": ("BOOLEAN", {
                    "default": True,
                    "label_on": "自动填充账号密码",
                    "label_off": "手动登录"
                }),
                "wait_timeout": ("INT", {
                    "default": login_config.get("wait_for_login_timeout", 120),
                    "min": 30,
                    "max": 600,
                    "step": 10
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("api_token", "username", "status_info")
    FUNCTION = "execute_login"
    CATEGORY = "ModelScopeAPI/登录"

    def execute_login(self, action, username="", password="", manual_token="",
                      headless=False, auto_fill=True, wait_timeout=120):

        if action == "浏览器自动登录获取Token":
            return self._action_browser_login(username, password, headless, auto_fill, wait_timeout)
        elif action == "验证已保存的Token":
            return self._action_verify_saved_tokens()
        elif action == "打开Token页面手动获取":
            return self._action_open_token_page()
        else:
            return ("", "", f"未知操作: {action}")

    def _action_browser_login(self, username, password, headless, auto_fill, wait_timeout):
        if not check_playwright_available():
            return ("", "", "❌ Playwright未安装\n请运行:\npip install playwright\nplaywright install chromium")

        if auto_fill and (not username or not password):
            print("⚠️ 未提供账号密码，将打开浏览器手动登录")

        print("🚀 启动浏览器自动化登录...")
        success, token, detail = login_with_playwright(
            username=username,
            password=password,
            headless=headless,
            auto_fill=auto_fill,
            wait_timeout=wait_timeout
        )

        if success and token:
            valid, user_info = verify_token(token)
            if valid:
                existing_tokens = load_api_tokens()
                if token not in existing_tokens:
                    existing_tokens.append(token)
                    save_api_tokens(existing_tokens)
                    print(f"✅ Token已保存 (共 {len(existing_tokens)} 个)")
                else:
                    print("ℹ️ Token已存在，无需重复保存")

                uname = user_info.get("username", "")
                email = user_info.get("email", "")
                status = f"✅ 登录成功\n用户: {uname}\n邮箱: {email}\nToken: {token[:20]}...\n已自动保存"
                return (token, uname, status)
            else:
                return (token, "", f"⚠️ 获取到Token但验证失败: {user_info.get('error')}")
        else:
            error = detail.get("error", "未知错误")
            return ("", "", f"❌ 登录失败: {error}")

    def _action_verify_saved_tokens(self):
        tokens = load_api_tokens()
        if not tokens:
            return ("", "", "❌ 没有已保存的Token\n请先登录获取Token")

        print(f"🔍 验证 {len(tokens)} 个已保存的Token...")
        results = []
        valid_tokens = []
        first_valid_token = ""
        first_username = ""

        for i, token in enumerate(tokens):
            valid, info = verify_token(token)
            if valid:
                uname = info.get("username", "")
                email = info.get("email", "")
                results.append(f"✅ Token {i+1}: 有效 | 用户: {uname} | 邮箱: {email}")
                valid_tokens.append(token)
                if not first_valid_token:
                    first_valid_token = token
                    first_username = uname
            else:
                results.append(f"❌ Token {i+1}: 无效 | {info.get('error')}")

        if len(valid_tokens) != len(tokens):
            save_api_tokens(valid_tokens)
            print(f"🧹 已清理无效Token，保留 {len(valid_tokens)} 个有效Token")

        status = "\n".join(results)
        if not first_valid_token:
            status += "\n\n⚠️ 所有Token均无效，请重新登录获取"
        return (first_valid_token, first_username, status)

    def _action_open_token_page(self):
        success = open_token_page_in_browser()
        if success:
            return ("", "", "🌐 已在浏览器中打开Token页面\n请登录后复制Access Token\n然后粘贴到manual_token字段\n再执行'验证已保存的Token'")
        else:
            return ("", "", "❌ 打开浏览器失败")


class ModelScopeTokenManageNode:
    """
    Token 管理节点 - 管理多个 API Token
    """

    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        saved_tokens = load_api_tokens()
        return {
            "required": {
                "action": (
                    ["查看所有Token", "添加Token", "删除Token", "清空所有Token", "验证Token"],
                    {"default": "查看所有Token"}
                ),
            },
            "optional": {
                "token_input": ("STRING", {
                    "default": "",
                    "placeholder": "输入Token (ms-开头，添加时必填)",
                    "multiline": True
                }),
                "token_index": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 100,
                    "step": 1
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("api_token", "status_info")
    FUNCTION = "manage_tokens"
    CATEGORY = "ModelScopeAPI/登录"

    def manage_tokens(self, action, token_input="", token_index=1):
        tokens = load_api_tokens()

        if action == "查看所有Token":
            if not tokens:
                return ("", "没有已保存的Token")
            lines = [f"=== 已保存 {len(tokens)} 个Token ==="]
            for i, token in enumerate(tokens):
                valid, info = verify_token(token)
                status = f"✅ {info.get('username', '未知')}" if valid else "❌ 无效"
                lines.append(f"{i+1}. {token[:25]}... | {status}")
            return (tokens[0] if tokens else "", "\n".join(lines))

        elif action == "添加Token":
            if not token_input or not token_input.strip():
                return ("", "❌ 请输入要添加的Token")
            new_tokens = [t.strip() for t in token_input.replace(',', '\n').split('\n') if t.strip()]
            added = 0
            for t in new_tokens:
                if t not in tokens:
                    tokens.append(t)
                    added += 1
            save_api_tokens(tokens)
            return (new_tokens[0] if new_tokens else "", f"✅ 添加了 {added} 个Token\n当前共 {len(tokens)} 个Token")

        elif action == "删除Token":
            if not tokens:
                return ("", "❌ 没有可删除的Token")
            if token_index < 1 or token_index > len(tokens):
                return ("", f"❌ 索引超出范围 (1-{len(tokens)})")
            removed = tokens.pop(token_index - 1)
            save_api_tokens(tokens)
            return ("", f"✅ 已删除Token: {removed[:25]}...\n剩余 {len(tokens)} 个Token")

        elif action == "清空所有Token":
            count = len(tokens)
            save_api_tokens([])
            return ("", f"✅ 已清空 {count} 个Token")

        elif action == "验证Token":
            if not token_input or not token_input.strip():
                return ("", "❌ 请输入要验证的Token")
            token = token_input.strip()
            valid, info = verify_token(token)
            if valid:
                login_ok, login_info = login_with_token(token)
                login_status = "✅ 登录成功" if login_ok else f"⚠️ 登录接口: {login_info.get('error')}"
                return (token, f"✅ Token有效\n用户: {info.get('username')}\n邮箱: {info.get('email')}\n{login_status}")
            else:
                return ("", f"❌ Token无效: {info.get('error')}")

        return ("", "")


NODE_CLASS_MAPPINGS = {
    "QIBOLoginNode": ModelScopeLoginNode,
    "QIBOTokenManageNode": ModelScopeTokenManageNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "QIBOLoginNode": "QIBO 登录获取Token",
    "QIBOTokenManageNode": "QIBO Token管理",
}