"""Admin only: edit premium emoji and message texts from inside the bot.

  /emoji 💎 <premium emoji>   set a premium emoji (saved in the database)
  /emoji_del 💎 | all         remove one / all
  /emoji_list                 show everything that is set

  /texts                      list the messages that can be edited
  /texts welcome              show one message (original + current)
  /settext welcome <text>     change a message   (add  en  or  km  after the name to choose
                              the language; otherwise Khmer letters => km, else en)
  /resettext welcome          go back to the original text

Everything is saved in the database and works immediately - no GitHub push, no restart.
Nothing here replaces or removes any existing admin feature.
"""
import re
import string
from typing import Optional

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app import texts as texts_module
from app.database import repositories as repo
from app.database.db import Database
from app.texts import TEXTS
from app.utils import icons
from app.utils.emoji_store import EmojiStore
from app.utils.filters import IsAdmin
from app.utils.formatting import esc

router = Router(name="live_edit")
router.message.filter(IsAdmin())

LANGS = ("en", "km")
MAX_TEXT = 3500          # a Telegram message holds 4096 characters
MAX_CAPTION = 900        # a photo caption holds 1024 characters
PREMIUM_NOTE = (
    "ℹ️ In message text a premium emoji is animated only if the bot has a Fragment "
    "username; in inline buttons it shows anyway."
)

# Telegram HTML: only these tags are allowed.
ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a", "code", "pre",
    "tg-spoiler", "tg-emoji", "span", "blockquote",
}
_TAG_RE = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)((?:\s[^<>]*)?)>")
_BAD_AMP_RE = re.compile(r"&(?!(?:amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);)")
_SET_RE = re.compile(
    r"^/settext(?:@\w+)?\s+(\S+)(?:[ \t]+(en|km)(?=\s))?\s+(.+)$", re.S | re.I)
_KHMER_RE = re.compile("[\u1780-\u17ff]")


# --------------------------------------------------------------------- helpers


def editable_keys() -> list:
    """Messages an admin may edit. Menu / button labels stay fixed: the bot recognises
    the big-menu buttons by their exact text, and buttons cannot contain HTML."""
    return [k for k in TEXTS["en"] if not k.startswith(("menu_", "btn_"))]


def fields_of(key: str) -> set:
    """Placeholders like {name} used by the original text (in either language)."""
    found = set()
    for lang in LANGS:
        template = TEXTS[lang].get(key)
        if template:
            found |= {f for _, f, _, _ in string.Formatter().parse(template) if f}
    return found


def validate_html(text: str) -> Optional[str]:
    """Return a problem description, or None when Telegram will accept the text."""

    def check_plain(chunk: str) -> Optional[str]:
        if "<" in chunk:
            return "a lone '<' - write &lt; instead"
        if _BAD_AMP_RE.search(chunk):
            return "a lone '&' - write &amp; instead"
        return None

    stack, pos = [], 0
    for m in _TAG_RE.finditer(text):
        problem = check_plain(text[pos:m.start()])
        if problem:
            return problem
        closing, name, attrs = m.group(1) == "/", m.group(2).lower(), m.group(3)
        if name not in ALLOWED_TAGS:
            return f"tag <{name}> is not allowed by Telegram"
        if closing:
            if not stack or stack[-1] != name:
                return f"closing tag </{name}> does not match an open tag"
            stack.pop()
        else:
            if name == "a" and "href" not in attrs:
                return "<a> needs href=\"...\""
            if name == "tg-emoji" and "emoji-id" not in attrs:
                return "<tg-emoji> needs emoji-id=\"...\""
            stack.append(name)
        pos = m.end()
    problem = check_plain(text[pos:])
    if problem:
        return problem
    if stack:
        return f"tag <{stack[-1]}> is never closed"
    return None


def validate_template(key: str, text: str) -> Optional[str]:
    """Check an edited message BEFORE saving. Returns a problem or None."""
    limit = MAX_CAPTION if "caption" in key else MAX_TEXT
    if len(text) > limit:
        return f"too long ({len(text)} characters, the limit for this message is {limit})"
    allowed = fields_of(key)
    try:
        parsed = list(string.Formatter().parse(text))
    except ValueError as exc:
        return f"curly brackets are broken ({exc}). Use only the placeholders listed below."
    for _, field, spec, conv in parsed:
        if field is None:
            continue
        if field not in allowed or spec or conv:
            names = ", ".join("{" + f + "}" for f in sorted(allowed)) or "none"
            return f"unknown placeholder {{{field}}}. Allowed for this message: {names}"
    if not allowed and ("{" in text or "}" in text):
        return "this message has no placeholders, so curly brackets { } are not allowed"
    return validate_html(text)


def sample_render(key: str, text: str) -> str:
    fields = fields_of(key)
    if not fields:
        return text
    return text.format(**{f: f"‹{f}›" for f in fields})


def detect_lang(text: str) -> str:
    return "km" if _KHMER_RE.search(text) else "en"


def body_for_saving(message: Message) -> str:
    """The text exactly as typed. If the admin used Telegram's own formatting (bold,
    italic, premium emoji...) it is converted to HTML; otherwise typed <b>tags</b> stay."""
    others = [e for e in (message.entities or []) if e.type != "bot_command"]
    return (message.html_text if others else message.text) or ""


async def reply_chunks(message: Message, lines: list, header: str = "") -> None:
    """Send long lists in several messages (Telegram limit is 4096 characters)."""
    chunk = header
    for line in lines:
        if len(chunk) + len(line) + 1 > 3800:
            await message.answer(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        await message.answer(chunk)


async def load_text_overrides(db: Database) -> int:
    """Called once at start-up: bring saved text edits back into memory."""
    keys = set(editable_keys())
    texts_module.OVERRIDES.clear()
    for row in await repo.list_custom_texts(db):
        if row["lang"] in LANGS and row["key"] in keys:
            texts_module.OVERRIDES[(row["lang"], row["key"])] = row["value"]
    return len(texts_module.OVERRIDES)


# ------------------------------------------------------------ premium emoji


def parse_emoji_pairs(message: Message) -> Optional[list]:
    """'/emoji 💎 <premium>' -> [('💎', 'id')]. Several pairs in one message work too.
    '/emoji <premium>' alone uses the premium emoji's own normal emoji."""
    text = message.text or ""
    raw = text.encode("utf-16-le")  # Telegram counts positions in UTF-16 units
    command = next((e for e in (message.entities or []) if e.type == "bot_command"), None)
    cursor = (command.offset + command.length) if command else 0
    customs = sorted((e for e in (message.entities or []) if e.type == "custom_emoji"),
                     key=lambda e: e.offset)
    pairs = []
    for ent in customs:
        before = raw[cursor * 2:ent.offset * 2].decode("utf-16-le").strip()
        char = raw[ent.offset * 2:(ent.offset + ent.length) * 2].decode("utf-16-le").strip()
        base = icons.clean_plain_emoji(before or char)
        if not base or not icons.valid_id(ent.custom_emoji_id):
            return None
        pairs.append((base, str(ent.custom_emoji_id)))
        cursor = ent.offset + ent.length
    if not pairs or raw[cursor * 2:].decode("utf-16-le").strip():
        return None
    return pairs


@router.message(Command("emoji"))
async def cmd_emoji(message: Message, db: Database, emoji_store: EmojiStore):
    pairs = parse_emoji_pairs(message)
    if pairs is None:
        await message.answer(
            "😀 <b>Set a premium emoji</b>\n\n"
            "Send the normal emoji, then the premium one (you need Telegram Premium to "
            "send it):\n<code>/emoji 💎</code> + premium 💎\n\n"
            "• <code>/emoji_del 💎</code> or <code>/emoji_del all</code> — remove\n"
            "• /emoji_list — see all\n\n" + PREMIUM_NOTE)
        return
    for emoji, emoji_id in pairs:
        await emoji_store.set(db, emoji, emoji_id)
    shown = " ".join(e for e, _ in pairs)
    await message.answer(
        f"✅ Premium emoji saved: {shown}\nIt is active now — no restart needed.\n\n"
        + PREMIUM_NOTE)


@router.message(Command("emoji_del"))
async def cmd_emoji_del(message: Message, command: CommandObject, db: Database,
                        emoji_store: EmojiStore):
    arg = (command.args or "").strip()
    if not arg:
        await message.answer("Usage: <code>/emoji_del 💎</code> or <code>/emoji_del all</code>")
        return
    if arg.lower() == "all":
        n = await emoji_store.clear(db)
        await message.answer(f"🗑 Removed all premium emoji ({n}).")
        return
    removed, missing = [], []
    for token in arg.split():
        base = icons.clean_plain_emoji(token)
        if base and await emoji_store.delete(db, base):
            removed.append(base)
        else:
            missing.append(token)
    parts = []
    if removed:
        parts.append("🗑 Removed: " + " ".join(removed))
    if missing:
        parts.append("⚠️ Not found: " + " ".join(esc(m) for m in missing))
    await message.answer("\n".join(parts))


@router.message(Command("emoji_list"))
async def cmd_emoji_list(message: Message, emoji_store: EmojiStore):
    items = emoji_store.items()
    if not items:
        await message.answer("No premium emoji set yet.\nUse <code>/emoji 💎</code> + premium 💎")
        return
    lines = [f"{e} → <code>{esc(i)}</code>" for e, i in items]
    await reply_chunks(message, lines, f"😀 <b>Premium emoji ({len(items)})</b>\n\n")


# ------------------------------------------------------------ message texts


@router.message(Command("texts"))
async def cmd_texts(message: Message, command: CommandObject):
    keys = editable_keys()
    arg = (command.args or "").strip()
    if arg:
        if arg not in keys:
            await message.answer(f"⚠️ No editable message called <code>{esc(arg)}</code>. "
                                 "Send /texts to see the list.")
            return
        placeholders = ", ".join("{" + f + "}" for f in sorted(fields_of(arg))) or "none"
        await message.answer(
            f"📝 <b>{esc(arg)}</b>\nPlaceholders (keep them as they are): {esc(placeholders)}")
        for lang in LANGS:
            original = TEXTS[lang].get(arg) or TEXTS["en"][arg]
            current = texts_module.OVERRIDES.get((lang, arg))
            body = current if current is not None else original
            tag = "✏️ edited" if current is not None else "original"
            await message.answer(f"<b>{lang}</b> ({tag}):\n<pre>{esc(body)}</pre>")
        await message.answer(
            f"Change it: <code>/settext {esc(arg)} your new text</code>\n"
            f"Go back: <code>/resettext {esc(arg)}</code>")
        return
    lines = []
    for key in keys:
        marks = " ".join(
            f"{lang}{'✏️' if (lang, key) in texts_module.OVERRIDES else ''}" for lang in LANGS)
        lines.append(f"<code>{esc(key)}</code> — {marks}")
    await reply_chunks(
        message, lines,
        "📝 <b>Editable messages</b> (✏️ = edited)\n"
        "/texts <code>name</code> shows one · /settext changes · /resettext restores\n\n")


@router.message(Command("settext"))
async def cmd_settext(message: Message, db: Database):
    keys = set(editable_keys())
    match = _SET_RE.match(body_for_saving(message).strip())
    if not match:
        await message.answer(
            "✏️ <b>Edit a message</b>\n\n"
            "<code>/settext welcome Your new text...</code>\n"
            "Add <code>en</code> or <code>km</code> after the name to pick the language "
            "(otherwise Khmer letters → km, anything else → en).\n"
            "You can use bold/italic from Telegram's formatting, or HTML tags.\n"
            "Keep placeholders like <code>{name}</code> exactly as they are.\n\n"
            "/texts shows the names.")
        return
    key, lang_arg, value = match.group(1), match.group(2), match.group(3).strip()
    if key not in keys:
        await message.answer(f"⚠️ No editable message called <code>{esc(key)}</code>. "
                             "Send /texts to see the list.")
        return
    lang = (lang_arg or detect_lang(value)).lower()
    problem = validate_template(key, value)
    if problem:
        await message.answer(f"⚠️ Not saved — {esc(problem)}.")
        return
    # Final check: really send it through Telegram. If Telegram rejects it, it is NOT saved,
    # so customers can never get a broken message.
    try:
        await message.answer(sample_render(key, value))
    except TelegramBadRequest as exc:
        await message.answer(f"⚠️ Not saved — Telegram rejected this text: {esc(str(exc))}")
        return
    await repo.set_custom_text(db, lang, key, value)
    texts_module.OVERRIDES[(lang, key)] = value
    await message.answer(
        f"✅ <b>{esc(key)}</b> saved for <b>{lang}</b> (preview above, placeholders shown "
        "as ‹name›). Active now.")


@router.message(Command("resettext"))
async def cmd_resettext(message: Message, command: CommandObject, db: Database):
    parts = (command.args or "").split()
    if not parts or len(parts) > 2 or (len(parts) == 2 and parts[1].lower() not in LANGS):
        await message.answer("Usage: <code>/resettext welcome</code>  (or add <code>en</code> / "
                             "<code>km</code> to restore one language only)")
        return
    key = parts[0]
    lang = parts[1].lower() if len(parts) == 2 else None
    if key not in set(editable_keys()):
        await message.answer(f"⚠️ No editable message called <code>{esc(key)}</code>. "
                             "Send /texts to see the list.")
        return
    removed = await repo.delete_custom_text(db, key, lang)
    for code in ([lang] if lang else LANGS):
        texts_module.OVERRIDES.pop((code, key), None)
    if removed:
        await message.answer(f"↩️ <b>{esc(key)}</b> is back to the original text.")
    else:
        await message.answer(f"<b>{esc(key)}</b> was not edited — it already uses the original text.")
