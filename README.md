# Insight AI Report Platform

基于 FastAPI + React/TypeScript 的 AI 报告生成平台。支持多模块报告编排、报告级共享资料池、相关性筛选与 KRI 异常分析（趋势 / 门店 / 仓库 / 复盘四大模块）。

## 技术栈

- **后端**：FastAPI + SQLAlchemy(async) + Celery + Alembic，PostgreSQL + Redis
- **前端**：React + TypeScript + Vite + Ant Design
- **模型**：OpenAI 兼容接口（默认 DeepSeek）

## 核心能力

- 多模块报告生成引擎，按 `(url, 凭证id)` 去重抓取并共享资料池
- 抓取内容按模块关键词做相关性筛选后注入 prompt
- KRI 异常分析：trend / offices / stores / retrospective 四大 section

## 快速开始

1. 复制 `.env.example` 为 `.env` 并填入配置（`SECRET_KEY`、数据库、DeepSeek API key 等）
2. 安装依赖：`pip install -r requirements.txt`
3. 启动后端：`uvicorn app.main:app --host 0.0.0.0 --port 8080`

> ⚠️ 注意：`.env` 含敏感凭证，已被 `.gitignore` 排除，**请勿提交**。
