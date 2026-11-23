"""All customer-facing text in English (en) and Khmer (km)."""

TEXTS = {
    "en": {
        "menu_buy": "💎 Buy Diamonds",
        "menu_orders": "📦 My Orders",
        "menu_wallet": "👛 My Wallet",
        "menu_deposit": "➕ Deposit Money",
        "menu_promos": "🎁 Promotions",
        "menu_support": "💬 Contact Support",
        "menu_history": "🧾 Transaction History",
        "menu_howto": "ℹ️ How to Use",
        "menu_language": "🌐 Language / ភាសា",
        "choose_language": "🌐 Please choose your language\nសូមជ្រើសរើសភាសារបស់អ្នក",
        "language_changed": "✅ Language set to English.",
        "welcome": (
            "👑 <b>Welcome to DIAMOND ZS</b>\n\n"
            "Hello, {name}! Top up your favorite games quickly and safely.\n\n"
            "Use the menu below to get started. 👇"
        ),
        "menu_hint": "Please choose an option from the menu below 👇",
        "btn_confirm": "✅ Confirm",
        "btn_cancel": "❌ Cancel",
        "btn_back": "⬅️ Back",
        "btn_deposit": "➕ Deposit",
        "btn_history": "🧾 History",
        "choose_game": "💎 <b>Buy Diamonds</b>\nChoose your game:",
        "choose_package": "{game}\nChoose a package:",
        "no_products": "No packages are available for this game yet. Please check back soon.",
        "product_unavailable": "Sorry, this package is not available right now.",
        "ask_player_id": (
            "You selected <b>{product}</b> ({price}).\n\n"
            "Please send your <b>{game} Player ID</b> (numbers only):"
        ),
        "ask_server_id": "Now send your <b>Server / Zone ID</b> (numbers only):",
        "invalid_player_id": "⚠️ Invalid ID. Please send numbers only (5–15 digits).",
        "invalid_server_id": "⚠️ Invalid Zone ID. Please send numbers only (1–6 digits).",
        "order_summary": (
            "🧾 <b>Order Summary</b>\n\n"
            "Game: {game}\nPackage: {product}\nPlayer ID: <code>{player_id}</code>{server_line}\n"
            "Price: <b>{price}</b>\nYour balance: {balance}\n\n"
            "Please check carefully, then confirm."
        ),
        "server_line": "\nZone ID: <code>{server_id}</code>",
        "order_created": (
            "✅ <b>Order #{id} received!</b>\n\n"
            "{price} was taken from your wallet. Your order is <b>pending</b>. "
            "Our team processes orders manually and will notify you here."
        ),
        "insufficient": (
            "❌ Not enough balance. You need {price} but have {balance}.\n"
            "Please use ➕ Deposit Money first."
        ),
        "duplicate_order": "⚠️ You already have an identical pending order. Please wait for it to be processed.",
        "flow_cancelled": "Cancelled ✅",
        "session_expired": "This session expired. Please start again from the menu.",
        "orders_title": "📦 <b>My Orders</b> (latest 10)",
        "orders_empty": "You have no orders yet.",
        "order_line": "#{id} • {product} • {price} • {status}\n   ID: <code>{player_id}</code> • {date}",
        "status_pending": "⏳ Pending",
        "status_completed": "✅ Completed",
        "status_cancelled": "❌ Cancelled",
        "wallet": "👛 <b>My Wallet</b>\n\nBalance: <b>{balance}</b>",
        "deposit_intro": (
            "➕ <b>Deposit Money</b>\n\n"
            "Automatic payments are not available yet. Send the amount you want to "
            "deposit (example: <code>5</code> or <code>10.50</code>).\n"
            "Then contact support to pay. Your wallet is credited only after our team "
            "confirms your payment manually.\n\nSend /cancel to stop."
        ),
        "deposit_pending_exists": (
            "⏳ You already have a pending deposit request of {amount} (#{id}). "
            "Please wait for confirmation or contact support."
        ),
        "invalid_amount": "⚠️ Invalid amount. Send a number like 5 or 10.50 (between $0.50 and $1000).",
        "deposit_created": (
            "✅ Deposit request #{id} for {amount} created.\n"
            "Please contact {support} to complete payment. "
            "Your wallet will be credited after our team confirms it."
        ),
        "deposit_approved_user": "✅ Your deposit #{id} of {amount} was approved. New balance: {balance}",
        "deposit_rejected_user": "❌ Your deposit request #{id} ({amount}) was rejected. Please contact support.",
        "balance_added_user": "💰 {amount} was added to your wallet. New balance: {balance}",
        "balance_deducted_user": "💳 {amount} was deducted from your wallet. New balance: {balance}",
        "deposit_intro_auto": (
            "➕ <b>Deposit Money</b>\n\n"
            "Send the amount you want to deposit in USD "
            "(example: <code>5</code> or <code>10.50</code>).\n"
            "I will show a KHQR to pay with ABA Mobile, and your wallet is credited "
            "automatically after you pay.\n\nSend /cancel to stop."
        ),
        "deposit_qr_caption": (
            "💳 <b>Deposit #{id} — {amount}</b>\n\n"
            "Scan this KHQR with <b>ABA Mobile</b> and pay exactly {amount}.\n"
            "⏱ The code expires in about {seconds} seconds.\n"
            "⚠️ Only a payment made through this QR is detected. "
            "A normal bank transfer will NOT be credited.\n\n"
            "Your wallet is credited automatically after payment."
        ),
        "deposit_paid_user": "✅ Payment received! Deposit #{id} of {amount} was added. New balance: {balance}",
        "deposit_expired_user": "⌛ Deposit #{id} ({amount}) was not paid in time and has been closed. You can start a new deposit anytime.",
        "deposit_cancelled_user": "❎ Deposit #{id} ({amount}) was cancelled.",
        "deposit_mismatch_user": (
            "⚠️ We received a payment for deposit #{id}, but the amount did not match, "
            "so it was not credited automatically. Please contact {support} with your payment receipt."
        ),
        "deposit_gateway_error": "⚠️ The payment service is not available right now. Please try again in a few minutes or contact {support}.",
        "deposit_check_wait": "⏳ Payment not received yet. Scan the QR, pay, then try again.",
        "btn_check_payment": "🔄 Check payment",
        "btn_pay_page": "💳 Open payment page",
        "order_completed_user": "✅ Your order #{id} ({product}) is completed. Thank you!",
        "order_created_auto": (
            "✅ <b>Order #{id} received!</b>\n\n"
            "{price} was taken from your wallet. We are delivering your diamonds "
            "automatically - you will get a message here in a few seconds."
        ),
        "order_review_user": (
            "⏳ Your order #{id} ({product}) needs a quick check by our team. "
            "Your money is safe. We will update you here very soon."
        ),
        "order_cancelled_user": "❌ Your order #{id} ({product}) was cancelled. {price} was refunded to your wallet.",
        "history_title": "🧾 <b>Transaction History</b> (latest 15)",
        "history_empty": "No transactions yet.",
        "tx_line": "{date} • {type} • {amount}\n   Balance: {balance}",
        "tx_deposit": "Deposit",
        "tx_purchase": "Purchase",
        "tx_refund": "Refund",
        "tx_referral": "Referral bonus",
        "tx_level": "Membership level bonus",
        "level_up_bonus_user": (
            "🎉 Congratulations! You reached the {icon} <b>{level}</b> membership level.\n"
            "🎁 A bonus of <b>{amount}</b> was added to your wallet. Thank you for shopping with Diamond ZS 💎"
        ),
        "level_up_user": (
            "🎉 Congratulations! You reached the {icon} <b>{level}</b> membership level.\n"
            "Thank you for shopping with Diamond ZS 💎"
        ),
        "referral_reward_user": (
            "🎉 Your friend <b>{friend}</b> made their first purchase!\n"
            "You earned <b>{amount}</b> in your wallet. Keep inviting friends 💎"
        ),
        "promos_empty": "🎁 <b>Promotions</b>\n\nNo promotions right now. Check back soon!",
        "promos_title": "🎁 <b>Promotions</b>\n\n{text}",
        "support": "💬 <b>Contact Support</b>\n\nTalk to us on Telegram: {support}",
        "support_missing": "💬 <b>Contact Support</b>\n\nSupport contact is not set up yet.",
        "howto": (
            "ℹ️ <b>How to Use</b>\n\n"
            "1️⃣ Tap ➕ Deposit Money and request a wallet top-up.\n"
            "2️⃣ Pay as instructed and wait for our team to confirm.\n"
            "3️⃣ Tap 💎 Buy Diamonds, pick a game and a package.\n"
            "4️⃣ Send your Player ID (and Zone ID if asked), then confirm.\n"
            "5️⃣ We process your order and notify you here.\n\n"
            "⚠️ Always double-check your ID. A wrong ID can delay or fail delivery."
        ),
    },
    "km": {
        "menu_buy": "💎 ទិញពេជ្រ",
        "menu_orders": "📦 ការបញ្ជាទិញរបស់ខ្ញុំ",
        "menu_wallet": "👛 កាបូបរបស់ខ្ញុំ",
        "menu_deposit": "➕ ដាក់ប្រាក់",
        "menu_promos": "🎁 ប្រូម៉ូសិន",
        "menu_support": "💬 ទាក់ទងជំនួយ",
        "menu_history": "🧾 ប្រវត្តិប្រតិបត្តិការ",
        "menu_howto": "ℹ️ របៀបប្រើប្រាស់",
        "menu_language": "🌐 Language / ភាសា",
        "choose_language": "🌐 Please choose your language\nសូមជ្រើសរើសភាសារបស់អ្នក",
        "language_changed": "✅ បានប្តូរភាសាទៅជាភាសាខ្មែរ។",
        "welcome": (
            "👑 <b>សូមស្វាគមន៍មកកាន់ DIAMOND ZS</b>\n\n"
            "សួស្តី {name}! បញ្ចូលហ្គេមដែលអ្នកចូលចិត្តបានរហ័ស និងមានសុវត្ថិភាព។\n\n"
            "សូមប្រើម៉ឺនុយខាងក្រោមដើម្បីចាប់ផ្តើម។ 👇"
        ),
        "menu_hint": "សូមជ្រើសរើសជម្រើសពីម៉ឺនុយខាងក្រោម 👇",
        "btn_confirm": "✅ បញ្ជាក់",
        "btn_cancel": "❌ បោះបង់",
        "btn_back": "⬅️ ត្រឡប់ក្រោយ",
        "btn_deposit": "➕ ដាក់ប្រាក់",
        "btn_history": "🧾 ប្រវត្តិ",
        "choose_game": "💎 <b>ទិញពេជ្រ</b>\nសូមជ្រើសរើសហ្គេម៖",
        "choose_package": "{game}\nសូមជ្រើសរើសកញ្ចប់៖",
        "no_products": "មិនទាន់មានកញ្ចប់សម្រាប់ហ្គេមនេះនៅឡើយទេ។ សូមត្រឡប់មកវិញពេលក្រោយ។",
        "product_unavailable": "សូមអភ័យទោស កញ្ចប់នេះមិនអាចទិញបានក្នុងពេលនេះទេ។",
        "ask_player_id": (
            "អ្នកបានជ្រើសរើស <b>{product}</b> ({price})។\n\n"
            "សូមផ្ញើ <b>Player ID របស់ {game}</b> (លេខប៉ុណ្ណោះ)៖"
        ),
        "ask_server_id": "ឥឡូវនេះសូមផ្ញើ <b>Server / Zone ID</b> របស់អ្នក (លេខប៉ុណ្ណោះ)៖",
        "invalid_player_id": "⚠️ ID មិនត្រឹមត្រូវ។ សូមផ្ញើលេខប៉ុណ្ណោះ (៥ ដល់ ១៥ ខ្ទង់)។",
        "invalid_server_id": "⚠️ Zone ID មិនត្រឹមត្រូវ។ សូមផ្ញើលេខប៉ុណ្ណោះ (១ ដល់ ៦ ខ្ទង់)។",
        "order_summary": (
            "🧾 <b>សេចក្តីសង្ខេបការបញ្ជាទិញ</b>\n\n"
            "ហ្គេម៖ {game}\nកញ្ចប់៖ {product}\nPlayer ID៖ <code>{player_id}</code>{server_line}\n"
            "តម្លៃ៖ <b>{price}</b>\nសមតុល្យរបស់អ្នក៖ {balance}\n\n"
            "សូមពិនិត្យឱ្យបានល្អិតល្អន់ រួចបញ្ជាក់។"
        ),
        "server_line": "\nZone ID៖ <code>{server_id}</code>",
        "order_created": (
            "✅ <b>បានទទួលការបញ្ជាទិញលេខ #{id}!</b>\n\n"
            "{price} ត្រូវបានកាត់ពីកាបូបរបស់អ្នក។ ការបញ្ជាទិញកំពុង <b>រង់ចាំ</b>។ "
            "ក្រុមការងារដំណើរការដោយដៃ ហើយនឹងជូនដំណឹងអ្នកនៅទីនេះ។"
        ),
        "insufficient": (
            "❌ សមតុល្យមិនគ្រប់គ្រាន់។ អ្នកត្រូវការ {price} ប៉ុន្តែមាន {balance}។\n"
            "សូមចុច ➕ ដាក់ប្រាក់ ជាមុនសិន។"
        ),
        "duplicate_order": "⚠️ អ្នកមានការបញ្ជាទិញដូចគ្នានេះកំពុងរង់ចាំរួចហើយ។ សូមរង់ចាំឱ្យវាត្រូវបានដំណើរការ។",
        "flow_cancelled": "បានបោះបង់ ✅",
        "session_expired": "សម័យនេះបានផុតកំណត់។ សូមចាប់ផ្តើមឡើងវិញពីម៉ឺនុយ។",
        "orders_title": "📦 <b>ការបញ្ជាទិញរបស់ខ្ញុំ</b> (១០ចុងក្រោយ)",
        "orders_empty": "អ្នកមិនទាន់មានការបញ្ជាទិញនៅឡើយទេ។",
        "order_line": "#{id} • {product} • {price} • {status}\n   ID: <code>{player_id}</code> • {date}",
        "status_pending": "⏳ កំពុងរង់ចាំ",
        "status_completed": "✅ បានបញ្ចប់",
        "status_cancelled": "❌ បានបោះបង់",
        "wallet": "👛 <b>កាបូបរបស់ខ្ញុំ</b>\n\nសមតុល្យ៖ <b>{balance}</b>",
        "deposit_intro": (
            "➕ <b>ដាក់ប្រាក់</b>\n\n"
            "ការទូទាត់ស្វ័យប្រវត្តិមិនទាន់មានទេ។ សូមផ្ញើចំនួនទឹកប្រាក់ដែលអ្នកចង់ដាក់ "
            "(ឧទាហរណ៍៖ <code>5</code> ឬ <code>10.50</code>)។\n"
            "បន្ទាប់មកសូមទាក់ទងជំនួយដើម្បីបង់ប្រាក់។ កាបូបរបស់អ្នកនឹងត្រូវបានបញ្ចូលប្រាក់ "
            "លុះត្រាតែក្រុមការងារបញ្ជាក់ការទូទាត់ដោយដៃ។\n\nផ្ញើ /cancel ដើម្បីបញ្ឈប់។"
        ),
        "deposit_pending_exists": (
            "⏳ អ្នកមានសំណើដាក់ប្រាក់ {amount} (#{id}) កំពុងរង់ចាំរួចហើយ។ "
            "សូមរង់ចាំការបញ្ជាក់ ឬទាក់ទងជំនួយ។"
        ),
        "invalid_amount": "⚠️ ចំនួនទឹកប្រាក់មិនត្រឹមត្រូវ។ សូមផ្ញើលេខដូចជា 5 ឬ 10.50 (ចន្លោះ $0.50 ដល់ $1000)។",
        "deposit_created": (
            "✅ បានបង្កើតសំណើដាក់ប្រាក់លេខ #{id} ចំនួន {amount}។\n"
            "សូមទាក់ទង {support} ដើម្បីបង់ប្រាក់។ "
            "កាបូបរបស់អ្នកនឹងត្រូវបានបញ្ចូលប្រាក់ បន្ទាប់ពីក្រុមការងារបញ្ជាក់។"
        ),
        "deposit_approved_user": "✅ ការដាក់ប្រាក់ #{id} ចំនួន {amount} ត្រូវបានអនុម័ត។ សមតុល្យថ្មី៖ {balance}",
        "deposit_rejected_user": "❌ សំណើដាក់ប្រាក់ #{id} ({amount}) ត្រូវបានបដិសេធ។ សូមទាក់ទងជំនួយ។",
        "balance_added_user": "💰 {amount} ត្រូវបានបន្ថែមចូលកាបូបរបស់អ្នក។ សមតុល្យថ្មី៖ {balance}",
        "balance_deducted_user": "💳 {amount} ត្រូវបានកាត់ចេញពីកាបូបរបស់អ្នក។ សមតុល្យថ្មី៖ {balance}",
        "deposit_intro_auto": (
            "➕ <b>ដាក់ប្រាក់</b>\n\n"
            "សូមផ្ញើចំនួនទឹកប្រាក់ជាដុល្លារដែលអ្នកចង់ដាក់ "
            "(ឧទាហរណ៍៖ <code>5</code> ឬ <code>10.50</code>)។\n"
            "ខ្ញុំនឹងបង្ហាញ KHQR សម្រាប់បង់តាម ABA Mobile ហើយកាបូបរបស់អ្នកនឹងត្រូវបានបញ្ចូលប្រាក់ "
            "ដោយស្វ័យប្រវត្តិក្រោយអ្នកបង់ប្រាក់។\n\nផ្ញើ /cancel ដើម្បីបញ្ឈប់។"
        ),
        "deposit_qr_caption": (
            "💳 <b>ការដាក់ប្រាក់ #{id} — {amount}</b>\n\n"
            "សូមស្កេន KHQR នេះដោយ <b>ABA Mobile</b> ហើយបង់ចំនួន {amount} ឱ្យបានត្រឹមត្រូវ។\n"
            "⏱ កូដនេះនឹងផុតកំណត់ក្នុងរយៈពេលប្រហែល {seconds} វិនាទី។\n"
            "⚠️ មានតែការបង់តាម QR នេះប៉ុណ្ណោះដែលត្រូវបានរកឃើញ។ "
            "ការផ្ទេរប្រាក់ធម្មតានឹងមិនត្រូវបានបញ្ចូលទេ។\n\n"
            "កាបូបរបស់អ្នកនឹងត្រូវបានបញ្ចូលប្រាក់ដោយស្វ័យប្រវត្តិក្រោយបង់ប្រាក់។"
        ),
        "deposit_paid_user": "✅ បានទទួលការបង់ប្រាក់! ការដាក់ប្រាក់ #{id} ចំនួន {amount} ត្រូវបានបន្ថែម។ សមតុល្យថ្មី៖ {balance}",
        "deposit_expired_user": "⌛ ការដាក់ប្រាក់ #{id} ({amount}) មិនត្រូវបានបង់ទាន់ពេល ហើយត្រូវបានបិទ។ អ្នកអាចចាប់ផ្ដើមការដាក់ប្រាក់ថ្មីបានគ្រប់ពេល។",
        "deposit_cancelled_user": "❎ ការដាក់ប្រាក់ #{id} ({amount}) ត្រូវបានលុបចោល។",
        "deposit_mismatch_user": (
            "⚠️ យើងបានទទួលការបង់ប្រាក់សម្រាប់ការដាក់ប្រាក់ #{id} ប៉ុន្តែចំនួនទឹកប្រាក់មិនត្រូវគ្នា "
            "ដូច្នេះមិនបានបញ្ចូលដោយស្វ័យប្រវត្តិទេ។ សូមទាក់ទង {support} ជាមួយបង្កាន់ដៃបង់ប្រាក់។"
        ),
        "deposit_gateway_error": "⚠️ សេវាទូទាត់មិនទាន់អាចប្រើបាននៅពេលនេះទេ។ សូមព្យាយាមម្ដងទៀតក្នុងរយៈពេលប៉ុន្មាននាទី ឬទាក់ទង {support}។",
        "deposit_check_wait": "⏳ មិនទាន់ទទួលបានការបង់ប្រាក់ទេ។ សូមស្កេន QR បង់ប្រាក់ រួចសាកល្បងម្ដងទៀត។",
        "btn_check_payment": "🔄 ពិនិត្យការបង់ប្រាក់",
        "btn_pay_page": "💳 បើកទំព័របង់ប្រាក់",
        "order_completed_user": "✅ ការបញ្ជាទិញ #{id} ({product}) បានបញ្ចប់។ អរគុណ!",
        "order_created_auto": (
            "✅ <b>បានទទួលការបញ្ជាទិញ #{id}!</b>\n\n"
            "{price} ត្រូវបានកាត់ចេញពីកាបូបរបស់អ្នក។ យើងកំពុងដឹកជូនពេជ្រដោយស្វ័យប្រវត្តិ "
            "អ្នកនឹងទទួលបានសារនៅទីនេះក្នុងរយៈពេលប៉ុន្មានវិនាទី។"
        ),
        "order_review_user": (
            "⏳ ការបញ្ជាទិញ #{id} ({product}) ត្រូវការការត្រួតពិនិត្យរហ័សពីក្រុមការងារ។ "
            "លុយរបស់អ្នកមានសុវត្ថិភាព។ យើងនឹងជូនដំណឹងអ្នកនៅទីនេះឆាប់ៗ។"
        ),
        "order_cancelled_user": "❌ ការបញ្ជាទិញ #{id} ({product}) ត្រូវបានលុបចោល។ {price} ត្រូវបានសងចូលកាបូបរបស់អ្នកវិញ។",
        "history_title": "🧾 <b>ប្រវត្តិប្រតិបត្តិការ</b> (១៥ចុងក្រោយ)",
        "history_empty": "មិនទាន់មានប្រតិបត្តិការនៅឡើយទេ។",
        "tx_line": "{date} • {type} • {amount}\n   សមតុល្យ៖ {balance}",
        "tx_deposit": "ដាក់ប្រាក់",
        "tx_purchase": "ទិញ",
        "tx_refund": "សងប្រាក់វិញ",
        "tx_referral": "ប្រាក់រង្វាន់ណែនាំមិត្ត",
        "tx_level": "ប្រាក់រង្វាន់កម្រិតសមាជិក",
        "level_up_bonus_user": (
            "🎉 សូមអបអរសាទរ! អ្នកបានឡើងដល់កម្រិតសមាជិក {icon} <b>{level}</b>។\n"
            "🎁 ប្រាក់រង្វាន់ <b>{amount}</b> ត្រូវបានបន្ថែមក្នុងកាបូបរបស់អ្នក។ អរគុណដែលជឿទុកចិត្ត Diamond ZS 💎"
        ),
        "level_up_user": (
            "🎉 សូមអបអរសាទរ! អ្នកបានឡើងដល់កម្រិតសមាជិក {icon} <b>{level}</b>។\n"
            "អរគុណដែលជឿទុកចិត្ត Diamond ZS 💎"
        ),
        "referral_reward_user": (
            "🎉 មិត្តភក្តិ <b>{friend}</b> បានទិញលើកដំបូង!\n"
            "អ្នកបានទទួល <b>{amount}</b> ក្នុងកាបូប។ សូមបន្តអញ្ជើញមិត្តភក្តិ 💎"
        ),
        "promos_empty": "🎁 <b>ប្រូម៉ូសិន</b>\n\nមិនទាន់មានប្រូម៉ូសិនទេពេលនេះ។ សូមត្រឡប់មកវិញពេលក្រោយ!",
        "promos_title": "🎁 <b>ប្រូម៉ូសិន</b>\n\n{text}",
        "support": "💬 <b>ទាក់ទងជំនួយ</b>\n\nនិយាយជាមួយយើងលើ Telegram៖ {support}",
        "support_missing": "💬 <b>ទាក់ទងជំនួយ</b>\n\nមិនទាន់បានកំណត់ទំនាក់ទំនងជំនួយនៅឡើយទេ។",
        "howto": (
            "ℹ️ <b>របៀបប្រើប្រាស់</b>\n\n"
            "1️⃣ ចុច ➕ ដាក់ប្រាក់ ហើយស្នើសុំបញ្ចូលប្រាក់ក្នុងកាបូប។\n"
            "2️⃣ បង់ប្រាក់តាមការណែនាំ ហើយរង់ចាំក្រុមការងារបញ្ជាក់។\n"
            "3️⃣ ចុច 💎 ទិញពេជ្រ ហើយជ្រើសរើសហ្គេម និងកញ្ចប់។\n"
            "4️⃣ ផ្ញើ Player ID (និង Zone ID បើត្រូវបានស្នើ) រួចបញ្ជាក់។\n"
            "5️⃣ យើងដំណើរការការបញ្ជាទិញ ហើយជូនដំណឹងអ្នកនៅទីនេះ។\n\n"
            "⚠️ សូមពិនិត្យ ID ឱ្យបានច្បាស់។ ID ខុសអាចធ្វើឱ្យយឺត ឬបរាជ័យក្នុងការដឹកជូន។"
        ),
    },
}

MENU_KEYS = ["buy", "orders", "wallet", "deposit", "promos", "support", "history", "howto", "language"]


# Texts edited by an admin from inside the bot (/settext). Filled from the database
# at start-up and updated live, so no restart is needed.  {(lang, key): text}
OVERRIDES: dict = {}


def t(lang: str, key: str, **kwargs) -> str:
    """Look up a text in the user's language (falls back to English).

    An admin-edited text (see /settext) wins over the original one. If an edited
    text is somehow broken, the original text is used instead - so the bot never
    fails to answer a customer.
    """
    table = TEXTS.get(lang) or TEXTS["en"]
    custom = OVERRIDES.get((lang if lang in TEXTS else "en", key))
    if custom is not None:
        try:
            return custom.format(**kwargs) if kwargs else custom
        except (KeyError, IndexError, ValueError):
            pass
    template = table.get(key) or TEXTS["en"][key]
    return template.format(**kwargs) if kwargs else template


def menu_labels(key: str) -> set:
    """Both language versions of a menu button, so any user's tap is recognised."""
    return {TEXTS["en"][f"menu_{key}"], TEXTS["km"][f"menu_{key}"]}
