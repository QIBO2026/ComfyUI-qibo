import requests
import json
import os
import time
import re
from typing import Optional, Tuple, List, Dict, Any

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'qibo_config.json')

DEFAULT_CONFIG = {
    "default_model": "Qwen/Qwen-Image",
    "timeout": 720,
    "image_download_timeout": 30,
    "default_prompt": "A beautiful landscape",
    "default_negative_prompt": "",
    "default_width": 512,
    "default_height": 512,
    "default_seed": -1,
    "default_steps": 30,
    "default_guidance": 7.5,
    "default_text_model": "Qwen/Qwen3-Coder-480B-A35B-Instruct",
    "default_system_prompt": "You are a helpful assistant.",
    "default_user_prompt": "你好",
    "api_token": "",
    "image_models": ["Qwen/Qwen-Image"],
    "image_edit_models": ["Qwen/Qwen-Image-Edit"],
    "text_models": ["Qwen/Qwen3-Coder-480B-A35B-Instruct"],
    "vision_models": ["stepfun-ai/step3"],
    "caption_models": ["Qwen/Qwen3-VL-8B-Instruct"],
    "default_lora_weight": 0.8,
    "lora_presets": [{"name": "无LoRA", "model_id": "", "weight": 0.8}],
    "api_tokens": [],
    "login_config": {
        "base_url": "https://modelscope.cn",
        "login_page_url": "https://modelscope.cn/login",
        "token_page_url": "https://modelscope.cn/my/myaccesstoken",
        "browser_headless": False,
        "auto_fill_credentials": True,
        "wait_for_login_timeout": 120
    }
}


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
            for key, value in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = value
            return config
    except Exception as e:
        print(f"读取配置文件失败，使用默认配置: {e}")
        return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> bool:
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存配置文件失败: {e}")
        return False


def save_api_tokens(tokens: List[str]) -> bool:
    try:
        cfg = load_config()
        cfg["api_tokens"] = tokens
        return save_config(cfg)
    except Exception as e:
        print(f"保存API tokens失败: {e}")
        return False


def load_api_tokens() -> List[str]:
    try:
        cfg = load_config()
        tokens_from_cfg = cfg.get("api_tokens", [])
        if tokens_from_cfg and isinstance(tokens_from_cfg, list):
            return [token.strip() for token in tokens_from_cfg if token.strip()]
        return []
    except Exception as e:
        print(f"加载API tokens失败: {e}")
        return []


def parse_api_tokens(token_input: str) -> List[str]:
    if not token_input or token_input.strip() in ["", "***已保存***"]:
        return load_api_tokens()
    stripped = token_input.strip()
    if stripped.startswith("***已保存") and stripped.endswith("***"):
        return load_api_tokens()
    tokens = re.split(r'[,;\n]+', token_input)
    return [token.strip() for token in tokens if token.strip()]


def save_single_api_token(token: str) -> bool:
    try:
        cfg = load_config()
        cfg["api_token"] = token.strip()
        return save_config(cfg)
    except Exception as e:
        print(f"保存token失败: {e}")
        return False


def load_single_api_token() -> str:
    try:
        cfg = load_config()
        return cfg.get("api_token", "").strip()
    except Exception as e:
        print(f"读取token失败: {e}")
        return ""


# -------------------------- Token 验证 --------------------------
def verify_token(token: str) -> Tuple[bool, Dict[str, Any]]:
    """
    验证 API Token 是否有效，返回 (是否有效, 用户信息)
    调用 whoami 接口: GET /openapi/v1/users/me
    """
    if not token or not token.strip():
        return False, {"error": "Token为空"}

    base_url = "https://modelscope.cn"
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "User-Agent": "modelscope-comfyui-plugin/2.0",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.get(
            f"{base_url}/openapi/v1/users/me",
            headers=headers,
            timeout=30
        )
        if resp.status_code == 200:
            data = resp.json()
            user_data = data.get("data", data)
            username = (user_data.get("Username") or user_data.get("username")
                        or user_data.get("name") or user_data.get("preferred_username") or "")
            email = user_data.get("Email") or user_data.get("email") or ""
            return True, {
                "username": username,
                "email": email,
                "raw": user_data
            }
        else:
            return False, {
                "error": f"HTTP {resp.status_code}",
                "detail": resp.text[:200]
            }
    except Exception as e:
        return False, {"error": str(e)}


def login_with_token(token: str) -> Tuple[bool, Dict[str, Any]]:
    """
    用 Access Token 登录魔塔，换取 git token 和 session cookies
    POST /api/v1/login
    """
    if not token or not token.strip():
        return False, {"error": "Token为空"}

    base_url = "https://modelscope.cn"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "modelscope-comfyui-plugin/2.0",
    }

    try:
        resp = requests.post(
            f"{base_url}/api/v1/login",
            headers=headers,
            json={"AccessToken": token.strip()},
            cookies={"m_session_id": token.strip()},
            timeout=30
        )
        data = resp.json()
        if data.get("Code") == 200 and data.get("Success"):
            login_data = data.get("Data", {})
            return True, {
                "git_token": login_data.get("AccessToken", ""),
                "username": login_data.get("Username", ""),
                "email": login_data.get("Email", ""),
            }
        else:
            return False, {"error": data.get("Message", "登录失败")}
    except Exception as e:
        return False, {"error": str(e)}


# -------------------------- Playwright 浏览器自动化登录 --------------------------
def check_playwright_available() -> bool:
    try:
        import playwright
        return True
    except ImportError:
        return False


def login_with_playwright(
    username: str = "",
    password: str = "",
    headless: bool = False,
    auto_fill: bool = True,
    wait_timeout: int = 120
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    使用 Playwright 浏览器自动化登录魔塔并获取 API Token

    流程:
    1. 打开魔塔登录页面
    2. 自动填入账号密码 (如果提供且 auto_fill=True)
    3. 等待用户完成登录 (处理验证码等)
    4. 导航到 Access Token 页面
    5. 抓取现有 Token 或创建新 Token
    6. 返回 Token

    返回: (是否成功, Token, 详情)
    """
    if not check_playwright_available():
        return False, "", {
            "error": "Playwright未安装，请运行: pip install playwright && playwright install chromium"
        }

    from playwright.sync_api import sync_playwright

    config = load_config()
    login_config = config.get("login_config", {})
    login_url = login_config.get("login_page_url", "https://modelscope.cn/login")
    token_url = login_config.get("token_page_url", "https://modelscope.cn/my/myaccesstoken")

    token_result = ""
    detail_info = {}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = context.new_page()

            print(f"🌐 打开登录页面: {login_url}")
            page.goto(login_url, wait_until="networkidle", timeout=60000)

            if auto_fill and username and password:
                try:
                    print(f"📝 自动填入账号密码...")
                    username_input = page.wait_for_selector(
                        'input[placeholder*="账号"], input[placeholder*="邮箱"], input[placeholder*="手机"], input[type="text"]',
                        timeout=10000
                    )
                    username_input.fill(username)
                    time.sleep(0.5)

                    password_input = page.wait_for_selector(
                        'input[type="password"]',
                        timeout=10000
                    )
                    password_input.fill(password)
                    time.sleep(0.5)

                    login_btn = page.query_selector('button:has-text("登录"), button:has-text("登 录"), .login-btn')
                    if login_btn:
                        login_btn.click()
                        print(f"🚀 已点击登录按钮")
                except Exception as e:
                    print(f"⚠️ 自动填充失败，请手动登录: {e}")

            print(f"⏳ 等待登录完成 (超时: {wait_timeout}秒)...")
            print(f"💡 如果有验证码，请在浏览器中手动完成验证")

            try:
                page.wait_for_url(
                    lambda url: "login" not in url.lower() and "myaccesstoken" not in url.lower(),
                    timeout=wait_timeout * 1000
                )
                print(f"✅ 检测到登录成功")
            except Exception:
                current_url = page.url
                if "login" in current_url.lower():
                    return False, "", {"error": f"登录超时，仍在登录页面: {current_url}"}

            print(f"🌐 导航到 Token 页面: {token_url}")
            page.goto(token_url, wait_until="networkidle", timeout=60000)
            time.sleep(3)

            token_result = _extract_token_from_page(page)

            if not token_result:
                token_result = _try_create_new_token(page)

            if not token_result:
                token_result = _extract_token_from_network(context, page)

            if token_result:
                print(f"✅ 成功获取 Token: {token_result[:15]}...")
                detail_info = {"token": token_result, "page_url": page.url}
            else:
                print(f"❌ 未能自动获取 Token，请手动复制")

            browser.close()

    except Exception as e:
        return False, "", {"error": f"Playwright执行失败: {str(e)}"}

    return (bool(token_result), token_result, detail_info)


def _extract_token_from_page(page) -> str:
    """从 Token 页面提取已有的 Access Token"""
    try:
        selectors = [
            'text=ms-',
            '[class*="token"]',
            '[class*="access"]',
            'code',
            'pre',
            'input[readonly]',
            'input[value*="ms-"]',
        ]
        for selector in selectors:
            try:
                elements = page.query_selector_all(selector)
                for elem in elements:
                    text = elem.inner_text() if elem.inner_text() else elem.get_attribute("value") or ""
                    match = re.search(r'ms-[a-zA-Z0-9\-]{20,}', text)
                    if match:
                        return match.group(0)
            except Exception:
                continue

        page_text = page.inner_text("body")
        matches = re.findall(r'ms-[a-zA-Z0-9\-]{20,}', page_text)
        if matches:
            return matches[0]
    except Exception as e:
        print(f"从页面提取Token失败: {e}")
    return ""


def _try_create_new_token(page) -> str:
    """尝试在 Token 页面创建新的 Access Token"""
    try:
        print(f"🔧 尝试创建新的 Token...")
        create_btn_selectors = [
            'button:has-text("创建")',
            'button:has-text("新建")',
            'button:has-text("生成")',
            'button:has-text("新增")',
            '.create-btn',
        ]
        for selector in create_btn_selectors:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(2)

                    confirm_selectors = [
                        'button:has-text("确定")',
                        'button:has-text("确认")',
                        'button:has-text("提交")',
                        'button:has-text("保存")',
                    ]
                    for conf_sel in confirm_selectors:
                        try:
                            conf_btn = page.query_selector(conf_sel)
                            if conf_btn and conf_btn.is_visible():
                                conf_btn.click()
                                time.sleep(3)
                                break
                        except Exception:
                            continue

                    token = _extract_token_from_page(page)
                    if token:
                        return token
                    break
            except Exception:
                continue
    except Exception as e:
        print(f"创建新Token失败: {e}")
    return ""


def _extract_token_from_network(context, page) -> str:
    """从网络请求中提取 Token"""
    try:
        token = ""

        def on_response(response):
            nonlocal token
            try:
                url = response.url
                if "token" in url.lower() or "access" in url.lower() or "user" in url.lower():
                    try:
                        body = response.text()
                        matches = re.findall(r'ms-[a-zA-Z0-9\-]{20,}', body)
                        if matches and not token:
                            token = matches[0]
                    except Exception:
                        pass
            except Exception:
                pass

        page.on("response", on_response)
        page.reload(wait_until="networkidle", timeout=30000)
        time.sleep(3)
        page.remove_listener("response", on_response)

        return token
    except Exception as e:
        print(f"从网络请求提取Token失败: {e}")
    return ""


def open_token_page_in_browser() -> bool:
    """用系统默认浏览器打开魔塔 Token 页面"""
    import webbrowser
    config = load_config()
    token_url = config.get("login_config", {}).get(
        "token_page_url", "https://modelscope.cn/my/myaccesstoken"
    )
    try:
        webbrowser.open(token_url)
        print(f"🌐 已在浏览器中打开: {token_url}")
        print(f"💡 请登录后复制您的 Access Token (ms- 开头)")
        return True
    except Exception as e:
        print(f"打开浏览器失败: {e}")
        return False