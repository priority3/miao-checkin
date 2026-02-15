#!/usr/bin/env python3
import argparse
import asyncio
import getpass
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession


@dataclass
class Config:
    api_id: int
    api_hash: str
    phone: Optional[str]
    session_name: str
    string_session: Optional[str]
    target_bot: str
    checkin_command: str


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _parse_api_id(raw: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError("TG_API_ID must be an integer.") from exc


def load_config() -> Config:
    load_dotenv()
    api_id = _parse_api_id(_require_env("TG_API_ID"))
    api_hash = _require_env("TG_API_HASH")
    phone = os.getenv("TG_PHONE", "").strip() or None
    session_name = os.getenv("TG_SESSION_NAME", "miao_checkin").strip() or "miao_checkin"
    string_session = os.getenv("TG_STRING_SESSION", "").strip() or None
    target_bot = os.getenv("TG_TARGET_BOT", "that_miao_bot").strip() or "that_miao_bot"
    checkin_command = os.getenv("TG_CHECKIN_COMMAND", "/checkin").strip() or "/checkin"
    if not phone and not string_session:
        raise ValueError("Set TG_STRING_SESSION (recommended for CI) or TG_PHONE.")
    return Config(
        api_id=api_id,
        api_hash=api_hash,
        phone=phone,
        session_name=session_name,
        string_session=string_session,
        target_bot=target_bot,
        checkin_command=checkin_command,
    )


def parse_hhmm(raw: str) -> tuple[int, int]:
    if not re.fullmatch(r"\d{2}:\d{2}", raw):
        raise ValueError("Time must use HH:MM format, e.g. 09:30")
    hour, minute = map(int, raw.split(":"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Invalid time. Hour must be 00-23 and minute must be 00-59.")
    return hour, minute


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


async def do_checkin(client: TelegramClient, target_bot: str, checkin_command: str, dry_run: bool) -> None:
    if dry_run:
        print(f"[DRY RUN] Would send '{checkin_command}' to @{target_bot}")
        return
    await client.send_message(target_bot, checkin_command)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] Sent '{checkin_command}' to @{target_bot}")


def seconds_until_next_run(hour: int, minute: int, timezone: ZoneInfo) -> tuple[float, datetime]:
    now = datetime.now(timezone)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds(), target


async def run_once(config: Config, dry_run: bool, target_bot: str, checkin_command: str) -> None:
    async with build_client(config) as client:
        await ensure_login(client, config.phone)
        await do_checkin(client, target_bot, checkin_command, dry_run=dry_run)


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
    checkin_command: str,
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
                await do_checkin(client, target_bot, checkin_command, dry_run=dry_run)
            except Exception as exc:  # noqa: BLE001
                print(f"Check-in failed: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Telegram daily check-in sender")
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
        "--command",
        default=None,
        help="Override command text (default from TG_CHECKIN_COMMAND)",
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
    target_bot = args.target or config.target_bot
    checkin_command = args.command or config.checkin_command

    if args.daily_at and args.export_string_session:
        raise ValueError("--daily-at cannot be used together with --export-string-session.")

    if args.export_string_session:
        await export_string_session(config)
        return 0

    if args.daily_at:
        await run_daily(
            config=config,
            daily_at=args.daily_at,
            timezone_name=args.timezone,
            dry_run=args.dry_run,
            target_bot=target_bot,
            checkin_command=checkin_command,
        )
    else:
        await run_once(
            config=config,
            dry_run=args.dry_run,
            target_bot=target_bot,
            checkin_command=checkin_command,
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
