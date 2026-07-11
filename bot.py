import discord
from discord.ext import commands
from flask import Flask, request, session, redirect, url_for, render_template_string, flash
from threading import Thread
import os
import json
import asyncio
import datetime
import re
import time
import urllib.request
import urllib.error
import urllib.parse
import sqlite3
import secrets
import hashlib
from functools import wraps

app = Flask('')
app.secret_key = os.environ.get("PANEL_SECRET_KEY", os.urandom(32))
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=True, SESSION_COOKIE_SAMESITE="Lax")

@app.route('/')
def home():
    discord_status = "désactivé" if not DISCORD_ENABLED else ("connecté" if bot.is_ready() else DISCORD_STATE)
    return {"service": "PinkGift", "panel": "/panel", "discord": discord_status, "derniere_erreur": DISCORD_LAST_ERROR}

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
class PinkGiftBot(commands.Bot):
    async def setup_hook(self):
        try:
            synced = await self.tree.sync()
            print(f"{len(synced)} commande(s) slash synchronisée(s).")
        except discord.HTTPException as error:
            print(f"Synchronisation des commandes slash impossible : {error}")


bot = PinkGiftBot(command_prefix="!", intents=intents)
BOT_LOOP = None
DISCORD_STATE = "démarrage"
DISCORD_LAST_ERROR = ""
ORDER_LOCKS = {}

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "pinkgift.db"))
PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
if SUPABASE_URL.endswith("/rest/v1"):
    SUPABASE_URL = SUPABASE_URL[:-8]
SUPABASE_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)
DISCORD_ENABLED = os.environ.get("DISCORD_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")



def supabase_request(method, path, payload=None, prefer=None):
    headers = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
    if SUPABASE_KEY.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {SUPABASE_KEY}"
    if prefer:
        headers["Prefer"] = prefer
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/{path}", data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as response:
        content = response.read().decode("utf-8")
        return json.loads(content) if content else None


def db_connect():
    connection = sqlite3.connect(DB_PATH, timeout=20)
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    if USE_SUPABASE:
        return
    with db_connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS balances (guild_id INTEGER, user_id INTEGER, cents INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, user_id))")
        db.execute("CREATE TABLE IF NOT EXISTS balance_history (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, delta_cents INTEGER, staff_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        db.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER, message_id INTEGER, user_id INTEGER, service TEXT, amount REAL, paid REAL, status TEXT DEFAULT 'pending', code TEXT DEFAULT '', user_name TEXT DEFAULT '', received_label TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        try:
            db.execute("ALTER TABLE orders ADD COLUMN user_name TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            db.execute("ALTER TABLE orders ADD COLUMN received_label TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass


def get_balance(guild_id, user_id):
    if USE_SUPABASE:
        rows = supabase_request("GET", f"balances?guild_id=eq.{guild_id}&user_id=eq.{user_id}&select=cents")
        return (rows[0]["cents"] if rows else 0) / 100
    with db_connect() as db:
        row = db.execute("SELECT cents FROM balances WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
        return (row["cents"] if row else 0) / 100

def change_balance(guild_id, user_id, delta, staff_id):
    delta_cents = round(float(delta) * 100)
    if USE_SUPABASE:
        result = supabase_request("POST", "rpc/change_balance", {"p_guild_id": guild_id, "p_user_id": user_id, "p_delta_cents": delta_cents, "p_staff_id": staff_id})
        return float(result) / 100
    with db_connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT cents FROM balances WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()
        current = row["cents"] if row else 0
        updated = current + delta_cents
        if updated < 0: raise ValueError("Solde insuffisant")
        db.execute("INSERT INTO balances(guild_id,user_id,cents) VALUES(?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET cents=excluded.cents", (guild_id, user_id, updated))
        db.execute("INSERT INTO balance_history(guild_id,user_id,delta_cents,staff_id) VALUES(?,?,?,?)", (guild_id, user_id, delta_cents, staff_id))
        return updated / 100



def is_balance_ticket(channel) -> bool:
    return bool(getattr(channel, "topic", "") and channel.topic.startswith("pinkgift-balance:"))


def get_balance_ticket_user_id(channel):
    if not is_balance_ticket(channel):
        return None
    parts = channel.topic.split(":")
    if len(parts) < 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def balance_ticket_marked_credited(channel) -> bool:
    return is_balance_ticket(channel) and channel.topic.endswith(":credited")


def balance_was_added_after(guild_id, user_id, created_at) -> bool:
    if created_at is None:
        return False
    created_at_utc = created_at.astimezone(datetime.timezone.utc)
    if USE_SUPABASE:
        since = urllib.parse.quote(created_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), safe="")
        rows = supabase_request(
            "GET",
            f"balance_history?guild_id=eq.{guild_id}&user_id=eq.{user_id}&delta_cents=gt.0&created_at=gte.{since}&select=id&limit=1"
        )
        return bool(rows)
    with db_connect() as db:
        since = created_at_utc.strftime("%Y-%m-%d %H:%M:%S")
        row = db.execute(
            "SELECT id FROM balance_history WHERE guild_id=? AND user_id=? AND delta_cents>0 AND created_at>=? LIMIT 1",
            (guild_id, user_id, since)
        ).fetchone()
        return row is not None


async def mark_balance_ticket_credited(guild, user_id: int):
    if guild is None:
        return
    expected_prefix = f"pinkgift-balance:{user_id}"
    for channel in guild.text_channels:
        topic = channel.topic or ""
        if topic.startswith(expected_prefix) and not channel.name.startswith("closed-") and not topic.endswith(":credited"):
            try:
                await channel.edit(topic=f"{expected_prefix}:credited", reason="Solde ajoute au client")
            except discord.HTTPException as error:
                print(f"Erreur marquage ticket solde credite pour {user_id}: {error}")

def save_order(guild_id, channel_id, message_id, user_id, service, amount, paid, user_name="", received_label=""):
    values = {"guild_id": guild_id, "channel_id": channel_id, "message_id": message_id, "user_id": user_id, "service": service, "amount": amount, "paid": paid, "user_name": user_name, "received_label": received_label}
    if USE_SUPABASE:
        rows = supabase_request("POST", "orders", values, "return=representation")
        return rows[0]["id"]
    with db_connect() as db:
        cursor = db.execute("INSERT INTO orders(guild_id,channel_id,message_id,user_id,service,amount,paid,user_name,received_label) VALUES(?,?,?,?,?,?,?,?,?)", tuple(values.values()))
        return cursor.lastrowid



init_database()


PAYPAL_EMOJI = "<:paypal:1517582845315649751>"
STAFF_ROLE_ID = 1517487833886228550
PURGE_ROLE_ID = 1517495087825817691
NEW_MEMBER_ROLE_ID = 1517580901356277921
TICKET_CATEGORY_ID = 1519898899047776336
VALO_TICKET_CATEGORY_ID = 1519913523440779404
BALANCE_CATEGORY_ID = int(os.environ.get("BALANCE_CATEGORY_ID", TICKET_CATEGORY_ID))
CLOSED_TICKET_CATEGORY_ID = 1517526916549181612
EMBED_CONFIG_URL = os.environ.get("EMBED_CONFIG_URL", "https://raw.githubusercontent.com/ynnlz/pinky-software/main/config_embeds.json")
TICKET_IMAGE_URL = "https://media.discordapp.net/attachments/1517516946390908949/1517517071217332424/Ticket_cree.png?ex=6a369167&is=6a353fe7&hm=ce29c76d8a92020dd78c32b4ef8c7a7a41338df78ecf9455f930b9c0dcb1bd08&=&format=webp&quality=lossless"
TARIFS_THUMBNAIL_URL = "https://media.discordapp.net/attachments/1517516946390908949/1517517070894502108/Produits.png?ex=6a369167&is=6a353fe7&hm=06c63f7fb8cca01a4b847fd53b228c2442a158c7fe04c5f61c858a015c517c24&=&format=webp&quality=lossless"
TARIFS_IMAGE_URL = "https://media.discordapp.net/attachments/1517516946390908949/1517517070554890385/Photo_accueil.png?ex=6a369167&is=6a353fe7&hm=07fe98ebafb4108c5c5288ea0d18e1ce113aeebd25d71c4b433033e914d21e44&=&format=webp&quality=lossless"
ORDER_PENDING_IMAGE_URL = "https://media.discordapp.net/attachments/1517516946390908949/1517517069657309204/Commande_recu.png?ex=6a369167&is=6a353fe7&hm=5a401706a47f8c7571510f5112ea122b3061eca7382f31d077c7bdbe7c690d9a&=&format=webp&quality=lossless"
ORDER_FINISHED_IMAGE_URL = "https://media.discordapp.net/attachments/1517516946390908949/1517517069061456102/commande_fini.png?ex=6a369167&is=6a353fe7&hm=e736d0cec28bfc2192e4f360738654e7b4e446adb36b81d33273845a462ce4b8&=&format=webp&quality=lossless"

PRODUCT_CONFIG = {
    "GOOGLE_PLAY": {"display": "GOOGLE PLAY", "emoji": "<:googleplay:1519907060555186278>", "emoji_ch": "🎮"},
    "STEAM": {"display": "STEAM", "emoji": "<:steam:1519907154545610873>", "emoji_ch": "🎮"},
    "DISCORD_NITRO": {"display": "DISCORD NITRO", "emoji": "<:nitroboost:1524439577656561846>", "emoji_ch": "💎"},
    "PLAYSTATION": {"display": "PLAYSTATION", "emoji": "<:playstation:1519906767268741200>", "emoji_ch": "🎮"},
    "NINTENDO": {"display": "NINTENDO", "emoji": "<:nintendo:1519907394157678632>", "emoji_ch": "🎮"},
    "ZARA": {"display": "ZARA", "emoji": "<:zara:1519907265681948773>", "emoji_ch": "👕"},
    "SEPHORA": {"display": "SEPHORA", "emoji": "<:sephora:1519907492862103742>", "emoji_ch": "💄"},
    "ZALANDO": {"display": "ZALANDO", "emoji": "<:zalando:1519907231812816906>", "emoji_ch": "👟"},
    "ADIDAS": {"display": "ADIDAS", "emoji": "<:adidas:1519906784515588116>", "emoji_ch": "👟"},
    "FOOT_LOCKER": {"display": "FOOT LOCKER", "emoji": "<:footlocker:1519907296342310952>", "emoji_ch": "👟"},
    "SHEIN": {"display": "SHEIN", "emoji": "<:shein:1524439283367411793>", "emoji_ch": "👗"},
    "NIKE": {"display": "NIKE", "emoji": "<:nike:1519906735589167164>", "emoji_ch": "👟"},
    "UBEREATS": {"display": "UBER EATS", "emoji": "<:ubereats:1519907186636099604>", "emoji_ch": "🍔"},
    "DELIVEROO": {"display": "DELIVEROO", "emoji": "<:deliveroo:1519906860356993174>", "emoji_ch": "🍽️"},
    "AMAZON": {"display": "AMAZON", "emoji": "<:amazon:1519907450403160104>", "emoji_ch": "📦"},
    "CARREFOUR": {"display": "CARREFOUR", "emoji": "<:carrefour:1519906825494073414>", "emoji_ch": "🛒"},
    "INTERMARCHE": {"display": "INTERMARCHE", "emoji": "<:intermarche:1519907100057276546>", "emoji_ch": "🏬"},
    "APPLE": {"display": "APPLE", "emoji": "<:apple:1519906800411869204>", "emoji_ch": "🍎"},
    "JOYBUY": {"display": "JOYBUY", "emoji": "<:Joybuy:1524439360638943242>", "emoji_ch": "🛍️"},
    "SMYTHS_TOYS": {"display": "SMYTHS TOYS", "emoji": "<:smythstoys:1519907368429944832>", "emoji_ch": "🧸"},
    "LEGO": {"display": "LEGO", "emoji": "<:lego:1519907470854852720>", "emoji_ch": "🧱"},
    "TESLA": {"display": "TESLA", "emoji": "<:tesla:1524439914811359293>", "emoji_ch": "🚗"},
    "AIRBNB": {"display": "AIRBNB", "emoji": "<:airbnb:1519906701900386344>", "emoji_ch": "🏠"},
    "SKRILL": {"display": "SKRILL", "emoji": "<:skrill:1524440310489288755>", "emoji_ch": "💳"},
    "PAYSAFECARD": {"display": "PAYSAFECARD", "emoji": "<:paysafecard:1519906750571085995>", "emoji_ch": "💳"},
    "VALORANT": {"display": "VALORANT", "emoji": "🎮", "emoji_ch": "🎮"},
}

UBEREATS_PACKS = {20: "28–42", 65: "85–115", 125: "165–225", 350: "501–680"}
NITRO_PRICE = 8

DEFAULT_EMBED_DATA = {
    "images": {
        "paiement_securise": "https://media.discordapp.net/attachments/1517516946390908949/1520055535389638756/paiement_secure.jpg?ex=6a3fcd88&is=6a3e7c08&hm=fcd785c6d9ad1fc767e0df567093a5848bfff636be686eb0e0426d70d3a160bb&=&format=webp",
        "ticket_cree": "https://media.discordapp.net/attachments/1517516946390908949/1520055535632781475/ticket_cree.jpg?ex=6a3fcd88&is=6a3e7c08&hm=09bf5c3a14e418a2771408952bd21c6ae8cb5dcaae845d7948a8e1d3690be48a&=&format=webp&width=1768&height=573",
        "commande_confirmee": "https://media.discordapp.net/attachments/1517516946390908949/1520055535162888263/commande_confirme.jpg?ex=6a3fcd88&is=6a3e7c08&hm=cedcd1942d15b1cdd2a6a2d74566d4e89872d424578caf3e26dbf98c551c3d96&=&format=webp",
        "commande_livree": "https://media.discordapp.net/attachments/1517516946390908949/1520055534819086586/finito_la_commande.jpg?ex=6a3fcd88&is=6a3e7c08&hm=cad0daca6c8a92695ba99bdf18fad7007370c597b06e1dbfe4cecb6c7d2128f1&=&format=webp"
    },
    "tarifs_embed": {
        "title": "🎟️ COMMANDES PINKGIFT",
        "description": [
            "Clique sur **Commander** pour choisir ton produit en privé. Cartes cadeaux à **-30 %**, sauf Uber Eats avec sa grille fixe et Discord Nitro à **8 €**.",
            "",
            "🎮 **GAMING**",
            "<:googleplay:1519907060555186278> **Google Play**", " <:steam:1519907154545610873> **Steam**",
            "<:nitroboost:1524439577656561846> **Discord Nitro — 8 €**", "<:playstation:1519906767268741200> **PlayStation**", "<:nintendo:1519907394157678632> **Nintendo**",
            "",
            "👗 **MODE & BEAUTÉ**",
            "<:zara:1519907265681948773> **Zara**", "<:sephora:1519907492862103742> **Sephora**", "<:zalando:1519907231812816906> **Zalando**",
            "<:adidas:1519906784515588116> **Adidas**", "<:footlocker:1519907296342310952> **Foot Locker**", "<:shein:1524439283367411793> **Shein**", "<:nike:1519906735589167164> **Nike**",
            "",
            "🍔 **FOOD & LIVRAISON**", "<:ubereats:1519907186636099604> **Uber Eats**", "<:deliveroo:1519906860356993174> **Deliveroo**",
            "",
            "🛍️ **SHOPPING & COURSES**", "<:amazon:1519907450403160104> **Amazon**", "<:carrefour:1519906825494073414> **Carrefour**",
            "<:intermarche:1519907100057276546> **Intermarché**", "<:apple:1519906800411869204> **Apple**", "<:Joybuy:1524439360638943242> **Joybuy**",
            "",
            "🧸 **JOUETS**", "<:smythstoys:1519907368429944832> **Smyths Toys**", "<:lego:1519907470854852720> **LEGO**",
            "",
            "🚗 **VOYAGE & AUTO**", "<:tesla:1524439914811359293> **Tesla**", "<:airbnb:1519906701900386344> **Airbnb**",
            "",
            "💳 **PRÉPAYÉ**", "<:skrill:1524440310489288755> **Skrill**", "<:paysafecard:1519906750571085995> **Paysafecard**",
            "",
            "🎫 Clique sur le bouton **Commander** ci-dessous. Les menus sont visibles uniquement par toi."
        ],
        "color_rgb": [255, 192, 203],
        "image_url": ""
    },
    "valo_embed": {
        "title": "💘 VALORANT POINTS 💘",
        "description": [
            "Choisis ton montant. 💞",
            "",
            "🇪🇺 **Europe**",
            "<:vp:1519915966476320901> **3650 VP** — 30€",
            "<:vp:1519915966476320901> **5350 VP** — 40€",
            "<:vp:1519915966476320901> **8700 VP** — 60€",
            "",
            "🇹🇷 **Turquie**",
            "<:vp:1519915966476320901> **2925 VP** — 15€",
            "<:vp:1519915966476320901> **4325 VP** — 20€",
            "<:vp:1519915966476320901> **8900 VP** — 45€",
            "",
            "🛒 Clique sur le bouton ci-dessous pour ouvrir un ticket."
        ],
        "color_rgb": [255, 192, 203],
        "image_url": ""
    },
    "ticket_bienvenue": {
        "title": "🎫 Ticket d achat",
        "description": [
            "Bonjour {user} !",
            "",
            "Merci de l interet que tu portes a PinkGift.",
            "Indique l article et le montant souhaite dans ce ticket.",
            "",
            "Le <@&1517487833886228550> a ete prevenu et va te prendre en charge rapidement.",
            "",
            "⚠️ Les seuls moyens de paiement acceptes sont PayPal & les Virements Bancaires."
        ],
        "color_rgb": [255, 192, 203]
    }
}

DEFAULT_EMBED_DATA.update({
    "menu_ticket_embed": {
        "title": "🎫 Commande — {service}",
        "description": [
            "Bonjour {user} !",
            "",
            "Ta commande a bien été enregistrée. Le staff va te prendre en charge rapidement."
        ],
        "fields": [
            {
                "name": "Service sélectionné",
                "value": "{emoji} **{service}**",
                "inline": False
            },
            {
                "name": "Montant que tu vas recevoir",
                "value": "**{amount} €**",
                "inline": True
            },
            {
                "name": "Montant à payer (-30 %)",
                "value": "**{paid} €**",
                "inline": True
            }
        ],
        "color_rgb": [
            255,
            192,
            203
        ],
        "image_key": "ticket_cree"
    },
    "nitro_ticket_embed": {
        "title": "<:nitroboost:1524439577656561846> Commande — DISCORD NITRO",
        "description": ["Bonjour {user} !", "", "Ta commande Discord Nitro a bien été enregistrée. Le staff va te prendre en charge rapidement."],
        "fields": [
            {"name": "Produit", "value": "{emoji} **{service}**", "inline": False},
            {"name": "Prix", "value": "**{paid} €**", "inline": True},
            {"name": "Solde restant", "value": "**{balance} €**", "inline": True}
        ],
        "color_rgb": [255, 192, 203],
        "image_key": "ticket_cree"
    },
    "valo_ticket_bienvenue_embed": {
        "title": "🎫 Ticket d'achat — VALORANT",
        "description": [
            "Bonjour {user} !",
            "",
            "Merci de l'intérêt que tu portes à PinkGift.",
            "Indique le pack Valorant Points souhaité dans ce ticket.",
            "",
            "Le staff a été prévenu et va te prendre en charge rapidement."
        ],
        "color_rgb": [
            255,
            192,
            203
        ],
        "image_key": "ticket_cree"
    },
    "close_ticket_embed": {
        "title": "🔒 Fermeture du ticket",
        "description": [
            "Utilise le bouton ci-dessous pour fermer ce ticket."
        ],
        "color_rgb": [
            255,
            192,
            203
        ]
    },
    "commande_embed": {
        "title": "{emoji} Commande prise en charge",
        "description": [
            "Merci pour votre confiance {user} !"
        ],
        "fields": [
            {
                "name": "Article",
                "value": "**{service}**",
                "inline": True
            },
            {
                "name": "Montant reçu",
                "value": "{amount}€",
                "inline": True
            },
            {
                "name": "Payé",
                "value": "{paid}€",
                "inline": True
            },
            {
                "name": "Code",
                "value": "{code}",
                "inline": False
            }
        ],
        "color_rgb": [
            46,
            204,
            113
        ],
        "image_key": "commande_confirmee",
        "footer": "PinkGift — Ticket commande"
    },
    "commande_vp_embed": {
        "title": "{emoji} Commande Valorant prise en charge",
        "description": [
            "Merci pour votre confiance {user} !"
        ],
        "fields": [
            {
                "name": "Produit",
                "value": "**Valorant Points**",
                "inline": True
            },
            {
                "name": "Pack VP",
                "value": "**{pack}**",
                "inline": True
            },
            {
                "name": "Prix",
                "value": "{amount}€",
                "inline": True
            },
            {
                "name": "Code",
                "value": "{code}",
                "inline": False
            }
        ],
        "color_rgb": [
            46,
            204,
            113
        ],
        "image_key": "commande_confirmee",
        "footer": "PinkGift — Ticket Valorant"
    },
    "commande_finalisee": {
        "color_rgb": [
            46,
            204,
            113
        ],
        "image_key": "commande_livree",
        "footer": "PinkGift — Commande finalisée",
        "code_field_name": "Code"
    },
    "commandes_embed": {
        "title": "📜 COMMANDES STAFF — PinkGift",
        "description": [
            "Liste des commandes actuellement actives sur le bot."
        ],
        "fields": [
            {
                "name": "🎫 Tickets",
                "value": "!tarifs : affiche les cartes cadeaux et les menus de commande.\n!valo : envoie l'embed Valorant avec son bouton ticket.\n!maj_tarifs, !maj_valo, !maj_solde : mettent à jour sans ping.\n!maj_categories : met à jour tous les embeds publics sans ping.\n!close_button : ajoute un bouton Close persistant.",
                "inline": False
            },
            {
                "name": "🛍️ Articles",
                "value": "Syntaxe : !article montant\n!amazon, !carrefour, !intermarche, !zara, !sephora, !ubereats\n!apple, !googleplay, !steam, !netflix, !smyths, !zalando\n!kingjouet, !lego, !adidas, !footlocker, !deliveroo, !claude\n!airbnb, !xbox, !playstation, !paysafecard, !fnac, !nintendo, !nike, !vp",
                "inline": False
            },
            {
                "name": "✅ Finalisation",
                "value": "!finish <code> : ajoute le code et marque la commande comme livrée.",
                "inline": False
            },
            {
                "name": "🛡️ Modération / Staff",
                "value": "!clear <nombre>, !purge_all, !ban, !tempban, !tempmute",
                "inline": False
            }
        ],
        "color_rgb": [
            255,
            192,
            203
        ]
    }
})

DEFAULT_EMBED_DATA.update({"balance_embed":{"title":"💰 Solde & paiements PinkGift","description":["Consulte ton solde ou ouvre un ticket de recharge avec les boutons ci-dessous.","","💳 **Moyens de paiement acceptés**","<:paypal:1517582845315649751> **PayPal**","🏦 **Virement bancaire**","₿ **Cryptomonnaies**","","Une fois le paiement confirmé par le staff, ton solde sera ajouté et utilisable pour commander."],"color_rgb":[255,192,203],"image_key":"paiement_securise","footer":"PinkGift — Solde & paiements"},"balance_ticket_embed":{"title":"➕ Recharge de solde","description":["Bonjour {user} !","","Ton solde actuel est de **{balance} €**.","Indique au staff le montant et le moyen de paiement souhaités."],"color_rgb":[255,192,203],"image_key":"paiement_securise"}})

DEFAULT_EMBED_DATA.update({"uber_eats_ticket_embed": {"title": "🍔 Commande — UBER EATS", "description": ["Bonjour {user} !", "", "Ta commande Uber Eats a bien été enregistrée selon la grille fixe."], "fields": [{"name": "Service sélectionné", "value": "{emoji} **{service}**", "inline": False}, {"name": "Prix payé", "value": "**{paid} €**", "inline": True}, {"name": "Drop estimé", "value": "**{drop}**", "inline": True}, {"name": "Solde restant", "value": "**{balance} €**", "inline": False}], "color_rgb": [255, 192, 203], "image_key": "ticket_cree"}})

def load_embed_texts():
    if EMBED_CONFIG_URL:
        try:
            separator = "&" if "?" in EMBED_CONFIG_URL else "?"
            url = f"{EMBED_CONFIG_URL}{separator}t={int(time.time() * 1000)}"
            request = urllib.request.Request(url, headers={"User-Agent": "PinkSoftwareBot/1.0", "Cache-Control": "no-cache", "Pragma": "no-cache"})
            with urllib.request.urlopen(request, timeout=5) as response:
                raw_content = response.read().decode("utf-8")
            cleaned_content = re.sub(r",\s*([\]}])", r"\1", raw_content)
            data = json.loads(cleaned_content)
            for key, default_value in DEFAULT_EMBED_DATA.items():
                if key not in data or not isinstance(data[key], dict):
                    data[key] = default_value
            return data
        except Exception as e:
            print(f"Erreur chargement JSON distant : {e}")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    possible_paths = [os.path.join(base_dir, "config_embeds.json"), os.path.join(os.getcwd(), "config_embeds.json")]
    for filename in possible_paths:
        if filename and os.path.exists(filename):
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    raw_content = f.read()
                cleaned_content = re.sub(r",\s*([\]}])", r"\1", raw_content)
                data = json.loads(cleaned_content)
                for key, default_value in DEFAULT_EMBED_DATA.items():
                    if key not in data or not isinstance(data[key], dict):
                        data[key] = default_value
                return data
            except Exception as e:
                print(f"Erreur chargement config_embeds.json local : {e}")
    return DEFAULT_EMBED_DATA


def get_image_url(image_key: str, fallback_url: str = "") -> str:
    data = load_embed_texts()
    images = data.get("images", {})
    if isinstance(images, dict):
        return images.get(image_key) or fallback_url
    return fallback_url


class SafeFormatDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def format_embed_text(value, variables=None):
    return str(value).format_map(SafeFormatDict(variables or {}))


def build_json_embed(embed_key, variables=None):
    data = load_embed_texts().get(embed_key, DEFAULT_EMBED_DATA.get(embed_key, {}))
    variables = variables or {}
    rgb = data.get("color_rgb", [255, 192, 203])
    desc_raw = data.get("description", [])
    if isinstance(desc_raw, list):
        description = "\n".join(format_embed_text(line, variables) for line in desc_raw)
    else:
        description = format_embed_text(desc_raw, variables)
    embed = discord.Embed(
        title=format_embed_text(data.get("title", ""), variables),
        description=description or None,
        color=discord.Color.from_rgb(rgb[0], rgb[1], rgb[2])
    )
    for field in data.get("fields", []):
        embed.add_field(
            name=format_embed_text(field.get("name", ""), variables),
            value=format_embed_text(field.get("value", ""), variables),
            inline=field.get("inline", False)
        )
    footer = data.get("footer", "")
    if footer:
        embed.set_footer(text=format_embed_text(footer, variables))
    thumbnail_url = data.get("thumbnail_url", "")
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    image_url = data.get("image_url", "")
    image_key = data.get("image_key", "")
    if image_key:
        image_url = get_image_url(image_key, image_url)
    if image_url:
        embed.set_image(url=image_url)
    return embed


def apply_custom_brand_emojis(text: str):
    replacements = {
        "📦 **Amazon**": "<:amazon:1519907450403160104> **Amazon**",
        "🛒 **Carrefour**": "<:carrefour:1519906825494073414> **Carrefour**",
        "🏬 **Intermarché**": "<:intermarche:1519907100057276546> **Intermarché**",
        "🏬 **Intermarche**": "<:intermarche:1519907100057276546> **Intermarche**",
        "👕 **Zara**": "<:zara:1519907265681948773> **Zara**",
        "💄 **Sephora**": "<:sephora:1519907492862103742> **Sephora**",
        "🍔 **Uber Eats**": "<:ubereats:1519907186636099604> **Uber Eats**",
        "🍎 **Apple**": "<:apple:1519906800411869204> **Apple**",
        "🎮 **Google Play**": "<:googleplay:1519907060555186278> **Google Play**",
        "🎮 **Steam**": "<:steam:1519907154545610873> **Steam**",
        "🎬 **Netflix**": "<:netflix:1519907125160316928> **Netflix**",
        "🧸 **Smyths Toys**": "<:smythstoys:1519907368429944832> **Smyths Toys**",
        "👟 **Zalando**": "<:zalando:1519907231812816906> **Zalando**",
        "🧸 **King Jouet**": "<:kingjouet:1519907322783338557> **King Jouet**",
        "🧱 **LEGO**": "<:lego:1519907470854852720> **LEGO**",
        "👟 **Adidas**": "<:adidas:1519906784515588116> **Adidas**",
        "👟 **Foot Locker**": "<:footlocker:1519907296342310952> **Foot Locker**",
        "🍽️ **Deliveroo**": "<:deliveroo:1519906860356993174> **Deliveroo**",
        "✨ **Claude**": "<:claude:1519906842006913065> **Claude**",
        "🏠 **Airbnb**": "<:airbnb:1519906701900386344> **Airbnb**",
        "🎮 **Xbox**": "<:xbox:1519907418836828230> **Xbox**",
        "🎮 **PlayStation**": "<:playstation:1519906767268741200> **PlayStation**",
        "💳 **Paysafecard**": "<:paysafecard:1519906750571085995> **Paysafecard**",
        "📚 **Fnac**": "<:fnac:1519906718140727387> **Fnac**",
        "🎮 **Nintendo**": "<:nintendo:1519907394157678632> **Nintendo**",
        "👟 **Nike**": "<:nike:1519906735589167164> **Nike**",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def ticket_channel_name(emoji: str, label: str, suffix: str) -> str:
    clean_label = label.upper().replace(" ", "-").replace("_", "-")
    clean_suffix = str(suffix).replace(" ", "-")
    return f"{emoji}-{clean_label}-{clean_suffix}"[:95]


def parse_duration(duration_str: str):
    match = re.match(r"(\d+)([mhds])?", duration_str.lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2) or "m"
    if unit == "m": return amount * 60
    if unit == "h": return amount * 3600
    if unit == "d": return amount * 86400
    if unit == "s": return amount
    return None

async def create_product_ticket(interaction, product_key, amount):
    guild = interaction.guild
    user = interaction.user
    cfg = PRODUCT_CONFIG.get(product_key)
    if guild is None or cfg is None:
        await interaction.followup.send("❌ Impossible de créer cette commande.", ephemeral=True)
        return
    if product_key == "DISCORD_NITRO":
        amount = NITRO_PRICE
    uber_drop = UBEREATS_PACKS.get(amount) if product_key == "UBEREATS" else None
    if product_key == "UBEREATS" and uber_drop is None:
        await interaction.followup.send("❌ Pack Uber Eats invalide.", ephemeral=True)
        return
    fixed_price = product_key in {"UBEREATS", "DISCORD_NITRO"}
    paid_amount = float(amount) if fixed_price else round(amount * 0.70, 2)
    received_display = "Discord Nitro" if product_key == "DISCORD_NITRO" else (f"{uber_drop} € estimés" if uber_drop else f"{amount} €")
    lock = ORDER_LOCKS.setdefault((guild.id, user.id), asyncio.Lock())
    async with lock:
        current_balance = get_balance(guild.id, user.id)
        if current_balance < paid_amount:
            await interaction.followup.send(f"❌ Solde insuffisant. Il faut **{paid_amount:g} €**, ton solde est de **{current_balance:.2f} €**. Utilise le panneau !solde pour le recharger.", ephemeral=True)
            return
        category = guild.get_channel(TICKET_CATEGORY_ID)
        if category is None:
            await interaction.followup.send("❌ Catégorie ticket introuvable.", ephemeral=True)
            return
        ticket_channel = None
        for channel in category.text_channels:
            if channel.topic == f"pinkgift-owner:{user.id}" and not channel.name.startswith("closed-"):
                ticket_channel = channel
                if not channel.name.startswith("🎁"):
                    try:
                        await channel.edit(name=f"🎁・{user.display_name}"[:95])
                    except discord.HTTPException:
                        pass
                break
        if ticket_channel is None:
            staff_role = guild.get_role(STAFF_ROLE_ID)
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            safe_user = re.sub(r"[^a-z0-9-]", "", user.name.lower().replace(" ", "-")) or str(user.id)
            try:
                ticket_channel = await guild.create_text_channel(name=f"🎁・{user.display_name}"[:95], category=category, topic=f"pinkgift-owner:{user.id}", overwrites=overwrites, reason=f"Commandes PinkGift de {user}")
            except discord.HTTPException as error:
                await interaction.followup.send("⏳ Discord ne peut pas créer le ticket actuellement. Réessaie dans quelques minutes.", ephemeral=True)
                print(f"Erreur création ticket commande pour {user}: {error}")
                return
        try:
            remaining_balance = change_balance(guild.id, user.id, -paid_amount, bot.user.id if bot.user else 0)
        except Exception as error:
            print(f"Erreur débit solde de {user}: {error}")
            await interaction.followup.send("❌ Le débit du solde a échoué. Aucun montant n'a été retiré.", ephemeral=True)
            return
        if product_key == "UBEREATS":
            embed_key = "uber_eats_ticket_embed"
        elif product_key == "DISCORD_NITRO":
            embed_key = "nitro_ticket_embed"
        else:
            embed_key = "menu_ticket_embed"
        embed = build_json_embed(embed_key, {
            "user": user.mention, "service": cfg["display"], "emoji": cfg["emoji"],
            "amount": amount, "paid": f"{paid_amount:g}", "drop": received_display, "balance": f"{remaining_balance:.2f}"
        })
        try:
            order_message = await ticket_channel.send(content=f"{user.mention} | <@&{STAFF_ROLE_ID}>", embed=embed, view=CloseTicketView(user.id))
        except Exception as error:
            try:
                change_balance(guild.id, user.id, paid_amount, bot.user.id if bot.user else 0)
            except Exception as refund_error:
                print(f"ERREUR REMBOURSEMENT {user}: {refund_error}")
            await interaction.followup.send("❌ L'envoi de la commande a échoué. Le montant a été recrédité.", ephemeral=True)
            print(f"Erreur envoi commande pour {user}: {error}")
            return
        try:
            save_order(guild.id, ticket_channel.id, order_message.id, user.id, cfg["display"], amount, paid_amount, user.name, received_display if product_key in {"UBEREATS", "DISCORD_NITRO"} else "")
        except Exception as error:
            print(f"Erreur sauvegarde commande panneau: {error}")
        await interaction.followup.send(f"✅ Commande ajoutée dans {ticket_channel.mention}. Nouveau solde : **{remaining_balance:.2f} €**.", ephemeral=True)


VALO_REGIONS = {
    "EUROPE": {
        "label": "Europe", "emoji": "🇪🇺",
        "packs": {30: "3650 VP", 40: "5350 VP", 60: "8700 VP", 80: "11000 VP"}
    },
    "TURQUIE": {
        "label": "Turquie", "emoji": "🇹🇷",
        "packs": {15: "2925 VP", 20: "4325 VP", 45: "8900 VP", 55: "11000 VP"}
    }
}


async def create_valo_order(interaction, region_key, price):
    guild = interaction.guild
    user = interaction.user
    region = VALO_REGIONS.get(region_key)
    pack = region["packs"].get(price) if region else None
    if guild is None or pack is None:
        await interaction.followup.send("❌ Région ou pack Valorant invalide.", ephemeral=True)
        return
    region_label = region["label"]
    region_emoji = region["emoji"]
    lock = ORDER_LOCKS.setdefault((guild.id, user.id), asyncio.Lock())
    async with lock:
        current_balance = get_balance(guild.id, user.id)
        if current_balance < price:
            await interaction.followup.send(f"❌ Solde insuffisant. Il faut **{price} €**, ton solde est de **{current_balance:.2f} €**.", ephemeral=True)
            return
        category = guild.get_channel(VALO_TICKET_CATEGORY_ID)
        if category is None:
            await interaction.followup.send("❌ Catégorie Valorant introuvable.", ephemeral=True)
            return
        ticket_channel = None
        for channel in category.text_channels:
            if channel.topic == f"pinkgift-valorant-owner:{user.id}" and not channel.name.startswith("closed-"):
                ticket_channel = channel
                if not channel.name.startswith("🎁"):
                    try:
                        await channel.edit(name=f"🎁・{user.display_name}"[:95])
                    except discord.HTTPException:
                        pass
                break
        if ticket_channel is None:
            staff_role = guild.get_role(STAFF_ROLE_ID)
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            try:
                ticket_channel = await guild.create_text_channel(name=f"🎁・{user.display_name}"[:95], category=category, topic=f"pinkgift-valorant-owner:{user.id}", overwrites=overwrites, reason=f"Commande Valorant de {user}")
            except discord.HTTPException as error:
                await interaction.followup.send("⏳ Discord ne peut pas créer le ticket actuellement.", ephemeral=True)
                print(f"Erreur création ticket Valorant pour {user}: {error}")
                return
        try:
            remaining_balance = change_balance(guild.id, user.id, -price, bot.user.id if bot.user else 0)
        except Exception as error:
            print(f"Erreur débit Valorant de {user}: {error}")
            await interaction.followup.send("❌ Le débit du solde a échoué. Aucun montant n'a été retiré.", ephemeral=True)
            return
        code_pending = (chr(96) * 3) + "\nEn attente...\n" + (chr(96) * 3)
        embed = build_json_embed("commande_vp_embed", {
            "emoji": "<:vp:1519915966476320901>", "user": user.mention,
            "region": f"{region_emoji} {region_label}", "pack": pack, "amount": price,
            "code": code_pending, "balance": f"{remaining_balance:.2f}"
        })
        try:
            order_message = await ticket_channel.send(content=f"{user.mention} | <@&{STAFF_ROLE_ID}>", embed=embed, view=CloseTicketView(user.id))
        except Exception as error:
            try:
                change_balance(guild.id, user.id, price, bot.user.id if bot.user else 0)
            except Exception as refund_error:
                print(f"ERREUR REMBOURSEMENT VALORANT {user}: {refund_error}")
            await interaction.followup.send("❌ L'envoi a échoué. Le montant a été recrédité.", ephemeral=True)
            return
        try:
            save_order(guild.id, ticket_channel.id, order_message.id, user.id, f"Valorant {region_label} {pack}", price, price, user.name, pack)
        except Exception as error:
            print(f"Erreur sauvegarde commande Valorant: {error}")
        await interaction.followup.send(f"✅ {region_emoji} **{pack} ({region_label})** commandés dans {ticket_channel.mention}. Nouveau solde : **{remaining_balance:.2f} €**.", ephemeral=True)


class ValoRegionSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=data["label"], value=key, emoji=data["emoji"]) for key, data in VALO_REGIONS.items()]
        super().__init__(placeholder="Choisis ta région Valorant", options=options)

    async def callback(self, interaction: discord.Interaction):
        region_key = self.values[0]
        region = VALO_REGIONS[region_key]
        await interaction.response.edit_message(content=f"{region['emoji']} **{region['label']}** — choisis ton pack :", view=ValoPackView(region_key))


class ValoRegionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(ValoRegionSelect())


class ValoPackSelect(discord.ui.Select):
    def __init__(self, region_key):
        self.region_key = region_key
        packs = VALO_REGIONS[region_key]["packs"]
        options = [discord.SelectOption(label=f"{pack} — {price} €", value=str(price), emoji=discord.PartialEmoji.from_str("<:vp:1519915966476320901>")) for price, pack in packs.items()]
        super().__init__(placeholder="Choisis ton pack Valorant Points", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await create_valo_order(interaction, self.region_key, int(self.values[0]))


class ValoPackView(discord.ui.View):
    def __init__(self, region_key):
        super().__init__(timeout=180)
        self.add_item(ValoPackSelect(region_key))


class ValoOrderLauncherView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Commander des VP", emoji="<:vp:1519915966476320901>", style=discord.ButtonStyle.success, custom_id="pinkgift_start_valo_order")
    async def start_valo_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Choisis d'abord ta région Valorant :", view=ValoRegionView(), ephemeral=True)


class UberEatsAmountSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=f"{price} € → {drop} € estimés", value=str(price), emoji="🍔")
            for price, drop in UBEREATS_PACKS.items()
        ]
        super().__init__(placeholder="Choisis ton pack Uber Eats", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await create_product_ticket(interaction, "UBEREATS", int(self.values[0]))


class UberEatsAmountView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(UberEatsAmountSelect())


class NitroOrderView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(
        label="Commander Discord Nitro — 8 €",
        emoji="<:nitroboost:1524439577656561846>",
        style=discord.ButtonStyle.success
    )
    async def confirm_nitro(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await create_product_ticket(interaction, "DISCORD_NITRO", NITRO_PRICE)


class ProductAmountSelect(discord.ui.Select):
    def __init__(self, product_key):
        self.product_key = product_key
        options = [
            discord.SelectOption(label=f"Carte cadeau {amount} € → {amount * 0.70:g} € débités", value=str(amount), emoji="💳")
            for amount in (100, 200, 400, 800)
        ]
        super().__init__(placeholder="Choisis le montant de la carte", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await create_product_ticket(interaction, self.product_key, int(self.values[0]))


class ProductAmountView(discord.ui.View):
    def __init__(self, product_key):
        super().__init__(timeout=180)
        self.add_item(ProductAmountSelect(product_key))


class ProductServiceSelect(discord.ui.Select):
    def __init__(self):
        options = []
        for key, cfg in PRODUCT_CONFIG.items():
            if key == "VALORANT":
                continue
            emoji = discord.PartialEmoji.from_str(cfg["emoji"])
            options.append(discord.SelectOption(label=cfg["display"], value=key, emoji=emoji))
        super().__init__(
            placeholder="Choisis une marque",
            custom_id="pinkgift_product_service",
            min_values=1,
            max_values=1,
            options=options[:25]
        )

    async def callback(self, interaction: discord.Interaction):
        product_key = self.values[0]
        cfg = PRODUCT_CONFIG[product_key]
        if product_key == "UBEREATS":
            amount_view = UberEatsAmountView()
            prompt = "choisis maintenant ton pack :"
        elif product_key == "DISCORD_NITRO":
            amount_view = NitroOrderView()
            prompt = "confirme l'achat du produit à **8 €** :"
        else:
            amount_view = ProductAmountView(product_key)
            prompt = "choisis maintenant le montant :"
        await interaction.response.send_message(
            f"{cfg['emoji']} **{cfg['display']}** — {prompt}",
            view=amount_view,
            ephemeral=True
        )


class ProductSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProductServiceSelect())


class OrderLauncherView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Commander",
        emoji="🛍️",
        style=discord.ButtonStyle.success,
        custom_id="pinkgift_start_order"
    )
    async def start_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Choisis d'abord la marque que tu souhaites commander :",
            view=ProductSelectView(),
            ephemeral=True
        )


class BalanceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Voir mon solde", emoji="💰", style=discord.ButtonStyle.secondary, custom_id="pinkgift_view_balance")
    async def view_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        balance = get_balance(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(f"💰 Ton solde PinkGift est de **{balance:.2f} €**.", ephemeral=True)

    @discord.ui.button(label="Recharger mon solde", emoji="➕", style=discord.ButtonStyle.success, custom_id="pinkgift_recharge_balance")
    async def recharge_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild = interaction.guild
        user = interaction.user
        category = guild.get_channel(BALANCE_CATEGORY_ID) if guild else None
        if category is None:
            await interaction.followup.send("❌ Catégorie de recharge introuvable.", ephemeral=True)
            return
        for channel in category.text_channels:
            if (channel.topic or "").startswith(f"pinkgift-balance:{user.id}") and not channel.name.startswith("closed-"):
                await interaction.followup.send(f"ℹ️ Ton ticket de recharge existe déjà : {channel.mention}", ephemeral=True)
                return
        staff_role = guild.get_role(STAFF_ROLE_ID)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        channel = await guild.create_text_channel(name=f"solde-{user.name}"[:95], category=category, topic=f"pinkgift-balance:{user.id}:pending", overwrites=overwrites, reason=f"Recharge solde de {user}")
        embed = build_json_embed("balance_ticket_embed", {"user": user.mention, "balance": f"{get_balance(guild.id, user.id):.2f}"})
        await channel.send(content=f"{user.mention} | <@&{STAFF_ROLE_ID}>", embed=embed, view=CloseTicketView(user.id))
        await interaction.followup.send(f"✅ Ticket de recharge créé : {channel.mention}", ephemeral=True)


class CloseTicketView(discord.ui.View):
    def __init__(self, client_id: int = 0):
        super().__init__(timeout=None)
        self.client_id = client_id

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="pinkgift_close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        channel = interaction.channel
        client = guild.get_member(self.client_id) if guild and self.client_id else None
        staff_role = guild.get_role(STAFF_ROLE_ID) if guild else None
        is_staff = staff_role in interaction.user.roles if hasattr(interaction.user, "roles") and staff_role else False
        if not is_staff:
            await interaction.response.send_message("❌ Seul le staff peut fermer ce ticket.", ephemeral=True)
            return
        if client:
            await channel.set_permissions(client, view_channel=False, send_messages=False, read_message_history=False)
        elif guild:
            for target, overwrite in channel.overwrites.items():
                if isinstance(target, discord.Member):
                    has_staff_role = staff_role in target.roles if staff_role else False
                    if not target.bot and not has_staff_role:
                        await channel.set_permissions(target, view_channel=False, send_messages=False, read_message_history=False)
        if is_balance_ticket(channel):
            balance_user_id = get_balance_ticket_user_id(channel)
            credited = balance_ticket_marked_credited(channel)
            if not credited and balance_user_id and guild:
                try:
                    credited = balance_was_added_after(guild.id, balance_user_id, channel.created_at)
                except Exception as error:
                    print(f"Erreur verification credit ticket solde {channel.id}: {error}")
            if not credited:
                await interaction.response.send_message("🗑️ Ticket de recharge ferme sans ajout de solde : suppression du salon.", ephemeral=True)
                await channel.delete(reason=f"Ticket solde sans ajout ferme par {interaction.user}")
                return

        closed_category = guild.get_channel(CLOSED_TICKET_CATEGORY_ID) if guild else None
        await interaction.response.send_message("🔒 Ticket ferme : le client n a plus acces a ce salon.")
        try:
            new_name = channel.name if channel.name.startswith("closed-") else f"closed-{channel.name}"
            if closed_category:
                await channel.edit(name=new_name, category=closed_category, reason=f"Ticket ferme par {interaction.user}")
            else:
                await channel.edit(name=new_name, reason=f"Ticket ferme par {interaction.user}")
        except:
            pass

class OpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ouvrir un ticket", emoji="🎫", style=discord.ButtonStyle.success, custom_id="pinkgift_open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user
        if guild is None:
            await interaction.response.send_message("❌ Cette action doit etre utilisee sur un serveur.", ephemeral=True)
            return
        category = guild.get_channel(TICKET_CATEGORY_ID)
        if category is None:
            await interaction.response.send_message("❌ Categorie ticket introuvable.", ephemeral=True)
            return
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{user.name}",
            category=category,
            overwrites=overwrites,
            reason=f"Ouverture ticket PinkGift par {user}"
        )
        texts = load_embed_texts()["ticket_bienvenue"]
        desc_raw = texts["description"]
        if isinstance(desc_raw, list):
            desc_lines = [line for line in desc_raw if "Tu as sélectionné" not in line and "Tu as selectionne" not in line]
            description = "\n".join(desc_lines)
        else:
            description = str(desc_raw)
            description = re.sub(r"^.*Tu as s[ée]lectionn[ée].*$", "", description, flags=re.MULTILINE)
        description = description.format(user=user.mention, product="")
        rgb = texts.get("color_rgb", [255, 192, 203])
        title = texts.get("title", "🎫 Ticket d achat")
        title = title.replace(" — {product}", "").replace(" - {product}", "").format(product="")
        embed_ticket = discord.Embed(title=title, description=description, color=discord.Color.from_rgb(rgb[0], rgb[1], rgb[2]))
        embed_ticket.set_image(url=get_image_url("ticket_cree", TICKET_IMAGE_URL))
        await ticket_channel.send(content=f"{user.mention} | <@&{STAFF_ROLE_ID}>", embed=embed_ticket, view=CloseTicketView(user.id))
        await interaction.response.send_message(f"✅ Ton ticket a ete cree ici : {ticket_channel.mention}", ephemeral=True)

class ProductView(OpenTicketView):
    pass


class ValoTicketButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ouvrir un ticket Valorant", emoji="🎮", style=discord.ButtonStyle.success, custom_id="pinkgift_open_valo_ticket")
    async def open_valo_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user
        if guild is None:
            await interaction.response.send_message("❌ Cette action doit etre utilisee sur un serveur.", ephemeral=True)
            return
        category = guild.get_channel(VALO_TICKET_CATEGORY_ID)
        if category is None:
            await interaction.response.send_message("❌ Categorie Valorant introuvable.", ephemeral=True)
            return
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        ticket_channel = await guild.create_text_channel(
            name=f"ticket-valorant-{user.name}",
            category=category,
            overwrites=overwrites,
            reason=f"Ouverture ticket Valorant par {user}"
        )
        embed_ticket = build_json_embed("valo_ticket_bienvenue_embed", {"user": user.mention})
        await ticket_channel.send(content=f"{user.mention} | <@&{STAFF_ROLE_ID}>", embed=embed_ticket, view=CloseTicketView(user.id))
        await interaction.response.send_message(f"✅ Ton ticket Valorant a ete cree ici : {ticket_channel.mention}", ephemeral=True)

@bot.event
async def on_ready():
    global BOT_LOOP
    BOT_LOOP = asyncio.get_running_loop()
    bot.add_view(OpenTicketView())
    bot.add_view(ProductSelectView())
    bot.add_view(OrderLauncherView())
    bot.add_view(BalanceView())
    bot.add_view(ValoTicketButton())
    bot.add_view(ValoOrderLauncherView())
    bot.add_view(CloseTicketView())
    await bot.change_presence(activity=discord.Game(name="🎀 PinkGift | Tickets ouverts"))
    print("Le bot PinkSoftware est en ligne et fonctionnel !")

@bot.event
async def on_member_join(member):
    role = member.guild.get_role(NEW_MEMBER_ROLE_ID)
    if role:
        try:
            await member.add_roles(role, reason="Attribution automatique nouveau membre")
        except Exception as e:
            print(f"Erreur attribution role : {e}")


def build_tarifs_embed():
    texts = load_embed_texts()["tarifs_embed"]
    rgb = texts.get("color_rgb", [255, 192, 203])
    desc_raw = texts.get("description", [])
    description = "\n".join(desc_raw) if isinstance(desc_raw, list) else str(desc_raw)
    description = apply_custom_brand_emojis(description)
    embed = discord.Embed(title=texts.get("title", "🎟️ COMMANDES PINKGIFT"), description=description, color=discord.Color.from_rgb(rgb[0], rgb[1], rgb[2]))
    embed.set_thumbnail(url=TARIFS_THUMBNAIL_URL)
    image_url = texts.get("image_url", TARIFS_IMAGE_URL)
    if image_url:
        embed.set_image(url=image_url)
    return embed

def build_valo_embed():
    texts = load_embed_texts().get("valo_embed", DEFAULT_EMBED_DATA["valo_embed"])
    rgb = texts.get("color_rgb", [255, 192, 203])
    desc_raw = texts.get("description", [])
    description = "\n".join(desc_raw) if isinstance(desc_raw, list) else str(desc_raw)
    embed = discord.Embed(title=texts.get("title", "💘 VALORANT POINTS 💘"), description=description, color=discord.Color.from_rgb(rgb[0], rgb[1], rgb[2]))
    image_url = texts.get("image_url", "")
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text="PinkGift — Valorant Points")
    return embed

async def update_last_embed(ctx, embed_builder, title_keywords, view=None):
    embed = embed_builder()
    updated_count = 0
    async for msg in ctx.channel.history(limit=100):
        if msg.author == bot.user and msg.embeds:
            title = msg.embeds[0].title or ""
            if any(keyword.lower() in title.lower() for keyword in title_keywords):
                if view is None:
                    await msg.edit(embed=embed)
                else:
                    await msg.edit(embed=embed, view=view)
                updated_count += 1
    if updated_count:
        preview = (embed.description or "").replace("\n", " ")[:120]
        confirmation = await ctx.send(f"✅ {updated_count} embed(s) mis à jour sans ping. Aperçu chargé : {preview}")
        await asyncio.sleep(8)
        try:
            await confirmation.delete()
        except:
            pass
        try:
            await ctx.message.delete()
        except:
            pass
        return
    await ctx.send("❌ Aucun embed correspondant trouvé dans ce salon.", delete_after=6)
async def update_public_embeds_without_ping(ctx):
    builders = [
        (["COMMANDES PINKGIFT", "CARTE CADEAUX"], build_tarifs_embed, OrderLauncherView()),
        (["VALORANT", "VALORANT POINTS"], build_valo_embed, ValoOrderLauncherView()),
        (["Solde PinkGift", "Solde & paiements", "Solde"], lambda: build_json_embed("balance_embed"), BalanceView()),
    ]
    updated_count = 0
    async for msg in ctx.channel.history(limit=150):
        if msg.author == bot.user and msg.embeds:
            title = msg.embeds[0].title or ""
            for keywords, builder, view in builders:
                if any(keyword.lower() in title.lower() for keyword in keywords):
                    if view is None:
                        await msg.edit(embed=builder())
                    else:
                        await msg.edit(embed=builder(), view=view)
                    updated_count += 1
                    break
    return updated_count


@bot.hybrid_command(name="maj_categories", description="Mettre à jour tous les embeds publics sans ping")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def update_categories(ctx):
    updated_count = await update_public_embeds_without_ping(ctx)
    if updated_count:
        confirmation = await ctx.send(f"✅ {updated_count} embed(s) public(s) mis à jour sans ping.")
        await asyncio.sleep(8)
        try:
            await confirmation.delete()
        except:
            pass
        try:
            await ctx.message.delete()
        except:
            pass
    else:
        await ctx.send("❌ Aucun embed public trouvé dans ce salon.", delete_after=6)


@bot.hybrid_command(name="debug_embed", description="Afficher les données JSON chargées pour un embed")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.describe(embed_name="Nom du bloc JSON à examiner")
@commands.has_role(STAFF_ROLE_ID)
async def debug_embed(ctx, embed_name: str = "tarifs_embed"):
    data = load_embed_texts()
    embed_data = data.get(embed_name)
    if not embed_data:
        await ctx.send(f"❌ Embed introuvable : {embed_name}", delete_after=8)
        return
    desc_raw = embed_data.get("description", [])
    description = "\n".join(desc_raw) if isinstance(desc_raw, list) else str(desc_raw)
    preview = description.replace("\n", " ")[:300]
    await ctx.send(f"📦 JSON lu pour **{embed_name}** : {preview}", delete_after=20)


@bot.hybrid_command(name="close_button", description="Envoyer le bouton de fermeture dans un ticket")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_close_button(ctx):
    embed = build_json_embed("close_ticket_embed")
    await ctx.send(embed=embed, view=CloseTicketView())

@bot.hybrid_command(name="tarifs", description="Publier le panneau des tarifs et des commandes")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def send_tarifs(ctx):
    embed = build_tarifs_embed()
    await ctx.send(content="||@everyone||", embed=embed, view=OrderLauncherView())

@bot.hybrid_command(name="maj_tarifs", description="Mettre à jour le panneau des tarifs sans ping")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def update_tarifs(ctx):
    await update_last_embed(ctx, build_tarifs_embed, ["COMMANDES PINKGIFT", "CARTE CADEAUX"], OrderLauncherView())

@bot.hybrid_command(name="valo", description="Publier le panneau des Valorant Points")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_valo(ctx):
    embed = build_valo_embed()
    await ctx.send(content="||@everyone||", embed=embed, view=ValoOrderLauncherView())

@bot.hybrid_command(name="maj_valo", description="Mettre à jour le panneau Valorant sans ping")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def update_valo(ctx):
    await update_last_embed(ctx, build_valo_embed, ["VALORANT", "VALORANT POINTS"], ValoOrderLauncherView())

@bot.hybrid_command(name="purge_all", description="Supprimer tous les messages du salon")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_purge_all(ctx):
    status_msg = await ctx.send("🔄 Purge complete des tickets et commandes...")
    deleted_count = 0
    for channel in ctx.guild.text_channels:
        if channel.name.startswith("ticket-") or channel.name.startswith("closed-"):
            try:
                await channel.delete(reason="Purge complete demandee.")
                deleted_count += 1
                await asyncio.sleep(0.5)
            except:
                pass
    try:
        await status_msg.edit(content=f"✅ Purge terminee. {deleted_count} salons supprimes.")
    except:
        pass

@bot.hybrid_command(name="clear", aliases=["purge"], description="Supprimer un nombre précis de messages")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.describe(amount="Nombre de messages à supprimer")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_clear_messages(ctx, amount: int):
    if amount <= 0:
        await ctx.send("❌ Indique un nombre de messages superieur a 0.", delete_after=3)
        return
    try:
        await ctx.message.delete()
    except:
        pass
    deleted = await ctx.channel.purge(limit=amount)
    msg = await ctx.send(f"🗑️ {len(deleted)} messages effaces.")
    await asyncio.sleep(4)
    try:
        await msg.delete()
    except:
        pass

@bot.hybrid_command(name="ban", description="Bannir définitivement un membre du serveur")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.describe(member="Membre à bannir", reason="Raison du bannissement")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_ban(ctx, member: discord.Member, *, reason: str = "Aucune raison fournie"):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 {member.name} a ete banni. Raison : {reason}")

@bot.hybrid_command(name="tempban", description="Bannir temporairement un membre du serveur")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.describe(member="Membre à bannir", duration="Durée, par exemple 2h ou 3d", reason="Raison du bannissement")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_tempban(ctx, member: discord.Member, duration: str, *, reason: str = "Aucune raison fournie"):
    seconds = parse_duration(duration)
    if not seconds:
        await ctx.send("❌ Format invalide. Exemple : 10m, 2h, 3d.")
        return
    await member.ban(reason=f"[Tempban {duration}] {reason}")
    await ctx.send(f"⏳ {member.name} banni temporairement pour {duration}.")
    await asyncio.sleep(seconds)
    try:
        await ctx.guild.unban(member, reason="Fin du tempban.")
    except:
        pass

@bot.hybrid_command(name="tempmute", description="Rendre un membre muet temporairement")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.describe(member="Membre à rendre muet", duration="Durée, par exemple 10m ou 2h", reason="Raison du mute")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_tempmute(ctx, member: discord.Member, duration: str, *, reason: str = "Aucune raison fournie"):
    seconds = parse_duration(duration)
    if not seconds:
        await ctx.send("❌ Format invalide. Exemple : 10m, 2h.")
        return
    await member.timeout(datetime.timedelta(seconds=seconds), reason=reason)
    await ctx.send(f"🔇 {member.name} mute pendant {duration}.")

@bot.hybrid_command(name="solde", description="Publier le panneau de consultation et recharge du solde")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_solde(ctx):
    await ctx.send(embed=build_json_embed("balance_embed"), view=BalanceView())


@bot.hybrid_command(name="maj_solde", description="Mettre à jour le panneau solde sans ping")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def update_solde(ctx):
    await update_last_embed(ctx, lambda: build_json_embed("balance_embed"), ["Solde PinkGift", "Solde & paiements", "Solde"], BalanceView())


@bot.hybrid_command(name="ajouter_solde", description="Ajouter un montant au solde d'un client")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.describe(member="Client concerné", montant="Montant à ajouter en euros")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_ajouter_solde(ctx, member: discord.Member, montant: float):
    if montant <= 0:
        await ctx.send("❌ Le montant doit être positif.", delete_after=5)
        return
    balance = change_balance(ctx.guild.id, member.id, montant, ctx.author.id)
    await mark_balance_ticket_credited(ctx.guild, member.id)
    await ctx.send(f"✅ **{montant:.2f} €** ajoutés à {member.mention}. Nouveau solde : **{balance:.2f} €**.")


@bot.hybrid_command(name="retirer_solde", description="Retirer un montant du solde d'un client")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.describe(member="Client concerné", montant="Montant à retirer en euros")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_retirer_solde(ctx, member: discord.Member, montant: float):
    if montant <= 0:
        await ctx.send("❌ Le montant doit être positif.", delete_after=5)
        return
    try:
        balance = change_balance(ctx.guild.id, member.id, -montant, ctx.author.id)
    except ValueError:
        await ctx.send("❌ Solde insuffisant.", delete_after=5)
        return
    await ctx.send(f"✅ **{montant:.2f} €** retirés à {member.mention}. Nouveau solde : **{balance:.2f} €**.")



@bot.hybrid_command(name="commandes", description="Afficher le répertoire des commandes réservées au staff")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_directory(ctx):
    await ctx.send(embed=build_json_embed("commandes_embed"))

def panel_auth_token():
    return hashlib.sha256(("pinkgift-panel:" + PANEL_PASSWORD).encode("utf-8")).hexdigest()


def panel_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        login_time = session.get("panel_login_at", 0)
        valid_token = PANEL_PASSWORD and secrets.compare_digest(session.get("panel_auth", ""), panel_auth_token())
        if not valid_token or time.time() - login_time > 1800:
            session.clear()
            return redirect(url_for("panel_login"))
        if not session.get("csrf"):
            session["csrf"] = secrets.token_urlsafe(24)
        return view(*args, **kwargs)
    return wrapped


PANEL_TEMPLATE = """
<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Panel</title>
<style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}h1{margin:0;color:#ff8fc8;font-size:23px}main{padding:22px 5%}nav{display:flex;gap:8px;margin-bottom:18px}.tab{color:#e8dce3;text-decoration:none;padding:10px 14px;border:1px solid #4c3543}.tab.active{background:#e8509a;color:white;border-color:#e8509a}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}table{width:100%;border-collapse:collapse;background:#171419}th,td{text-align:left;padding:11px;border-bottom:1px solid #332630}th{color:#ff9dce}input,select{background:#0e0d11;color:white;border:1px solid #5a3a4d;padding:9px;min-width:160px}select{cursor:pointer}.filters{display:flex;gap:10px;align-items:center;margin:0 0 16px 0}.filters label{color:#ff9dce;font-weight:bold}button{background:#e8509a;color:white;border:0;padding:10px 13px;cursor:pointer}.delete{background:#9d294b;margin-left:5px}.done{color:#74d99f}.pending{color:#ffd27b}.muted{color:#aa98a4;font-size:12px}@media(max-width:800px){table,thead,tbody,tr,td{display:block}thead{display:none}tr{padding:12px;border-bottom:1px solid #332630}td{border:0;padding:6px}}</style></head><body>
<header><h1>PinkGift — Panel staff</h1><a href="{{ url_for('panel_logout') }}" style="color:#ff9dce">Déconnexion</a></header><main>
<nav><a class="tab {{ 'active' if tab == 'orders' else '' }}" href="{{ url_for('panel_orders', tab='orders') }}">Commandes</a><a class="tab {{ 'active' if tab == 'valorant' else '' }}" href="{{ url_for('panel_orders', tab='valorant') }}">Valorant</a><a class="tab {{ 'active' if tab == 'clients' else '' }}" href="{{ url_for('panel_orders', tab='clients') }}">Clients</a></nav>
{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}
{% if tab == 'clients' %}<table><thead><tr><th>Client</th><th>ID Discord</th><th>Commandes</th><th>Total dépensé</th></tr></thead><tbody>{% for client in clients %}<tr><td><a href="https://discord.com/users/{{ client.user_id }}" target="_blank" style="color:#ff9dce;text-decoration:none"><strong>@{{ client.user_name }}</strong></a></td><td class="muted">{{ client.user_id }}</td><td>{{ client.order_count }}</td><td><strong>{{ '%.2f'|format(client.total_spent) }} €</strong></td></tr>{% else %}<tr><td colspan="4">Aucun client enregistré.</td></tr>{% endfor %}</tbody></table>
{% else %}{% if tab == 'orders' %}<form class="filters" method="get" action="{{ url_for('panel_orders') }}"><input type="hidden" name="tab" value="orders"><label for="service-filter">Service</label><select id="service-filter" name="service" onchange="this.form.submit()"><option value="">Tous les services</option>{% for service in service_options %}<option value="{{ service }}" {% if service == service_filter %}selected{% endif %}>{{ service }}</option>{% endfor %}</select></form>{% endif %}<table><thead><tr><th>ID</th><th>Client</th><th>Service</th><th>Reçu</th><th>Payé</th><th>État</th><th>Actions</th></tr></thead><tbody>{% for order in orders %}<tr><td>#{{ loop.index }}</td><td><a href="https://discord.com/users/{{ order.user_id }}" target="_blank" style="color:#ff9dce;text-decoration:none">@{{ order.user_name or order.user_id }}</a></td><td>{{ order.service }}</td><td>{{ order.received_label or ((order.amount|string) + " €") }}</td><td>{{ order.paid }} €</td><td class="{{ order.status }}">{{ order.status }}</td><td><form method="post" action="{{ url_for('panel_set_code', order_id=order.id) }}" style="display:inline"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="return_tab" value="{{ tab }}"><input type="hidden" name="return_service" value="{{ service_filter }}"><input name="code" required placeholder="Code cadeau" value="{{ order.code or '' }}"><button type="submit">Livrer</button></form><form method="post" action="{{ url_for('panel_delete_order', order_id=order.id) }}" style="display:inline" onsubmit="return confirm('Supprimer cette commande du panel ?')"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="return_tab" value="{{ tab }}"><input type="hidden" name="return_service" value="{{ service_filter }}"><button class="delete" type="submit" title="Supprimer">Supprimer</button></form></td></tr>{% else %}<tr><td colspan="7">Aucune commande enregistrée.</td></tr>{% endfor %}</tbody></table>{% endif %}
</main></body></html>"""


LOGIN_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift</title><style>body{background:#0e0d11;color:#fff;font-family:Arial;display:grid;place-items:center;height:100vh;margin:0}form{background:#19151b;padding:28px;border:1px solid #4a3040;width:min(340px,80vw)}h1{color:#ff8fc8}input,button{box-sizing:border-box;width:100%;padding:12px;margin-top:10px}input{background:#0e0d11;color:#fff;border:1px solid #5a3a4d}button{background:#e8509a;color:#fff;border:0}</style></head><body><form method="post"><h1>PinkGift Staff</h1><input type="password" name="password" placeholder="Mot de passe" required><button>Connexion</button></form></body></html>"""


@app.after_request
def secure_panel_response(response):
    if request.path.startswith("/panel"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
    return response


@app.route("/panel/login", methods=["GET", "POST"])
def panel_login():
    if request.method == "POST" and PANEL_PASSWORD and secrets.compare_digest(request.form.get("password", ""), PANEL_PASSWORD):
        session.clear()
        session["panel_auth"] = panel_auth_token()
        session["panel_login_at"] = time.time()
        session["csrf"] = secrets.token_urlsafe(24)
        return redirect(url_for("panel_orders"))
    return render_template_string(LOGIN_TEMPLATE)


@app.route("/panel/logout")
def panel_logout():
    session.clear()
    return redirect(url_for("panel_login"))


@app.route("/panel")
@panel_required
def panel_orders():
    tab = request.args.get("tab", "orders")
    if tab not in ("orders", "valorant", "clients"):
        tab = "orders"
    try:
        if USE_SUPABASE:
            orders = supabase_request("GET", "orders?select=*&order=id.desc&limit=1000")
        else:
            with db_connect() as db:
                orders = [dict(row) for row in db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 1000").fetchall()]
    except Exception as error:
        print(f"Erreur chargement panneau : {error}")
        flash("Connexion à Supabase impossible. Vérifie la configuration et le script SQL.")
        orders = []
    all_orders = orders
    service_filter = request.args.get("service", "").strip()
    command_orders = [order for order in all_orders if not str(order.get("service", "")).lower().startswith("valorant")]
    service_options = sorted({str(order.get("service") or "Service inconnu") for order in command_orders})
    if tab == "valorant":
        orders = [order for order in all_orders if str(order.get("service", "")).lower().startswith("valorant")]
        service_filter = ""
    elif tab == "orders":
        orders = command_orders
        if service_filter:
            orders = [order for order in orders if str(order.get("service") or "Service inconnu") == service_filter]
    for order in all_orders:
        if not order.get("user_name"):
            guild = bot.get_guild(int(order.get("guild_id") or 0))
            member = guild.get_member(int(order.get("user_id") or 0)) if guild else None
            if member:
                order["user_name"] = member.name
    clients_by_id = {}
    for order in all_orders:
        user_id = order.get("user_id")
        client = clients_by_id.setdefault(user_id, {"user_id": user_id, "user_name": order.get("user_name") or str(user_id), "order_count": 0, "total_spent": 0.0})
        if order.get("user_name"):
            client["user_name"] = order["user_name"]
        client["order_count"] += 1
        client["total_spent"] += float(order.get("paid") or 0)
    clients = sorted(clients_by_id.values(), key=lambda item: item["total_spent"], reverse=True)
    return render_template_string(PANEL_TEMPLATE, orders=orders, clients=clients, tab=tab, service_options=service_options, service_filter=service_filter)


async def deliver_order_from_panel(order, code):
    channel = bot.get_channel(order["channel_id"])
    if channel is None:
        channel = await bot.fetch_channel(order["channel_id"])
    message = await channel.fetch_message(order["message_id"])
    if not message.embeds:
        raise RuntimeError("Embed Discord introuvable")
    old = message.embeds[0]
    finish_data = load_embed_texts().get("commande_finalisee", DEFAULT_EMBED_DATA["commande_finalisee"])
    rgb = finish_data.get("color_rgb", [46, 204, 113])
    updated = discord.Embed(title=old.title, description=old.description, color=discord.Color.from_rgb(*rgb))
    code_found = False
    for field in old.fields:
        if "code" in field.name.lower():
            updated.add_field(name=finish_data.get("code_field_name", field.name), value=(chr(96) * 3) + "\n" + code + "\n" + (chr(96) * 3), inline=False)
            code_found = True
        else:
            updated.add_field(name=field.name, value=field.value, inline=field.inline)
    if not code_found:
        updated.add_field(name=finish_data.get("code_field_name", "Code"), value=(chr(96) * 3) + "\n" + code + "\n" + (chr(96) * 3), inline=False)
    updated.set_image(url=get_image_url(finish_data.get("image_key", "commande_livree"), finish_data.get("image_url", ORDER_FINISHED_IMAGE_URL)))
    updated.set_footer(text=finish_data.get("footer", "PinkGift — Commande finalisée"))
    await message.edit(embed=updated)


def valid_panel_csrf():
    expected = session.get("csrf", "")
    received = request.form.get("csrf", "")
    return bool(expected and secrets.compare_digest(expected, received))


@app.post("/panel/orders/<int:order_id>/delete")
@panel_required
def panel_delete_order(order_id):
    if not valid_panel_csrf():
        flash("Session invalide. Recharge la page.")
        return redirect(url_for("panel_orders", tab=request.form.get("return_tab", "orders"), service=request.form.get("return_service", "")))
    try:
        if USE_SUPABASE:
            deleted = supabase_request("DELETE", f"orders?id=eq.{order_id}", prefer="return=representation")
            if not deleted:
                raise RuntimeError("Aucune ligne supprimée. Vérifie que SUPABASE_SECRET_KEY est bien une clé secrète et non la clé publishable/anon.")
        else:
            with db_connect() as db:
                cursor = db.execute("DELETE FROM orders WHERE id=?", (order_id,))
                if cursor.rowcount == 0:
                    raise RuntimeError("Commande introuvable")
        flash("Commande supprimée du panel. Les numéros ont été recalculés.")
    except Exception as error:
        print(f"Erreur suppression commande {order_id}: {error}")
        flash("La suppression a échoué.")
    return redirect(url_for("panel_orders", tab=request.form.get("return_tab", "orders"), service=request.form.get("return_service", "")))


@app.post("/panel/orders/<int:order_id>/code")
@panel_required
def panel_set_code(order_id):
    if not valid_panel_csrf():
        flash("Session invalide. Recharge la page.")
        return redirect(url_for("panel_orders", tab=request.form.get("return_tab", "orders"), service=request.form.get("return_service", "")))
    code = request.form.get("code", "").strip()
    if USE_SUPABASE:
        rows = supabase_request("GET", f"orders?id=eq.{order_id}&select=*")
        order = rows[0] if rows else None
    else:
        with db_connect() as db:
            order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order or not code:
        flash("Commande ou code invalide.")
        return redirect(url_for("panel_orders", tab=request.form.get("return_tab", "orders"), service=request.form.get("return_service", "")))
    if BOT_LOOP is None:
        flash("Le bot Discord n'est pas encore prêt.")
        return redirect(url_for("panel_orders", tab=request.form.get("return_tab", "orders"), service=request.form.get("return_service", "")))
    try:
        asyncio.run_coroutine_threadsafe(deliver_order_from_panel(order, code), BOT_LOOP).result(timeout=25)
        if USE_SUPABASE:
            supabase_request("PATCH", f"orders?id=eq.{order_id}", {"code": code, "status": "done", "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
        else:
            with db_connect() as db:
                db.execute("UPDATE orders SET code=?, status='done', updated_at=CURRENT_TIMESTAMP WHERE id=?", (code, order_id))
        flash(f"Commande #{order_id} livrée et embed Discord mis à jour.")
    except Exception as error:
        flash(f"Erreur Discord : {error}")
    return redirect(url_for("panel_orders", tab=request.form.get("return_tab", "orders"), service=request.form.get("return_service", "")))


async def send_slash_error(interaction, message):
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@bot.tree.error
async def on_app_command_error(interaction, error):
    original = getattr(error, "original", error)
    if isinstance(original, (commands.MissingRole, commands.MissingPermissions, commands.CheckFailure, discord.app_commands.CheckFailure)):
        await send_slash_error(interaction, "❌ Tu n'as pas la permission requise.")
    else:
        print(f"Erreur commande slash [{interaction.command}] par [{interaction.user}] : {error}")
        await send_slash_error(interaction, "❌ Une erreur est survenue pendant cette commande.")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        try: await ctx.message.delete()
        except: pass
        await ctx.send(f"❌ {ctx.author.mention}, tu n as pas la permission requise.", delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Argument manquant pour cette commande.", delete_after=5)
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Format de commande invalide.", delete_after=5)
    else:
        print(f"Erreur commande [{ctx.command}] par [{ctx.author}] : {error}")

token_discord = os.environ.get("TOKEN")

def run_discord():
    global DISCORD_STATE, DISCORD_LAST_ERROR
    if not token_discord:
        DISCORD_STATE = "token manquant"
        DISCORD_LAST_ERROR = "La variable TOKEN est absente."
        return
    while True:
        try:
            DISCORD_STATE = "connexion en cours"
            request_discord = urllib.request.Request(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {token_discord}", "User-Agent": "PinkGiftBot/1.0"}
            )
            with urllib.request.urlopen(request_discord, timeout=20):
                pass
            break
        except urllib.error.HTTPError as error:
            if error.code == 401:
                DISCORD_STATE = "token invalide"
                DISCORD_LAST_ERROR = "Discord refuse le token (401)."
                print(DISCORD_LAST_ERROR)
                return
            if error.code == 429:
                wait_seconds = 900
                try:
                    payload = json.loads(error.read().decode("utf-8"))
                    wait_seconds = max(60, min(int(float(payload.get("retry_after", 900))) + 5, 1800))
                except Exception:
                    pass
                DISCORD_STATE = f"bloqué par Discord, nouvel essai dans {wait_seconds // 60} min"
                DISCORD_LAST_ERROR = "Discord 429 Too Many Requests"
                print(f"{DISCORD_LAST_ERROR}. Nouvel essai dans {wait_seconds} secondes.")
                time.sleep(wait_seconds)
                continue
            DISCORD_LAST_ERROR = f"Discord HTTP {error.code}"
        except Exception as error:
            DISCORD_LAST_ERROR = str(error)[:200]
        DISCORD_STATE = "nouvel essai dans 1 min"
        print(f"Connexion Discord impossible : {DISCORD_LAST_ERROR}")
        time.sleep(60)
    try:
        DISCORD_STATE = "connexion à la passerelle Discord"
        bot.run(token_discord)
    except Exception as error:
        DISCORD_STATE = "temporairement hors ligne"
        DISCORD_LAST_ERROR = str(error)[:200]
        print(f"Le bot Discord est temporairement hors ligne : {error}")

if DISCORD_ENABLED:
    Thread(target=run_discord, daemon=True).start()
else:
    print("Connexion Discord désactivée par DISCORD_ENABLED=false")
run_web()
