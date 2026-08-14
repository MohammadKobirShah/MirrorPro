from html import escape
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# BUG FIX #1: HTML injection প্রতিরোধ
def safe(s) -> str:
    if s is None:
        return ""
    return escape(str(s), quote=False)


# BUG FIX #9: progress_pct None হলে crash ঠেকাও
def progress_bar(pct, width: int = 12) -> str:
    pct = float(pct or 0)
    fill = int(width * pct / 100)
    fill = max(0, min(width, fill))
    return "█" * fill + "░" * (width - fill)


def msg_start(server_url: str, server_name: str) -> str:
    return (
        f"⚡ <b>{safe(server_name)}</b>\n\n"
        f"তোমার পার্সোনাল মিরর সার্ভারের ক্লায়েন্ট।\n\n"
        f"🚀 <b>কমান্ড:</b>\n"
        f"<code>/mirror url</code> — মিরর শুরু\n"
        f"<code>/status</code> — চলমান ডাউনলোড\n"
        f"<code>/list</code> — সব টাস্ক\n"
        f"<code>/server</code> — সার্ভার হেলথ\n"
        f"<code>/cancel gid</code> — থামাও\n\n"
        f"💡 সরাসরি URL পাঠালেও চলবে\n"
        f"💡 <code>/mirror url | name.zip | ttl=0</code>\n\n"
        f"🌐 <code>{safe(server_url)}</code>"
    )


def msg_active(d: dict) -> str:
    bar = progress_bar(d.get("progress_pct", 0))
    pct = d.get("progress_pct", 0)
    return (
        f"⚡ <b>MirrorPro</b>\n\n"
        f"📄 <b>File:</b> <code>{safe(d.get('filename', '—'))}</code>\n"
        f"🌐 <b>Source:</b> <code>{safe(d.get('source', '—'))}</code>\n\n"
        f"📥 <b>Downloading</b>\n"
        f"<code>{bar}</code> {pct}%\n\n"
        f"📊 <b>Done:</b> <code>{safe(d.get('downloaded', '—'))} / {safe(d.get('total', '—'))}</code>\n"
        f"🚀 <b>Speed:</b> <code>{safe(d.get('speed', '—'))}</code>\n"
        f"⏱ <b>ETA:</b> <code>{safe(d.get('eta', '—'))}</code>\n"
        f"🔗 <b>Conns:</b> <code>{d.get('connections', '16')}</code>\n"
        f"📈 <b>Avg:</b> <code>{safe(d.get('average_speed', '—'))}</code>"
    )


def msg_starting(d: dict) -> str:
    return (
        f"⚡ <b>MirrorPro</b>\n\n"
        f"📄 <b>File:</b> <code>{safe(d.get('filename', '—'))}</code>\n"
        f"🌐 <b>Source:</b> <code>{safe(d.get('source', '—'))}</code>\n\n"
        f"📥 <b>Starting download...</b>"
    )


def msg_complete(d: dict) -> str:
    lines = [
        f"⚡ <b>MirrorPro</b>\n",
        f"✅ <b>Mirror Ready</b>\n",
        f"📄 <b>File:</b> <code>{safe(d.get('filename', '—'))}</code>",
        f"🌐 <b>Source:</b> <code>{safe(d.get('source', '—'))}</code>",
        f"📦 <b>Size:</b> <code>{safe(d.get('size_human', '—'))}</code>",
        f"⏱ <b>Duration:</b> <code>{safe(d.get('download_duration', '—'))}</code>",
        f"🚀 <b>Avg Speed:</b> <code>{safe(d.get('average_speed', '—'))}</code>",
        f"💨 <b>Peak Speed:</b> <code>{safe(d.get('peak_speed', '—'))}</code>\n",
        f"🔗 <b>Mirror Link:</b>",
        f"<code>{safe(d.get('mirror_url', '—'))}</code>",
    ]
    if d.get("auto_delete"):
        mins = max(0, d.get("expires_in_sec", 0) // 60)
        lines.append(f"\n⏳ <b>Auto-delete:</b> <code>{mins}m</code>")
    return "\n".join(lines)


def msg_error(gid: str, error: str) -> str:
    return (
        f"⚡ <b>MirrorPro</b>\n\n"
        f"❌ <b>Error</b>\n"
        f"<code>{safe(error)}</code>\n\n"
        f"GID: <code>{safe(gid)}</code>"
    )


def msg_cancelled(gid: str) -> str:
    return (
        f"⚡ <b>MirrorPro</b>\n\n"
        f"🚫 <b>Cancelled</b>\n"
        f"GID: <code>{safe(gid)}</code>"
    )


def msg_deleted(gid: str) -> str:
    return (
        f"⚡ <b>MirrorPro</b>\n\n"
        f"🗑 <b>Deleted</b>\n"
        f"GID: <code>{safe(gid)}</code>"
    )


def msg_help() -> str:
    return (
        f"⚡ <b>MirrorPro Help</b>\n\n"
        f"<b>/mirror &lt;url&gt;</b>\n"
        f"  মিরর শুরু করো। TTL ও নাম যোগ করতে পারো:\n"
        f"  <code>/mirror url | name.zip | ttl=3600</code>\n\n"
        f"<b>/status</b>\n  চলমান ডাউনলোড দেখাও\n\n"
        f"<b>/list</b>\n  সার্ভারের সব টাস্ক\n\n"
        f"<b>/server</b>\n  সার্ভার হেলথ চেক\n\n"
        f"<b>/cancel &lt;gid&gt;</b>\n  ডাউনলোড থামাও\n\n"
        f"💡 সরাসরি URL পাঠালেও মিরর শুরু হবে"
    )


def msg_list(data: dict) -> str:
    tasks = data.get("tasks", [])
    if not tasks:
        return "⚡ <b>MirrorPro</b>\n\n📭 কোনো টাস্ক নেই"

    lines = [f"⚡ <b>MirrorPro</b>\n", f"📊 <b>Total: {data.get('total_tasks', 0)}</b>\n"]

    for t in tasks[:15]:
        status_emoji = {"active": "⏳", "complete": "✅", "error": "❌"}.get(t.get("status", ""), "❓")
        lines.append(f"\n{status_emoji} <code>{safe(t.get('filename', '—'))}</code>")
        meta_parts = []
        if t.get("source"):
            meta_parts.append(f"🌐 {safe(t['source'])}")
        if t.get("size_human"):
            meta_parts.append(f"📦 {safe(t['size_human'])}")
        if t.get("downloaded"):
            meta_parts.append(f"⬇ {safe(t['downloaded'])}/{safe(t.get('total', ''))}")
        if t.get("expires_in_sec") is not None:
            meta_parts.append(f"⏳ {max(0, t['expires_in_sec'] // 60)}m")
        if meta_parts:
            lines.append(f"   {' · '.join(meta_parts)}")
        lines.append(f"   GID: <code>{safe(t.get('gid', '—'))}</code>")

    if len(tasks) > 15:
        lines.append(f"\n... আরও {len(tasks) - 15}টা")
    return "\n".join(lines)


def msg_health(d: dict) -> str:
    status_emoji = "✅" if d.get("status") == "ok" else "⚠️"
    lines = [
        f"⚡ <b>MirrorPro Server</b>\n",
        f"{status_emoji} <b>Status:</b> <code>{safe(d.get('status', '—'))}</code>",
        f"🔧 <b>aria2:</b> <code>{safe(d.get('aria2', '—'))}</code>",
        f"📛 <b>Name:</b> <code>{safe(d.get('server_name', '—'))}</code>",
        f"📥 <b>Active:</b> <code>{d.get('active_downloads', 0)}</code>",
        f"✅ <b>Completed:</b> <code>{d.get('completed_files', 0)}</code>",
    ]
    if d.get("auto_delete"):
        hours = d.get("ttl_seconds", 0) / 3600
        lines.append(f"⏳ <b>Auto-delete:</b> <code>{hours:.1f}h</code>")
    else:
        lines.append(f"⏳ <b>Auto-delete:</b> <code>OFF</code>")
    return "\n".join(lines)


def kb_active(gid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✕ Cancel", callback_data=f"cancel_{gid}")]
    ])


def kb_complete(gid: str, mirror_url: str, server_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬇ Download", url=mirror_url)],
        [
            InlineKeyboardButton(text="📋 Details", url=f"{server_url}/status/{gid}"),
            InlineKeyboardButton(text="🗑 Delete", callback_data=f"delete_{gid}")
        ]
    ])


def kb_start(server_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Dashboard", url=f"{server_url}/dashboard"),
            InlineKeyboardButton(text="❤️ Health", url=f"{server_url}/health")
        ]
    ])
