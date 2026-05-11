# scheduled-bot-message

通过 Telegram 用户会话，定时向指定 Bot 发送指定文案。当前默认任务是每天给 `@gopay1232bot` 发送 `/checkin`。

## 原理

- Telegram Bot 通常不能主动给另一个 Bot 发消息；这里使用 MTProto 用户会话（Telethon）以你的账号身份发送消息。
- GitHub Actions 无法交互输入验证码；需要先在本地生成 `TG_STRING_SESSION`，再放到 GitHub Secrets。
- 定时由 GitHub Actions 的 `schedule` 或手动触发的 `workflow_dispatch` 执行。

## 使用流程

### 1. 获取 Telegram API

1. 打开 [my.telegram.org](https://my.telegram.org)
2. 登录手机号
3. 创建应用并记录：
   - `api_id`
   - `api_hash`

### 2. 本地导出 `TG_STRING_SESSION`

创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

编辑 `.env`，先填这几项：

```dotenv
TG_API_ID=123456
TG_API_HASH=your_api_hash
TG_PHONE=+8613800000000
TG_TARGET_BOT=gopay1232bot
TG_MESSAGE_TEXT=/checkin
```

导出字符串会话（会提示输入验证码/2FA）：

```bash
python bot_message.py --export-string-session
```

复制输出的字符串，并在 GitHub 仓库中创建 Secret：`TG_STRING_SESSION`。

### 3. 配置 GitHub Secrets / Variables

GitHub 仓库：Settings -> Secrets and variables -> Actions

Secrets（必填）：
- `TG_API_ID`
- `TG_API_HASH`
- `TG_STRING_SESSION`

Secrets（可选）：
- `PUSHPLUS_TOKEN`：PushPlus 推送 token，填写后会把发送结果和 Bot 最新回复推送到微信（[获取 token](http://www.pushplus.plus/)）

Variables（可选，不填则使用当前默认签到任务）：
- `TG_TARGET_BOT`：目标 Bot 用户名，默认 `gopay1232bot`
- `TG_MESSAGE_TEXT`：要发送的文案，默认 `/checkin`

Variables（可选）：
- `TG_SESSION_NAME`：本地 session 文件名，默认 `scheduled_bot_message`

> 兼容说明：旧变量 `TG_CHECKIN_COMMAND` 仍可作为 `TG_MESSAGE_TEXT` 的 fallback，但新配置建议统一使用 `TG_MESSAGE_TEXT`。

### 4. 定时执行

工作流文件：`.github/workflows/scheduled-bot-message.yml`

已开启每日定时任务：

```yaml
schedule:
  - cron: "5 1 * * *"
```

说明：
- GitHub Actions 的 cron 使用 UTC。
- UTC `01:05` = 北京时间 `09:05`（UTC+8）。
- GitHub schedule 属于 best-effort，可能延迟几分钟。

### 5. 手动验证

在 GitHub Actions 页面手动触发 `Scheduled Bot Message`，默认会给 `@gopay1232bot` 发送 `/checkin`。也可以临时填写：
- `target_bot`
- `message_text`

不填写时会使用仓库 Variables 里的 `TG_TARGET_BOT` 和 `TG_MESSAGE_TEXT`。

## 本地运行

把 `TG_STRING_SESSION` 写入 `.env` 后，直接发送一次：

```bash
python bot_message.py
```

仅打印将要发送的目标和内容，不真正发送：

```bash
python bot_message.py --dry-run
```

覆盖目标和文案：

```bash
python bot_message.py --target gopay1232bot --message "/checkin"
```

本地常驻，每天按指定时区发送：

```bash
python bot_message.py --daily-at 09:05 --timezone Asia/Shanghai
```

## 常见问题

### Session 失效 / Actions 报未授权

1. 本地重新运行 `python bot_message.py --export-string-session`
2. 更新 GitHub Secret `TG_STRING_SESSION`

### Bot 不回 / 不接受消息

先在 Telegram 里打开与目标 Bot 的对话并手动发一次消息，确保账号允许向其发送消息，然后再跑脚本或工作流。

## 安全提示

- `.env` 已被 `.gitignore` 忽略，不应提交到仓库。
- `TG_STRING_SESSION` 等同于登录态，请当作密码级别的 Secret 管理。
