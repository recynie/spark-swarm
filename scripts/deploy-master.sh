#!/usr/bin/env bash
# =============================================================================
# spark-swarm Master 一键部署脚本
#   功能：clone 项目 → 安装依赖 → 注册 systemd 服务并启动
#   适用：Ubuntu 24.04 LTS (Python 3.12)
#
# 用法：
#   sudo bash deploy-master.sh                          # 交互式输入端口
#   sudo bash deploy-master.sh 8000                    # 直接指定端口
#
# 环境变量覆盖：
#   MASTER_PORT      监听端口 (默认: 8000)
#   INSTALL_DIR      Master 代码安装目录 (默认: /opt/spark-swarm)
#   DATA_DIR         持久化数据目录 (默认: /var/lib/spark-swarm)
# =============================================================================
set -euo pipefail

# ── 0. 确定端口 ──────────────────────────────────────────────────────────────
MASTER_PORT="${MASTER_PORT:-${1:-8000}}"

# ── 1. 基本参数 ───────────────────────────────────────────────────────────────
REPO_URL="https://github.com/recynie/spark-swarm.git"
INSTALL_DIR="${INSTALL_DIR:-/opt/spark-swarm}"
DATA_DIR="${DATA_DIR:-/var/lib/spark-swarm}"
LOCAL_IP=$(hostname -I | awk '{print $1}')

echo "============================================"
echo " spark-swarm Master 部署"
echo "============================================"
echo " 监听地址:      0.0.0.0:${MASTER_PORT}"
echo " 本机 IP:        ${LOCAL_IP}"
echo " 安装目录:       ${INSTALL_DIR}"
echo " 数据目录:       ${DATA_DIR}"
echo "============================================"

# ── 2. 前置检查 ───────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  echo "❌ 请用 sudo 运行此脚本 (需要写入 systemd 配置)。"
  exit 1
fi

# ── 3. 安装 uv (如果还没有) ──────────────────────────────────────────────────
if command -v uv &>/dev/null; then
  echo "✔ uv 已安装: $(uv --version)"
else
  echo "→ 安装 uv..."
  SUDO_USER="${SUDO_USER:-dgx}"
  if id "$SUDO_USER" &>/dev/null 2>&1; then
    su - "$SUDO_USER" -c "curl -LsSf https://astral.sh/uv/install.sh | sh"
    if [[ -d "/home/$SUDO_USER/.local/bin" ]]; then
      export PATH="/home/$SUDO_USER/.local/bin:$PATH"
    fi
  else
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
  echo "✔ uv 安装完成"
fi
export PATH="$HOME/.local/bin:/home/dgx/.local/bin:$PATH"

# ── 4. Clone / 更新项目代码 ──────────────────────────────────────────────────
if [[ -d "$INSTALL_DIR/.git" ]]; then
  echo "→ 项目已存在，更新代码..."
  cd "$INSTALL_DIR"
  git pull --ff-only
else
  echo "→ Clone 项目到 $INSTALL_DIR..."
  rm -rf "$INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
  chown -R root:root "$INSTALL_DIR"
  cd "$INSTALL_DIR"
fi

# ── 5. 安装 Python 依赖 ──────────────────────────────────────────────────────
echo "→ 安装 Python 依赖..."
uv sync --no-dev

# ── 6. 创建数据目录 ──────────────────────────────────────────────────────────
mkdir -p "$DATA_DIR"
chown -R root:root "$DATA_DIR"
chmod 755 "$DATA_DIR"

# ── 7. 写入 systemd 服务文件 ─────────────────────────────────────────────────
SERVICE_FILE="/etc/systemd/system/spark-swarm-master.service"
echo "→ 写入 $SERVICE_FILE ..."

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Spark Swarm Master
After=network.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
Environment=SPARK_SWARM_DATABASE_URL=sqlite:///${DATA_DIR}/spark_swarm.db
Environment=SPARK_SWARM_HEARTBEAT_TIMEOUT_SECONDS=15
Environment=SPARK_SWARM_SCHEDULER_INTERVAL_SECONDS=5
ExecStart=${INSTALL_DIR}/.venv/bin/uvicorn master.main:app --host 0.0.0.0 --port ${MASTER_PORT}
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF

chmod 644 "$SERVICE_FILE"

# ── 8. 重载 systemd 并启动服务 ──────────────────────────────────────────────
echo "→ 重载 systemd 配置..."
systemctl daemon-reload

echo "→ 启用并启动 spark-swarm-master 服务..."
systemctl enable --now spark-swarm-master

# ── 9. 等待并检查状态 ──────────────────────────────────────────────────────
sleep 3
if systemctl is-active --quiet spark-swarm-master; then
  echo ""
  echo "============================================"
  echo "✔ spark-swarm-master 已成功启动！"
  echo "============================================"
  echo " 服务状态:"
  systemctl status spark-swarm-master --no-pager 2>&1 | head -20
  echo ""
  echo " 健康检查:"
  curl -s http://127.0.0.1:${MASTER_PORT}/healthz
  echo ""
  echo " 检查 Agent 接入:"
  echo "   curl http://127.0.0.1:${MASTER_PORT}/api/v1/hosts"
  echo ""
  echo " 实时日志:"
  echo "   sudo journalctl -u spark-swarm-master -f"
  echo ""
  echo " Agent 需配置的地址: http://${LOCAL_IP}:${MASTER_PORT}"
  echo ""
  echo " 常用操作:"
  echo "   启动: sudo systemctl start spark-swarm-master"
  echo "   停止: sudo systemctl stop spark-swarm-master"
  echo "   重启: sudo systemctl restart spark-swarm-master"
  echo "   日志: sudo journalctl -u spark-swarm-master -f"
  echo "============================================"
else
  echo "⚠ 服务启动失败，查看日志:"
  journalctl -u spark-swarm-master --no-pager -n 30
  exit 1
fi
