# Agent 部署与使用

本文档说明 `spark-swarm` 中 `agent` 端的职责、部署方式、运行参数和执行结果保存方式。

## 1. 作用说明

`agent` 运行在工作机上，负责：

- 定期向 `master` 上报心跳和机器资源
- 从 `master` 拉取已调度到本机的任务
- 使用 Docker 构建镜像并运行容器
- 收集执行日志、退出码和产物文件列表
- 将执行结果回传给 `master`

代码入口位于 `agent/main.py`。

## 2. 运行前提

每台部署 `agent` 的机器需要具备：

- Python `3.11+`
- `uv`
- Docker Engine
- 运行 `agent` 的用户有权限访问 Docker
- 可以访问 `master` 的 HTTP 地址，例如 `http://<master-ip>:8000`

如果 Docker 不可用，任务执行会失败。

## 3. 安装依赖

在每台 worker 机器上准备项目代码后，进入项目根目录执行：

```bash
uv sync
```

如果你也要在 worker 上跑测试，可使用：

```bash
uv sync --extra test
```

## 4. 启动方式

### 最小启动命令

```bash
SPARK_SWARM_AGENT_MASTER_URL=http://<master-ip>:8000 uv run python -m agent.main
```

### 指定主机名启动

建议为每台 worker 设置唯一的 `hostname`：

```bash
SPARK_SWARM_AGENT_MASTER_URL=http://<master-ip>:8000 \
SPARK_SWARM_AGENT_HOSTNAME=worker-01 \
uv run python -m agent.main
```

### 单次调试运行

如果只想运行固定轮次，便于调试：

```bash
SPARK_SWARM_AGENT_MASTER_URL=http://<master-ip>:8000 \
uv run python -m agent.main --iterations 1
```

`--iterations` 参数定义在 `agent/main.py`。

## 5. 配置项

`agent` 使用环境变量前缀 `SPARK_SWARM_AGENT_`。

### 当前支持的配置

- `SPARK_SWARM_AGENT_MASTER_URL`
  - 默认值：`http://127.0.0.1:8000`
- `SPARK_SWARM_AGENT_POLL_INTERVAL_SECONDS`
  - 默认值：`5`
- `SPARK_SWARM_AGENT_HOSTNAME`
  - 默认值：`worker`
- `SPARK_SWARM_AGENT_IP_ADDRESS`
  - 默认值：`127.0.0.1`
- `SPARK_SWARM_AGENT_HOST_ID_FILE`
  - 默认值：`./.spark-swarm-agent-id`
- `SPARK_SWARM_AGENT_OUTPUT_DIR`
  - 默认值：`./agent-output`

示例：

```bash
export SPARK_SWARM_AGENT_MASTER_URL=http://192.168.5.100:8000
export SPARK_SWARM_AGENT_HOSTNAME=worker-03
export SPARK_SWARM_AGENT_OUTPUT_DIR=/data/spark-swarm/agent-output
uv run python -m agent.main
```

## 6. Agent 主循环

`agent` 默认会一直循环执行以下步骤：

1. 采集当前主机资源
2. 向 `master` 发送心跳
3. 如果心跳响应中包含任务，则开始执行
4. 上报 `BUILDING` 状态
5. 用 Docker SDK 构建镜像
6. 运行容器
7. 收集标准输出、标准错误、退出码和产物文件列表
8. 向 `master` 上报最终结果
9. 休眠 `poll_interval_seconds` 后继续下一轮

## 7. 任务执行方式

当前实现中：

- `master` 下发的是 `Dockerfile` 文本
- `agent` 会构造一个只包含 `Dockerfile` 的临时 build context
- 然后在本机 Docker 上执行 `build` 和 `run`

这带来一个重要限制：

- 当前任务不支持上传完整源码目录
- `Dockerfile` 中如果依赖 `COPY . .`、`ADD` 本地文件等，会因构建上下文缺失而失败

适合当前版本的任务示例：

```Dockerfile
FROM busybox
CMD sh -c 'echo hello > /output/result.txt && echo done'
```

## 8. 执行结果如何保存在 worker 上

`agent` 启动容器时，会把本机输出目录挂载到容器的 `/output`：

- 宿主机目录：`<output_dir>/<task_id>`
- 容器内目录：`/output`

因此：

- 容器只要把文件写入 `/output`
- 执行该任务的 worker 主机本地就能直接拿到这些文件

例如容器内写入：

```sh
echo result > /output/result.txt
```

则 worker 本地会出现：

```text
<output_dir>/<task_id>/result.txt
```

默认 `output_dir` 为：

- `./agent-output`

## 9. 回传给 master 的结果

任务执行完成后，`agent` 会把以下信息上传给 `master`：

- `status`
- `stdout_log`
- `stderr_log`
- `exit_code`
- `error_message`
- `output_files`

要注意：

- `output_files` 只是产物文件的相对路径列表
- 文件内容本体不会上传到 `master`
- 如果要拿到产物文件，请到实际执行该任务的 worker 机器查看

## 10. 如何验证 agent 已接入

### 查看 `master` 健康接口

先确认 `master` 可访问：

```bash
curl http://<master-ip>:8000/healthz
```

### 查看主机列表

在 `master` 机器或任何能访问 `master` 的机器上执行：

```bash
curl http://<master-ip>:8000/api/v1/hosts
```

如果 `agent` 已成功接入，应能看到：

- `hostname`
- `ip_address`
- `status=ONLINE`
- `last_heartbeat`
- 当前资源数据

## 11. 多台机器部署建议

每台 worker 建议：

- 设置唯一 `SPARK_SWARM_AGENT_HOSTNAME`
- 使用独立的数据目录保存 `host_id` 和产物
- 确保本机 Docker 正常工作

例如：

```bash
export SPARK_SWARM_AGENT_MASTER_URL=http://192.168.5.100:8000
export SPARK_SWARM_AGENT_HOSTNAME=worker-05
export SPARK_SWARM_AGENT_HOST_ID_FILE=/var/lib/spark-swarm/agent-id
export SPARK_SWARM_AGENT_OUTPUT_DIR=/var/lib/spark-swarm/output
uv run python -m agent.main
```

这样重启后仍可复用同一个 `host_id`。

## 12. systemd 部署示例

建议在每台 worker 上用 `systemd` 常驻运行 `agent`。

示例文件 `/etc/systemd/system/spark-swarm-agent.service`：

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

启用命令：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now spark-swarm-agent
sudo systemctl status spark-swarm-agent
```

## 13. 使用示例

### 1）启动 `agent`

```bash
SPARK_SWARM_AGENT_MASTER_URL=http://192.168.5.100:8000 \
SPARK_SWARM_AGENT_HOSTNAME=worker-01 \
uv run python -m agent.main
```

### 2）在 `master` 上提交任务

```bash
uv run spark-swarm submit ./Dockerfile --name demo
```

### 3）查看任务状态

```bash
uv run spark-swarm status <task_id>
```

### 4）查看任务产物

到实际执行该任务的 worker 上查看：

```bash
ls -R ./agent-output/<task_id>
```

如果你自定义了输出目录，请改用对应目录。

## 14. 常见问题

### 1）`agent` 启动后看不到主机注册

检查：

- `SPARK_SWARM_AGENT_MASTER_URL` 是否正确
- `master` 是否监听了 `0.0.0.0`
- worker 到 `master:8000` 的网络是否畅通
- 防火墙是否阻断了访问

### 2）`agent` 能心跳，但任务执行失败

检查：

- worker 上 Docker 是否已启动
- 当前用户是否有 Docker 权限
- `Dockerfile` 是否依赖本地构建上下文文件

### 3）任务完成了，但 `master` 上没有文件内容

这是当前实现的预期行为：

- `master` 只保存日志、退出码和产物文件列表
- 文件本体留在执行任务的 worker 上

### 4）worker 重启后变成新主机

检查 `SPARK_SWARM_AGENT_HOST_ID_FILE`：

- 如果该文件丢失，`agent` 会重新注册为新的主机记录
- 建议把它放在持久化目录中

## 15. 当前实现限制

当前版本的 `agent` 使用时需要注意：

- 不支持完整构建上下文上传
- 不支持把产物文件内容自动同步到 `master`
- 不支持并发执行多个任务的 worker 容量控制细化配置
- 任务执行依赖本机 Docker 环境，未内置容器沙箱隔离增强能力
