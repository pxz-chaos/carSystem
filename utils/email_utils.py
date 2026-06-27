# -*- coding: utf-8 -*-
import os
import random
import smtplib
from email.message import EmailMessage

from config import (
    EMAIL_PROVIDER,
    EMAIL_CODE_LENGTH,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
    SMTP_USERNAME,
    SMTP_PASSWORD,
    SMTP_FROM_NAME,
    SMTP_FROM_EMAIL,
)

EMAIL_PURPOSE_RESET = "reset_email"


def generate_email_code() -> str:
    length = max(4, int(EMAIL_CODE_LENGTH or 6))
    return str(random.randint(10 ** (length - 1), 10 ** length - 1))


def _write_console_email(to_email: str, code: str, purpose: str) -> None:
    os.makedirs("debug_ocr", exist_ok=True)
    line = f"[邮箱测试] email={to_email} purpose={purpose} code={code}\n"
    print(line.strip())
    with open(os.path.join("debug_ocr", "email_codes.txt"), "a", encoding="utf-8") as f:
        f.write(line)


def _build_message(to_email: str, code: str, purpose: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "车辆管理系统验证码"
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL or SMTP_USERNAME}>"
    msg["To"] = to_email
    purpose_text = "找回密码" if purpose == EMAIL_PURPOSE_RESET else "身份验证"
    body = (
        f"您好：\n\n"
        f"您正在进行【车辆管理系统】{purpose_text}操作。\n\n"
        f"验证码：{code}\n\n"
        f"验证码 5 分钟内有效。若非本人操作，请忽略本邮件。\n\n"
        f"车辆管理系统\n"
    )
    msg.set_content(body, subtype="plain", charset="utf-8")
    return msg


def send_email_code(to_email: str, code: str, purpose: str = EMAIL_PURPOSE_RESET) -> None:
    to_email = (to_email or "").strip().lower()
    if not to_email:
        raise ValueError("邮箱不能为空")

    if EMAIL_PROVIDER != "smtp":
        _write_console_email(to_email, code, purpose)
        return

    if not SMTP_HOST or not SMTP_USERNAME or not SMTP_PASSWORD:
        raise ValueError("SMTP 邮箱配置不完整，请检查 .env 中的 SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD")

    msg = _build_message(to_email, code, purpose)
    if SMTP_USE_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            if SMTP_USE_TLS:
                server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
