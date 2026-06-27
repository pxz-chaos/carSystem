## 版本记录

当前版本：v1.5.0

| 版本 | 提交号 | 修改内容 |
|---|---|---|
| v1.5.0 | f79efa8 | 定位地址优化：管理员初始化补充资料填写，定位从经纬度优化为城市/区县地址展示 |
| v1.4.0 | ca1f89b | 企业级权限系统：头像下拉菜单、注销账号、管理员密码确认删除司机、隐藏重复导出入口 |
| v1.3.0 | cf8a268 | 导出表头优化：调整 Excel 表头顺序，补充性别、单位、部门、班组等字段 |
| v1.2.0 | 9550a04 | Excel 导出补充单位信息 |
| v1.1.0 | 9550a04 | 用户注册和个人资料：注册保存用户资料，点击头像查看个人信息 |
| v1.0.0 | 6f8f916 | 初始可用版本 |
如果要下载旧版本，操作步骤如下：
git clone --branch v1.3.0 https://github.com/pxz-chaos/carSystem.git carSystem_v1.3.0
# 车辆管理系统
本包用于正式上线部署，已包含以下功能：

- 首次启动自定义管理员账号和密码，不内置默认管理员密码。
- 管理员可管理用户权限，并导出所有司机 Excel 和图片。
- 普通司机只能查看和导出自己的行程数据。
- 支持用户名/手机号密码登录、手机号短信验证码登录、短信验证码找回密码。
- 出车/回场支持手动输入优先；OCR 仅作为辅助识别，识别结果必须人工确认后才入库。
- OCR 已增强“总里程”模糊识别，降低把本次行驶、续航、电量误选为总里程的概率。
- Excel 导出不包含经纬度；图片导出按“用户名_车牌号_时间.jpg”命名。
- 管理员后台支持数据维护、清理历史行程、清理孤儿照片、清理导出文件。
- 支持公网部署：Gunicorn + Nginx + systemd，参考 `deploy_public_ubuntu.md`。

## 本地 Windows 运行

1. 解压本包。
2. 双击 `setup_env.bat` 安装环境。
3. 双击 `run.bat` 启动系统。
4. 首次访问时先设置管理员账号和密码。

## 生产环境关键配置

复制 `.env.example` 为 `.env`，至少修改：

```env
SECRET_KEY=请改成足够长的随机字符串
APP_DEBUG=0
SMS_PROVIDER=aliyun
ALIYUN_ACCESS_KEY_ID=你的AccessKeyId
ALIYUN_ACCESS_KEY_SECRET=你的AccessKeySecret
ALIYUN_SMS_SIGN_NAME=你的短信签名
ALIYUN_SMS_TEMPLATE_CODE_LOGIN=登录验证码模板CODE
ALIYUN_SMS_TEMPLATE_CODE_RESET=找回密码验证码模板CODE
```

如需先本地测试短信验证码，可保持：

```env
SMS_PROVIDER=console
```

验证码会写入 `debug_ocr/sms_codes.txt`。

## 数据目录

- 数据库：`database/vehicle.db`
- 上传照片：`uploads/`
- 导出文件：`exports/`
- OCR/短信调试：`debug_ocr/`

上线后请定期备份 `database/vehicle.db` 和 `uploads/`。
<<<<<<< HEAD

## Windows 常见修复

如果启动时出现：`No module named 'google'`，说明 PaddlePaddle 依赖的 `protobuf` 未安装完整。请先关闭运行窗口，然后双击：

```bat
fix_paddle_google.bat
```

或重新执行 `setup_env.bat`。
=======
>>>>>>> 55a777a7d7dc7a1e307a6131d3c93efa554ea949
