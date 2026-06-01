# 藏红曲销售日报云端自动化 — 部署指南

## 概述

每天晚上 21:00，GitHub Actions 自动运行 Python 脚本，读取腾讯文档中的两张表格，分析四位销售人员的数据，通过 PushPlus 推送到你的微信。

> 电脑关机也能执行 — 全程在 GitHub 云端运行。

---

## 认证方式选择

有两种认证方式可选：

| 方式 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **直接模式** | 无需 OAuth 注册，即刻可用 | Token 约30天过期需手动更新 | 快速上手、临时使用 |
| **OAuth 模式** | Refresh Token 有效期 1 年，自动刷新 | 需注册开放平台应用 | 长期稳定运行 |

当前已配置**直接模式**，后续可升级到 OAuth 模式。

---

## 直接模式部署（当前方案，仅需 4 步）

### 第一步：创建 GitHub 仓库并推送代码

```bash
# 在项目根目录 (WorkBuddy/2026-06-01-task-20/) 执行:

git init
git add cloud-automation/ .github/
git commit -m "藏红曲销售日报自动化"

# 在 GitHub 上创建新仓库，然后:
git remote add origin https://github.com/你的用户名/仓库名.git
git branch -M main
git push -u origin main
```

### 第二步：配置 GitHub Secrets

在 GitHub 仓库页面: **Settings → Secrets and variables → Actions → New repository secret**

添加以下 **4 个** Secrets:

| Secret 名称 | 值 |
|-------------|-----|
| `TENCENT_ACCESS_TOKEN` | `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...` (你的 JWT access_token) |
| `TENCENT_OPEN_ID` | `5fe0d89849d04569b18c0aefac842be9` |
| `TENCENT_CLIENT_ID` | `6cb5d909f1674bc18663b5362d38fbf7` |
| `PUSHPLUS_TOKEN` | `bdf1d66a49e346cd95c946ef9a131e5f` |

### 第三步：测试运行

1. 在 GitHub 仓库页面 → **Actions** 标签
2. 选择「藏红曲销售团队每日总结」workflow
3. 点击 **Run workflow** → **Run workflow**
4. 等待运行完成，检查微信是否收到推送

### 第四步：确认自动化运行

- 定时任务配置为**北京时间每晚 21:00** 自动执行
- 可在 Actions 页面查看每次执行日志

### Token 过期处理

当前 access_token 有效期约 30 天（至 2026-07-01 左右）。过期后需要：
1. 获取新的 access_token（通过 WorkBuddy 腾讯文档连接器自动获取）
2. 更新 GitHub Secrets 中的 `TENCENT_ACCESS_TOKEN`

---

## OAuth 模式部署（可选，长期稳定方案）
