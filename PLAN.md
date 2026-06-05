# Docker 任务分发系统 — 设计方案

## 背景

构建一个集中式 Docker 任务分发系统。用户在 CLI 提交 Dockerfile，调度器将任务分发到 16 台工作主机（192.168.5.10-25）上执行。调度器专职调度，工作主机负责构建镜像并运行容器。系统需支持任务排队、资源感知调度、主机在线检测和结果收集。

## 架构总览

```
                          ┌──────────────────────────────┐
  用户 ──CLI──▶           │        Master (调度器)        │
                          │  - FastAPI REST API          │
                          │  - 任务队列 + 调度引擎        │
                          │  - 主机健康监控              │
                          │  - SQLite 持久化             │
                          └──────┬───────────────────────┘
                                 │  Agent 轮询拉取任务
          ┌──────────────────────┼──────────────────────────┐
          ▼                      ▼                           ▼
   ┌─────────────┐       ┌─────────────┐            ┌─────────────┐
   │ Agent       │       │ Agent       │    ...     │ Agent       │
   │ .5.10       │       │ .5.11       │            │ .5.25       │
   │ Docker SDK  │       │ Docker SDK  │            │ Docker SDK  │
   └─────────────┘       └─────────────┘            └─────────────┘
```

- Master 部署在专用主机上（192.168.5.x 网段内或独立机器）
- Agent 运行在所有 16 台 Worker 上，轮询 Master 获取任务
- 用户通过 CLI 工具向 Master 提交 Dockerfile、查询状态、获取结果

## 通信协议

**Pull 模型**（Agent 轮询）:
- Agent 每 5 秒发送心跳 + 资源快照到 Master
- Master 在心跳响应中携带已分配的任务
- Agent 执行过程中通过 API 报告状态变更
- 完成时通过 API 上报结果（退出码 + 日志 + 输出文件）

优点：Agent 只需要知道 Master 地址，不需要在 Worker 上开放端口，部署最简单。

## 项目结构

```
spark-swarm/
├── pyproject.toml              # 项目配置 (uv/poetry)
├── requirements.txt            # 备选依赖清单
├── README.md
├── master/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 入口, uvicorn 启动
│   ├── config.py               # 配置 (DB路径, 监听地址等)
│   ├── database.py             # SQLAlchemy 引擎 & session
│   ├── models.py               # ORM 模型: Task, Host
│   ├── schemas.py              # Pydantic 请求/响应模型
│   ├── api/
│   │   ├── __init__.py
│   │   ├── tasks.py            # 任务相关端点
│   │   └── hosts.py            # 主机/心跳端点
│   ├── scheduler.py            # 调度逻辑 (资源匹配 + 分配)
│   └── monitor.py              # 心跳超时检测, 离线主机处理
├── agent/
│   ├── __init__.py
│   ├── main.py                 # Agent 主循环 (心跳 + 拉任务)
│   ├── config.py               # Agent 配置
│   ├── executor.py             # Docker 构建 & 运行
│   └── reporter.py             # 状态上报 & 结果上传
├── cli/
│   ├── __init__.py
│   └── main.py                 # CLI 命令 (click/typer)
└── tests/
    ├── test_scheduler.py
    ├── test_api.py
    └── test_agent.py
```

## 数据库设计

### tasks 表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(36) PK | UUID |
| name | VARCHAR(255) | 任务名称 (用户指定) |
| dockerfile_content | TEXT | Dockerfile 内容 |
| status | VARCHAR(20) | PENDING / SCHEDULED / BUILDING / RUNNING / SUCCESS / FAILED / CANCELLED |
| priority | INTEGER | 优先级 (0=最高, 默认10) |
| cpu_limit | FLOAT | 用户请求的 CPU 限制, 可空 |
| memory_limit_mb | INTEGER | 用户请求的内存限制 (MB), 可空 |
| timeout_seconds | INTEGER | 超时时间, 可空 |
| assigned_host_id | VARCHAR(36) FK | 分配的主机 |
| stdout_log | TEXT | 容器标准输出 |
| stderr_log | TEXT | 容器标准错误 |
| exit_code | INTEGER | 容器退出码 |
| error_message | TEXT | 错误信息 (构建失败等) |
| created_at | DATETIME | 创建时间 |
| scheduled_at | DATETIME | 分配时间 |
| started_at | DATETIME | 开始执行时间 |
| completed_at | DATETIME | 完成时间 |

### hosts 表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(36) PK | UUID |
| hostname | VARCHAR(255) | 主机名 |
| ip_address | VARCHAR(45) | IP 地址 |
| status | VARCHAR(20) | ONLINE / OFFLINE |
| cpu_total | INTEGER | CPU 总核心数 |
| cpu_available | FLOAT | 可用 CPU |
| memory_total_mb | INTEGER | 总内存 (MB) |
| memory_available_mb | INTEGER | 可用内存 (MB) |
| disk_total_mb | INTEGER | 总磁盘 (MB) |
| disk_available_mb | INTEGER | 可用磁盘 (MB) |
| last_heartbeat | DATETIME | 最后心跳时间 |
| registered_at | DATETIME | 首次注册时间 |

## 调度算法

1. 新任务到达 → 状态 PENDING，加入队列
2. 调度器定期扫描 PENDING 任务，按 priority ASC + created_at ASC 排序
3. 对每个任务，筛选可用主机：
   - status = ONLINE
   - last_heartbeat 在 15 秒内
   - CPU: cpu_available >= cpu_limit (如指定)
   - Memory: memory_available_mb >= memory_limit_mb (如指定)
4. 选择策略：**Best Fit** — 选出满足条件的主机后，选剩余资源最少的那台（避免碎片化，让大资源主机留给大任务）
5. 分配任务 → SCHEDULED，主机资源乐观扣减
6. Agent 拉取到任务后报告 BUILDING/RUNNING
7. 完成后 Agent 上报结果，主机资源在下次心跳时真实更新

## 主机健康检测

- Agent 每 5 秒发送心跳，携带当前资源快照
- Master 后台任务每 5 秒扫描：last_heartbeat 超过 15 秒 → 标记 OFFLINE
- OFFLINE 主机上的 SCHEDULED/BUILDING/RUNNING 任务 → 回退为 PENDING，等待重新调度
- 主机恢复心跳 → 自动 ONLINE，资源从心跳更新

## API 端点

### 用户侧
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/v1/tasks | 提交 Dockerfile 任务 |
| GET | /api/v1/tasks | 列出任务 (支持 ?status= 过滤) |
| GET | /api/v1/tasks/{id} | 获取任务详情 + 结果 |
| DELETE | /api/v1/tasks/{id} | 取消 PENDING 任务 |
| GET | /api/v1/hosts | 查看主机状态 |

### Agent 侧
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/v1/agent/heartbeat | 心跳 + 资源上报, 响应中携带待执行任务 |
| PUT | /api/v1/agent/tasks/{id}/status | 更新任务状态 |
| PUT | /api/v1/agent/tasks/{id}/result | 上报任务结果 |

## Agent 主循环

```
loop:
    1. 收集本地资源 (psutil: CPU/内存/磁盘)
    2. POST /agent/heartbeat → Master 响应包含已分配任务 (if any)
    3. 如有任务:
       a. PUT status=BUILDING
       b. docker build (Docker SDK)
       c. 如失败 → PUT result (error)
       d. PUT status=RUNNING
       e. docker run (挂载 /output 卷)
       f. 等待容器退出
       g. 收集 logs + exit_code + /output 文件
       h. PUT /agent/tasks/{id}/result
       i. docker rm 清理容器
    4. sleep(5)
```

## CLI 命令

```
spark-swarm submit <dockerfile_path> [--name] [--cpu] [--memory] [--timeout]
spark-swarm status <task_id>
spark-swarm tasks [--status]
spark-swarm hosts
spark-swarm cancel <task_id>
spark-swarm logs <task_id>
```

## 技术栈

- **Web 框架**: FastAPI + uvicorn (异步, 自带 OpenAPI 文档)
- **ORM**: SQLAlchemy 2.0 + SQLite (可后续迁移到 PostgreSQL)
- **容器**: Docker SDK for Python (`docker` 包)
- **CLI**: Typer (基于 Click, 类型提示驱动)
- **系统监控**: psutil (Agent 资源采集)
- **验证**: Pydantic v2 (FastAPI 内置)
- **测试**: pytest + httpx (API 测试)

## 实现顺序

1. **Master 核心** — 数据库模型 + FastAPI 骨架 + 任务 CRUD
2. **Agent 基础** — 心跳 + 资源采集 + Docker 执行
3. **调度引擎** — 任务队列 + 资源匹配 + 自动分配
4. **健康监控** — 心跳超时检测 + 离线/恢复处理
5. **CLI 工具** — submit / status / tasks / hosts / cancel / logs
6. **集成测试** — 端到端流程验证

## 验证方式

1. 启动 Master: `uvicorn master.main:app --host 0.0.0.0 --port 8000`
2. 启动 Agent (多台): `python -m agent.main --master-url http://<master>:8000`
3. CLI 提交任务: `python -m cli.main submit ./test.Dockerfile --cpu 0.5 --memory 128`
4. 观察调度日志, 确认任务完成
5. `python -m cli.main logs <id>` 查看结果
6. 模拟主机离线 (kill agent) → 确认 Master 在 15s 内标记 OFFLINE 且任务回退
