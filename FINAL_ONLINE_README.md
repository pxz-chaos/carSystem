# 车辆行程管理系统（生产部署说明）

本文件用于正式部署前逐项确认，避免把本地测试文件、数据库、照片或密钥上传到 GitHub。

## 1. 代码提交前检查

执行：

```bash
git status
git diff --cached --name-only
```

禁止提交：

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
carsystem_*_patch*.sh
carsystem_*_fix*.sh
```

## 2. 服务器最低建议配置

```text
系统：Ubuntu 22.04
内存：2G 起步
硬盘：40G 起步
Python：3.10 / 3.11
Web：Nginx + Gunicorn + Flask
数据库：SQLite
```

## 3. .env 必改项

```env
SECRET_KEY=换成32位以上随机字符串
APP_DEBUG=0
APP_HOST=0.0.0.0
APP_PORT=5000

WEB_CONCURRENCY=1
GUNICORN_THREADS=4
GUNICORN_TIMEOUT=180

MAX_CONTENT_LENGTH_MB=8
IMAGE_MAX_DIMENSION=1280
IMAGE_JPEG_QUALITY=75
```

## 4. 邮箱找回密码

本地测试：

```env
EMAIL_PROVIDER=console
```

正式上线：

```env
EMAIL_PROVIDER=smtp
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USE_SSL=1
SMTP_USERNAME=你的邮箱@qq.com
SMTP_PASSWORD=SMTP授权码
SMTP_FROM_EMAIL=你的邮箱@qq.com
```

## 5. 定位地址

免费方案：

```env
REVERSE_GEOCODE_PROVIDER=nominatim
NOMINATIM_USER_AGENT=VehicleTripSystem/1.0 (your_email@example.com)
NOMINATIM_EMAIL=your_email@example.com
```

更稳定方案：高德 Web 服务 Key。

## 6. Nginx 上传限制

```nginx
client_max_body_size 8m;
proxy_read_timeout 180s;
proxy_connect_timeout 30s;
proxy_send_timeout 180s;
```

## 7. 必须备份的数据

```text
.env
database/vehicle.db
uploads/
```

## 8. 上线后验证

- 管理员首次初始化正常。
- 司机注册能保存邮箱。
- 邮箱找回密码能发送验证码。
- 手机能打开页面。
- 手机能拍照上传和从相册上传。
- 出车/回场能保存定位和照片。
- 手动车牌号输入正常。
- 删除错误行程需要输入密码。
- Excel 导出正常。
