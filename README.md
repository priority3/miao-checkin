# miao-checkin

每天通过 GitHub Actions 定时向 `@that_miao_bot` 发送 `/checkin` 完成签到。

## 原理

- Telegram Bot 不能给 Bot 发消息；这里使用 MTProto 用户会话（Telethon）以你的账号身份发送消息。
- GitHub Actions 无法交互输入验证码；需要先在本地生成 `TG_STRING_SESSION`，再放到 GitHub Secrets。

## 使用流程（推荐）

### 1) 获取 Telegram API（`api_id` / `api_hash`）

1. 打开 [my.telegram.org](https://my.telegram.org)
2. 登录手机号
3. 创建应用并记录：
   - `api_id`
   - `api_hash`

### 2) 本地导出 `TG_STRING_SESSION`（首次/失效时）

创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`，先填这 3 项（仅用于导出 session）：

```dotenv
TG_API_ID=123456
TG_API_HASH=your_api_hash
TG_PHONE=+8613800000000
```

导出字符串会话（会提示输入验证码/2FA）：

```bash
python checkin.py --export-string-session
```

复制输出的字符串，并在 GitHub 仓库中创建 Secret：`TG_STRING_SESSION`。

### 3) 配置 GitHub Secrets / Variables

GitHub 仓库：Settings -> Secrets and variables -> Actions

Secrets（必填）：
- `TG_API_ID`
- `TG_API_HASH`
- `TG_STRING_SESSION`

Variables（可选，不填走默认值）：
- `TG_TARGET_BOT`（默认 `that_miao_bot`）
- `TG_CHECKIN_COMMAND`（默认 `/checkin`）

### 4) 定时执行（GitHub Actions）

工作流文件：`.github/workflows/checkin.yml`

当前 cron（UTC）：

```yaml
cron: "5 1 * * *"
```

说明：
- GitHub Actions 的 cron 使用 **UTC**。
- UTC `01:05` = 北京时间 `09:05`（UTC+8）。
- GitHub schedule 属于 best-effort，可能延迟几分钟。

### 5) 验收（建议先做一次）

在 GitHub Actions 页面手动触发 `Miao Checkin`（`workflow_dispatch`），然后到 Telegram 查看 `@that_miao_bot` 回复确认签到成功。

## 本地验证签到（可选）

把 `TG_STRING_SESSION` 写入 `.env` 后，直接运行：

```bash
python checkin.py
```

## 常见问题

### 1) Session 失效 / Actions 报未授权

1. 本地重新运行 `python checkin.py --export-string-session`
2. 更新 GitHub Secret `TG_STRING_SESSION`

### 2) Bot 不回 / 不接受消息

先在 Telegram 里打开与 `@that_miao_bot` 的对话并手动发一次消息，确保账号允许向其发送消息，然后再跑脚本/工作流。

## 安全提示

- `.env` 已被 `.gitignore` 忽略，不应提交到仓库。
- `TG_STRING_SESSION` 等同于登录态，请当作密码级别的 Secret 管理。
