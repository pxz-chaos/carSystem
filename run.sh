#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -x "venv/bin/python" ]; then
  echo "未找到 venv/bin/python，请先创建虚拟环境并安装 requirements.txt"
  exit 1
fi
venv/bin/python app.py
