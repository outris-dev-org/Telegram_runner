#!/usr/bin/env python3
"""
One-off recovery: pull the most recent document the LeakOSINT bot sent
back to our userbot, without re-running the batch.

Why this exists:
    telegram-runner clears its in-memory result_bytes the moment the caller
    successfully GETs /lookup/{job_id}/result. If the upstream parser blows
    up *after* that, the bytes are gone from the runner — but the bot's
    reply file is still sitting in the userbot's chat history with the bot.
    This script reaches into that chat history and pulls it out.

Required env vars (lift from Railway → telegramrunner service → Variables):
    TELEGRAM_API_ID
    TELEGRAM_API_HASH
    TELEGRAM_SESSION_STRING        same string the runner uses
    TELEGRAM_LOOKUP_BOT_USERNAME   defaults to @LeakOsintInformBot

Usage:
    pip install telethon
    python fetch_last_bot_result.py list                 # show last 20 messages
    python fetch_last_bot_result.py fetch                # download most recent document
    python fetch_last_bot_result.py fetch --msg-id 1234  # download a specific message
    python fetch_last_bot_result.py fetch --out out.json # custom output path

Safety note:
    This logs a *second* Telethon client into the same Telegram account that
    the deployed runner is using. Telegram allows multiple devices per account,
    so this is fine in practice, but keep the session short (run, get file, exit)
    and don't leave it running.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except ImportError:
    sys.exit("telethon not installed — run: pip install telethon")


def _env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if val is None:
        sys.exit(f"missing required env var: {name}")
    return val


async def _list(limit: int) -> None:
    api_id = int(_env("TELEGRAM_API_ID"))
    api_hash = _env("TELEGRAM_API_HASH")
    session = _env("TELEGRAM_SESSION_STRING")
    bot = _env("TELEGRAM_LOOKUP_BOT_USERNAME", "@LeakOsintInformBot")

    async with TelegramClient(StringSession(session), api_id, api_hash) as client:
        entity = await client.get_entity(bot)
        print(f"# last {limit} messages with {bot}")
        async for msg in client.iter_messages(entity, limit=limit):
            ts = msg.date.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
            doc = msg.document
            if doc:
                size_kb = doc.size / 1024
                fname = next(
                    (a.file_name for a in doc.attributes if hasattr(a, "file_name")),
                    "<no name>",
                )
                print(
                    f"  msg_id={msg.id:<8} ts={ts}  doc={fname}  "
                    f"size={size_kb:,.1f} KB  mime={doc.mime_type}"
                )
            else:
                snippet = (msg.message or "").replace("\n", " ")[:80]
                print(f"  msg_id={msg.id:<8} ts={ts}  text={snippet!r}")


async def _fetch(out_path: str, msg_id: int | None, lookback: int) -> None:
    api_id = int(_env("TELEGRAM_API_ID"))
    api_hash = _env("TELEGRAM_API_HASH")
    session = _env("TELEGRAM_SESSION_STRING")
    bot = _env("TELEGRAM_LOOKUP_BOT_USERNAME", "@LeakOsintInformBot")

    async with TelegramClient(StringSession(session), api_id, api_hash) as client:
        entity = await client.get_entity(bot)

        if msg_id is not None:
            msg = await client.get_messages(entity, ids=msg_id)
            if msg is None:
                sys.exit(f"message {msg_id} not found in chat with {bot}")
            if not msg.document:
                sys.exit(f"message {msg_id} has no document attached")
            target = msg
        else:
            target = None
            async for msg in client.iter_messages(entity, limit=lookback):
                if msg.document:
                    target = msg
                    break
            if target is None:
                sys.exit(f"no document in the last {lookback} messages with {bot}")

        ts = target.date.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        size_kb = target.document.size / 1024
        print(f"# downloading msg_id={target.id} ({ts}, {size_kb:,.1f} KB) → {out_path}")
        await client.download_media(target, out_path)
        print(f"# done")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="show last N messages from the bot")
    p_list.add_argument("--limit", type=int, default=20)

    p_fetch = sub.add_parser("fetch", help="download a document from the bot chat")
    p_fetch.add_argument("--out", default=f"leakosint_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin")
    p_fetch.add_argument("--msg-id", type=int, help="specific message id (from `list`)")
    p_fetch.add_argument("--lookback", type=int, default=20, help="how many recent messages to scan when --msg-id omitted")

    args = parser.parse_args()
    if args.cmd == "list":
        asyncio.run(_list(args.limit))
    elif args.cmd == "fetch":
        asyncio.run(_fetch(args.out, args.msg_id, args.lookback))


if __name__ == "__main__":
    main()
