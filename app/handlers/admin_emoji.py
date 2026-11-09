"""Admin command /emoji - change premium emoji from inside the bot (no file editing).

Only admins can use it. Changes are saved to custom_emoji.json AND applied immediately
(no restart), because the middleware shares the same `emoji_mapping` dict.

Usage (admin sends in the bot chat):
  /emoji                      -> show current emoji + which emoji in texts.py are not set yet
  /emoji <premium emoji>...   -> each premium emoji replaces its own normal emoji
                                 e.g.  /emoji 💎(premium) 👛(premium)
  /emoji 💎 <premium emoji>   -> use a normal emoji as key, then the premium one to put in
                                 (premium emoji can look different from the normal one)
  /emoji_del 💎               -> remove one          /emoji_del all -> remove everything
"""
import json
import logging
import os
import re
import tempfile

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.texts import TEXTS
from app.utils.filters import IsAdmin

log = logging.getLogger(__name__)
router = Router(name="admin_emoji")
router.message.filter(IsAdmin())      # same admin check as appearance.py / admin.py

EMOJI_FILE = "custom_emoji.json"          # keep the same path you pass to load_mapping()
_VS16 = "\ufe0f"
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF\u2190-\u21FF\u2900-\u297F]"
)


def _norm(emoji: str) -> str:
    return emoji.replace(_VS16, "").strip()


def _strip_entities(text: str, entities) -> str:
    """Remove the custom-emoji parts from text (Telegram offsets are UTF-16)."""
    raw = text.encode("utf-16-le")
    out, pos = bytearray(), 0
    for e in sorted(entities, key=lambda x: x.offset):
        out += raw[pos:e.offset * 2]
        pos = (e.offset + e.length) * 2
    out += raw[pos:]
    return out.decode("utf-16-le")


def _save(mapping: dict) -> None:
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=os.path.dirname(os.path.abspath(EMOJI_FILE)))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, EMOJI_FILE)


def _used_in_texts() -> set:
    found = set()

    def walk(value):
        if isinstance(value, str):
            found.update(_norm(c) for c in _EMOJI_RE.findall(value))
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)

    walk(TEXTS)
    return found


async def _show(message: Message, mapping: dict):
    current = "  ".join(mapping) if mapping else "(គ្មាន)"
    missing = sorted(_used_in_texts() - set(mapping))
    await message.answer(
        "✨ <b>Premium emoji</b>\n\n"
        f"កំណត់រួច: {current}\n"
        f"មិនទាន់កំណត់: {'  '.join(missing) or '(គ្មាន)'}\n\n"
        "ផ្ញើ <code>/emoji</code> ជាមួយ premium emoji ដើម្បីប្តូរ។\n"
        "ឧទាហរណ៍: <code>/emoji</code> + premium 💎 + premium 👛\n"
        "ឬកំណត់ចំៗ: <code>/emoji 💎</code> + premium emoji\n"
        "លុប: <code>/emoji_del 💎</code> ឬ <code>/emoji_del all</code>",
        parse_mode="HTML",
    )


@router.message(Command("emoji"))
async def emoji_set(message: Message, emoji_mapping: dict):
    ents = [e for e in (message.entities or []) if e.type == "custom_emoji"]
    if not ents:
        return await _show(message, emoji_mapping)

    text = message.text or ""
    fallbacks = [_norm(e.extract_from(text)) for e in ents]
    rest = re.sub(r"^/\S+", "", _strip_entities(text, ents))
    keys = [_norm(tok) for tok in rest.split() if not re.search(r"[A-Za-z0-9]", tok)]
    if not keys:
        keys = fallbacks
    if len(keys) != len(ents):
        return await message.answer(
            "⚠️ ចំនួន emoji ធម្មតា និង premium emoji មិនស្មើគ្នា។ "
            "ដាក់ premium emoji ឲ្យស្មើនឹង emoji ធម្មតា ឬកុំដាក់ emoji ធម្មតាសោះ។"
        )

    new = dict(emoji_mapping)
    for key, ent in zip(keys, ents):
        if key:
            new[key] = str(ent.custom_emoji_id)
    try:
        _save(new)
    except OSError as exc:
        log.error("could not save %s: %s", EMOJI_FILE, exc)
        return await message.answer("⚠️ រក្សាទុកមិនបាន សូមពិនិត្យ log។")
    emoji_mapping.clear()
    emoji_mapping.update(new)               # applies immediately
    await message.answer(f"✅ បានកំណត់ {len(ents)} emoji: {'  '.join(keys)}")


@router.message(Command("emoji_del"))
async def emoji_delete(message: Message, command: CommandObject, emoji_mapping: dict):
    arg = (command.args or "").strip()
    if not arg:
        return await message.answer("ប្រើ: /emoji_del 💎  ឬ  /emoji_del all")
    new = {} if arg.lower() == "all" else {k: v for k, v in emoji_mapping.items()
                                           if k not in {_norm(t) for t in arg.split()}}
    try:
        _save(new)
    except OSError:
        return await message.answer("⚠️ រក្សាទុកមិនបាន សូមពិនិត្យ log។")
    emoji_mapping.clear()
    emoji_mapping.update(new)
    await message.answer("✅ បានលុប")
