import os
import re
import asyncio

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest

from mirror_client import MirrorClient
import templates as tpl

# ── কনফিগ ────────────────────────────────────────────────────

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
SERVER_URL = os.getenv("SERVER_URL", "").rstrip("/")
SERVER_API_KEY = os.getenv("SERVER_API_KEY", "")
POLL_INTERVAL = 3
MAX_POLL_ERRORS = 10

bot = Bot(BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()
router = Router()
dp.include_router(router)

client = MirrorClient(SERVER_URL, SERVER_API_KEY)

# gid → {chat_id, msg_id, url}
active: dict = {}


# ── হেল্পার ──────────────────────────────────────────────────

def parse_mirror_args(text: str):
    # BUG FIX #2: URL-এ | থাকলে ভাঙত না, এখন regex দিয়ে URL আলাদা করি
    rest = text.strip()
    url_match = re.match(r'(https?://[^\s|]+)', rest)
    if url_match:
        url = url_match.group(1)
        remaining = rest[url_match.end():].lstrip()
        if remaining.startswith("|"):
            remaining = remaining[1:].strip()
    else:
        url = rest.split("|")[0].strip()
        remaining = "|".join(rest.split("|")[1:]).strip()

    filename = None
    ttl = None

    for part in remaining.split("|"):
        part = part.strip()
        if part.startswith("ttl="):
            try:
                ttl = int(part[4:])
            except ValueError:
                pass
        elif part and not part.startswith("http"):
            filename = part

    return url, filename, ttl


async def start_mirror(chat_id: int, url: str, filename: str = None, ttl: int = None):
    status_msg = await bot.send_message(chat_id, "⏳ সার্ভারে অনুরোধ পাঠানো হচ্ছে...")

    try:
        result = await client.mirror(url, filename, ttl)
    except Exception as e:
        await status_msg.edit_text(f"❌ সার্ভার এরর: <code>{tpl.safe(str(e))}</code>")
        return

    gid = result["gid"]
    await status_msg.edit_text(
        tpl.msg_starting(result),
        reply_markup=tpl.kb_active(gid),
    )

    active[gid] = {"chat_id": chat_id, "msg_id": status_msg.id, "url": url}
    asyncio.create_task(poll_download(gid, chat_id, status_msg.id))


async def poll_download(gid: str, chat_id: int, msg_id: int):
    last_text = ""
    error_count = 0

    while gid in active:
        try:
            d = await client.status(gid)
            error_count = 0

            if d["status"] == "active":
                text = tpl.msg_active(d)
                if text != last_text:
                    last_text = text
                    try:
                        await bot.edit_message_text(
                            chat_id, msg_id, text,
                            reply_markup=tpl.kb_active(gid),
                        )
                    except TelegramBadRequest as e:
                        if "message is not modified" in str(e).lower():
                            pass
                        else:
                            raise
                await asyncio.sleep(POLL_INTERVAL)

            elif d["status"] == "complete":
                # BUG FIX #8: active থেকে আগে সরাও, তারপর এডিট
                active.pop(gid, None)
                text = tpl.msg_complete(d)
                kb = tpl.kb_complete(gid, d["mirror_url"], SERVER_URL)
                try:
                    await bot.edit_message_text(chat_id, msg_id, text, reply_markup=kb)
                except TelegramBadRequest:
                    pass
                return

            elif d["status"] in ("error", "removed"):
                active.pop(gid, None)
                text = tpl.msg_error(gid, d.get("error", "unknown"))
                try:
                    await bot.edit_message_text(chat_id, msg_id, text)
                except TelegramBadRequest:
                    pass
                return

        except Exception as e:
            error_count += 1
            print(f"[poll] gid={gid} err={e} ({error_count}/{MAX_POLL_ERRORS})")
            if error_count >= MAX_POLL_ERRORS:
                active.pop(gid, None)
                try:
                    await bot.edit_message_text(
                        chat_id, msg_id,
                        f"⚡ <b>MirrorPro</b>\n\n"
                        f"⚠️ সার্ভারের সাথে যোগাযোগ ব্যাহত\n"
                        f"GID: <code>{gid}</code>\n"
                        f"<code>/list</code> দিয়ে চেক করো",
                    )
                except Exception:
                    pass
                return
            await asyncio.sleep(5)


# ── কমান্ড হ্যান্ডলার ────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(m: Message):
    if m.from_user.id != OWNER_ID:
        return
    text = tpl.msg_start(SERVER_URL, "MirrorPro")
    kb = tpl.kb_start(SERVER_URL)
    await m.answer(text, reply_markup=kb)


@router.message(Command("help"))
async def cmd_help(m: Message):
    if m.from_user.id != OWNER_ID:
        return
    await m.answer(tpl.msg_help())


@router.message(Command("mirror"))
async def cmd_mirror(m: Message):
    if m.from_user.id != OWNER_ID:
        return

    raw = m.text.split(" ", 1)
    if len(raw) < 2:
        await m.answer(
            "📝 <code>/mirror &lt;url&gt;</code>\n"
            "বা <code>/mirror url | name.zip | ttl=3600</code>"
        )
        return

    url, filename, ttl = parse_mirror_args(raw[1])

    if not url.startswith(("http://", "https://")):
        await m.answer("❌ Valid URL দাও")
        return

    await start_mirror(m.chat.id, url, filename, ttl)


@router.message(Command("status"))
async def cmd_status(m: Message):
    if m.from_user.id != OWNER_ID:
        return

    if not active:
        await m.answer("📭 কোনো চলমান ডাউনলোড নেই")
        return

    lines = ["⚡ <b>Active Downloads</b>\n"]
    for gid, info in list(active.items()):
        try:
            d = await client.status(gid)
            if d["status"] == "active":
                lines.append(f"📄 <code>{tpl.safe(d.get('filename', '—'))}</code>")
                lines.append(
                    f"   {tpl.progress_bar(d.get('progress_pct', 0))} "
                    f"{d.get('progress_pct', 0)}%"
                )
                lines.append(f"   🚀 {d.get('speed', '—')} · ⏱ {d.get('eta', '—')}")
                lines.append(f"   GID: <code>{gid}</code>\n")
        except Exception:
            lines.append(f"⚠️ <code>{gid}</code> — N/A\n")

    await m.answer("\n".join(lines))


@router.message(Command("list"))
async def cmd_list(m: Message):
    if m.from_user.id != OWNER_ID:
        return
    try:
        data = await client.list_tasks()
        await m.answer(tpl.msg_list(data))
    except Exception as e:
        await m.answer(f"❌ <code>{tpl.safe(str(e))}</code>")


@router.message(Command("server"))
async def cmd_server(m: Message):
    if m.from_user.id != OWNER_ID:
        return
    try:
        data = await client.health()
        await m.answer(tpl.msg_health(data))
    except Exception as e:
        await m.answer(f"❌ সার্ভার unreachable: <code>{tpl.safe(str(e))}</code>")


@router.message(Command("cancel"))
async def cmd_cancel(m: Message):
    if m.from_user.id != OWNER_ID:
        return

    parts = m.text.split()
    if len(parts) < 2:
        await m.answer("📝 <code>/cancel &lt;gid&gt;</code>")
        return

    gid = parts[1]
    try:
        await client.delete(gid)
    except Exception:
        pass

    active.pop(gid, None)
    await m.answer(tpl.msg_cancelled(gid))


# ── সরাসরি URL অটো-মিরর ─────────────────────────────────────

URL_RE = re.compile(r"^https?://\S+$")


@router.message(F.text & ~F.text.startswith("/"))
async def auto_mirror(m: Message):
    if m.from_user.id != OWNER_ID:
        return

    text = m.text.strip()
    if not URL_RE.match(text):
        return

    await start_mirror(m.chat.id, text)


# ── কলব্যাক ──────────────────────────────────────────────────

@router.callback_query(F.data.startswith("cancel_"))
async def cq_cancel(cq: CallbackQuery):
    if cq.from_user.id != OWNER_ID:
        await cq.answer("authorized na", show_alert=True)
        return

    gid = cq.data.split("_", 1)[1]
    try:
        await client.delete(gid)
    except Exception:
        pass
    active.pop(gid, None)
    await cq.message.edit_text(tpl.msg_cancelled(gid))
    await cq.answer("Cancelled")


@router.callback_query(F.data.startswith("delete_"))
async def cq_delete(cq: CallbackQuery):
    if cq.from_user.id != OWNER_ID:
        await cq.answer("authorized na", show_alert=True)
        return

    gid = cq.data.split("_", 1)[1]
    try:
        await client.delete(gid)
    except Exception:
        pass
    active.pop(gid, None)
    await cq.message.edit_text(tpl.msg_deleted(gid))
    await cq.answer("Deleted")


# ── স্টার্ট ──────────────────────────────────────────────────

async def main():
    print("[*] MirrorPro Bot (aiogram) starting...")
    print(f"[*] Server: {SERVER_URL}")
    print(f"[*] Owner: {OWNER_ID}")
    try:
        await dp.start_polling(bot)
    finally:
        # BUG FIX #4: session close
        await client.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
