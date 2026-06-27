"""
CarFleetSystem V8.1 SMS utilities.

生产环境推荐 SMS_PROVIDER=aliyun，并在服务器环境变量中配置阿里云短信参数。
本地测试可用 SMS_PROVIDER=console，验证码会写入控制台和 debug_ocr/sms_codes.txt。
"""

import json
import os
import random
from pathlib import Path
from typing import Dict

from config import (
    ALIYUN_ACCESS_KEY_ID,
    ALIYUN_ACCESS_KEY_SECRET,
    ALIYUN_SMS_REGION,
    ALIYUN_SMS_SIGN_NAME,
    ALIYUN_SMS_TEMPLATE_CODE_LOGIN,
    ALIYUN_SMS_TEMPLATE_CODE_RESET,
    ALIYUN_SMS_TEMPLATE_PARAM_NAME,
    BASE_DIR,
    SMS_CODE_LENGTH,
    SMS_CODE_TTL_SECONDS,
    SMS_PROVIDER,
)

SMS_PURPOSE_LOGIN = "login"
SMS_PURPOSE_RESET = "reset_password"


def generate_sms_code() -> str:
    length = max(4, min(int(SMS_CODE_LENGTH), 8))
    start = 10 ** (length - 1)
    end = (10 ** length) - 1
    return str(random.randint(start, end))


def _purpose_label(purpose: str) -> str:
    if purpose == SMS_PURPOSE_LOGIN:
        return "短信验证码登录"
    if purpose == SMS_PURPOSE_RESET:
        return "找回密码"
    return purpose or "验证码"


def send_sms_code(phone: str, code: str, purpose: str) -> None:
    provider = (SMS_PROVIDER or "console").strip().lower()
    if provider == "aliyun":
        _send_sms_code_aliyun(phone, code, purpose)
        return
    if provider == "console":
        _send_sms_code_console(phone, code, purpose)
        return
    raise RuntimeError(f"不支持的 SMS_PROVIDER：{provider}")


def _send_sms_code_console(phone: str, code: str, purpose: str) -> None:
    """仅用于本地测试：把验证码打印并写入文件，不发送真实短信。"""
    msg = f"[短信测试] 手机号={phone} 用途={_purpose_label(purpose)} 验证码={code} 有效期={SMS_CODE_TTL_SECONDS}秒"
    print(msg)
    try:
        debug_dir = Path(BASE_DIR) / "debug_ocr"
        debug_dir.mkdir(parents=True, exist_ok=True)
        with open(debug_dir / "sms_codes.txt", "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _aliyun_template_code(purpose: str) -> str:
    if purpose == SMS_PURPOSE_LOGIN:
        return ALIYUN_SMS_TEMPLATE_CODE_LOGIN
    if purpose == SMS_PURPOSE_RESET:
        return ALIYUN_SMS_TEMPLATE_CODE_RESET
    return ALIYUN_SMS_TEMPLATE_CODE_LOGIN


def _send_sms_code_aliyun(phone: str, code: str, purpose: str) -> None:
    """阿里云短信服务。需要先申请短信签名和验证码模板。"""
    missing = []
    for name, value in {
        "ALIYUN_ACCESS_KEY_ID": ALIYUN_ACCESS_KEY_ID,
        "ALIYUN_ACCESS_KEY_SECRET": ALIYUN_ACCESS_KEY_SECRET,
        "ALIYUN_SMS_SIGN_NAME": ALIYUN_SMS_SIGN_NAME,
        "ALIYUN_SMS_TEMPLATE_CODE_LOGIN/RESET": _aliyun_template_code(purpose),
    }.items():
        if not value:
            missing.append(name)
    if missing:
        raise RuntimeError("阿里云短信配置不完整：" + ", ".join(missing))

    try:
        from alibabacloud_dysmsapi20170525.client import Client as DysmsapiClient
        from alibabacloud_dysmsapi20170525 import models as dysmsapi_models
        from alibabacloud_tea_openapi import models as open_api_models
        from alibabacloud_tea_util import models as util_models
    except Exception as exc:
        raise RuntimeError("未安装阿里云短信SDK，请执行 pip install alibabacloud_dysmsapi20170525") from exc

    config = open_api_models.Config(
        access_key_id=ALIYUN_ACCESS_KEY_ID,
        access_key_secret=ALIYUN_ACCESS_KEY_SECRET,
    )
    config.endpoint = f"dysmsapi.aliyuncs.com"
    client = DysmsapiClient(config)

    template_param: Dict[str, str] = {ALIYUN_SMS_TEMPLATE_PARAM_NAME or "code": code}
    request = dysmsapi_models.SendSmsRequest(
        phone_numbers=phone,
        sign_name=ALIYUN_SMS_SIGN_NAME,
        template_code=_aliyun_template_code(purpose),
        template_param=json.dumps(template_param, ensure_ascii=False),
    )
    runtime = util_models.RuntimeOptions()
    response = client.send_sms_with_options(request, runtime)
    body = getattr(response, "body", None)
    result_code = getattr(body, "code", None)
    if result_code and str(result_code).upper() != "OK":
        message = getattr(body, "message", "未知错误")
        raise RuntimeError(f"阿里云短信发送失败：{result_code} {message}")
