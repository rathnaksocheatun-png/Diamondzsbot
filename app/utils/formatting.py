"""Small helpers for showing money, dates and safe text."""
import html


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def esc(value) -> str:
    """Escape text so user-provided names can't break our HTML messages."""
    return html.escape(str(value or ""), quote=False)


def short_date(value: str) -> str:
    """'2026-11-07 16:31:15' -> '2026-11-07 16:31'."""
    return (value or "")[:16]
