import os
import sqlite3
import hashlib
import hmac
import secrets
import time
from typing import Any, Dict, List, Optional

from config import (
    DB_PATH,
    DATABASE_DIR,
    DEFAULT_USERS,
    LEGACY_DEFAULT_ADMIN_PASSWORD,
    LEGACY_DEFAULT_ADMIN_USERNAME,
    SECRET_KEY,
    SMS_CODE_TTL_SECONDS,
    SMS_MAX_ATTEMPTS,
    SMS_SEND_COOLDOWN_SECONDS,
)


ADMIN_ROLE_NAMES = {"管理员", "超级管理员", "admin", "administrator"}


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_conn() -> sqlite3.Connection:
    os.makedirs(DATABASE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
    except Exception:
        pass
    return conn


def _table_columns(cur: sqlite3.Cursor, table: str) -> List[str]:
    cur.execute(f"PRAGMA table_info({table})")
    return [str(row[1]) for row in cur.fetchall()]


def _ensure_user_columns(cur: sqlite3.Cursor) -> None:
    # extended profile fields
    columns = _table_columns(cur, "users")
    for col in ["email","gender","unit","department","team","unit_other","department_other","team_other"]:
        if col not in columns:
            try:
                cur.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
            except:
                pass

    """兼容旧数据库：补齐用户表字段。"""
    columns = _table_columns(cur, "users")
    if "phone" not in columns:
        cur.execute("ALTER TABLE users ADD COLUMN phone TEXT")
    if "role" not in columns:
        cur.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT '司机'")


def init_db() -> None:
    os.makedirs(DATABASE_DIR, exist_ok=True)
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT '司机',
        phone TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    _ensure_user_columns(cur)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS trip_records(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        plate TEXT,
        date TEXT,

        start_mileage INTEGER,
        end_mileage INTEGER,
        distance INTEGER,

        start_photo TEXT,
        end_photo TEXT,

        start_time TEXT,
        end_time TEXT,

        start_lat REAL,
        start_lng REAL,
        end_lat REAL,
        end_lng REAL,

        start_address TEXT,
        end_address TEXT,

        start_ocr_text TEXT,
        end_ocr_text TEXT,
        start_ocr_conf REAL,
        end_ocr_conf REAL,

        warning TEXT,
        status TEXT NOT NULL DEFAULT '未回场'
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sms_codes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT NOT NULL,
        purpose TEXT NOT NULL,
        code_hash TEXT NOT NULL,
        expires_at INTEGER NOT NULL,
        used_at INTEGER,
        attempts INTEGER NOT NULL DEFAULT 0,
        send_ip TEXT,
        created_at INTEGER NOT NULL
    )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sms_codes_phone_purpose ON sms_codes(phone, purpose, created_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_trip_records_username_status ON trip_records(username, status, id DESC)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_trip_records_status_time ON trip_records(status, COALESCE(end_time, start_time, date))")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_trip_records_username_time ON trip_records(username, COALESCE(end_time, start_time, date))")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")

    for username, password, role in DEFAULT_USERS:
        cur.execute("""
        INSERT OR IGNORE INTO users(username, password_hash, role)
        VALUES(?,?,?)
        """, (username, _hash_password(password), role))

    # 确保内置管理员账号始终拥有管理员权限；不覆盖已有密码和手机号。
    for username, _password, role in DEFAULT_USERS:
        if role == "管理员":
            cur.execute("UPDATE users SET role=? WHERE username=?", (role, username))

    conn.commit()
    conn.close()



def _admin_role_where_sql() -> str:
    return "role IN ('管理员', '超级管理员', 'admin', 'administrator')"


def admin_exists() -> bool:
    """系统里是否已经存在管理员。"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT 1 FROM users WHERE {_admin_role_where_sql()} LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return row is not None


def legacy_default_admin_exists() -> bool:
    """
    兼容旧版本：如果数据库里还存在 admin/admin123 管理员，视为未完成安全初始化，
    启动后会强制进入管理员设置页面，避免继续使用默认密码。
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT 1 FROM users
        WHERE username=? AND password_hash=? AND {_admin_role_where_sql()}
        LIMIT 1
        """,
        (LEGACY_DEFAULT_ADMIN_USERNAME, _hash_password(LEGACY_DEFAULT_ADMIN_PASSWORD)),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def initial_admin_setup_required() -> bool:
    """首次运行无管理员，或旧版默认管理员仍存在时，需要管理员自行设置密码。"""
    return (not admin_exists()) or legacy_default_admin_exists()


def setup_initial_admin(
    username: str,
    password: str,
    phone: str,
    gender: str = "",
    unit: str = "",
    department: str = "",
    team: str = "",
    unit_other: str = "",
    department_other: str = "",
    team_other: str = "",
) -> int:
    """
    首次初始化管理员。
    - 新系统：创建第一个管理员；
    - 旧系统：如果存在 admin/admin123，则改成用户自定义账号/密码；
    - 如果无管理员但已存在同名普通用户，则把该用户升级为管理员并重设密码；
    - 同步保存管理员的性别、单位、部门、班组，保证用户资料完整。
    """
    username = (username or "").strip()
    phone = (phone or "").strip()
    gender = (gender or "").strip()
    unit = (unit or "").strip()
    department = (department or "").strip()
    team = (team or "").strip()
    unit_other = (unit_other or "").strip()
    department_other = (department_other or "").strip()
    team_other = (team_other or "").strip()

    if not username:
        raise ValueError("请输入管理员用户名")
    if not password:
        raise ValueError("请输入管理员密码")

    conn = get_conn()
    cur = conn.cursor()
    _ensure_user_columns(cur)
    default_hash = _hash_password(LEGACY_DEFAULT_ADMIN_PASSWORD)

    cur.execute(
        f"""
        SELECT id FROM users
        WHERE username=? AND password_hash=? AND {_admin_role_where_sql()}
        LIMIT 1
        """,
        (LEGACY_DEFAULT_ADMIN_USERNAME, default_hash),
    )
    legacy_row = cur.fetchone()

    cur.execute("SELECT id FROM users WHERE username=? LIMIT 1", (username,))
    same_username_row = cur.fetchone()

    if phone:
        cur.execute("SELECT id FROM users WHERE phone=? LIMIT 1", (phone,))
        same_phone_row = cur.fetchone()
    else:
        same_phone_row = None

    profile_values = (gender, unit, department, team, unit_other, department_other, team_other)

    if legacy_row is not None:
        target_id = int(legacy_row[0])
        if same_username_row is not None and int(same_username_row[0]) != target_id:
            conn.close()
            raise ValueError("该用户名已存在，请换一个管理员用户名")
        if same_phone_row is not None and int(same_phone_row[0]) != target_id:
            conn.close()
            raise ValueError("该手机号已被其他用户绑定")
        cur.execute(
            """
            UPDATE users
            SET username=?, password_hash=?, phone=?, role='管理员',
                gender=?, unit=?, department=?, team=?,
                unit_other=?, department_other=?, team_other=?
            WHERE id=?
            """,
            (username, _hash_password(password), phone, *profile_values, target_id),
        )
    elif same_username_row is not None:
        target_id = int(same_username_row[0])
        if same_phone_row is not None and int(same_phone_row[0]) != target_id:
            conn.close()
            raise ValueError("该手机号已被其他用户绑定")
        cur.execute(
            """
            UPDATE users
            SET password_hash=?, phone=?, role='管理员',
                gender=?, unit=?, department=?, team=?,
                unit_other=?, department_other=?, team_other=?
            WHERE id=?
            """,
            (_hash_password(password), phone, *profile_values, target_id),
        )
    else:
        if same_phone_row is not None:
            conn.close()
            raise ValueError("该手机号已被注册")
        cur.execute(
            """
            INSERT INTO users(
                username, password_hash, role, phone,
                gender, unit, department, team,
                unit_other, department_other, team_other
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (username, _hash_password(password), "管理员", phone, *profile_values),
        )
        target_id = int(cur.lastrowid)

    conn.commit()
    conn.close()
    return int(target_id)


def email_exists(email: str) -> bool:
    email = (email or "").strip().lower()
    if not email:
        return False
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE email=? LIMIT 1", (email,))
    row = cur.fetchone()
    conn.close()
    return row is not None


def set_user_email(username: str, email: str) -> None:
    username = (username or "").strip()
    email = (email or "").strip().lower()
    if not username:
        raise ValueError("用户名不能为空")
    if not email:
        raise ValueError("邮箱不能为空")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email=? AND username<>? LIMIT 1", (email, username))
    if cur.fetchone():
        conn.close()
        raise ValueError("该邮箱已被注册")
    cur.execute("UPDATE users SET email=? WHERE username=?", (email, username))
    conn.commit()
    conn.close()


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    email = (email or "").strip().lower()
    if not email:
        return None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username, role, phone, email, email, gender, unit, department, team, unit_other, department_other, team_other, created_at "
        "FROM users WHERE email=? LIMIT 1",
        (email,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def reset_password_by_email(username: str, email: str, new_password: str) -> bool:
    username = (username or "").strip()
    email = (email or "").strip().lower()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET password_hash=? WHERE username=? AND email=?",
        (_hash_password(new_password), username, email),
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def get_user_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    phone = (phone or "").strip()
    if not phone:
        return None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, username, role, phone, email, email, email, gender, unit, department, team, unit_other, department_other, team_other, created_at FROM users WHERE phone=? LIMIT 1", (phone,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def _hash_sms_code(phone: str, purpose: str, code: str) -> str:
    payload = f"{phone}|{purpose}|{code}".encode("utf-8")
    key = str(SECRET_KEY).encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def can_send_sms_code(phone: str, purpose: str) -> bool:
    """同一手机号同一用途在冷却期内不能重复发送。"""
    phone = (phone or "").strip()
    purpose = (purpose or "").strip()
    now = int(time.time())
    cutoff = now - int(SMS_SEND_COOLDOWN_SECONDS)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1 FROM sms_codes
        WHERE phone=? AND purpose=? AND created_at>=?
        LIMIT 1
        """,
        (phone, purpose, cutoff),
    )
    row = cur.fetchone()
    conn.close()
    return row is None


def create_sms_code(phone: str, purpose: str, code: str, send_ip: str = "") -> int:
    phone = (phone or "").strip()
    purpose = (purpose or "").strip()
    if not phone:
        raise ValueError("手机号不能为空")
    if not purpose:
        raise ValueError("验证码用途不能为空")
    if not can_send_sms_code(phone, purpose):
        raise ValueError(f"验证码发送太频繁，请 {SMS_SEND_COOLDOWN_SECONDS} 秒后再试")

    now = int(time.time())
    expires_at = now + int(SMS_CODE_TTL_SECONDS)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO sms_codes(phone, purpose, code_hash, expires_at, send_ip, created_at)
        VALUES(?,?,?,?,?,?)
        """,
        (phone, purpose, _hash_sms_code(phone, purpose, code), expires_at, send_ip, now),
    )
    code_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return code_id


def verify_sms_code(phone: str, purpose: str, code: str) -> bool:
    phone = (phone or "").strip()
    purpose = (purpose or "").strip()
    code = (code or "").strip()
    if not phone or not purpose or not code:
        return False

    now = int(time.time())
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, code_hash, expires_at, attempts, used_at
        FROM sms_codes
        WHERE phone=? AND purpose=?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (phone, purpose),
    )
    row = cur.fetchone()
    if row is None:
        conn.close()
        return False

    code_id = int(row["id"])
    attempts = int(row["attempts"] or 0)
    used_at = row["used_at"]
    expires_at = int(row["expires_at"] or 0)

    if used_at is not None or now > expires_at or attempts >= int(SMS_MAX_ATTEMPTS):
        conn.close()
        return False

    cur.execute("UPDATE sms_codes SET attempts=attempts+1 WHERE id=?", (code_id,))
    expected_hash = str(row["code_hash"])
    actual_hash = _hash_sms_code(phone, purpose, code)
    ok = secrets.compare_digest(expected_hash, actual_hash)
    if ok:
        cur.execute("UPDATE sms_codes SET used_at=? WHERE id=?", (now, code_id))
    conn.commit()
    conn.close()
    return bool(ok)


def verify_user(identifier: str, password: str) -> Optional[Dict[str, Any]]:
    """支持用户名或手机号登录。"""
    identifier = (identifier or "").strip()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT username, role, phone
        FROM users
        WHERE (username=? OR phone=?) AND password_hash=?
        """,
        (identifier, identifier, _hash_password(password)),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def username_exists(username: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE username=? LIMIT 1", ((username or "").strip(),))
    row = cur.fetchone()
    conn.close()
    return row is not None


def phone_exists(phone: str) -> bool:
    phone = (phone or "").strip()
    if not phone:
        return False
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE phone=? LIMIT 1", (phone,))
    row = cur.fetchone()
    conn.close()
    return row is not None


def create_user(
    username: str,
    password: str,
    phone: str,
    role: str = "司机",
    gender: str = "",
    unit: str = "",
    department: str = "",
    team: str = "",
    unit_other: str = "",
    department_other: str = "",
    team_other: str = "",
) -> int:
    username = (username or "").strip()
    phone = (phone or "").strip()
    if username_exists(username):
        raise ValueError("用户名已存在")
    if phone and phone_exists(phone):
        raise ValueError("手机号已被注册")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users(
            username, password_hash, role, phone,
            gender, unit, department, team,
            unit_other, department_other, team_other
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            username,
            _hash_password(password),
            role,
            phone,
            (gender or "").strip(),
            (unit or "").strip(),
            (department or "").strip(),
            (team or "").strip(),
            (unit_other or "").strip(),
            (department_other or "").strip(),
            (team_other or "").strip(),
        ),
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()
    return int(user_id)

def reset_password_by_phone(username: str, phone: str, new_password: str) -> bool:
    """
    内网/单机版找回密码：用“用户名 + 注册手机号”核验后重置密码。
    正式公网部署应接入短信验证码或管理员审核。
    """
    username = (username or "").strip()
    phone = (phone or "").strip()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE users
        SET password_hash=?
        WHERE username=? AND phone=?
        """,
        (_hash_password(new_password), username, phone),
    )
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed




def get_user(username: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, username, role, phone, email, email, email, gender, unit, department, team, unit_other, department_other, team_other, created_at FROM users WHERE username=?", ((username or "").strip(),))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_users() -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, username, role, phone, email, email, email, gender, unit, department, team, unit_other, department_other, team_other, created_at FROM users ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_user_role(username: str, role: str) -> bool:
    username = (username or "").strip()
    role = (role or "").strip()
    if role not in ("管理员", "司机"):
        raise ValueError("角色只能设置为管理员或司机")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET role=? WHERE username=?", (role, username))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed


def verify_user_password(username: str, password: str) -> bool:
    username = (username or "").strip()
    if not username or password is None:
        return False
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM users WHERE username=? AND password_hash=? LIMIT 1",
        (username, _hash_password(password)),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username, role, phone, email, email, email, gender, unit, department, team, unit_other, department_other, team_other, created_at FROM users WHERE id=?",
        (int(user_id),),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def user_has_running_trip(username: str) -> bool:
    username = (username or "").strip()
    if not username:
        return False
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM trip_records WHERE username=? AND status='未回场' LIMIT 1",
        (username,),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None

def delete_driver_user(user_id: int) -> bool:
    target = get_user_by_id(int(user_id))
    if not target:
        return False
    if target.get("role") != "司机":
        raise ValueError("只能删除司机账号")
    if user_has_running_trip(target.get("username", "")):
        raise ValueError("该司机存在未回场行程，请先完成回场登记后再删除")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id=? AND role='司机'", (int(user_id),))
    changed = cur.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def create_start_trip(data: Dict[str, Any]) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO trip_records(
        username, plate, date,
        start_mileage, start_photo, start_time,
        start_lat, start_lng, start_address,
        start_ocr_text, start_ocr_conf,
        warning, status
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data["username"], data.get("plate"), data.get("date"),
        data.get("start_mileage"), data.get("start_photo"), data.get("start_time"),
        data.get("start_lat"), data.get("start_lng"), data.get("start_address"),
        data.get("start_ocr_text"), data.get("start_ocr_conf"),
        data.get("warning"), "未回场",
    ))
    trip_id = cur.lastrowid
    conn.commit()
    conn.close()
    return int(trip_id)


def get_running_trip(username: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT * FROM trip_records
    WHERE username=? AND status='未回场'
    ORDER BY id DESC
    LIMIT 1
    """, (username,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_trip_by_id(trip_id: int, username: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    if username:
        cur.execute("SELECT * FROM trip_records WHERE id=? AND username=?", (trip_id, username))
    else:
        cur.execute("SELECT * FROM trip_records WHERE id=?", (trip_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def finish_trip(data: Dict[str, Any]) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    UPDATE trip_records
    SET
        end_mileage=?,
        end_photo=?,
        end_time=?,
        end_lat=?,
        end_lng=?,
        end_address=?,
        distance=?,
        end_ocr_text=?,
        end_ocr_conf=?,
        warning=?,
        status='已完成'
    WHERE id=?
    """, (
        data.get("end_mileage"),
        data.get("end_photo"),
        data.get("end_time"),
        data.get("end_lat"),
        data.get("end_lng"),
        data.get("end_address"),
        data.get("distance"),
        data.get("end_ocr_text"),
        data.get("end_ocr_conf"),
        data.get("warning"),
        data.get("trip_id"),
    ))
    conn.commit()
    conn.close()


def _record_select_sql(where_clause: str = "") -> str:
    return f"""
        SELECT
            r.*,
            u.gender AS gender,
            COALESCE(NULLIF(u.unit_other, ''), u.unit, '') AS unit,
            COALESCE(NULLIF(u.department_other, ''), u.department, '') AS department,
            COALESCE(NULLIF(u.team_other, ''), u.team, '') AS team
        FROM trip_records r
        LEFT JOIN users u ON u.username = r.username
        {where_clause}
        ORDER BY r.id DESC
    """


def get_user_records(username: str) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(_record_select_sql("WHERE r.username=?"), (username,))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_all_records() -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(_record_select_sql())
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]

