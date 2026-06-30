"""Email verification utilities for carSystem.

Supports two providers:
- console: write verification codes to debug_ocr/email_codes.txt for local tests.
- smtp: send real email through SMTP. If SMTP fails and
  EMAIL_SMTP_FALLBACK_TO_CONSOLE=1, the code is also written to the debug file
  so you can still complete local testing and see the real error in logs.
"""

from __future__ import annotations

import logging
import os
import random
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional

from config import (
    BASE_DIR,
    EMAIL_CODE_LENGTH,
    EMAIL_PROVIDER,
    EMAIL_SMTP_FALLBACK_TO_CONSOLE,
    EMAIL_CODE_TTL_SECONDS,
    SMTP_DEBUG,
    SMTP_FROM_EMAIL,
    SMTP_FROM_NAME,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_TIMEOUT_SECONDS,
    SMTP_USERNAME,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
)

logger = logging.getLogger(__name__)

EMAIL_PURPOSE_RESET = "reset_password"
EMAIL_PURPOSE_BIND = "bind_email"


def generate_email_code(length: Optional[int] = None) -> str:
    """Generate a numeric email verification code."""
    n = int(length or EMAIL_CODE_LENGTH or 6)
    n = max(4, min(n, 10))
    return "".join(str(random.randint(0, 9)) for _ in range(n))


def _debug_file_path() -> str:
    debug_dir = os.path.join(BASE_DIR, "debug_ocr")
    os.makedirs(debug_dir, exist_ok=True)
    return os.path.join(debug_dir, "email_codes.txt")


def _mask_email(email: str) -> str:
    email = (email or "").strip()
    if "@" not in email:
        return email
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        masked = name[:1] + "*"
    else:
        masked = name[:2] + "***" + name[-1:]
    return f"{masked}@{domain}"


def _purpose_text(purpose: str) -> str:
    if purpose == EMAIL_PURPOSE_BIND:
        return "绑定邮箱"
    return "找回密码"


def _write_console_email_code(email: str, code: str, purpose: str, note: str = "") -> None:
    """Write code to console and debug file. Useful for local debugging."""
    line = (
        f"[{_purpose_text(purpose)}] email={email} code={code} "
        f"ttl={EMAIL_CODE_TTL_SECONDS}s"
    )
    if note:
        line += f" note={note}"
    print("[EMAIL_CODE] " + line)
    try:
        with open(_debug_file_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        logger.exception("failed to write email debug code")


def _build_message(email: str, code: str, purpose: str) -> MIMEText:
    action = _purpose_text(purpose)
    subject = f"车辆管理系统{action}验证码"
    body = f"""您好：

您正在进行车辆管理系统的{action}操作。

验证码：{code}
有效期：{EMAIL_CODE_TTL_SECONDS // 60 if EMAIL_CODE_TTL_SECONDS >= 60 else EMAIL_CODE_TTL_SECONDS} {'分钟' if EMAIL_CODE_TTL_SECONDS >= 60 else '秒'}

如果不是您本人操作，请忽略本邮件。
"""
    msg = MIMEText(body, "plain", "utf-8")
    from_email = SMTP_FROM_EMAIL or SMTP_USERNAME
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(SMTP_FROM_NAME or "车辆管理系统", "utf-8")), from_email))
    msg["To"] = email
    return msg


def _send_smtp(email: str, code: str, purpose: str) -> None:
    if not SMTP_HOST:
        raise RuntimeError("SMTP_HOST 未配置")
    if not SMTP_USERNAME:
        raise RuntimeError("SMTP_USERNAME 未配置")
    if not SMTP_PASSWORD:
        raise RuntimeError("SMTP_PASSWORD 未配置；QQ/163 等邮箱需要 SMTP 授权码，不是登录密码")
    if not (SMTP_FROM_EMAIL or SMTP_USERNAME):
        raise RuntimeError("SMTP_FROM_EMAIL 或 SMTP_USERNAME 未配置")

    msg = _build_message(email, code, purpose)
    from_email = SMTP_FROM_EMAIL or SMTP_USERNAME

    logger.info(
        "[EMAIL] sending purpose=%s to=%s host=%s port=%s ssl=%s tls=%s",
        purpose,
        _mask_email(email),
        SMTP_HOST,
        SMTP_PORT,
        SMTP_USE_SSL,
        SMTP_USE_TLS,
    )

    server = None
    try:
        if SMTP_USE_SSL:
            server = smtplib.SMTP_SSL(SMTP_HOST, int(SMTP_PORT), timeout=int(SMTP_TIMEOUT_SECONDS))
        else:
            server = smtplib.SMTP(SMTP_HOST, int(SMTP_PORT), timeout=int(SMTP_TIMEOUT_SECONDS))
        if SMTP_DEBUG:
            server.set_debuglevel(1)
        server.ehlo()
        if SMTP_USE_TLS and not SMTP_USE_SSL:
            server.starttls()
            server.ehlo()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.sendmail(from_email, [email], msg.as_string())
        logger.info("[EMAIL] sent success purpose=%s to=%s", purpose, _mask_email(email))
    finally:
        try:
            if server is not None:
                server.quit()
        except Exception:
            pass


def send_email_code(email: str, code: str, purpose: str = EMAIL_PURPOSE_RESET) -> None:
    """Send an email verification code or write it locally in console mode."""
    email = (email or "").strip().lower()
    purpose = (purpose or EMAIL_PURPOSE_RESET).strip()

    if not email:
        raise ValueError("邮箱不能为空")
    if not code:
        raise ValueError("验证码不能为空")

    provider = (EMAIL_PROVIDER or "console").strip().lower()
    if provider == "console":
        _write_console_email_code(email, code, purpose)
        return

    if provider != "smtp":
        raise RuntimeError(f"不支持的 EMAIL_PROVIDER: {EMAIL_PROVIDER}，只能是 console 或 smtp")

    try:
        _send_smtp(email, code, purpose)
    except Exception as exc:
        logger.exception("[EMAIL] smtp send failed to=%s", _mask_email(email))
        if EMAIL_SMTP_FALLBACK_TO_CONSOLE:
            _write_console_email_code(email, code, purpose, note=f"SMTP发送失败，已降级写入本地：{exc}")
            return
        raise RuntimeError(f"邮箱验证码发送失败：{exc}") from exc
