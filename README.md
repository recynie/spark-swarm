# spark-swarm

基于 FastAPI + Docker SDK 的集中式 Docker 任务分发系统。

## 组件
- Master: 任务接收、调度、主机健康监控
- Agent: 轮询心跳、执行 Docker build/run、结果上报
- CLI: 提交任务、查询状态、查看主机

## 快速开始
```bash
uv sync --extra test
uv run uvicorn master.main:app --reload
```
