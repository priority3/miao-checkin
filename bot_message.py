#!/usr/bin/env python3
import argparse
import asyncio
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

PUSHPLUS_API = "http://www.pushplus.plus/send"
DEFAULT_SESSION_NAME = "scheduled_bot_message"
NOTIFICATION_PREFIX = "scheduled-bot-message"


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    phone: Optional[str]
    session_name: str
    string_session: Optional[str]
    target_bot: Optional[str]
    message_text: Optional[str]
    pushplus_token: Optional[str]


def _get_env(name: str) -> Optional[str]:
    value = os.getenv(name, "").strip()
    return value or None


def _require_env(name: str) -> str:
    value = _get_env(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _parse_api_id(raw: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError("TG_API_ID must be an integer.") from exc


def _read_message_text() -> Optional[str]:
    message_text = _get_env("TG_MESSAGE_TEXT")
    if message_text:
        return message_text

    legacy_checkin_command = _get_env("TG_CHECKIN_COMMAND")
    if legacy_checkin_command:
        return legacy_checkin_command

    return None


def load_config() -> Config:
    load_dotenv()
    api_id = _parse_api_id(_require_env("TG_API_ID"))
    api_hash = _require_env("TG_API_HASH")
    phone = _get_env("TG_PHONE")
    session_name = _get_env("TG_SESSION_NAME") or DEFAULT_SESSION_NAME
    string_session = _get_env("TG_STRING_SESSION")
    target_bot = _get_env("TG_TARGET_BOT")
    message_text = _read_message_text()
    pushplus_token = _get_env("PUSHPLUS_TOKEN")
    return Config(
        api_id=api_id,
        api_hash=api_hash,
        phone=phone,
        session_name=session_name,
        string_session=string_session,
        target_bot=target_bot,
        message_text=message_text,
        pushplus_token=pushplus_token,
    )


def parse_hhmm(raw: str) -> tuple[int, int]:
    if not re.fullmatch(r"\d{2}:\d{2}", raw):
        raise ValueError("Time must use HH:MM format, e.g. 09:30")
    hour, minute = map(int, raw.split(":"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Invalid time. Hour must be 00-23 and minute must be 00-59.")
    return hour, minute


def display_target(target_bot: str) -> str:
    if target_bot.startswith("@") or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,}", target_bot):
        return target_bot
    return f"@{target_bot}"


def print_dry_run(target_bot: str, message_text: str) -> None:
    print(f"[DRY RUN] Would send {message_text!r} to {display_target(target_bot)}")


def build_client(config: Config) -> TelegramClient:
    if config.string_session:
        return TelegramClient(StringSession(config.string_session), config.api_id, config.api_hash)
    return TelegramClient(config.session_name, config.api_id, config.api_hash)


async def ensure_login(client: TelegramClient, phone: Optional[str]) -> None:
    if await client.is_user_authorized():
        return

    if not phone:
        raise RuntimeError(
            "Session is not authorized and TG_PHONE is missing. "
            "Use a valid TG_STRING_SESSION or set TG_PHONE for first-time login."
        )

    if not sys.stdin.isatty():
        raise RuntimeError(
            "Login is required but no TTY is available. Run this script manually once to finish login."
        )

    print("First-time login required.")
    await client.send_code_request(phone)
    code = input("Enter the login code from Telegram: ").strip()
    try:
        await client.sign_in(phone=phone, code=code)
    except SessionPasswordNeededError:
        password = getpass.getpass("Enter your Telegram 2FA password: ")
        await client.sign_in(password=password)
    print("Login successful. Session saved.")


async def send_bot_message(
    client: TelegramClient,
    target_bot: str,
    message_text: str,
    dry_run: bool,
    pushplus_token: Optional[str] = None,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target_display = display_target(target_bot)
    if dry_run:
        print_dry_run(target_bot, message_text)
        return

    await client.send_message(target_bot, message_text)
    print(f"[{now}] Sent {message_text!r} to {target_display}")

    if pushplus_token:
        reply_text = await wait_for_reply(client, target_bot)
        if reply_text:
            title = f"[{NOTIFICATION_PREFIX}] {reply_text}"
        else:
            title = f"[{NOTIFICATION_PREFIX}] Message sent, no reply received"
        content = f"{now} {target_display}\n\n{message_text}"
        send_pushplus(pushplus_token, title, content)


async def wait_for_reply(client: TelegramClient, target_bot: str, timeout: int = 10) -> Optional[str]:
    await asyncio.sleep(timeout)
    try:
        messages = await client.get_messages(target_bot, limit=1)
        if messages and not messages[0].out:
            return messages[0].text
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to read bot reply: {exc}")
    return None


def send_pushplus(token: str, title: str, content: str) -> None:
    payload = json.dumps({
        "token": token,
        "title": title,
        "content": content,
        "template": "txt",
    }).encode()
    req = urllib.request.Request(
        PUSHPLUS_API,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            if result.get("code") != 200:
                print(f"PushPlus failed: {result.get('msg', 'unknown error')}")
            else:
                print("PushPlus notification sent.")
    except (urllib.error.URLError, OSError) as exc:
        print(f"PushPlus error: {exc}")


def seconds_until_next_run(hour: int, minute: int, timezone: ZoneInfo) -> tuple[float, datetime]:
    now = datetime.now(timezone)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds(), target


async def run_once(config: Config, dry_run: bool, target_bot: str, message_text: str) -> None:
    if dry_run:
        print_dry_run(target_bot, message_text)
        return

    async with build_client(config) as client:
        await ensure_login(client, config.phone)
        await send_bot_message(
            client,
            target_bot,
            message_text,
            dry_run=False,
            pushplus_token=config.pushplus_token,
        )


async def export_string_session(config: Config) -> None:
    async with build_client(config) as client:
        await ensure_login(client, config.phone)
        session_str = StringSession.save(client.session)
        if not session_str:
            raise RuntimeError("Failed to export TG_STRING_SESSION from current session.")
        print("Copy this into GitHub Secret TG_STRING_SESSION:")
        print(session_str)


async def run_daily(
    config: Config,
    daily_at: str,
    timezone_name: str,
    dry_run: bool,
    target_bot: str,
    message_text: str,
) -> None:
    hour, minute = parse_hhmm(daily_at)
    timezone = ZoneInfo(timezone_name)
    async with build_client(config) as client:
        await ensure_login(client, config.phone)
        while True:
            wait_seconds, run_time = seconds_until_next_run(hour, minute, timezone)
            print(f"Next run at {run_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            await asyncio.sleep(wait_seconds)
            try:
                await send_bot_message(
                    client,
                    target_bot,
                    message_text,
                    dry_run=dry_run,
                    pushplus_token=config.pushplus_token,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"Scheduled message failed: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Telegram scheduled bot message sender")
    parser.add_argument(
        "--daily-at",
        help="Run in daemon mode and send daily at HH:MM, e.g. 09:05",
    )
    parser.add_argument(
        "--timezone",
        default=os.getenv("TZ", "Asia/Shanghai"),
        help="IANA timezone name, e.g. Asia/Shanghai (default: TZ env or Asia/Shanghai)",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="Override target bot username (default from TG_TARGET_BOT)",
    )
    parser.add_argument(
        "--message",
        default=None,
        help="Override message text (default from TG_MESSAGE_TEXT)",
    )
    parser.add_argument(
        "--command",
        default=None,
        help="Deprecated alias for --message",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be sent without actually sending message",
    )
    parser.add_argument(
        "--export-string-session",
        action="store_true",
        help="Login if needed and print TG_STRING_SESSION for GitHub Actions",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    config = load_config()

    if args.daily_at and args.export_string_session:
        raise ValueError("--daily-at cannot be used together with --export-string-session.")

    if args.export_string_session:
        await export_string_session(config)
        return 0

    target_bot = args.target or config.target_bot
    message_text = args.message or args.command or config.message_text
    if not target_bot:
        raise ValueError("Missing required environment variable: TG_TARGET_BOT")
    if not message_text:
        raise ValueError(
            "Missing required environment variable: TG_MESSAGE_TEXT "
            "(legacy TG_CHECKIN_COMMAND is also supported)."
        )

    if args.daily_at:
        await run_daily(
            config=config,
            daily_at=args.daily_at,
            timezone_name=args.timezone,
            dry_run=args.dry_run,
            target_bot=target_bot,
            message_text=message_text,
        )
    else:
        await run_once(
            config=config,
            dry_run=args.dry_run,
            target_bot=target_bot,
            message_text=message_text,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
