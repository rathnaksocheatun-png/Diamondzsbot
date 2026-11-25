"""Admin only: Lucky wheel statistics button (Admin panel -> 🎡 Lucky wheel stats)."""
from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.database.db import Database
from app.keyboards import admin as kb
from app.services import reports
from app.utils.filters import IsAdmin
from app.utils.formatting import money
from app.utils.telegram import edit_or_send

router = Router(name="spin_admin")
router.callback_query.filter(IsAdmin())


@router.callback_query(F.data == "adm:spin")
async def cb_spin_stats(cb: CallbackQuery, db: Database):
    r = await reports.spin_report(db)
    src, prz, sold = r["by_source"], r["by_prize"], r["sold"]
    net = sold["revenue"] - r["total"]["paid"]
    lines = [
        "🎡 <b>Lucky wheel</b>", "",
        f"🔄 បង្វិលសរុប: <b>{r['total']['n']}</b> (ថ្ងៃនេះ: {r['today']['n']})",
        f"👥 អ្នកលេង: {r['total']['players']}",
        f"🎁 ឥតគិតថ្លៃ: {src.get('free', 0)} • 🪙 ប្រើកាក់: {src.get('coin', 0)} • 🔁 ថែម: {src.get('bonus', 0)}",
        "",
        "<b>🏆 លទ្ធផល</b>",
        f"$0.05: {prz.get(5, 0)} • $0.10: {prz.get(10, 0)} • $0.50: {prz.get(50, 0)}",
        f"អត់បាន / បង្វិលថែម: {prz.get(0, 0)}",
        "",
        "<b>💸 លុយ</b>",
        f"រង្វាន់ចំណាយសរុប: <b>{money(r['total']['paid'])}</b> (ថ្ងៃនេះ: {money(r['today']['paid'])})",
        f"ចំណូលលក់កាក់: <b>{money(sold['revenue'])}</b> ({sold['buys']} ដង • {sold['coins']} កាក់)",
        f"📈 ចំណេញសុទ្ធ: <b>{money(net)}</b>",
        f"🪙 កាក់នៅអតិថិជន: {r['held']}",
    ]
    await cb.answer()
    await edit_or_send(cb, "\n".join(lines), kb.simple_home_kb())
