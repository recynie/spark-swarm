# spark-swarm

基于 FastAPI + Docker SDK 的集中式 Docker 任务分发系统。`master` 负责接收任务和调度，`agent` 负责在工作机上执行 Docker 任务并回传结果。

## 组件
- **Master**：任务接收、调度、主机健康监控
- **Agent**：心跳上报、拉取任务、执行 Docker build/run、结果上报
- **CLI**：提交任务、查询任务状态、查看主机列表

## 环境要求
- Python 3.11+
- `uv`
- Agent 所在机器可访问本机 Docker daemon

## 安装依赖
```bash
uv sync --extra test
```

---

## User Guide

本节说明如何在本地或多台机器上完整部署并使用 spark-swarm。

### 架构概览

```
┌─────────────┐        HTTP        ┌──────────────────┐
│   CLI / curl │ ──────────────── ▶ │   Master (8000)  │
└─────────────┘                    │  任务调度 + DB   │
                                   └────────┬─────────┘
                                            │ 心跳 / 任务下发
                          ┌─────────────────┼─────────────────┐
                          ▼                 ▼                 ▼
                   ┌────────────┐  ┌────────────┐  ┌────────────┐
                   │  Agent     │  │  Agent     │  │  Agent     │
                   │ worker-01  │  │ worker-02  │  │ worker-03  │
                   │  Docker    │  │  Docker    │  │  Docker    │
                   └────────────┘  └────────────┘  └────────────┘
```

- **Master** 是唯一的调度中心，所有 agent 和 CLI 都连接到它。
- **Agent** 运行在每台 worker 机器上，定期心跳并领取任务。
- **CLI** 在任意能访问 master 的机器上运行，默认连接 `127.0.0.1:8000`，也可以通过 `--master-url` 或 `SPARK_SWARM_MASTER_URL` 指定远程 master。

---

### 第一步：部署 Master

#### 本地开发（单机）

```bash
uv run uvicorn master.main:app --host 127.0.0.1 --port 8000 --reload
```

#### 多机部署（让 agent 从其他机器访问）

Master 必须监听 `0.0.0.0`，否则远程 agent 无法连接：

```bash
uv run uvicorn master.main:app --host 0.0.0.0 --port 8000
```

验证 master 是否正常运行：

```bash
curl http://<master-ip>:8000/healthz
# 返回 {"ok": true}
```

#### Master 配置项

通过环境变量（前缀 `SPARK_SWARM_`）覆盖默认值：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `SPARK_SWARM_DATABASE_URL` | `sqlite:///$(pwd)/spark_swarm.db` | 数据库连接串 |
| `SPARK_SWARM_ARTIFACT_DIR` | `$(pwd)/spark_swarm_artifacts` | master 保存任务产物的目录 |
| `SPARK_SWARM_SCHEDULER_INTERVAL_SECONDS` | `5` | 调度循环间隔（秒） |
| `SPARK_SWARM_HEARTBEAT_TIMEOUT_SECONDS` | `15` | agent 离线判定超时（秒） |

示例：

```bash
export SPARK_SWARM_DATABASE_URL=sqlite:////data/spark-swarm/spark_swarm.db
export SPARK_SWARM_HEARTBEAT_TIMEOUT_SECONDS=20
uv run uvicorn master.main:app --host 0.0.0.0 --port 8000
```

#### 使用 systemd 常驻运行 Master

创建 `/etc/systemd/system/spark-swarm-master.service`：

```ini
[Unit]
Description=Spark Swarm Master
After=network.target

[Service]
WorkingDirectory=/opt/spark-swarm
Environment=SPARK_SWARM_DATABASE_URL=sqlite:////opt/spark-swarm/data/spark_swarm.db
ExecStart=/usr/bin/env uv run uvicorn master.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now spark-swarm-master
sudo systemctl status spark-swarm-master
```

---

### 第二步：部署 Agent

每台 worker 机器都需要单独部署 agent。

#### 前提条件

- 安装了 Python 3.11+、`uv`、Docker Engine
- 运行 agent 的用户有权限访问 Docker（通常需要加入 `docker` 用户组）
- 能够访问 master 的 HTTP 地址

#### 启动 Agent

最小启动命令：

```bash
SPARK_SWARM_AGENT_MASTER_URL=http://<master-ip>:8000 uv run python -m agent.main
```

建议为每台 worker 设置唯一 hostname：

```bash
SPARK_SWARM_AGENT_MASTER_URL=http://<master-ip>:8000 \
SPARK_SWARM_AGENT_HOSTNAME=worker-01 \
uv run python -m agent.main
```

#### Agent 配置项

通过环境变量（前缀 `SPARK_SWARM_AGENT_`）覆盖默认值：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `SPARK_SWARM_AGENT_MASTER_URL` | `http://127.0.0.1:8000` | Master 地址 |
| `SPARK_SWARM_AGENT_POLL_INTERVAL_SECONDS` | `5` | 心跳与轮询间隔（秒） |
| `SPARK_SWARM_AGENT_HOSTNAME` | `worker` | 上报给 master 的主机名 |
| `SPARK_SWARM_AGENT_IP_ADDRESS` | `127.0.0.1` | 上报给 master 的 IP（自动探测） |
| `SPARK_SWARM_AGENT_HOST_ID_FILE` | `./.spark-swarm-agent-id` | host_id 持久化文件路径 |
| `SPARK_SWARM_AGENT_OUTPUT_DIR` | `./agent-output` | 任务产物输出目录 |
| `SPARK_SWARM_AGENT_ENABLE_GPU` | `false` | 为任务容器挂载全部 GPU |
| `SPARK_SWARM_AGENT_MODEL_CACHE_DIR` | 空 | 挂载到任务容器 `/models` 的模型缓存目录 |
| `SPARK_SWARM_AGENT_MAX_ARTIFACT_BYTES` | `104857600` | 单次任务回传 artifact 总大小上限 |

建议将 `HOST_ID_FILE` 和 `OUTPUT_DIR` 设置为持久化路径，避免重启后 agent 被注册为新主机：

```bash
export SPARK_SWARM_AGENT_MASTER_URL=http://192.168.5.100:8000
export SPARK_SWARM_AGENT_HOSTNAME=worker-01
export SPARK_SWARM_AGENT_HOST_ID_FILE=/var/lib/spark-swarm/agent-id
export SPARK_SWARM_AGENT_OUTPUT_DIR=/var/lib/spark-swarm/output
uv run python -m agent.main
```

#### 使用 systemd 常驻运行 Agent

创建 `/etc/systemd/system/spark-swarm-agent.service`：

```ini
[Unit]
Description=Spark Swarm Agent
After=network.target docker.service
Requires=docker.service

[Service]
WorkingDirectory=/opt/spark-swarm
Environment=SPARK_SWARM_AGENT_MASTER_URL=http://<master-ip>:8000
Environment=SPARK_SWARM_AGENT_HOSTNAME=worker-01
Environment=SPARK_SWARM_AGENT_HOST_ID_FILE=/var/lib/spark-swarm/agent-id
Environment=SPARK_SWARM_AGENT_OUTPUT_DIR=/var/lib/spark-swarm/output
ExecStart=/usr/bin/env uv run python -m agent.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now spark-swarm-agent
sudo systemctl status spark-swarm-agent
```

#### 验证 Agent 已接入

```bash
# 查看所有已注册主机
curl http://<master-ip>:8000/api/v1/hosts
```

在线的 agent 会显示 `"status": "ONLINE"` 以及最近的心跳时间和资源信息。

---

### 第三步：分发任务

#### 使用 CLI

项目安装后提供 `spark-swarm` 命令，当前版本默认连接 `http://127.0.0.1:8000`，建议在 master 机器上执行。
也可以使用 `--master-url` 或环境变量连接远程 master：

```bash
SPARK_SWARM_MASTER_URL=http://<master-ip>:8000 uv run spark-swarm hosts
uv run spark-swarm --help
uv run spark-swarm tasks --master-url http://<master-ip>:8000
```

**提交任务**（提供 Dockerfile 文件路径）：

```bash
uv run spark-swarm submit ./Dockerfile --name my-task
```

可选参数：

```bash
uv run spark-swarm submit ./Dockerfile \
  --name my-task \
  --cpu 2.0 \        # CPU 限制（核心数）
  --memory 512 \     # 内存限制（MB）
  --timeout 120 \    # 超时秒数
  --priority 5       # 优先级，数字越小越优先（默认 10）
```

**查看任务列表**：

```bash
uv run spark-swarm tasks

# 按状态过滤
uv run spark-swarm tasks --status PENDING
uv run spark-swarm tasks --status RUNNING
uv run spark-swarm tasks --status DONE
```

**查看任务详情**：

```bash
uv run spark-swarm status <task-id>
```

**查看任务日志**：

```bash
uv run spark-swarm logs <task-id>
```

**取消任务**（仅支持 `PENDING` 状态的任务）：

```bash
uv run spark-swarm cancel <task-id>
```

**查看主机列表**：

```bash
uv run spark-swarm hosts
```

#### 使用 curl / HTTP API

提交任务：

```bash
curl -X POST http://<master-ip>:8000/api/v1/tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "demo",
    "dockerfile_content": "FROM busybox\nCMD echo hello\n",
    "priority": 10,
    "cpu_limit": 1.0,
    "memory_limit_mb": 128,
    "timeout_seconds": 30
  }'
```

查询任务列表：

```bash
curl http://<master-ip>:8000/api/v1/tasks
curl http://<master-ip>:8000/api/v1/tasks?status=PENDING
```

查询任务详情：

```bash
curl http://<master-ip>:8000/api/v1/tasks/<task-id>
```

取消任务：

```bash
curl -X DELETE http://<master-ip>:8000/api/v1/tasks/<task-id>
```

查看主机：

```bash
curl http://<master-ip>:8000/api/v1/hosts
```

---

### 任务 Dockerfile 注意事项

当前版本提交的是 Dockerfile 文本，**不支持上传完整的构建上下文**。这意味着：

- `Dockerfile` 中的 `COPY . .`、`ADD <本地文件>` 等指令会因构建上下文缺失而失败
- 适合当前版本的任务是自包含的，不依赖本地文件

推荐的 Dockerfile 示例：

```dockerfile
FROM busybox
CMD sh -c 'echo hello > /output/result.txt && echo done'
```

容器写入 `/output` 目录的文件，会被挂载到 worker 机器的 `<output_dir>/<task-id>/` 下保存，并在任务结束后上传到 master。

---

### 查看任务产物

任务产物文件会先保存在**执行该任务的 agent 机器**上：

```
<SPARK_SWARM_AGENT_OUTPUT_DIR>/<task-id>/
```

默认路径示例：

```bash
ls ./agent-output/<task-id>/
```

任务结束后，agent 会把 `/output` 下的文件内容上传给 master。通过任务详情可以查看产物列表和下载地址：

```bash
curl http://<master-ip>:8000/api/v1/tasks/<task-id>
```

响应中的关键字段：

- `output_files`：产物相对路径列表
- `artifact_urls`：可直接下载的 master API 路径

下载示例：

```bash
curl -o result.txt \
  http://<master-ip>:8000/api/v1/tasks/<task-id>/artifacts/result.txt
```

注意：当前 artifact 通过 JSON base64 回传，适合图片、日志、报告等中小文件；不要用它传输模型权重或超大数据集。

---

### 任务状态流转

```
PENDING → SCHEDULED → BUILDING → RUNNING → SUCCESS
                                          → FAILED
                                          → CANCELLED
         ↑ (agent 离线时自动退回)
```

- `PENDING`：已提交，等待调度
- `SCHEDULED`：已分配给某台 agent，等待执行
- `BUILDING`：agent 正在执行 `docker build`
- `RUNNING`：agent 正在执行容器
- `SUCCESS`：执行成功（exit code 0）
- `FAILED`：执行失败
- `CANCELLED`：任务已取消

当 agent 超过 `SPARK_SWARM_HEARTBEAT_TIMEOUT_SECONDS`（默认 15 秒）未发送心跳，master 会将其标记为 `OFFLINE`，并把该 agent 上处于 `SCHEDULED`/`BUILDING`/`RUNNING` 的任务退回 `PENDING`，等待重新调度。

---

### 典型多机部署流程

```bash
# 1. 在 master 机器上安装依赖并启动 master
uv sync
uv run uvicorn master.main:app --host 0.0.0.0 --port 8000

# 2. 在每台 worker 机器上安装依赖并启动 agent（分别执行）
uv sync
SPARK_SWARM_AGENT_MASTER_URL=http://192.168.5.100:8000 \
SPARK_SWARM_AGENT_HOSTNAME=worker-01 \
uv run python -m agent.main

# 3. 在 master 机器上确认 agent 已上线
curl http://127.0.0.1:8000/api/v1/hosts

# 4. 提交任务
uv run spark-swarm submit ./Dockerfile --name my-task

# 5. 轮询任务状态直到完成
uv run spark-swarm status <task-id>

# 6. 查看日志
uv run spark-swarm logs <task-id>
```

---

### Text-to-Image Swarm Studio

本仓库包含一个基于 spark-swarm 的文本生成图片案例，代码位于 `app/image_generation_case/`。它会把用户 prompt 拆成多张图片任务，通过 master 分发给多个 agent，下载 artifact 并生成结果集，也支持本地串行 baseline 对比。

启动前建议给 GPU worker 配置模型缓存和 artifact 上限：

```bash
SPARK_SWARM_AGENT_MASTER_URL=http://<master-ip>:8000 \
SPARK_SWARM_AGENT_HOSTNAME=gpu-worker-01 \
SPARK_SWARM_AGENT_ENABLE_GPU=true \
SPARK_SWARM_AGENT_MODEL_CACHE_DIR=/var/lib/spark-swarm/model-cache \
SPARK_SWARM_AGENT_MAX_ARTIFACT_BYTES=104857600 \
uv run python -m agent.main
```

启动案例 UI：

```bash
IMAGE_CASE_MASTER_URL=http://<master-ip>:8000 \
uv run image-generation-case-ui
```

默认访问：

```text
http://127.0.0.1:3100
```

也可以用 CLI 提交批量生成任务：

```bash
uv run image-generation-case submit \
  --master-url http://<master-ip>:8000 \
  --prompt "a compact espresso maker photographed for a premium launch" \
  --image-count 12 \
  --wait
```

更多运行、验证和 benchmark 步骤见 `app/image_generation_case/README.md`。

---

### 典型本地单机启动流程

```bash
uv sync --extra test
uv run uvicorn master.main:app --host 127.0.0.1 --port 8000 --reload &
uv run python -m agent.main &
uv run spark-swarm submit ./Dockerfile --name demo-task
```

---

### 常见问题

**远程 agent 连不上 master**
- 确认 master 使用 `--host 0.0.0.0` 启动
- 确认防火墙放行了 `8000` 端口
- 确认 `SPARK_SWARM_AGENT_MASTER_URL` 地址正确

**agent 能心跳，但任务执行失败**
- 确认 worker 机器上 Docker 已启动：`docker info`
- 确认当前用户有 Docker 权限：`docker ps`
- 确认 Dockerfile 不依赖本地构建上下文文件

**agent 重启后变成新主机**
- `SPARK_SWARM_AGENT_HOST_ID_FILE` 指向的文件丢失时会重新注册
- 将该文件路径设置到持久化目录，例如 `/var/lib/spark-swarm/agent-id`

**CLI 在非 master 机器上无法连接**
- 使用 `--master-url http://<master-ip>:8000`
- 或设置 `SPARK_SWARM_MASTER_URL=http://<master-ip>:8000`

---

## 常用配置速查

### Master
| 环境变量 | 默认值 |
|---|---|
| `SPARK_SWARM_DATABASE_URL` | `sqlite:///$(pwd)/spark_swarm.db` |
| `SPARK_SWARM_ARTIFACT_DIR` | `$(pwd)/spark_swarm_artifacts` |
| `SPARK_SWARM_SCHEDULER_INTERVAL_SECONDS` | `5` |
| `SPARK_SWARM_HEARTBEAT_TIMEOUT_SECONDS` | `15` |

### Agent
| 环境变量 | 默认值 |
|---|---|
| `SPARK_SWARM_AGENT_MASTER_URL` | `http://127.0.0.1:8000` |
| `SPARK_SWARM_AGENT_POLL_INTERVAL_SECONDS` | `5` |
| `SPARK_SWARM_AGENT_HOSTNAME` | `worker` |
| `SPARK_SWARM_AGENT_HOST_ID_FILE` | `./.spark-swarm-agent-id` |
| `SPARK_SWARM_AGENT_OUTPUT_DIR` | `./agent-output` |
| `SPARK_SWARM_AGENT_ENABLE_GPU` | `false` |
| `SPARK_SWARM_AGENT_MODEL_CACHE_DIR` | 空 |
| `SPARK_SWARM_AGENT_MAX_ARTIFACT_BYTES` | `104857600` |
