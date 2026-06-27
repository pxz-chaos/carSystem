# 车辆行程管理系统

车辆行程管理系统 是一个面向车队/司机的轻量级车辆行程管理系统，适合几十到上百名司机通过手机浏览器完成出车、回场、拍照上传、定位记录、里程登记和数据导出。

系统采用 Flask + SQLite 架构，默认不依赖 Redis、不依赖大型数据库，适合部署在 2G 内存、40G 硬盘的小型 Ubuntu 服务器上。照片会自动压缩保存，减少服务器硬盘压力。

---

## 主要功能

### 司机端

- 用户注册、登录、退出。
- 手机号验证码登录，可配置为本地 console 或阿里云短信。
- 邮箱验证码找回密码，可配置为本地 console 或 SMTP 邮箱。
- 出车登记：车牌号、出发里程、出发照片、出发定位。
- 回场登记：回场里程、回场照片、回场定位。
- 支持手机拍照上传，也支持从相册添加照片。
- OCR 辅助识别车牌号和里程，识别结果可人工确认和修改。
- 司机只能查看、导出、删除自己的行程。
- 删除错误行程时必须输入当前登录密码。

### 管理员端

- 首次启动时创建管理员账号，不内置默认密码。
- 管理司机账号、角色和权限。
- 查看所有司机行程。
- 导出 Excel 和照片。
- 管理员可以删除任意错误行程，但必须输入管理员登录密码。
- 数据维护：清理历史行程、孤儿照片、导出文件。

### 定位与地址

- 手机浏览器获取经纬度。
- 可选免费 Nominatim / OpenStreetMap 反向地理编码，将经纬度转换为地址。
- 可选高德 Web 服务逆地理编码，适合国内正式上线。
- 免费服务不保证稳定，失败时系统会保留经纬度。

### 部署和性能优化

- 上传照片自动压缩为 JPEG。
- 限制最大上传文件大小。
- Gunicorn 建议 1 worker + 多线程，避免 2G 内存服务器被 OCR 模型撑爆。
- SQLite 开启 WAL 和常用索引，降低并发提交时的锁冲突。
- 支持 Nginx + Gunicorn + systemd 部署。
- 支持 PWA，可添加到手机主屏幕，像 App 一样打开。

---

## 目录说明

```text
carSystem/
├── app.py                    # Flask 主入口，路由和页面逻辑
├── config.py                 # 系统配置，读取 .env 环境变量
├── requirements.txt          # Python 依赖
├── gunicorn.conf.py          # Gunicorn 生产配置
├── run.bat                   # Windows 一键启动
├── run.sh                    # Linux 启动脚本
├── setup_env.bat             # Windows 安装依赖
├── dao/                      # 数据库访问层
├── service/                  # 业务服务层
├── utils/                    # OCR、文件、定位、邮箱、短信等工具
├── templates/                # HTML 页面模板
├── static/                   # 静态资源、PWA、前端脚本
├── scripts/                  # 维护脚本，例如补地址、数据清理
├── deploy/                   # 部署相关文件
├── database/                 # 运行时数据库目录，不要提交 .db 文件
├── uploads/                  # 上传照片目录，不要提交
├── exports/                  # 导出文件目录，不要提交
└── debug_ocr/                # 本地调试验证码/OCR 日志，不要提交
```

---

## Windows 本地运行

### 1. 安装 Python

建议使用 Python 3.10 或 3.11。

```bash
python --version
```

### 2. 安装依赖

推荐直接双击：

```text
setup_env.bat
```

或手动执行：

```bash
python -m venv venv
source venv/Scripts/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

### 3. 创建本地配置

```bash
cp .env.example .env
```

Windows 也可以直接复制 `.env.example` 并重命名为 `.env`。

### 4. 启动系统

推荐双击：

```text
run.bat
```

或手动启动：

```bash
python app.py
```

浏览器访问：

```text
http://127.0.0.1:5000
```

手机局域网访问时，必须让 Flask 监听 `0.0.0.0`，并访问电脑的局域网 IP，例如：

```text
http://192.168.1.12:5000
```

---

## 首次使用流程

1. 启动系统。
2. 第一次打开页面时，系统会要求创建管理员账号。
3. 管理员登录后，可以创建或审核司机账号。
4. 司机登录后，进入出车登记页面。
5. 出车时上传出发照片、填写车牌号和出发里程。
6. 回场时上传回场照片、填写回场里程。
7. 管理员可在后台查看、导出和维护数据。

---

## .env 配置说明

`.env` 是运行配置文件，里面可能包含邮箱、短信、密钥等敏感信息，禁止提交到 GitHub。

### 推荐的本地测试配置

```env
SECRET_KEY=please-change-to-a-long-random-secret
APP_HOST=0.0.0.0
APP_PORT=5000
APP_DEBUG=0

SMS_PROVIDER=console
EMAIL_PROVIDER=console

REVERSE_GEOCODE_ENABLED=1
REVERSE_GEOCODE_PROVIDER=nominatim
REVERSE_GEOCODE_TIMEOUT_SECONDS=8
NOMINATIM_USER_AGENT=VehicleTripSystem/1.0 (your_email@example.com)
NOMINATIM_EMAIL=your_email@example.com
REVERSE_GEOCODE_LANGUAGE=zh-CN,zh,en
REVERSE_GEOCODE_COUNTRYCODES=cn

MAX_CONTENT_LENGTH_MB=8
IMAGE_MAX_DIMENSION=1280
IMAGE_JPEG_QUALITY=75

OCR_FALLBACK_ENABLED=1
OCR_MAX_ROI_IMAGES=3
OCR_CPU_THREADS=2
```

### 验证码位置

本地 console 模式下：

- 短信验证码写入：`debug_ocr/sms_codes.txt`
- 邮箱验证码写入：`debug_ocr/email_codes.txt`

正式上线需要改为真实短信或 SMTP 邮箱服务。

---

## 邮箱找回密码配置

本地测试：

```env
EMAIL_PROVIDER=console
```

正式使用 QQ 邮箱 SMTP 示例：

```env
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USE_SSL=1
SMTP_USE_TLS=0
SMTP_USERNAME=你的QQ邮箱@qq.com
SMTP_PASSWORD=QQ邮箱SMTP授权码
SMTP_FROM_NAME=车辆管理系统
SMTP_FROM_EMAIL=你的QQ邮箱@qq.com
EMAIL_CODE_TTL_SECONDS=300
EMAIL_SEND_COOLDOWN_SECONDS=60
EMAIL_MAX_ATTEMPTS=5
```

注意：`SMTP_PASSWORD` 不是邮箱登录密码，而是邮箱后台生成的 SMTP 授权码。

---

## 定位地址配置

### 免费方案：Nominatim

```env
REVERSE_GEOCODE_ENABLED=1
REVERSE_GEOCODE_PROVIDER=nominatim
REVERSE_GEOCODE_TIMEOUT_SECONDS=8
NOMINATIM_USER_AGENT=VehicleTripSystem/1.0 (your_email@example.com)
NOMINATIM_EMAIL=your_email@example.com
REVERSE_GEOCODE_LANGUAGE=zh-CN,zh,en
REVERSE_GEOCODE_COUNTRYCODES=cn
```

说明：免费服务不需要 Key，但稳定性和国内地址精度有限。请求失败时系统会显示经纬度。

### 国内推荐方案：高德 Web 服务

```env
REVERSE_GEOCODE_ENABLED=1
REVERSE_GEOCODE_PROVIDER=amap
AMAP_WEB_SERVICE_KEY=你的高德Web服务Key
AMAP_REVERSE_EXTENSIONS=all
AMAP_REVERSE_RADIUS=1000
AMAP_INPUT_COORD_TYPE=wgs84
AMAP_WGS84_TO_GCJ02=1
```

注意：必须申请“Web 服务 Key”，不是 JS Key、Android Key 或 iOS Key。

---

## 手机访问注意事项

本地测试时：

1. 手机和电脑连接同一个 WiFi。
2. 电脑防火墙允许 5000 端口。
3. 手机访问电脑局域网 IP，例如 `http://192.168.1.12:5000`。
4. 不要访问 `127.0.0.1`、`localhost` 或 `0.0.0.0`。

如果手机完全打不开，通常是以下原因：

- Flask 只监听了 `127.0.0.1`。
- Windows 防火墙拦截。
- 手机没有连接同一个 WiFi。
- 路由器开启了 AP 隔离。
- PWA/service worker 缓存了旧页面，需要清理浏览器站点数据。

---

## Ubuntu 22.04 生产部署概览

推荐部署结构：

```text
Nginx -> Gunicorn -> Flask -> SQLite
```

2G 内存服务器建议：

```env
WEB_CONCURRENCY=1
GUNICORN_THREADS=4
GUNICORN_TIMEOUT=180
APP_DEBUG=0
```

上传限制建议：

```nginx
client_max_body_size 8m;
proxy_read_timeout 180s;
proxy_connect_timeout 30s;
proxy_send_timeout 180s;
```

完整部署步骤见：

```text
deploy_public_ubuntu.md
```

---

## 数据备份

运行中最重要的数据：

```text
database/vehicle.db
uploads/
.env
```

建议至少每天备份一次：

```bash
mkdir -p backup
cp database/vehicle.db backup/vehicle_$(date +%Y%m%d_%H%M%S).db
```

照片较多时，建议把 `uploads/` 定期压缩备份或迁移到对象存储/独立数据盘。

---

## 不要提交到 GitHub 的文件

```text
.env
database/*.db
database/*.db-*
uploads/
exports/
debug_ocr/
logs/
venv/
ocr_user_home/
pip/
*.bak
*.patch
*_backup_/
```

提交前检查：

```bash
git status
git diff --cached --name-only
```

---

## 常见问题

### 1. 手机只有拍照，没有添加照片

页面应提供“拍照上传”和“添加照片”两个入口。如果手机仍只显示拍照，请检查 `templates/start.html`、`templates/finish.html` 和 `static/upload_picker.js` 是否为最新版本。

### 2. 定位只有经纬度，没有地址

先确认 `.env` 中：

```env
REVERSE_GEOCODE_ENABLED=1
REVERSE_GEOCODE_PROVIDER=nominatim
```

如果仍然只有经纬度，通常是免费反查服务超时或无数据。正式上线建议使用高德 Web 服务 Key。

### 3. 邮箱找回密码提示用户名和邮箱不匹配

说明数据库里该用户绑定的邮箱为空或和输入不一致。管理员需要给用户补邮箱，或者用户重新注册时填写邮箱。

### 4. OCR 第一次很慢

第一次加载 PaddleOCR 模型会比较慢。2G 内存服务器建议只开 1 个 Gunicorn worker，并减少 OCR 图片数量。

### 5. Windows 出现 `No module named google`

关闭运行窗口，执行：

```text
fix_paddle_google.bat
```

或重新执行：

```text
setup_env.bat
```

---

## 版本说明

当前维护版：Production Hardening

本版本重点优化：

- 上传图片压缩和磁盘压力控制。
- 邮箱验证码找回密码。
- 手机拍照/相册上传体验。
- 免费/高德反向地理编码。
- 手动车牌号输入和 OCR 结果人工确认。
- 密码确认删除错误行程。
- 小内存服务器部署参数。
