# 最终上线检查清单

上线前请确认：

1. `.env` 中已设置强随机 `SECRET_KEY`。
2. `APP_DEBUG=0`。
3. 已配置短信服务，正式环境建议使用 `SMS_PROVIDER=aliyun`。
4. 服务器防火墙和安全组放行 80、443、22。
5. 已通过 Nginx + Gunicorn 运行，不要直接把 Flask 开发服务器暴露到公网。
6. 已配置 HTTPS。
7. 已制定数据库和照片备份计划。
8. 管理员首次登录后及时创建司机账号并分配权限。

OCR 不是最终数据来源。系统已经改为：手动输入优先，OCR 只辅助预填，用户确认后才保存。
<<<<<<< HEAD

## Windows 常见修复

如果启动时出现：`No module named 'google'`，说明 PaddlePaddle 依赖的 `protobuf` 未安装完整。请先关闭运行窗口，然后双击：

```bat
fix_paddle_google.bat
```

或重新执行 `setup_env.bat`。
=======
>>>>>>> 55a777a7d7dc7a1e307a6131d3c93efa554ea949
