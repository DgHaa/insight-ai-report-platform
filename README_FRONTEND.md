# 服务部AI洞察平台 — 前端

基于 **React 18 + TypeScript + Ant Design 5 + Zustand + React Router v6 + Axios + Vite** 实现的完整前端。

## 一、目录结构

```
frontend/
├── package.json / tsconfig.json / vite.config.ts / index.html
└── src/
    ├── main.tsx                # 入口（挂载 App）
    ├── App.tsx                 # 路由注册 + ConfigProvider（浅色/深色主题）
    ├── index.css               # 全局样式（AIHOT 信息流风格）
    ├── api/
    │   ├── http.ts             # ★ axios 封装：JWT注入 / 统一错误 / 401跳转 / 文件下载
    │   ├── auth.ts / reports.ts / credentials.ts / system.ts
    ├── store/
    │   ├── auth.ts             # ★ Zustand：token + user（持久化）
    │   └── theme.ts            # 主题模式（持久化）
    ├── types/index.ts          # 全部接口类型定义
    ├── utils/format.ts         # 时间格式化 + WebSocket 地址构建
    ├── components/
    │   ├── ProtectedRoute.tsx  # 路由级权限守卫（角色）
    │   ├── PermGuard.tsx       # 组件级权限显隐
    │   ├── GenerationProgress.tsx  # ★ WebSocket 生成进度条
    │   ├── MarkdownView.tsx    # Markdown→HTML（GFM + 代码高亮）
    │   ├── ReportCard.tsx      # AIHOT 信息流报告卡片
    │   ├── CronEditor.tsx      # Cron 表达式生成器
    │   ├── DiffView.tsx        # 版本对比（LCS 行级 Diff）
    │   ├── Charts.tsx          # 纯 SVG 图表（折线/环形/排行/环形进度）
    │   └── ConfirmDialog.tsx   # 通用确认对话框
    ├── layouts/MainLayout.tsx  # 顶栏 + 侧边栏（角色菜单）+ 主题切换
    └── pages/
        ├── Login.tsx
        ├── reports/ReportList.tsx        # 多视图报告列表
        ├── reports/ReportCreate.tsx      # 三步定制向导
        ├── reports/ModuleFormModal.tsx   # 模块完整配置弹窗
        ├── reports/ReportDetail.tsx      # 报告详情（进度/版本/对比/导出/邮件）
        ├── department/DepartmentManage.tsx  # 统计看板 + 用户管理 + 公共模型配置
        ├── admin/SystemAdmin.tsx         # 白名单 + SMTP/并发配置 + 全部报告
        └── profile/Profile.tsx           # 数据源凭证 + 个人信息 + 主题
```

## 二、启动方式

```bash
cd frontend
npm install          # 或 pnpm install / yarn

# 开发模式（Vite 代理 /api 到后端 :8000）
npm run dev          # http://localhost:3000

# 生产构建
npm run build        # 产物输出到 dist/
npm run preview
```

后端需先启动（`uvicorn app.main:app --port 8000`），并确保已执行迁移与种子数据：
`admin / Admin@2026` 登录。

## 三、环境变量（frontend/.env）

| 变量 | 说明 | 默认 |
|------|------|------|
| VITE_API_BASE | 后端 API 基础路径 | /api/v1（开发走 Vite 代理） |

## 四、路由与权限矩阵

| 路由 | 页面 | 权限 |
|------|------|------|
| /login | 登录 | 公开 |
| /reports | 报告列表（my/department/public/all） | 登录用户（all 仅超管） |
| /reports/create | 报告定制 | 登录用户（部门报告需管理员） |
| /reports/:id/edit | 报告编辑 | 管理员 |
| /reports/:id | 报告详情 | 登录用户 |
| /department/manage | 部门管理（看板/用户/公共模型） | 部门管理员/超管 |
| /admin | 系统管理（白名单/SMTP/全部报告） | 超级管理员 |
| /profile | 个人中心（凭证/信息/主题） | 登录用户 |

权限控制双保险：`ProtectedRoute`（路由级，角色不符跳转 /reports）+ `PermGuard`（组件级显隐）。

## 五、关键实现说明

1. **Axios 封装**：请求拦截自动注入 `Authorization: Bearer <token>`；响应拦截解包
   `{code, message, data}`，`code !== 0` 统一 message.error 并 reject；HTTP 401 清空登录态并跳转
   /login；`downloadFile` 处理导出文件流（解析 Content-Disposition 文件名）。
2. **Zustand**：`auth`（token/user 持久化到 localStorage）、`theme`（浅色/深色持久化），
   配合 antd `ConfigProvider` 的 `darkAlgorithm/defaultAlgorithm` 实现主题切换。
3. **WebSocket 进度**：`GenerationProgress` 在触发生成后连接
   `ws://host/api/v1/reports/{id}/generate/progress?token=JWT`，实时更新 `init→fetching→
   building→generating→storing→complete` 阶段进度条；complete 后自动刷新详情。
4. **报告定制三步向导**：基本信息 → 模块配置（列表 + 完整配置弹窗：模型连接测试、
   temperature 滑块、关键词标签、Prompt 模板插入、URL 列表、凭证下拉、抓取超时/重试/截断、
   Cron 生成器）→ 预览 JSON + 保存/保存并生成。
5. **版本管理**：时间线切换查看 + 回滚确认；Diff 弹窗选两个版本，LCS 行级对比（绿增红删）。
6. **图表零依赖**：`Charts.tsx` 用纯 SVG 实现折线/环形/排行/环形进度，无需额外图表库。

## 六、注意事项

- 开发时 WebSocket 通过 Vite `/api` 代理（`ws: true`）转发到后端；
- 后端已增加 CORS 中间件（`allow_origins=["*"]`），生产环境建议收紧；
- 部门「公共模型配置」后端接口待扩展，当前暂存 localStorage（页面已注明）；
- 默认账号 `admin / Admin@2026`（种子数据）。
