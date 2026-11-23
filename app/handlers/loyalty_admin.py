"""Admin only: friend referral bonus (/referral) and membership levels (/levels).

  /referral                 show the settings and the numbers
  /referral 0.25            the inviter gets $0.25 (and the bonus is switched ON)
  /referral off | on        pause / resume
  /referral min 1           the friend's order must be at least $1
  /referral cap 20          at most 20 rewards per inviter per month

  /levels                   show the steps
  /levels Bronze=0 Silver=20 Gold=50 Diamond=100      set the steps (dollars spent)
  /levels reset             back to the default steps

(In bot messages a literal angle bracket must be written as &lt; and &gt; - the bot sends HTML.)
"""
import json
import re

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.database import repositories as repo
from app.database.db import Database
from app.services import loyalty
from app.utils.filters import IsAdmin
from app.utils.formatting import esc, money
from app.utils.validators import parse_money

router = Router(name="loyalty_admin")
router.message.filter(IsAdmin())

MAX_REWARD_CENTS = 10_000          # $100 per friend is the most the bot accepts
_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")


async def _referral_text(db: Database) -> str:
    cfg = await loyalty.get_referral_config(db)
    stats = await loyalty.referral_admin_stats(db)
    state = "✅ ON" if loyalty.referral_active(cfg) else "⏸ OFF (nothing is paid)"
    return (
        "🎁 <b>Friend referral</b>\n\n"
        f"Status: <b>{state}</b>\n"
        f"Reward for the inviter: <b>{money(cfg['reward_cents'])}</b> (once per friend)\n"
        f"The friend's order must be at least: <b>{money(cfg['min_cents'])}</b>\n"
        f"Max rewards per inviter per month: <b>{cfg['cap_month']}</b>\n\n"
        f"Customers invited so far: <b>{stats['invited']}</b>\n"
        f"Rewards paid: <b>{stats['paid_n']}</b> • {money(stats['paid_cents'])}\n\n"
        "The reward is paid after the friend's order is COMPLETED, not at sign-up.\n\n"
        "<code>/referral 0.25</code> set the reward and switch on\n"
        "<code>/referral off</code> or <code>/referral on</code>\n"
        "<code>/referral min 1</code> minimum order in dollars\n"
        "<code>/referral cap 20</code> max rewards per inviter per month")


@router.message(Command("referral"))
async def cmd_referral(message: Message, command: CommandObject, db: Database):
    args = (command.args or "").split()
    if not args:
        await message.answer(await _referral_text(db))
        return
    first = args[0].lower()
    if first in ("on", "off"):
        cfg = await loyalty.get_referral_config(db)
        if first == "on" and cfg["reward_cents"] <= 0:
            await message.answer("⚠️ First set the reward, for example <code>/referral 0.25</code>.")
            return
        await repo.set_setting(db, "ref_on", "1" if first == "on" else "0")
    elif first in ("min", "cap") and len(args) == 2:
        if first == "min":
            cents = parse_money(args[1])
            if cents is None or cents <= 0 or cents > 100_000:
                await message.answer("⚠️ Use dollars, for example <code>/referral min 1</code>.")
                return
            await repo.set_setting(db, "ref_min_cents", str(cents))
        else:
            if not args[1].isdigit() or not 1 <= int(args[1]) <= 1000:
                await message.answer("⚠️ Use a number from 1 to 1000, for example "
                                     "<code>/referral cap 20</code>.")
                return
            await repo.set_setting(db, "ref_cap_month", args[1])
    elif len(args) == 1:
        cents = parse_money(args[0])
        if cents is None or cents <= 0 or cents > MAX_REWARD_CENTS:
            await message.answer(
                f"⚠️ Use dollars between 0.01 and {MAX_REWARD_CENTS // 100}, "
                "for example <code>/referral 0.25</code>.")
            return
        await repo.set_setting(db, "ref_reward_cents", str(cents))
        await repo.set_setting(db, "ref_on", "1")
    else:
        await message.answer(await _referral_text(db))
        return
    await message.answer("✅ Saved.\n\n" + await _referral_text(db))


async def _levels_text(db: Database) -> str:
    levels = await loyalty.get_levels(db)
    lines = [f"{loyalty.LEVEL_ICONS[i]} <b>{esc(n)}</b> — from {money(c)} spent"
             for i, (n, c) in enumerate(levels)]
    return ("🏅 <b>Membership levels</b>\n(counted from COMPLETED orders)\n\n" + "\n".join(lines)
            + "\n\n<code>/levels Bronze=0 Silver=20 Gold=50 Diamond=100</code>\n"
              "Names: letters/numbers/_ only (max 16). The first must be 0. 2 to "
            f"{loyalty.MAX_LEVELS} levels.\n<code>/levels reset</code> back to the default steps")


@router.message(Command("levels"))
async def cmd_levels(message: Message, command: CommandObject, db: Database):
    args = (command.args or "").split()
    if not args:
        await message.answer(await _levels_text(db))
        return
    if args == ["reset"]:
        await repo.set_setting(db, "levels", "")
        await message.answer("✅ Back to the default steps.\n\n" + await _levels_text(db))
        return
    levels, seen = [], set()
    for token in args:
        name, _, amount = token.partition("=")
        cents = parse_money(amount) if amount else None
        if not _NAME_RE.match(name) or cents is None or name.lower() in seen:
            await message.answer(
                f"⚠️ <code>{esc(token)}</code> is not valid. Write it like "
                "<code>Silver=20</code> (name, equals sign, dollars). Names must be different.")
            return
        seen.add(name.lower())
        levels.append((name, cents))
    levels.sort(key=lambda x: x[1])
    if not 2 <= len(levels) <= loyalty.MAX_LEVELS or levels[0][1] != 0:
        await message.answer(f"⚠️ Give 2 to {loyalty.MAX_LEVELS} levels and make the lowest one "
                             "<code>=0</code>, for example <code>Bronze=0</code>.")
        return
    await repo.set_setting(db, "levels", json.dumps(levels))
    await message.answer("✅ Saved.\n\n" + await _levels_text(db))
