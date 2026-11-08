"""Conversation steps (a 'state' remembers where the user is in a flow)."""
from aiogram.fsm.state import State, StatesGroup


class OrderFlow(StatesGroup):
    player_id = State()
    server_id = State()
    confirm = State()


class DepositFlow(StatesGroup):
    amount = State()


class AdminFlow(StatesGroup):
    add_name = State()
    add_price = State()
    edit_price = State()
    edit_name = State()
    promo = State()
    b2g_margin = State()
    game_name = State()
    game_emoji = State()
    product_emoji = State()
    game_pkg_emoji = State()
