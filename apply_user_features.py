from pathlib import Path
import re
import sys

ROOT = Path.cwd()


def read(path: str) -> str:
    p = ROOT / path
    if not p.exists():
        raise FileNotFoundError(f"找不到文件：{path}，请在 carSystem 仓库根目录运行本脚本")
    return p.read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")
    print(f"已更新 {path}")


def replace_regex(text: str, pattern: str, replacement: str, desc: str) -> str:
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"未找到需要替换的位置：{desc}")
    return new_text


def insert_before(text: str, marker: str, addition: str, desc: str) -> str:
    if addition.strip() in text:
        return text
    idx = text.find(marker)
    if idx == -1:
        raise RuntimeError(f"未找到插入位置：{desc}")
    return text[:idx] + addition + text[idx:]


def patch_app() -> None:
    text = read("app.py")

    if "get_user," not in text:
        text = text.replace("get_all_users,", "get_all_users,\n    get_user,")

    if "GENDER_CHOICES" not in text:
        text = text.replace(
            'ADMIN_ROLE_NAMES = {"管理员", "超级管理员", "admin", "administrator"}',
            'ADMIN_ROLE_NAMES = {"管理员", "超级管理员", "admin", "administrator"}\n'
            'GENDER_CHOICES = {"男", "女"}\n'
            'UNIT_CHOICES = {"遵义供电局", "其他"}\n'
            'DEPARTMENT_CHOICES = {"变电管理一所", "变电管理二所", "其他"}\n'
            'TEAM_CHOICES = {"继保班", "自动化班", "检修一班", "检修二班", "试验一班", "试验二班", "电源班", "智能作业班", "其他"}'
        )

    validate_func = '''def _validate_register_form(
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

'''
    text = replace_regex(
        text,
        r"def _validate_register_form\(.*?\n(?=def _validate_admin_setup_form)",
        validate_func,
        "app.py 注册校验函数",
    )

    register_route = '''@app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            phone = request.form.get("phone", "").strip()
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

'''
    text = replace_regex(
        text,
        r"@app\.route\(\"/register\", methods=\[\"GET\", \"POST\"\]\).*?\n(?=    @app\.route\(\"/forgot-password\")",
        register_route,
        "app.py 注册路由",
    )

    profile_route = '''    @app.route("/profile")
    @login_required
    def profile():
        user = get_user(session["username"])
        if not user:
            flash("用户不存在，请重新登录", "danger")
            return redirect(url_for("logout"))
        return render_template("profile.html", user=user)

'''
    text = insert_before(text, '    @app.route("/dashboard")', profile_route, "app.py 个人资料路由")
    write("app.py", text)


def patch_record_dao() -> None:
    text = read("dao/record_dao.py")

    # 兼容旧数据库：如果本地代码还没有用户资料字段迁移，则追加到 _ensure_user_columns 中。
    if '"gender", "unit", "department", "team", "unit_other", "department_other", "team_other"' not in text and "extended profile fields" not in text:
        marker = 'if "role" not in columns:\n        cur.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT \'司机\'")'
        if marker in text:
            text = text.replace(
                marker,
                marker + '\n    for col in ["gender", "unit", "department", "team", "unit_other", "department_other", "team_other"]:\n        if col not in columns:\n            cur.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")'
            )

    create_user_func = '''def create_user(
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

'''
    text = replace_regex(
        text,
        r"def create_user\(.*?\n(?=def reset_password_by_phone)",
        create_user_func,
        "record_dao.py create_user",
    )

    profile_select = "id, username, role, phone, gender, unit, department, team, unit_other, department_other, team_other, created_at"
    text = text.replace(
        "SELECT username, role, phone FROM users WHERE phone=? LIMIT 1",
        f"SELECT {profile_select} FROM users WHERE phone=? LIMIT 1",
    )
    text = text.replace(
        "SELECT id, username, role, phone, created_at FROM users WHERE username=?",
        f"SELECT {profile_select} FROM users WHERE username=?",
    )
    text = text.replace(
        "SELECT id, username, role, phone, created_at FROM users ORDER BY id ASC",
        f"SELECT {profile_select} FROM users ORDER BY id ASC",
    )

    record_funcs = '''def _record_select_sql(where_clause: str = "") -> str:
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
'''
    text = replace_regex(
        text,
        r"def get_user_records\(username: str\).*?def get_all_records\(\) -> List\[Dict\[str, Any\]\]:.*?return \[dict\(row\) for row in rows\]",
        record_funcs,
        "record_dao.py 行程查询函数",
    )

    write("dao/record_dao.py", text)


def patch_base() -> None:
    text = read("templates/base.html")
    old = '<span class="navbar-text me-3">{{ session.get(\'username\') }} / {{ session.get(\'role\') }}</span>'
    new = '''<a class="navbar-text me-3 text-decoration-none text-light d-inline-flex align-items-center gap-2" href="{{ url_for('profile') }}" title="查看个人信息">
          <span class="rounded-circle bg-light text-dark d-inline-flex align-items-center justify-content-center" style="width:32px;height:32px;">{{ (session.get('username') or '用')[:1] }}</span>
          <span>{{ session.get('username') }} / {{ session.get('role') }}</span>
        </a>'''
    if old in text:
        text = text.replace(old, new)
    elif "url_for('profile')" not in text:
        raise RuntimeError("未找到 base.html 里的用户信息显示位置")
    write("templates/base.html", text)


def write_profile_template() -> None:
    profile = '''{% extends 'base.html' %}
{% block content %}
<div class="row justify-content-center">
  <div class="col-md-8 col-lg-6">
    <div class="card shadow-sm">
      <div class="card-body p-4">
        <div class="d-flex align-items-center mb-4">
          <div class="rounded-circle bg-primary text-white d-flex align-items-center justify-content-center me-3" style="width:64px;height:64px;font-size:28px;">
            {{ (user.username or '用')[:1] }}
          </div>
          <div>
            <h3 class="mb-1">{{ user.username }}</h3>
            <div class="text-muted">{{ user.role or '司机' }}</div>
          </div>
        </div>

        <table class="table table-bordered align-middle mb-0">
          <tr><th style="width: 35%;">用户名</th><td>{{ user.username or '-' }}</td></tr>
          <tr><th>手机号</th><td>{{ user.phone or '-' }}</td></tr>
          <tr><th>性别</th><td>{{ user.gender or '-' }}</td></tr>
          <tr><th>单位</th><td>{{ user.unit_other if user.unit == '其他' and user.unit_other else (user.unit or '-') }}</td></tr>
          <tr><th>部门</th><td>{{ user.department_other if user.department == '其他' and user.department_other else (user.department or '-') }}</td></tr>
          <tr><th>班组</th><td>{{ user.team_other if user.team == '其他' and user.team_other else (user.team or '-') }}</td></tr>
          <tr><th>注册时间</th><td>{{ user.created_at or '-' }}</td></tr>
        </table>

        <div class="mt-4 text-end">
          <a class="btn btn-outline-secondary" href="{{ url_for('dashboard') }}">返回首页</a>
        </div>
      </div>
    </div>
  </div>
</div>
{% endblock %}
'''
    write("templates/profile.html", profile)


def write_admin_users_template() -> None:
    admin = '''{% extends 'base.html' %}
{% block content %}
<h3>用户权限管理</h3>
<p class="text-muted">只有管理员可以进入本页。管理员可查看、导出全部司机数据；司机只能查看、导出自己的数据。</p>
<a class="btn btn-outline-secondary btn-sm mb-3" href="{{ url_for('records') }}">返回记录</a>

<div class="table-responsive">
  <table class="table table-striped table-bordered align-middle">
    <thead>
      <tr>
        <th>ID</th>
        <th>用户名</th>
        <th>手机号</th>
        <th>性别</th>
        <th>单位</th>
        <th>部门</th>
        <th>班组</th>
        <th>当前角色</th>
        <th>设置权限</th>
        <th>创建时间</th>
      </tr>
    </thead>
    <tbody>
      {% for u in users %}
      <tr>
        <td>{{ u.id }}</td>
        <td>{{ u.username }}</td>
        <td>{{ u.phone or '-' }}</td>
        <td>{{ u.gender or '-' }}</td>
        <td>{{ u.unit_other if u.unit == '其他' and u.unit_other else (u.unit or '-') }}</td>
        <td>{{ u.department_other if u.department == '其他' and u.department_other else (u.department or '-') }}</td>
        <td>{{ u.team_other if u.team == '其他' and u.team_other else (u.team or '-') }}</td>
        <td>
          {% if u.role == '管理员' %}
            <span class="badge bg-danger">管理员</span>
          {% else %}
            <span class="badge bg-secondary">司机</span>
          {% endif %}
        </td>
        <td>
          <form method="post" class="d-flex gap-2">
            <input type="hidden" name="username" value="{{ u.username }}">
            <select class="form-select form-select-sm" name="role">
              <option value="司机" {% if u.role == '司机' %}selected{% endif %}>司机</option>
              <option value="管理员" {% if u.role == '管理员' %}selected{% endif %}>管理员</option>
            </select>
            <button class="btn btn-primary btn-sm">保存</button>
          </form>
        </td>
        <td>{{ u.created_at or '-' }}</td>
      </tr>
      {% else %}
      <tr><td colspan="10" class="text-center text-muted">暂无用户</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
'''
    write("templates/admin_users.html", admin)


def main() -> None:
    patch_app()
    patch_record_dao()
    patch_base()
    write_profile_template()
    write_admin_users_template()
    print("\n用户资料、头像入口、Excel 导出单位信息相关代码已写入。")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"应用修改失败：{exc}", file=sys.stderr)
        sys.exit(1)
