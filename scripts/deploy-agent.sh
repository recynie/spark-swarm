#!/usr/bin/env bash
# =============================================================================
# spark-swarm Agent 一键部署脚本
#   功能：clone 项目 → 安装依赖 → 安装 Docker → 注册 systemd 服务并启动
#   适用：Ubuntu 24.04 LTS (Python 3.12)
#
# 用法：
#   sudo bash deploy-agent.sh                          # 交互式输入 Master 地址
#   sudo bash deploy-agent.sh http://192.168.5.10:8000 # 直接指定
#
# 环境变量覆盖：
#   MASTER_URL       Agent 连接的 Master 地址 (默认: 第一个参数)
#   AGENT_HOSTNAME   本机主机名 (默认: worker-<本机IP末段>)
#   INSTALL_DIR      Agent 代码安装目录 (默认: /opt/spark-swarm)
#   DATA_DIR         持久化数据目录 (默认: /var/lib/spark-swarm)
# =============================================================================
set -euo pipefail

# ── 0. 确定 Master 地址 ──────────────────────────────────────────────────────
if [[ $# -ge 1 ]]; then
  MASTER_URL="${MASTER_URL:-$1}"
else
  read -r -p "请输入 Master 地址 (例如 http://192.168.5.10:8000): " input_url
  MASTER_URL="${MASTER_URL:-$input_url}"
fi

if [[ -z "$MASTER_URL" ]]; then
  echo "❌ 必须指定 Master 地址。"
  echo "用法: sudo bash $0 http://<master-ip>:8000"
  exit 1
fi

# ── 1. 基本参数 ───────────────────────────────────────────────────────────────
REPO_URL="https://github.com/recynie/spark-swarm.git"
INSTALL_DIR="${INSTALL_DIR:-/opt/spark-swarm}"
DATA_DIR="${DATA_DIR:-/var/lib/spark-swarm}"

# 从本机 IP 自动生成主机名 (取 IP 最后一段)
LOCAL_IP=$(hostname -I | awk '{print $1}')
IP_SUFFIX=$(echo "$LOCAL_IP" | awk -F. '{print $NF}')
AGENT_HOSTNAME="${AGENT_HOSTNAME:-worker-${IP_SUFFIX}}"

echo "============================================"
echo " spark-swarm Agent 部署"
echo "============================================"
echo " Master 地址:    $MASTER_URL"
echo " 主机名:         $AGENT_HOSTNAME"
echo " 本机 IP:         $LOCAL_IP"
echo " 安装目录:       $INSTALL_DIR"
echo " 数据目录:       $DATA_DIR"
echo "============================================"

# ── 2. 前置检查 ───────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  echo "❌ 请用 sudo 运行此脚本 (需要安装 Docker 和 systemd 服务)。"
  exit 1
fi

# ── 3. 安装 Docker ────────────────────────────────────────────────────────────
if command -v docker &>/dev/null; then
  echo "✔ Docker 已安装"
else
  echo "→ 安装 Docker..."
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
  echo "✔ Docker 已安装并启动"
fi

# ── 4. 安装 uv (如果还没有) ──────────────────────────────────────────────────
if command -v uv &>/dev/null; then
  echo "✔ uv 已安装: $(uv --version)"
else
  echo "→ 安装 uv..."
  # 给当前非 root 用户安装
  SUDO_USER="${SUDO_USER:-dgx}"
  if id "$SUDO_USER" &>/dev/null 2>&1; then
    su - "$SUDO_USER" -c "curl -LsSf https://astral.sh/uv/install.sh | sh"
    # 添加到 PATH
    export UV_BIN="$HOME/.local/bin"
    if [[ -d "/home/$SUDO_USER/.local/bin" ]]; then
      export PATH="/home/$SUDO_USER/.local/bin:$PATH"
    fi
  else
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
  echo "✔ uv 安装完成"
fi

# 确保 uv 在 PATH 中
export PATH="$HOME/.local/bin:/home/dgx/.local/bin:$PATH"

# ── 5. Clone / 更新项目代码 ──────────────────────────────────────────────────
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

# ── 6. 安装 Python 依赖 ──────────────────────────────────────────────────────
echo "→ 安装 Python 依赖..."
uv sync --no-dev

# ── 7. 创建数据目录 ──────────────────────────────────────────────────────────
mkdir -p "$DATA_DIR"
chmod 755 "$DATA_DIR"

# ── 8. 写入 systemd 服务文件 ─────────────────────────────────────────────────
SERVICE_FILE="/etc/systemd/system/spark-swarm-agent.service"
echo "→ 写入 $SERVICE_FILE ..."

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Spark Swarm Agent (${AGENT_HOSTNAME})
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
Environment=SPARK_SWARM_AGENT_MASTER_URL=${MASTER_URL}
Environment=SPARK_SWARM_AGENT_HOSTNAME=${AGENT_HOSTNAME}
Environment=SPARK_SWARM_AGENT_HOST_ID_FILE=${DATA_DIR}/agent-id
Environment=SPARK_SWARM_AGENT_OUTPUT_DIR=${DATA_DIR}/output
Environment=SPARK_SWARM_AGENT_POLL_INTERVAL_SECONDS=5
ExecStart=${INSTALL_DIR}/.venv/bin/python -m agent.main
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF

chmod 644 "$SERVICE_FILE"

# ── 9. 重载 systemd 并启动服务 ──────────────────────────────────────────────
echo "→ 重载 systemd 配置..."
systemctl daemon-reload

echo "→ 启用并启动 spark-swarm-agent 服务..."
systemctl enable --now spark-swarm-agent

# ── 10. 等待并检查状态 ──────────────────────────────────────────────────────
sleep 3
if systemctl is-active --quiet spark-swarm-agent; then
  echo ""
  echo "============================================"
  echo "✔ spark-swarm-agent 已成功启动！"
  echo "============================================"
  echo " 服务状态:"
  systemctl status spark-swarm-agent --no-pager 2>&1 | head -20
  echo ""
  echo " 实时日志:"
  echo "   sudo journalctl -u spark-swarm-agent -f"
  echo ""
  echo " 检查 Master 是否注册成功:"
  echo "   curl ${MASTER_URL}/api/v1/hosts"
  echo ""
  echo " 常用操作:"
  echo "   启动: sudo systemctl start spark-swarm-agent"
  echo "   停止: sudo systemctl stop spark-swarm-agent"
  echo "   重启: sudo systemctl restart spark-swarm-agent"
  echo "   日志: sudo journalctl -u spark-swarm-agent -f"
  echo "============================================"
else
  echo "⚠ 服务启动失败，查看日志:"
  journalctl -u spark-swarm-agent --no-pager -n 30
  exit 1
fi
