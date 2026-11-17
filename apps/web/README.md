# 智修 V1.2 前端诊断工作台（apps/web）

Next.js 14（App Router）+ React 18 + TypeScript（strict）+ Tailwind CSS 实现的诊断工作台。
前端只通过 HTTP 调用 `services/api`，不直接访问数据库或模型。

## 环境要求

- Node.js 18+
- 后端 API 已启动（默认 `http://localhost:8000`）

## 启动

```bash
cd apps/web
npm install
npm run dev      # http://localhost:3000
```

生产构建：

```bash
npm run build
npm run start
```

`next.config.mjs` 已设置 `output: "standalone"`，构建产物可用于容器化部署。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE` | `http://localhost:8000/api/v1` | 后端 API 前缀 |

在 `apps/web/.env.local` 中覆盖即可，例如：

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8000/api/v1
```

## 页面

| 路由 | 功能 |
| --- | --- |
| `/` | 根据登录态跳转到 `/cases` 或 `/login` |
| `/login` | 登录与注册，成功后保存令牌 |
| `/cases` | 我的案例列表、状态筛选、新建案例 |
| `/cases/[id]` | 案例详情：受理、上传证据、证据账本、候选根因、检查卡片、结果录入与诊断结论 |

## 目录结构

```
apps/web
├─ app/
│  ├─ layout.tsx            全局布局与导航
│  ├─ globals.css           Tailwind 入口
│  ├─ page.tsx              登录态跳转
│  ├─ login/page.tsx        登录/注册
│  ├─ cases/page.tsx        案例列表与创建
│  └─ cases/[id]/page.tsx   案例详情与诊断动作编排
├─ components/
│  ├─ ui.tsx                Button / Card / Badge / ErrorBanner / Spinner
│  ├─ upload-panel.tsx      证据文件上传与列表
│  ├─ evidence-form.tsx     证据登记表单
│  └─ diagnosis-panel.tsx   证据账本、候选根因、检查卡片、结论区
└─ lib/
   ├─ api.ts                令牌管理与全部后端调用
   └─ types.ts              与后端契约一致的类型
```

## 交互约定

- 令牌保存在 `localStorage` 的 `zhixiu_token`。
- 任意接口返回 401 时清除令牌并跳转 `/login`；其他错误以 `code: message` 形式展示，不白屏。
- 候选根因展示的是置信级别（高/中/低），不展示为概率。
- 检查卡片一次只展示一项，录入结果后回到上一循环重新规划。