# Master 部署与使用

本文档说明 `spark-swarm` 中 `master` 端的职责、部署方式、运行参数和日常使用方式。

## 1. 作用说明

`master` 是调度中心，负责：

- 提供任务提交、查询、取消、主机查询等 HTTP API
- 接收各个 `agent` 的心跳和资源上报
- 根据可用资源为待执行任务分配主机
- 监控主机心跳超时，将离线主机上的任务重新入队
- 使用 SQLite 持久化任务和主机状态

代码入口位于 `master/main.py`。

## 2. 运行前提

部署 `master` 的机器需要具备：

- Python `3.11+`
- `uv`
- 能被各个 `agent` 访问到的网络地址

> `master` 本身不直接执行容器任务；Docker 主要由 `agent` 所在主机使用。

## 3. 安装依赖

在项目根目录执行：

```bash
uv sync --extra test
```

依赖定义位于 `pyproject.toml`。

## 4. 启动方式

### 本机开发启动

```bash
uv run uvicorn master.main:app --reload
```

默认监听 `127.0.0.1:8000`。

### 局域网/远程部署启动

如果需要让其他机器上的 `agent` 访问，必须监听非本地回环地址：

```bash
uv run uvicorn master.main:app --host 0.0.0.0 --port 8000
```

启动后可检查：

```bash
curl http://127.0.0.1:8000/healthz
```

如果是远程机器访问，请改为：

```bash
curl http://<master-ip>:8000/healthz
```

## 5. 配置项

`master` 使用环境变量前缀 `SPARK_SWARM_`。

### 当前支持的配置

- `SPARK_SWARM_APP_NAME`
  - 默认值：`spark-swarm-master`
- `SPARK_SWARM_API_PREFIX`
  - 默认值：`/api/v1`
- `SPARK_SWARM_DATABASE_URL`
  - 默认值：`sqlite:///$(pwd)/spark_swarm.db`
- `SPARK_SWARM_SCHEDULER_INTERVAL_SECONDS`
  - 默认值：`5`
- `SPARK_SWARM_HEARTBEAT_INTERVAL_SECONDS`
  - 默认值：`5`
- `SPARK_SWARM_HEARTBEAT_TIMEOUT_SECONDS`
  - 默认值：`15`

示例：

```bash
export SPARK_SWARM_DATABASE_URL=sqlite:////data/spark-swarm/spark_swarm.db
export SPARK_SWARM_HEARTBEAT_TIMEOUT_SECONDS=20
uv run uvicorn master.main:app --host 0.0.0.0 --port 8000
```

## 6. 数据文件

默认情况下，SQLite 数据库保存在当前工作目录：

- `spark_swarm.db`

如果你用 `systemd` 或容器部署，请确保：

- 工作目录固定
- 或者显式设置 `SPARK_SWARM_DATABASE_URL`
- 数据目录对运行用户可写

## 7. 对外 API

### 用户侧 API

- `POST /api/v1/tasks`
  - 提交任务
- `GET /api/v1/tasks`
  - 查询任务列表，可用 `?status=` 过滤
- `GET /api/v1/tasks/{task_id}`
  - 查询任务详情、日志、退出码、输出文件列表
- `DELETE /api/v1/tasks/{task_id}`
  - 取消任务，仅支持取消 `PENDING` 状态任务
- `GET /api/v1/hosts`
  - 查看所有主机状态

### Agent 侧 API

- `POST /api/v1/agent/heartbeat`
  - `agent` 上报心跳和资源快照，响应中可能携带待执行任务
- `PUT /api/v1/agent/tasks/{task_id}/status`
  - `agent` 上报状态，如 `BUILDING` / `RUNNING`
- `PUT /api/v1/agent/tasks/{task_id}/result`
  - `agent` 上报最终结果

### 健康检查

- `GET /healthz`

返回：

```json
{"ok": true}
```

## 8. 调度与离线处理

当前实现中：

- `master` 后台循环默认每 `5` 秒运行一次
- 会执行主机健康检查和待调度任务扫描
- 主机超过 `heartbeat_timeout_seconds` 未上报心跳，会被标记为 `OFFLINE`
- `OFFLINE` 主机上处于 `SCHEDULED` / `BUILDING` / `RUNNING` 的任务会被退回 `PENDING`

这意味着：

- `agent` 异常退出后，任务不会永久卡死
- 任务可在其他在线主机上被重新分配

## 9. 提交与查询任务

当前仓库自带 CLI，但要注意：CLI 中的 `master` 地址目前写死为：

- `http://127.0.0.1:8000`

因此当前版本中，最稳妥的使用方式是：

- 在 `master` 所在机器上运行 CLI
- 或者直接使用 HTTP API / `curl`

### 使用 CLI

提交任务：

```bash
uv run spark-swarm submit ./Dockerfile --name demo
```

查看任务：

```bash
uv run spark-swarm tasks
```

查看某个任务：

```bash
uv run spark-swarm status <task_id>
```

查看日志：

```bash
uv run spark-swarm logs <task_id>
```

查看主机：

```bash
uv run spark-swarm hosts
```

取消任务：

```bash
uv run spark-swarm cancel <task_id>
```

### 使用 curl 提交任务

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks \
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

查看主机：

```bash
curl http://127.0.0.1:8000/api/v1/hosts
```

## 10. 任务结果说明

`master` 保存并返回以下结果字段：

- `status`
- `stdout_log`
- `stderr_log`
- `exit_code`
- `error_message`
- `output_files`

要注意：

- `output_files` 目前只保存文件名列表
- 产物文件本体保留在执行该任务的 `agent` 主机上
- `master` 当前不提供产物文件下载接口

## 11. systemd 部署示例

如果你希望 `master` 常驻运行，可在 Linux 上使用 `systemd`。

示例文件 `/etc/systemd/system/spark-swarm-master.service`：

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

启用命令：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now spark-swarm-master
sudo systemctl status spark-swarm-master
```

## 12. 常见问题

### 1）远程 `agent` 连不上 `master`

检查：

- `master` 是否用 `--host 0.0.0.0` 启动
- 防火墙是否放行 `8000`
- `agent` 配置中的 `SPARK_SWARM_AGENT_MASTER_URL` 是否正确

### 2）CLI 在其他机器上连不到 `master`

当前 CLI 地址写死为 `127.0.0.1:8000`，所以：

- 要么在 `master` 机器本地执行 CLI
- 要么直接调用 HTTP API
- 要么修改 `cli/main.py` 让它支持环境变量配置

### 3）任务已经完成，但看不到产物文件

当前设计中：

- 产物文件写入执行机的本地目录
- `master` 只记录文件名列表，不保存文件内容

请到对应 `agent` 主机的输出目录查看。

## 13. 当前实现限制

当前版本是一个可运行原型，使用时需要注意：

- 提交的是 `Dockerfile` 文本，不是完整构建上下文
- 如果 `Dockerfile` 依赖 `COPY . .`、`ADD` 本地文件等，远程构建会失败
- CLI 不支持通过环境变量修改 `master` 地址
- `master` 不存储任务产物文件本体，只存元信息
