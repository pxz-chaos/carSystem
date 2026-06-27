# Ubuntu 22.04 公网部署说明

本文档适用于将 CarFleetSystem 部署到阿里云 Ubuntu 22.04 服务器。

## 1. 安装系统依赖

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git sqlite3
```

## 2. 拉取代码

```bash
cd /opt
sudo git clone https://github.com/pxz-chaos/carSystem.git carsystem
sudo chown -R $USER:$USER /opt/carsystem
cd /opt/carsystem
```

## 3. 创建虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## 4. 创建 .env

```bash
cp .env.example .env
nano .env
```

至少修改：

```env
SECRET_KEY=换成足够长的随机字符串
APP_DEBUG=0
APP_HOST=127.0.0.1
APP_PORT=8000
WEB_CONCURRENCY=1
GUNICORN_THREADS=4
GUNICORN_TIMEOUT=180
```

2G 内存服务器不建议开多个 worker。

## 5. 创建运行目录

```bash
mkdir -p database uploads exports logs debug_ocr
```

## 6. Gunicorn 测试启动

```bash
source venv/bin/activate
gunicorn -c gunicorn.conf.py 'app:create_app()'
```

如果没有报错，按 `Ctrl+C` 停止。

## 7. systemd 服务

```bash
sudo tee /etc/systemd/system/carsystem.service >/dev/null <<'SERVICE_EOF'
[Unit]
Description=CarFleetSystem Flask App
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/carsystem
EnvironmentFile=/opt/carsystem/.env
ExecStart=/opt/carsystem/venv/bin/gunicorn -c /opt/carsystem/gunicorn.conf.py 'app:create_app()'
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE_EOF
```

授权目录：

```bash
sudo chown -R www-data:www-data /opt/carsystem
```

启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable carsystem
sudo systemctl start carsystem
sudo systemctl status carsystem
```

查看日志：

```bash
sudo journalctl -u carsystem -f
```

## 8. Nginx 配置

```bash
sudo tee /etc/nginx/sites-available/carsystem >/dev/null <<'NGINX_EOF'
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 8m;
    proxy_read_timeout 180s;
    proxy_connect_timeout 30s;
    proxy_send_timeout 180s;

    location /static/ {
        alias /opt/carsystem/static/;
        expires 7d;
    }

    location /uploads/ {
        alias /opt/carsystem/uploads/;
        expires 7d;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX_EOF
```

启用站点：

```bash
sudo ln -sf /etc/nginx/sites-available/carsystem /etc/nginx/sites-enabled/carsystem
sudo nginx -t
sudo systemctl reload nginx
```

## 9. HTTPS

建议绑定域名并配置 HTTPS，否则手机定位、PWA 和拍照权限体验可能受影响。

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

HTTPS 生效后可在 `.env` 中设置：

```env
SESSION_COOKIE_SECURE=1
```

然后重启：

```bash
sudo systemctl restart carsystem
sudo systemctl reload nginx
```

## 10. 数据备份

```bash
mkdir -p /opt/carsystem_backup
cp /opt/carsystem/database/vehicle.db /opt/carsystem_backup/vehicle_$(date +%Y%m%d_%H%M%S).db
```

照片目录 `uploads/` 应定期备份。照片量很大时，建议迁移到独立数据盘或对象存储。

## 11. 常用维护命令

```bash
sudo systemctl restart carsystem
sudo systemctl status carsystem
sudo journalctl -u carsystem -f
sudo nginx -t
sudo systemctl reload nginx
```

## 12. 更新代码

```bash
cd /opt/carsystem
sudo -u www-data git pull
sudo -u www-data /opt/carsystem/venv/bin/pip install -r requirements.txt
sudo systemctl restart carsystem
```
