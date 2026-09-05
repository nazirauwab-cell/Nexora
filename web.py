import os
import sqlite3
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, request, render_template_string, jsonify, session, redirect

from Nexora import (
    setup_database,
    ask_nexora,
    get_answer,
    save_chat,
    get_all_chats,
    find_offline_answer,
)

try:
    from Nexora import delete_chat, delete_all_chats
except ImportError:
    delete_chat = None
    delete_all_chats = None


# ============================================================
# NEXORA WEB APP
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "CHANGE_THIS_SECRET_KEY"
)

# ============================================================
# SETTINGS
# ============================================================

API_KEY = os.environ.get("OPENROUTER_API_KEY")

PAYSTACK_SECRET_KEY = os.environ.get(
    "PAYSTACK_SECRET_KEY"
)

PAYSTACK_PUBLIC_KEY = os.environ.get(
    "PAYSTACK_PUBLIC_KEY",
    ""
)

# Free users get 10 chats per month.
FREE_CHATS_PER_MONTH = int(
    os.environ.get(
        "FREE_CHATS_PER_MONTH",
        "10"
    )
)

# Paid users get 2,000 chats per month.
PAID_CHATS_PER_MONTH = 2000

# Price = ₦2,000
PAYMENT_AMOUNT = 200000

AUTH_DB = "nexora_users.db"


# ============================================================
# START NEXORA DATABASE
# ============================================================

setup_database()


# ============================================================
# USER DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(AUTH_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_db():
    conn = db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            paid_until TEXT,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS usage (
            user_id INTEGER NOT NULL,
            usage_date TEXT NOT NULL,
            chat_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, usage_date)
        )
    """)

    conn.commit()
    conn.close()


init_auth_db()


# ============================================================
# USERS
# ============================================================

def current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    conn = db()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    conn.close()

    return user


def get_or_create_user(email):
    email = email.strip().lower()

    if not email or "@" not in email:
        return None

    conn = db()

    conn.execute(
        """
        INSERT INTO users (
            email,
            created_at
        )
        VALUES (?, ?)
        ON CONFLICT(email) DO NOTHING
        """,
        (
            email,
            datetime.now(timezone.utc).isoformat()
        )
    )

    conn.commit()

    user = conn.execute(
        "SELECT * FROM users WHERE email = ?",
        (email,)
    ).fetchone()

    conn.close()

    return user


# ============================================================
# PAYMENT STATUS
# ============================================================

def is_paid(user):
    if not user:
        return False

    if not user["paid_until"]:
        return False

    try:
        paid_until = datetime.fromisoformat(
            user["paid_until"]
        )

        return paid_until > datetime.now(timezone.utc)

    except ValueError:
        return False


def set_paid_for_30_days(user_id):
    paid_until = (
        datetime.now(timezone.utc)
        + timedelta(days=30)
    )

    conn = db()

    conn.execute(
        """
        UPDATE users
        SET paid_until = ?
        WHERE id = ?
        """,
        (
            paid_until.isoformat(),
            user_id
        )
    )

    conn.commit()
    conn.close()


# ============================================================
# MONTHLY USAGE
# ============================================================

def month_key():
    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m")


def chats_used_this_month(user_id):
    month = month_key()

    conn = db()

    row = conn.execute(
        """
        SELECT chat_count
        FROM usage
        WHERE user_id = ?
        AND usage_date = ?
        """,
        (
            user_id,
            month
        )
    ).fetchone()

    conn.close()

    if row:
        return int(row["chat_count"])

    return 0


def increment_chat_usage(user_id):
    month = month_key()

    conn = db()

    conn.execute(
        """
        INSERT INTO usage (
            user_id,
            usage_date,
            chat_count
        )
        VALUES (?, ?, 1)

        ON CONFLICT(user_id, usage_date)
        DO UPDATE SET
            chat_count = chat_count + 1
        """,
        (
            user_id,
            month
        )
    )

    conn.commit()
    conn.close()


def get_chat_limit(user):
    if is_paid(user):
        return PAID_CHATS_PER_MONTH

    return FREE_CHATS_PER_MONTH


def chats_remaining(user):
    used = chats_used_this_month(
        user["id"]
    )

    limit = get_chat_limit(user)

    return max(
        limit - used,
        0
    )


# ============================================================
# PAYSTACK
# ============================================================

def paystack_headers():
    return {
        "Authorization":
            f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type":
            "application/json",
    }


# ============================================================
# WEBSITE HTML
# ============================================================

HTML = r"""
<!doctype html>

<html lang="en">

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1"
>

<title>Nexora — Your Personal AI Assistant</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family:
        Arial,
        Helvetica,
        sans-serif;

    background: #f4f6f8;
    color: #171717;
}

.container {
    max-width: 900px;
    margin: auto;
    padding: 18px;
}

header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
}

.logo {
    font-size: 28px;
    font-weight: 700;
}

.tagline {
    color: #666;
    margin-top: 4px;
}

.card {
    background: white;
    border-radius: 16px;
    padding: 18px;
    margin-top: 16px;

    box-shadow:
        0 4px 18px rgba(0,0,0,.06);
}

input,
button {
    font: inherit;
}

input {
    width: 100%;
    padding: 13px;
    border: 1px solid #ccc;
    border-radius: 10px;
}

button {
    border: 0;
    border-radius: 10px;
    padding: 12px 15px;
    cursor: pointer;
}

.primary {
    background: #111;
    color: white;
}

.secondary {
    background: #e9ecef;
    color: #111;
}

.row {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

.message-row {
    display: grid;
    grid-template-columns: 1fr auto auto;
    gap: 8px;
}

.chatbox {
    white-space: pre-wrap;
    line-height: 1.55;
    padding: 14px;
    border-radius: 12px;
    margin-top: 12px;
}

.user {
    background: #e9ecef;
}

.ai {
    background: white;
    border: 1px solid #eee;
}

.status {
    text-align: center;
    min-height: 24px;
    color: #666;
    margin: 10px 0;
}

.small {
    font-size: 13px;
    color: #666;
}

.plan {
    font-size: 20px;
    font-weight: 700;
}

.remaining {
    font-size: 14px;
    color: #666;
}

@media (max-width: 650px) {

    .message-row {
        grid-template-columns: 1fr;
    }

    .container {
        padding: 12px;
    }

}

</style>

</head>

<body>

<div class="container">

<header>

<div>

<div class="logo">
🤖 Nexora
</div>

<div class="tagline">
Your Personal AI Assistant
</div>

</div>

{% if user %}

<div class="small">
{{ user["email"] }}
</div>

{% endif %}

</header>


{% if not user %}

<div class="card">

<h2>
Welcome to Nexora
</h2>

<p>
Your personal AI assistant.
</p>

<form
    method="post"
    action="/login"
>

<input
    name="email"
    type="email"
    placeholder="Enter your email"
    required
>

<br>
<br>

<button
    class="primary"
    type="submit"
>
Continue
</button>

</form>

</div>


{% else %}


<div class="card">

{% if paid %}

<div class="plan">
⭐ Nexora Plus
</div>

<p>
₦2,000/month
</p>

<p class="small">
Paid access until:
{{ user["paid_until"] }}
</p>

<p class="remaining">
{{ used }} / {{ paid_limit }}
chats used this month
</p>

{% else %}

<div class="plan">
Free Plan
</div>

<p class="remaining">
{{ used }} / {{ free_limit }}
chats used this month
</p>

<button
    class="primary"
    onclick="startPayment()"
>
Upgrade for ₦2,000/month
</button>

{% endif %}

</div>


<div class="card">

<div class="message-row">

<input
    id="message"
    placeholder="Type or speak to Nexora..."
    autocomplete="off"
>

<button
    class="secondary"
    onclick="startListening()"
>
🎤 Speak
</button>

<button
    class="primary"
    onclick="sendMessage()"
>
Send
</button>

</div>


<div
    id="status"
    class="status"
>
Ready
</div>


<div class="row">

<button
    class="secondary"
    onclick="stopSpeaking()"
>
🔇 Stop voice
</button>

<button
    class="secondary"
    onclick="deleteAllChats()"
>
🗑️ Delete all
</button>

<a href="/logout">

<button
    class="secondary"
    type="button"
>
Log out
</button>

</a>

</div>

</div>


<div class="card">

<div id="chat">

{% for chat_id, user_text, ai_text, created in chats %}

<div
    class="chatbox user"
>

<div class="small">
{{ created }}
</div>

<strong>
You:
</strong>

<br>

{{ user_text }}

</div>


<div
    class="chatbox ai"
>

<div class="small">
{{ created }}
</div>

<strong>
Nexora:
</strong>

<br>

<span class="answer">
{{ ai_text }}
</span>


<div
    class="row"
    style="margin-top:10px"
>

<button
    class="secondary"
    onclick="speakText(
        this
        .parentElement
        .parentElement
        .querySelector('.answer')
        .innerText
    )"
>
🔊 Read aloud
</button>


<button
    class="secondary"
    onclick="deleteChat(
        '{{ chat_id }}',
        this
    )"
>
Delete
</button>

</div>

</div>

{% endfor %}

</div>

</div>


{% endif %}

</div>


{% if user %}

<script src="https://js.paystack.co/v2/inline.js"></script>

<script>

const paystackPublicKey =
    {{ paystack_public_key|tojson }};


function setStatus(text) {

    const status =
        document.getElementById("status");

    if (status) {
        status.textContent = text;
    }

}


// ==========================================================
// VOICE OUTPUT
// ==========================================================

function speakText(text) {

    if (!text || !text.trim()) {
        return;
    }

    if (!("speechSynthesis" in window)) {

        setStatus(
            "Voice output is not supported."
        );

        return;
    }

    speechSynthesis.cancel();

    const utterance =
        new SpeechSynthesisUtterance(text);

    utterance.lang = "en-US";
    utterance.rate = 1;

    utterance.onstart = function() {
        setStatus(
            "🔊 Nexora is speaking..."
        );
    };

    utterance.onend = function() {
        setStatus("Ready");
    };

    utterance.onerror = function() {
        setStatus(
            "Voice output error."
        );
    };

    speechSynthesis.speak(
        utterance
    );
}


function stopSpeaking() {

    if ("speechSynthesis" in window) {
        speechSynthesis.cancel();
    }

    setStatus(
        "Voice stopped."
    );

}


// ==========================================================
// VOICE INPUT
// ==========================================================

function startListening() {

    const SpeechRecognition =
        window.SpeechRecognition ||
        window.webkitSpeechRecognition;

    if (!SpeechRecognition) {

        setStatus(
            "Voice input is not supported by this browser."
        );

        return;
    }

    const recognition =
        new SpeechRecognition();

    recognition.lang = "en-US";

    recognition.continuous = false;

    recognition.interimResults = false;

    recognition.maxAlternatives = 1;


    recognition.onstart = function() {

        setStatus(
            "🎤 Listening..."
        );

    };


    recognition.onresult =
        function(event) {

            document.getElementById(
                "message"
            ).value =
                event.results[0][0].transcript;


            setStatus(
                "Voice captured. Press Send."
            );

        };


    recognition.onerror =
        function(event) {

            setStatus(
                "Voice input error: "
                + event.error
            );

        };


    recognition.onend =
        function() {};


    recognition.start();

}


// ==========================================================
// SEND MESSAGE
// ==========================================================

async function sendMessage() {

    const input =
        document.getElementById(
            "message"
        );

    const message =
        input.value.trim();


    if (!message) {
        return;
    }


    setStatus(
        "Nexora is thinking..."
    );


    const formData =
        new FormData();

    formData.append(
        "message",
        message
    );


    try {

        const response =
            await fetch(
                "/",
                {
                    method: "POST",
                    body: formData
                }
            );


        const data =
            await response.json();


        if (response.status === 402) {

            setStatus(
                data.error
            );

            alert(
                data.error
            );

            return;
        }


        if (!response.ok) {

            throw new Error(
                data.error ||
                "Server error"
            );

        }


        const userBox =
            document.createElement(
                "div"
            );

        userBox.className =
            "chatbox user";


        userBox.innerHTML =
            "<strong>You:</strong><br>"
            +
            escapeHtml(message);


        const aiBox =
            document.createElement(
                "div"
            );


        aiBox.className =
            "chatbox ai";


        aiBox.innerHTML =
            "<strong>Nexora:</strong><br>"
            +
            "<span class='answer'>"
            +
            escapeHtml(
                data.answer
            )
            +
            "</span>"
            +
            "<div class='row' style='margin-top:10px'>"
            +
            "<button class='secondary'>"
            +
            "🔊 Read aloud"
            +
            "</button>"
            +
            "</div>";


        aiBox
            .querySelector("button")
            .onclick =
            function() {

                speakText(
                    aiBox
                        .querySelector(
                            ".answer"
                        )
                        .innerText
                );

            };


        document
            .getElementById("chat")
            .appendChild(
                userBox
            );


        document
            .getElementById("chat")
            .appendChild(
                aiBox
            );


        input.value = "";


        setStatus(
            "Ready"
        );


        speakText(
            data.answer
        );


    }

    catch (error) {

        console.error(error);

        setStatus(
            "Connection error: "
            + error.message
        );

    }

}


// ==========================================================
// SECURITY
// ==========================================================

function escapeHtml(value) {

    return value.replace(
        /[&<>"']/g,
        function(c) {

            return {

                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#039;"

            }[c];

        }
    );

}


// ==========================================================
// DELETE ONE CHAT
// ==========================================================

async function deleteChat(
    chatId,
    button
) {

    if (!confirm(
        "Delete this Nexora chat?"
    )) {
        return;
    }


    const response =
        await fetch(
            "/delete_chat",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({
                    chat_id: chatId
                })
            }
        );


    const data =
        await response.json();


    if (
        !response.ok ||
        !data.success
    ) {

        alert(
            data.error ||
            "Could not delete chat."
        );

        return;
    }


    const ai =
        button.closest(
            ".ai"
        );


    const user =
        ai
            ? ai.previousElementSibling
            : null;


    if (user) {
        user.remove();
    }


    if (ai) {
        ai.remove();
    }

}


// ==========================================================
// DELETE ALL CHATS
// ==========================================================

async function deleteAllChats() {

    if (!confirm(
        "Delete ALL Nexora chats?"
    )) {
        return;
    }


    const response =
        await fetch(
            "/delete_all_chats",
            {
                method: "POST"
            }
        );


    const data =
        await response.json();


    if (
        !response.ok ||
        !data.success
    ) {

        alert(
            data.error ||
            "Could not delete chats."
        );

        return;
    }


    document
        .getElementById("chat")
        .innerHTML = "";


    setStatus(
        "All chats deleted."
    );

}


// ==========================================================
// PAYMENT
// ==========================================================

function startPayment() {

    if (!paystackPublicKey) {

        setStatus(
            "Payment is not configured yet."
        );

        return;
    }


    const popup =
        new Paystack();


    popup.checkout({

        key:
            paystackPublicKey,

        email:
            {{ user["email"]|tojson }},

        amount:
            200000,

        currency:
            "NGN",

        reference:
            "NEXORA_" +
            Date.now(),


        onSuccess:
            async function(transaction) {

                setStatus(
                    "Payment received. Verifying..."
                );


                const response =
                    await fetch(
                        "/payment/verify",
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body:
                                JSON.stringify({
                                    reference:
                                        transaction.reference
                                })
                        }
                    );


                const data =
                    await response.json();


                if (data.success) {

                    alert(
                        "Payment successful! Nexora Plus is now active."
                    );

                    location.reload();

                }

                else {

                    setStatus(
                        data.error ||
                        "Payment verification failed."
                    );

                }

            },


        onCancel:
            function() {

                setStatus(
                    "Payment cancelled."
                );

            }

    });

}


// ==========================================================
// ENTER KEY
// ==========================================================

document
    .getElementById("message")
    .addEventListener(
        "keydown",
        function(event) {

            if (
                event.key === "Enter"
            ) {

                event.preventDefault();

                sendMessage();

            }

        }
    );

</script>

{% endif %}

</body>

</html>
"""


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["POST"]
)
def login():

    email = request.form.get(
        "email",
        ""
    ).strip().lower()


    user = get_or_create_user(email)


    if not user:

        return (
            "Please enter a valid email.",
            400
        )


    session["user_id"] = int(user["id"])


    return redirect("/")


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# ============================================================
# HOME / CHAT
# ============================================================

@app.route(
    "/",
    methods=["GET", "POST"]
)
def home():

    user = current_user()


    if not user:

        return render_template_string(

            HTML,

            user=None,

            paid=False,

            chats=[],

            used=0,

            free_limit=
                FREE_CHATS_PER_MONTH,

            paid_limit=
                PAID_CHATS_PER_MONTH,

            paystack_public_key=
                PAYSTACK_PUBLIC_KEY

        )


    # ========================================================
    # SEND MESSAGE
    # ========================================================

    if request.method == "POST":

        message = request.form.get(
                "message",
                ""
            ).strip()


        if not message:

            return jsonify({
                "error":
                    "Message is empty."
            }), 400


        paid = is_paid(user)


        used = chats_used_this_month(
                user["id"]
            )


        limit = PAID_CHATS_PER_MONTH \
            if paid \
            else FREE_CHATS_PER_MONTH


        # Check monthly limit
        if used >= limit:

            if paid:

                error_message = "You have reached your 2,000 chat limit for this month."

            else:

                error_message = "You have reached your free monthly chat limit. Upgrade to Nexora Plus for ₦2,000/month."


            return jsonify({
                "error":
                    error_message
            }), 402


        answer = None


        # ====================================================
        # ONLINE AI
        # ====================================================

        if API_KEY:

            try:

                result = ask_nexora(
                        API_KEY,
                        message
                    )


                if result:

                    answer = get_answer(
                            result
                        )

            except Exception as error:

                print(
                    "API ERROR:",
                    error
                )


        # ====================================================
        # OFFLINE MEMORY
        # ====================================================

        if not answer:

            try:

                answer = find_offline_answer(
                        message
                    )

            except Exception as error:

                print(
                    "OFFLINE MEMORY ERROR:",
                    error
                )


        # ====================================================
        # NO ANSWER
        # ====================================================

        if not answer:

            if API_KEY:

                answer = "Nexora could not get a new AI answer right now."

            else:

                answer = "Nexora is offline and does not have a saved answer for that question yet."


        # ====================================================
        # SAVE CHAT
        # ====================================================

        try:

            save_chat(
                message,
                answer
            )

        except Exception as error:

            print(
                "SAVE CHAT ERROR:",
                error
            )


        # ====================================================
        # INCREASE MONTHLY USAGE
        # ====================================================

        increment_chat_usage(
            user["id"]
        )


        new_used = used + 1


        remaining = max(
                limit - new_used,
                0
            )


        return jsonify({

            "answer":
                answer,

            "paid":
                paid,

            "used":
                new_used,

            "limit":
                limit,

            "remaining":
                remaining

        })


    # ========================================================
    # DISPLAY WEBSITE
    # ========================================================

    chats = get_all_chats() or []


    paid = is_paid(user)


    used = chats_used_this_month(
            user["id"]
        )


    return render_template_string(

        HTML,

        user=user,

        paid=paid,

        chats=chats,

        used=used,

        free_limit=
            FREE_CHATS_PER_MONTH,

        paid_limit=
            PAID_CHATS_PER_MONTH,

        paystack_public_key=
            PAYSTACK_PUBLIC_KEY

    )


# ============================================================
# PAYMENT VERIFICATION
# ============================================================

@app.route(
    "/payment/verify",
    methods=["POST"]
)
def payment_verify():

    user = current_user()


    if not user:

        return jsonify({
            "success": False,
            "error":
                "Not logged in."
        }), 401


    if not PAYSTACK_SECRET_KEY:

        return jsonify({
            "success": False,
            "error":
                "Payment is not configured on the server."
        }), 500


    data = request.get_json(
            silent=True
        ) or {}


    reference = str(
            data.get(
                "reference",
                ""
            )
        ).strip()


    if not reference:

        return jsonify({
            "success": False,
            "error":
                "Missing payment reference."
        }), 400


    try:

        response = requests.get(

                "https://api.paystack.co/"
                "transaction/verify/"
                + reference,

                headers=
                    paystack_headers(),

                timeout=20

            )


        result = response.json()


        if (
            not response.ok
            or not result.get("status")
        ):

            return jsonify({
                "success": False,
                "error":
                    "Paystack verification failed."
            }), 400


        payment = result.get(
                "data",
                {}
            )


        paid_amount = int(
                payment.get(
                    "amount",
                    0
                )
            )


        paid_email = str(
                payment.get(
                    "customer",
                    {}
                ).get(
                    "email",
                    ""
                )
            ).lower()


        # Payment must be successful
        if payment.get(
            "status"
        ) != "success":

            return jsonify({
                "success": False,
                "error":
                    "Payment was not successful."
            }), 400


        # Must be exactly at least ₦2,000
        if paid_amount < PAYMENT_AMOUNT:

            return jsonify({
                "success": False,
                "error":
                    "Incorrect payment amount."
            }), 400


        # Payment email must match account
        if paid_email != user["email"]:

            return jsonify({
                "success": False,
                "error":
                    "Payment email does not match your Nexora account."
            }), 400


        # Activate Plus for 30 days
        set_paid_for_30_days(
            user["id"]
        )


        return jsonify({
            "success": True
        })


    except requests.RequestException as error:

        return jsonify({
            "success": False,
            "error":
                "Payment server connection failed."
        }), 502


# ============================================================
# DELETE ONE CHAT
# ============================================================

@app.route(
    "/delete_chat",
    methods=["POST"]
)
def delete_chat_route():

    if delete_chat is None:

        return jsonify({
            "success": False,
            "error":
                "Nexora.py needs delete_chat()."
        }), 500


    try:

        data = request.get_json(
                silent=True
            ) or {}


        chat_id = data.get(
                "chat_id"
            )


        if chat_id is None:

            return jsonify({
                "success": False,
                "error":
                    "No chat ID provided."
            }), 400


        success = delete_chat(
                chat_id
            )


        if not success:

            return jsonify({
                "success": False,
                "error":
                    "Chat was not found."
            }), 404


        return jsonify({
            "success": True
        })


    except Exception as error:

        return jsonify({
            "success": False,
            "error":
                str(error)
        }), 500


# ============================================================
# DELETE ALL CHATS
# ============================================================

@app.route(
    "/delete_all_chats",
    methods=["POST"]
)
def delete_all_chats_route():

    if delete_all_chats is None:

        return jsonify({
            "success": False,
            "error":
                "Nexora.py needs delete_all_chats()."
        }), 500


    try:

        delete_all_chats()


        return jsonify({
            "success": True
        })


    except Exception as error:

        return jsonify({
            "success": False,
            "error":
                str(error)
        }), 500


# ============================================================
# PAYSTACK WEBHOOK
# ============================================================

@app.route(
    "/paystack/webhook",
    methods=["POST"]
)
def paystack_webhook():

    # Production version should verify
    # X-Paystack-Signature before
    # trusting webhook information.

    return jsonify({
        "received": True
    })


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    port = int(
            os.environ.get(
                "PORT",
                "5000"
            )
        )


    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )