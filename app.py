import os
import re
import time
from functools import wraps

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from config import (
    APP_DEBUG,
    APP_HOST,
    APP_PORT,
    SECRET_KEY,
    SMS_CODE_TTL_SECONDS,
    UPLOAD_DIR,
    EXPORT_DIR,
    DATA_RETENTION_MONTHS,
    DATA_CLEANUP_AUTO_ENABLED,
    DATA_CLEANUP_CHECK_INTERVAL_SECONDS,
    DATA_CLEANUP_BACKUP_BEFORE_DELETE,
    DATA_CLEANUP_DELETE_PHOTOS,
    EMAIL_CODE_TTL_SECONDS,
)

from dao.record_dao import (
    create_user,
    delete_driver_user,
    get_user_by_id,
    verify_user_password,
    get_all_records,
    get_all_users,
    get_user,
    get_user_by_phone,
    initial_admin_setup_required,
    get_running_trip,
    get_user_records,
    init_db,
    reset_password_by_phone,
    setup_initial_admin,
    create_sms_code,
    verify_sms_code,
    update_user_role,
    verify_user,
    get_user_by_email,
    reset_password_by_email,
    create_email_code,
    verify_email_code,
    set_user_email,
)

from service.trip_service import (
    finish_running_trip,
    preview_vehicle_ocr,
    start_trip,
)

from service.maintenance_service import (
    cleanup_export_files,
    cleanup_old_data,
    cleanup_orphan_upload_photos,
    get_storage_stats,
)

from utils.export_utils import export_excel, export_images_zip
from utils.file_utils import save_upload_optional
from utils.sms_utils import (
    SMS_PURPOSE_LOGIN,
    SMS_PURPOSE_RESET,
    generate_sms_code,
    send_sms_code,
)


PHONE_RE = re.compile(r"^1\d{10}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fa5]{2,30}$")

ADMIN_ROLE_NAMES = {"管理员", "超级管理员", "admin", "administrator"}

GENDER_CHOICES = {"男", "女"}
UNIT_CHOICES = {"遵义供电局", "其他"}
DEPARTMENT_CHOICES = {"变电管理一所", "变电管理二所", "其他"}
TEAM_CHOICES = {
    "继保班",
    "自动化班",
    "检修一班",
    "检修二班",
    "试验一班",
    "试验二班",
    "电源班",
    "智能作业班",
    "其他",
}

_LAST_AUTO_CLEANUP_CHECK = 0.0


def _validate_register_form(
    username: str,
    phone: str,
    password: str,
    password2: str,
    gender: str = "",
    unit: str = "",
    department: str = "",
    team: str = "",
    unit_other: str = "",
    department_other: str = "",
    team_other: str = "",
) -> None:
    if not USERNAME_RE.match(username or ""):
        raise ValueError("用户名需为2-30位中文、字母、数字或下划线")
    if not PHONE_RE.match(phone or ""):
        raise ValueError("请输入11位手机号")
    if len(password or "") < 6:
        raise ValueError("密码至少6位")
    if password != password2:
        raise ValueError("两次输入的密码不一致")

    if gender not in GENDER_CHOICES:
        raise ValueError("请选择性别")
    if unit not in UNIT_CHOICES:
        raise ValueError("请选择单位")
    if department not in DEPARTMENT_CHOICES:
        raise ValueError("请选择部门")
    if team not in TEAM_CHOICES:
        raise ValueError("请选择班组")

    if unit == "其他" and not (unit_other or "").strip():
        raise ValueError("请输入单位")
    if department == "其他" and not (department_other or "").strip():
        raise ValueError("请输入部门")
    if team == "其他" and not (team_other or "").strip():
        raise ValueError("请输入班组")


def _validate_admin_setup_form(
    username: str,
    phone: str,
    password: str,
    password2: str,
    gender: str = "",
    unit: str = "",
    department: str = "",
    team: str = "",
    unit_other: str = "",
    department_other: str = "",
    team_other: str = "",
) -> None:
    if not USERNAME_RE.match(username or ""):
        raise ValueError("管理员用户名需为2-30位中文、字母、数字或下划线")
    if not PHONE_RE.match(phone or ""):
        raise ValueError("请输入管理员11位手机号，后续可用于找回密码")
    if len(password or "") < 8:
        raise ValueError("管理员密码至少8位")
    if password != password2:
        raise ValueError("两次输入的管理员密码不一致")

    weak_passwords = {"admin123", "123456", "12345678", "password", "qwerty123"}
    if password.lower() in weak_passwords:
        raise ValueError("管理员密码不能使用默认密码或过弱密码")

    if gender not in GENDER_CHOICES:
        raise ValueError("请选择管理员性别")
    if unit not in UNIT_CHOICES:
        raise ValueError("请选择管理员单位")
    if department not in DEPARTMENT_CHOICES:
        raise ValueError("请选择管理员部门")
    if team not in TEAM_CHOICES:
        raise ValueError("请选择管理员班组")

    if unit == "其他" and not (unit_other or "").strip():
        raise ValueError("请输入管理员单位")
    if department == "其他" and not (department_other or "").strip():
        raise ValueError("请输入管理员部门")
    if team == "其他" and not (team_other or "").strip():
        raise ValueError("请输入管理员班组")


def create_app():
    app = Flask(__name__)
    app.secret_key = SECRET_KEY
    try:
        from config import MAX_CONTENT_LENGTH_MB
        app.config["MAX_CONTENT_LENGTH"] = int(MAX_CONTENT_LENGTH_MB) * 1024 * 1024
    except Exception:
        app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if os.environ.get("SESSION_COOKIE_SECURE", "0") == "1":
        app.config["SESSION_COOKIE_SECURE"] = True

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(EXPORT_DIR, exist_ok=True)

    init_db()

    def login_required(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if not session.get("username"):
                return redirect(url_for("login"))
            return view_func(*args, **kwargs)

        return wrapper

    def is_admin() -> bool:
        return str(session.get("role", "")).strip() in ADMIN_ROLE_NAMES

    def admin_required(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if not session.get("username"):
                return redirect(url_for("login"))
            if not is_admin():
                flash("只有管理员可以访问该功能", "danger")
                return redirect(url_for("dashboard"))
            return view_func(*args, **kwargs)

        return wrapper

    def _remote_ip() -> str:
        forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        return forwarded or request.remote_addr or ""

    def _send_and_store_sms_code(phone: str, purpose: str) -> None:
        if not PHONE_RE.match(phone or ""):
            raise ValueError("请输入11位手机号")

        code = generate_sms_code()

        # 先落库做频率限制，再调用短信网关。短信网关失败时验证码不会被页面使用。
        create_sms_code(phone=phone, purpose=purpose, code=code, send_ip=_remote_ip())
        send_sms_code(phone=phone, code=code, purpose=purpose)

    def _send_and_store_email_code(email: str, purpose: str) -> None:
        email = (email or "").strip().lower()
        if not EMAIL_RE.match(email or ""):
            raise ValueError("请输入有效邮箱地址")
        code = generate_email_code()
        create_email_code(email=email, purpose=purpose, code=code, send_ip=_remote_ip())
        send_email_code(to_email=email, code=code, purpose=purpose)

    def _maybe_auto_cleanup() -> None:
        """按配置进行轻量自动清理；默认关闭。"""
        global _LAST_AUTO_CLEANUP_CHECK

        if not DATA_CLEANUP_AUTO_ENABLED or int(DATA_RETENTION_MONTHS or 0) <= 0:
            return

        now = time.time()
        if now - _LAST_AUTO_CLEANUP_CHECK < int(DATA_CLEANUP_CHECK_INTERVAL_SECONDS):
            return

        _LAST_AUTO_CLEANUP_CHECK = now

        try:
            cleanup_old_data(
                retention_months=int(DATA_RETENTION_MONTHS),
                backup_before_delete=bool(DATA_CLEANUP_BACKUP_BEFORE_DELETE),
                delete_photos=bool(DATA_CLEANUP_DELETE_PHOTOS),
            )
        except Exception:
            # 自动清理失败不能影响司机登记。管理员可到“数据维护”页面手动查看和清理。
            pass

    @app.errorhandler(413)
    def request_entity_too_large(_error):
        flash("上传图片过大，请压缩后再上传", "danger")
        return redirect(request.referrer or url_for("dashboard"))

    @app.context_processor
    def inject_permissions():
        return {"is_admin": is_admin()}

    @app.before_request
    def force_initial_admin_setup():
        """首次启动或发现旧版默认 admin/admin123 时，强制先设置管理员。"""
        endpoint = request.endpoint or ""

        if endpoint in {"setup_admin", "static", "env"}:
            return None

        if initial_admin_setup_required():
            session.clear()
            return redirect(url_for("setup_admin"))

        _maybe_auto_cleanup()
        return None

    @app.route("/setup-admin", methods=["GET", "POST"])
    def setup_admin():
        if not initial_admin_setup_required():
            return redirect(url_for("login"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            phone = request.form.get("phone", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "").strip()
            password2 = request.form.get("password2", "").strip()
            gender = request.form.get("gender", "").strip()
            unit = request.form.get("unit", "").strip()
            department = request.form.get("department", "").strip()
            team = request.form.get("team", "").strip()
            unit_other = request.form.get("unit_other", "").strip()
            department_other = request.form.get("department_other", "").strip()
            team_other = request.form.get("team_other", "").strip()

            try:
                _validate_admin_setup_form(
                    username,
                    phone,
                    password,
                    password2,
                    gender,
                    unit,
                    department,
                    team,
                    unit_other,
                    department_other,
                    team_other,
                )
                if email and not EMAIL_RE.match(email):
                    raise ValueError("请输入有效邮箱地址")
                setup_initial_admin(
                    username=username,
                    password=password,
                    phone=phone,
                    gender=gender,
                    unit=unit,
                    department=department,
                    team=team,
                    unit_other=unit_other,
                    department_other=department_other,
                    team_other=team_other,
                )
                session.clear()
                flash("管理员账号已设置，请使用你刚设置的账号和密码登录", "success")
                return redirect(url_for("login"))
            except Exception as exc:
                flash(str(exc), "danger")

        return render_template("setup_admin.html")

    @app.route("/")
    def root():
        if session.get("username"):
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            identifier = request.form.get("identifier", "").strip()

            # 兼容旧模板字段名
            if not identifier:
                identifier = request.form.get("username", "").strip()

            password = request.form.get("password", "").strip()
            user = verify_user(identifier, password)

            if user:
                session["username"] = user["username"]
                session["role"] = user["role"]
                flash("登录成功", "success")
                return redirect(url_for("dashboard"))

            flash("用户名/手机号或密码错误", "danger")

        return render_template("login.html")

    @app.route("/sms-login", methods=["GET", "POST"])
    def sms_login():
        if request.method == "POST":
            action = request.form.get("action", "login").strip()
            phone = request.form.get("phone", "").strip()
            code = request.form.get("code", "").strip()

            try:
                if not PHONE_RE.match(phone or ""):
                    raise ValueError("请输入11位手机号")

                if action == "send_code":
                    # 为了减少手机号枚举，页面统一提示。未注册手机号不会发送真实验证码。
                    if get_user_by_phone(phone):
                        _send_and_store_sms_code(phone, SMS_PURPOSE_LOGIN)

                    flash(
                        f"如果手机号已注册，验证码已发送，有效期 {SMS_CODE_TTL_SECONDS // 60} 分钟",
                        "success",
                    )
                    return redirect(url_for("sms_login"))

                if not code:
                    raise ValueError("请输入短信验证码")

                user = get_user_by_phone(phone)
                if not user:
                    raise ValueError("手机号未注册")

                if not verify_sms_code(phone, SMS_PURPOSE_LOGIN, code):
                    raise ValueError("短信验证码错误或已过期")

                session["username"] = user["username"]
                session["role"] = user["role"]

                flash("短信验证码登录成功", "success")
                return redirect(url_for("dashboard"))
            except Exception as exc:
                flash(str(exc), "danger")

        return render_template("sms_login.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            phone = request.form.get("phone", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "").strip()
            password2 = request.form.get("password2", "").strip()
            gender = request.form.get("gender", "").strip()
            unit = request.form.get("unit", "").strip()
            department = request.form.get("department", "").strip()
            team = request.form.get("team", "").strip()
            unit_other = request.form.get("unit_other", "").strip()
            department_other = request.form.get("department_other", "").strip()
            team_other = request.form.get("team_other", "").strip()

            try:
                _validate_register_form(
                    username,
                    phone,
                    password,
                    password2,
                    gender,
                    unit,
                    department,
                    team,
                    unit_other,
                    department_other,
                    team_other,
                )
                if email and not EMAIL_RE.match(email):
                    raise ValueError("请输入有效邮箱地址")
                create_user(
                    username=username,
                    password=password,
                    phone=phone,
                    role="司机",
                    gender=gender,
                    unit=unit,
                    department=department,
                    team=team,
                    unit_other=unit_other,
                    department_other=department_other,
                    team_other=team_other,
                )
                flash("注册成功，请登录", "success")
                return redirect(url_for("login"))
            except Exception as exc:
                flash(str(exc), "danger")

        return render_template("register.html")

    @app.route("/forgot-password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST":
            action = request.form.get("action", "reset_email").strip()
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip().lower()
            phone = request.form.get("phone", "").strip()
            email_code = request.form.get("email_code", "").strip()
            sms_code = request.form.get("code", "").strip()
            password = request.form.get("password", "").strip()
            password2 = request.form.get("password2", "").strip()
            try:
                if not username:
                    raise ValueError("请输入用户名")

                if action in {"send_email_code", "reset_email"}:
                    if not EMAIL_RE.match(email or ""):
                        raise ValueError("请输入注册时绑定的邮箱")
                    user = get_user_by_email(email)
                    if not user or user.get("username") != username:
                        raise ValueError("用户名和邮箱不匹配，无法发送验证码")
                    if action == "send_email_code":
                        _send_and_store_email_code(email, EMAIL_PURPOSE_RESET)
                        flash(f"邮箱验证码已发送，有效期 {EMAIL_CODE_TTL_SECONDS // 60} 分钟", "success")
                        return redirect(url_for("forgot_password"))

                    if not email_code:
                        raise ValueError("请输入邮箱验证码")
                    if len(password or "") < 6:
                        raise ValueError("新密码至少6位")
                    if password != password2:
                        raise ValueError("两次输入的新密码不一致")
                    if not verify_email_code(email, EMAIL_PURPOSE_RESET, email_code):
                        raise ValueError("邮箱验证码错误或已过期")
                    if not reset_password_by_email(username, email, password):
                        raise ValueError("用户名和邮箱不匹配，无法重置密码")
                    flash("密码已通过邮箱验证码重置，请使用新密码登录", "success")
                    return redirect(url_for("login"))

                # 保留短信找回作为备用。
                if not PHONE_RE.match(phone or ""):
                    raise ValueError("请输入注册时绑定的11位手机号")
                if action == "send_sms_code":
                    user = get_user_by_phone(phone)
                    if not user or user.get("username") != username:
                        raise ValueError("用户名和手机号不匹配，无法发送验证码")
                    _send_and_store_sms_code(phone, SMS_PURPOSE_RESET)
                    flash(f"短信验证码已发送，有效期 {SMS_CODE_TTL_SECONDS // 60} 分钟", "success")
                    return redirect(url_for("forgot_password"))

                if not sms_code:
                    raise ValueError("请输入短信验证码")
                if len(password or "") < 6:
                    raise ValueError("新密码至少6位")
                if password != password2:
                    raise ValueError("两次输入的新密码不一致")
                if not verify_sms_code(phone, SMS_PURPOSE_RESET, sms_code):
                    raise ValueError("短信验证码错误或已过期")
                if not reset_password_by_phone(username, phone, password):
                    raise ValueError("用户名和手机号不匹配，无法重置密码")
                flash("密码已通过短信验证码重置，请使用新密码登录", "success")
                return redirect(url_for("login"))
            except Exception as exc:
                flash(str(exc), "danger")
        return render_template("forgot_password.html")

    @app.route("/logout")
    def logout():
        session.clear()
        flash("已退出登录", "info")
        return redirect(url_for("login"))

    @app.route("/profile")
    @login_required
    def profile():
        user = get_user(session["username"])
        if not user:
            flash("用户不存在，请重新登录", "danger")
            return redirect(url_for("logout"))

        return render_template("profile.html", user=user)

    @app.route("/dashboard")
    @login_required
    def dashboard():
        username = session["username"]
        running_trip = get_running_trip(username)
        records = (get_all_records() if is_admin() else get_user_records(username))[:5]
        return render_template("dashboard.html", running_trip=running_trip, records=records)

    @app.route("/start", methods=["GET", "POST"])
    @login_required
    def start():
        if request.method == "POST":
            action = request.form.get("action", "submit").strip()

            try:
                if action == "confirm_ocr":
                    pending = session.get("pending_start_ocr")
                    if not pending:
                        raise ValueError("自动识别确认信息已过期，请重新上传照片或手动填写")

                    try:
                        result = start_trip(
                            username=session["username"],
                            image_path=pending.get("image_path"),
                            lat=pending.get("lat"),
                            lng=pending.get("lng"),
                            plate_override=request.form.get("plate_override"),
                            mileage_override=request.form.get("mileage_override"),
                            ocr_context=pending.get("ocr"),
                        )
                    except Exception as confirm_exc:
                        flash(str(confirm_exc), "danger")
                        return render_template(
                            "start_confirm.html",
                            preview=pending.get("ocr") or {},
                        )

                    session.pop("pending_start_ocr", None)
                    return render_template("start_success.html", trip=result)

                plate_override = request.form.get("plate_override", "").strip()
                mileage_override = request.form.get("mileage_override", "").strip()
                image_path = save_upload_optional(request.files.get("image"), "start")

                # 手动同时填写车牌和里程时，手动值优先，直接保存，不跑 OCR。
                if plate_override and mileage_override:
                    session.pop("pending_start_ocr", None)
                    result = start_trip(
                        username=session["username"],
                        image_path=image_path,
                        lat=request.form.get("lat"),
                        lng=request.form.get("lng"),
                        plate_override=plate_override,
                        mileage_override=mileage_override,
                    )
                    return render_template("start_success.html", trip=result)

                # 缺少信息但有照片：先识别并进入确认页，不直接入库。
                if image_path:
                    preview = preview_vehicle_ocr(
                        image_path,
                        plate_override=plate_override,
                        mileage_override=mileage_override,
                    )

                    # Flask 默认 session 存在浏览器 Cookie 中，OCR 原文过长会导致 Cookie 过大，保留摘要即可。
                    preview_for_session = dict(preview)
                    preview_for_session["raw_text"] = str(
                        preview_for_session.get("raw_text") or ""
                    )[:1500]

                    session["pending_start_ocr"] = {
                        "image_path": image_path,
                        "lat": request.form.get("lat"),
                        "lng": request.form.get("lng"),
                        "ocr": preview_for_session,
                    }

                    return render_template("start_confirm.html", preview=preview)

                # 无照片且信息不完整：提示手动补齐。
                raise ValueError("请手动填写车牌号和出发里程；或上传照片自动识别后再确认")
            except Exception as exc:
                flash(str(exc), "danger")

        return render_template("start.html")

    @app.route("/finish", methods=["GET", "POST"])
    @login_required
    def finish():
        username = session["username"]
        running_trip = get_running_trip(username)

        if not running_trip:
            flash("当前没有未回场行程，请先出车登记", "warning")
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            action = request.form.get("action", "submit").strip()

            try:
                if action == "confirm_ocr":
                    pending = session.get("pending_finish_ocr")
                    if not pending:
                        raise ValueError("自动识别确认信息已过期，请重新上传照片或手动填写")

                    try:
                        result = finish_running_trip(
                            username=username,
                            trip_id=int(pending.get("trip_id")),
                            image_path=pending.get("image_path"),
                            lat=pending.get("lat"),
                            lng=pending.get("lng"),
                            mileage_override=request.form.get("mileage_override"),
                            ocr_context=pending.get("ocr"),
                        )
                    except Exception as confirm_exc:
                        flash(str(confirm_exc), "danger")
                        return render_template(
                            "finish_confirm.html",
                            trip=running_trip,
                            preview=pending.get("ocr") or {},
                        )

                    session.pop("pending_finish_ocr", None)
                    return render_template("finish_success.html", trip=result)

                mileage_override = request.form.get("mileage_override", "").strip()
                image_path = save_upload_optional(request.files.get("image"), "finish")

                # 手动填写回场里程时，手动值优先，直接保存，不跑 OCR。
                if mileage_override:
                    session.pop("pending_finish_ocr", None)
                    result = finish_running_trip(
                        username=username,
                        trip_id=int(request.form.get("trip_id")),
                        image_path=image_path,
                        lat=request.form.get("lat"),
                        lng=request.form.get("lng"),
                        mileage_override=mileage_override,
                    )
                    return render_template("finish_success.html", trip=result)

                # 未填里程但有照片：先识别并进入确认页，不直接入库。
                if image_path:
                    preview = preview_vehicle_ocr(image_path)
                    preview_for_session = dict(preview)
                    preview_for_session["raw_text"] = str(
                        preview_for_session.get("raw_text") or ""
                    )[:1500]

                    session["pending_finish_ocr"] = {
                        "trip_id": int(request.form.get("trip_id")),
                        "image_path": image_path,
                        "lat": request.form.get("lat"),
                        "lng": request.form.get("lng"),
                        "ocr": preview_for_session,
                    }

                    return render_template(
                        "finish_confirm.html",
                        trip=running_trip,
                        preview=preview,
                    )

                raise ValueError("请手动填写回场里程；或上传照片自动识别后再确认")
            except Exception as exc:
                flash(str(exc), "danger")

        return render_template("finish.html", trip=running_trip)

    @app.route("/records")
    @login_required
    def records():
        rows = get_all_records() if is_admin() else get_user_records(session["username"])
        return render_template("records.html", records=rows)

    @app.route("/admin/users", methods=["GET", "POST"])
    @admin_required
    def admin_users():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            role = request.form.get("role", "").strip()

            try:
                if username == session.get("username") and role != "管理员":
                    raise ValueError("不能把当前登录管理员降为司机，避免系统没有管理员")

                if not update_user_role(username, role):
                    raise ValueError("用户不存在，角色设置失败")

                flash(f"已将 {username} 设置为{role}", "success")
            except Exception as exc:
                flash(str(exc), "danger")

            return redirect(url_for("admin_users"))

        users = get_all_users()
        return render_template("admin_users.html", users=users)

    @app.route("/admin/users/delete", methods=["POST"])
    @admin_required
    def admin_delete_user():
        user_id = request.form.get("user_id", "").strip()
        admin_password = request.form.get("admin_password", "")

        try:
            if not user_id.isdigit():
                raise ValueError("请选择要删除的司机")

            if not admin_password:
                raise ValueError("请输入当前管理员密码")

            if not verify_user_password(session.get("username", ""), admin_password):
                raise ValueError("管理员密码错误，删除操作已取消")

            target = get_user_by_id(int(user_id))
            if not target:
                raise ValueError("用户不存在或已被删除")

            if target.get("username") == session.get("username"):
                raise ValueError("不能删除当前登录账号")

            if target.get("role") != "司机":
                raise ValueError("只能删除司机账号，不能删除管理员账号")

            if not delete_driver_user(int(user_id)):
                raise ValueError("删除失败：用户不存在或不是司机账号")

            flash(
                f"已删除司机账号：{target.get('username')}。历史行程记录已保留，便于后续审计。",
                "success",
            )
        except Exception as exc:
            flash(str(exc), "danger")

        return redirect(url_for("admin_users"))

    def _write_export_error(exc: Exception) -> None:
        try:
            import traceback

            debug_dir = os.path.abspath("debug_ocr")
            os.makedirs(debug_dir, exist_ok=True)

            with open(os.path.join(debug_dir, "export_error.txt"), "w", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass

    @app.route("/export")
    @login_required
    def export():
        # 管理员导出全部司机记录；普通司机只能导出自己的记录。
        try:
            export_username = None if is_admin() else session["username"]
            path = export_excel(export_username)
            return send_file(path, as_attachment=True, download_name=os.path.basename(path))
        except Exception as exc:
            _write_export_error(exc)
            flash(f"导出 Excel 失败：{exc}。详情见 debug_ocr/export_error.txt", "danger")
            return redirect(url_for("records"))

    @app.route("/export-images")
    @login_required
    def export_images():
        # 管理员导出全部司机图片；普通司机只能导出自己的图片。
        try:
            export_username = None if is_admin() else session["username"]
            path = export_images_zip(export_username)
            return send_file(path, as_attachment=True, download_name=os.path.basename(path))
        except Exception as exc:
            _write_export_error(exc)
            flash(f"导出图片失败：{exc}。详情见 debug_ocr/export_error.txt", "danger")
            return redirect(url_for("records"))

    @app.route("/admin/storage", methods=["GET"])
    @admin_required
    def admin_storage():
        stats = get_storage_stats()
        return render_template(
            "admin_storage.html",
            stats=stats,
            retention_months=DATA_RETENTION_MONTHS,
            auto_cleanup_enabled=DATA_CLEANUP_AUTO_ENABLED,
        )

    @app.route("/admin/cleanup", methods=["POST"])
    @admin_required
    def admin_cleanup():
        try:
            months = int(request.form.get("months", "0"))
            confirm = request.form.get("confirm", "").strip()
            backup = request.form.get("backup") == "1"
            delete_photos = request.form.get("delete_photos") == "1"

            if months < 0:
                raise ValueError("保留月份不能小于 0")

            if confirm != "确认清理":
                raise ValueError("请输入“确认清理”后再执行，避免误删")

            result = cleanup_old_data(
                retention_months=months,
                backup_before_delete=backup,
                delete_photos=delete_photos,
            )

            msg = (
                f"清理完成：匹配 {result['matched_records']} 条，"
                f"删除 {result['deleted_records']} 条行程记录、"
                f"{result['deleted_photos']} 张照片、"
                f"{result['deleted_sms_codes']} 条过期验证码"
            )

            if months == 0:
                msg += "；本次使用的是“保留 0 个月”，即清理当前全部行程记录"

            if result.get("archive_path"):
                msg += "；已先生成归档备份：" + os.path.basename(result["archive_path"])

            flash(msg, "success")
        except Exception as exc:
            flash(str(exc), "danger")

        return redirect(url_for("admin_storage"))

    @app.route("/admin/cleanup-orphans", methods=["POST"])
    @admin_required
    def admin_cleanup_orphans():
        try:
            confirm = request.form.get("confirm", "").strip()
            if confirm != "确认清理":
                raise ValueError("请输入“确认清理”后再执行，避免误删")

            result = cleanup_orphan_upload_photos()
            flash(
                f"孤儿照片清理完成：匹配 {result['matched_orphan_photos']} 张，"
                f"删除 {result['deleted_orphan_photos']} 张，释放 {result['deleted_orphan_photo_size']}",
                "success",
            )
        except Exception as exc:
            flash(str(exc), "danger")

        return redirect(url_for("admin_storage"))

    @app.route("/admin/cleanup-exports", methods=["POST"])
    @admin_required
    def admin_cleanup_exports():
        try:
            confirm = request.form.get("confirm", "").strip()
            if confirm != "确认清理":
                raise ValueError("请输入“确认清理”后再执行，避免误删")

            result = cleanup_export_files()
            flash(
                f"导出文件清理完成：匹配 {result['matched_export_files']} 个，"
                f"删除 {result['deleted_export_files']} 个，释放 {result['deleted_export_size']}",
                "success",
            )
        except Exception as exc:
            flash(str(exc), "danger")

        return redirect(url_for("admin_storage"))

    @app.route("/env")
    def env():
        import html
        import importlib
        import sys

        names = ["flask", "pandas", "openpyxl", "cv2", "numpy", "paddle", "paddleocr"]
        lines = [
            "CarFleetSystem Production Environment",
            "Python executable: " + sys.executable,
            "Python version: " + sys.version.replace("\n", " "),
            "",
        ]

        for name in names:
            try:
                mod = importlib.import_module(name)
                ver = getattr(mod, "__version__", "unknown")
                lines.append(f"[OK] {name}: {ver}")
            except Exception as exc:
                lines.append(f"[FAIL] {name}: {exc}")

        return "<pre>" + html.escape("\n".join(lines)) + "</pre>"

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host=APP_HOST, port=APP_PORT, debug=APP_DEBUG, use_reloader=False)
