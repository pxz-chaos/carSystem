# CarFleetSystem V8.1 公网部署说明（Ubuntu 22.04/24.04）

## 1. 准备条件

1. 一台云服务器，推荐 2核4G 起步；如果要在服务器上跑 PaddleOCR，建议 4G 以上内存。
2. 云服务器安全组放行：80、443、22。
3. 可选：域名解析到服务器公网 IP。
4. 阿里云短信服务：完成实名认证，申请短信签名和验证码模板。

## 2. 上传项目

把项目上传到服务器：

```bash
sudo mkdir -p /opt/CarFleetSystem
sudo chown -R $USER:$USER /opt/CarFleetSystem
# 将本项目文件上传/解压到 /opt/CarFleetSystem
cd /opt/CarFleetSystem
```

## 3. 安装系统依赖

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx unzip libgl1 libglib2.0-0
```

## 4. 安装 Python 环境

```bash
cd /opt/CarFleetSystem
python3 -m venv venv
./venv/bin/python -m pip install --upgrade pip setuptools wheel
./venv/bin/pip install -r requirements.txt
```

## 5. 配置 .env

```bash
cp .env.example .env
nano .env
```

公网真实短信请至少修改：

```env
SECRET_KEY=改成很长的随机字符串
SMS_PROVIDER=aliyun
ALIYUN_ACCESS_KEY_ID=你的AccessKeyId
ALIYUN_ACCESS_KEY_SECRET=你的AccessKeySecret
ALIYUN_SMS_SIGN_NAME=你的短信签名
ALIYUN_SMS_TEMPLATE_CODE_LOGIN=登录验证码模板CODE
ALIYUN_SMS_TEMPLATE_CODE_RESET=找回密码验证码模板CODE
```

短信模板变量默认使用 `code`。如果你的模板变量不是 `${code}`，请修改：

```env
ALIYUN_SMS_TEMPLATE_PARAM_NAME=你的变量名
```

## 6. 初始化数据库和管理员

先临时启动一次：

```bash
./venv/bin/python app.py
```

浏览器访问：

```text
http://服务器公网IP:5000
```

首次打开会要求设置管理员。设置完成后按 `Ctrl+C` 停止临时服务。

如果云服务器安全组没有放行 5000，也可以先跳过，等 Nginx 配好后通过 80 端口设置管理员。

## 7. 配置 Gunicorn + systemd

```bash
sudo cp deploy/carfleet.service /etc/systemd/system/carfleet.service
sudo chown -R www-data:www-data /opt/CarFleetSystem
sudo systemctl daemon-reload
sudo systemctl enable carfleet
sudo systemctl start carfleet
sudo systemctl status carfleet --no-pager
```

## 8. 配置 Nginx

编辑 `deploy/nginx_carfleet.conf`，把：

```nginx
server_name your-domain.com;
```

改成你的域名；没有域名就写服务器公网 IP 或 `_`。

然后执行：

```bash
sudo cp deploy/nginx_carfleet.conf /etc/nginx/sites-available/carfleet
sudo ln -sf /etc/nginx/sites-available/carfleet /etc/nginx/sites-enabled/carfleet
sudo nginx -t
sudo systemctl reload nginx
```

现在可以访问：

```text
http://你的域名
或 http://服务器公网IP
```

## 9. HTTPS

如果你有域名，建议安装证书：

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d 你的域名
```

## 10. 常用维护命令

```bash
sudo systemctl restart carfleet
sudo systemctl status carfleet --no-pager
sudo journalctl -u carfleet -f
sudo nginx -t
sudo systemctl reload nginx
```

## 11. 数据备份

至少定期备份：

```text
database/vehicle.db
uploads/
exports/
.env
```

`.env` 包含短信密钥，不要发给外人。
