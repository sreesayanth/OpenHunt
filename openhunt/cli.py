"""Command line: `openhunt` (run), `openhunt setup` (terminal-only setup for VMs), `openhunt reset`."""

import argparse
import asyncio
import logging
import sys

from openhunt import __version__, store
from openhunt.config import DATA_DIR, WEB_HOST, WEB_PORT


def cmd_run(args) -> None:
    from openhunt.runtime import Runtime

    asyncio.run(Runtime().serve(args.host, args.port, web=not args.no_web))


def cmd_setup(args) -> None:
    """For VMs without a browser: ask only for the bot token, the rest happens in Telegram."""
    import qrcode

    from openhunt.bot.app import new_link_code
    from openhunt.runtime import check_token

    print("\nOpenHunt setup\n")
    print("1. In Telegram, open @BotFather and send /newbot")
    print("2. Choose a name and a username ending in 'bot'")
    print("3. Copy the token BotFather gives you\n")
    while True:
        token = input("Paste your bot token here: ").strip()
        try:
            username = asyncio.run(check_token(token))
            break
        except ValueError as exc:
            print(f"  ✗ {exc}\n")
    store.put("bot_token", token)
    store.put("bot_username", username)
    url = f"https://t.me/{username}?start={new_link_code()}"
    print(f"\n✓ Bot @{username} saved.\n\nScan this with your phone, or open the link, and press Start:\n")
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.print_ascii(invert=True)
    print(f"\n  {url}\n")
    print("Now start OpenHunt with:  openhunt --no-web\n(Everything else, CV, AI and schedule, is set up in Telegram.)\n")


def cmd_reset(args) -> None:
    if input(f"This deletes ALL OpenHunt data in {DATA_DIR}. Type DELETE to confirm: ") == "DELETE":
        store.reset_all()
        print("All data deleted.")
    else:
        print("Cancelled.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="openhunt", description="Self-hosted AI job hunter")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--host", default=WEB_HOST)
    parser.add_argument("--port", type=int, default=WEB_PORT)
    parser.add_argument("--no-web", action="store_true", help="Telegram only, no web page (VMs / Android)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="Start OpenHunt (default)")
    sub.add_parser("setup", help="Set up from the terminal (no browser needed)")
    sub.add_parser("reset", help="Delete all data")
    args = parser.parse_args()

    # Old Windows consoles default to cp1252 and crash on emoji/arrows.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    # httpx logs full request URLs, and Telegram URLs contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    store.init_db()
    {"setup": cmd_setup, "reset": cmd_reset}.get(args.cmd, cmd_run)(args)
