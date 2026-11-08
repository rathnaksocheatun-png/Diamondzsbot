# 👑 DIAMOND ZS – Telegram Game Top-Up Bot (version 1)

Games: Free Fire, Mobile Legends: Bang Bang, PUBG Mobile, Honor of Kings.
Languages: English + Khmer. Database: SQLite (one file, no setup).

## What version 1 does (and does NOT do)

DOES: menus in 2 languages, customer registration, wallet, manual deposit
requests, orders paid from the wallet, order history, transaction history,
admin panel (customers, orders, products, prices, deposits, sales report).

DOES NOT (on purpose): no real payment gateway, no supplier API, no automatic
top-ups. Deposits are approved by an admin BY HAND after you really received
the money. Orders are completed by an admin BY HAND after you delivered the
diamonds. Nothing is faked.

The prices of the Free Fire packages are SAMPLE prices. Change them in the
admin panel before using the bot with real customers.

## Step 1 – Create your bot (on your iPhone, in Telegram)

1. Open Telegram and search for **@BotFather** (blue tick).
2. Send `/newbot`, choose a name and a username ending in `bot`.
3. BotFather sends you a **token** like `123456789:ABCdef...`. Keep it SECRET.
4. Search for **@userinfobot**, press Start, and note your numeric **Id**.

## Step 2 – Where the bot runs

A bot must run 24/7 on a computer that stays on. An iPhone cannot run this
Python project. Pick ONE:

A) Your own Windows/Mac computer (good for testing; the bot stops when you
   close it).
B) A cloud service you can control from the iPhone browser (for example
   Replit, or any VPS/Python host). Steps differ per service; see below.

## Step 3A – Run on a computer

1. Install Python 3.12 or newer from python.org.
2. Unzip this project and open a terminal inside the `diamond_zs` folder.
3. Create a private environment and install the libraries:

       python -m venv .venv
       # Windows:   .venv\Scripts\activate
       # Mac/Linux: source .venv/bin/activate
       pip install -r requirements.txt

4. Create your secrets file:

       # Windows:   copy .env.example .env
       # Mac/Linux: cp .env.example .env

5. Open `.env` in a text editor and replace the PASTE_... values:

       BOT_TOKEN=123456789:ABCdef...
       ADMIN_IDS=987654321
       SUPPORT_USERNAME=@your_support_username

6. Start the bot:

       python main.py

   You should see: `Bot started as @yourbot`. Leave the window open.
7. In Telegram open your bot, press Start. Send `/admin` for the admin panel.

## Step 3B – Run in the cloud (from iPhone)

1. Create a Python project and upload all files (keep the folder layout).
2. Do NOT upload a real `.env`. Instead add these as **Secrets /
   Environment variables** in the service: `BOT_TOKEN`, `ADMIN_IDS`,
   `SUPPORT_USERNAME`.
3. In the service's shell run `pip install -r requirements.txt`.
4. Set the run command to `python main.py` and press Run.
5. Make sure the service keeps the `data/` folder between restarts,
   otherwise the database (customers, wallets, orders) is lost.

## Keeping your token safe

- The token only lives in `.env` (or the host's Secrets). Never in code.
- Never send `.env` to anyone or post screenshots of it.
- If the token leaks: @BotFather -> `/revoke` -> pick the bot -> get a new
  token, then update `.env`.

## Test checklist

1. /start -> choose language -> main menu appears.
2. 👛 My Wallet shows $0.00. ➕ Deposit Money -> send `5`.
3. Admin (/admin) gets a message -> 💰 Deposits -> Approve.
4. Customer: 💎 Buy Diamonds -> Free Fire -> a package -> Player ID
   (8-12 digits) -> Confirm. Balance goes down.
5. Admin: 📦 Orders -> open the order -> Mark completed (or Cancel + refund).
6. Tap the same Confirm twice quickly: only ONE order is created.

## Folder map

    main.py                 starts the bot
    app/config.py           reads .env
    app/texts.py            English + Khmer texts
    app/database/           tables + queries (SQLite)
    app/services/           rules: orders, wallet, reports
    app/keyboards/          buttons (customer + admin)
    app/handlers/           what happens on each tap/message
    app/utils/              validation, formatting, filters, helpers
