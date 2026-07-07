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
import sqlite3
import secrets
from functools import wraps

app = Flask('')
app.secret_key = os.environ.get("PANEL_SECRET_KEY", os.urandom(32))

@app.route('/')
def home():
    return "67 j aime le TastyCrousty"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
BOT_LOOP = None

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "pinkgift.db"))
PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
if SUPABASE_URL.endswith("/rest/v1"):
    SUPABASE_URL = SUPABASE_URL[:-8]
SUPABASE_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)



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
        db.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, channel_id INTEGER, message_id INTEGER, user_id INTEGER, service TEXT, amount REAL, paid REAL, status TEXT DEFAULT 'pending', code TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")


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

def save_order(guild_id, channel_id, message_id, user_id, service, amount, paid):
    values = {"guild_id": guild_id, "channel_id": channel_id, "message_id": message_id, "user_id": user_id, "service": service, "amount": amount, "paid": paid}
    if USE_SUPABASE:
        rows = supabase_request("POST", "orders", values, "return=representation")
        return rows[0]["id"]
    with db_connect() as db:
        cursor = db.execute("INSERT INTO orders(guild_id,channel_id,message_id,user_id,service,amount,paid) VALUES(?,?,?,?,?,?,?)", tuple(values.values()))
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
    "AMAZON": {"display": "AMAZON", "emoji": "<:amazon:1519907450403160104>", "emoji_ch": "📦"},
    "CARREFOUR": {"display": "CARREFOUR", "emoji": "<:carrefour:1519906825494073414>", "emoji_ch": "🛒"},
    "INTERMARCHE": {"display": "INTERMARCHE", "emoji": "<:intermarche:1519907100057276546>", "emoji_ch": "🏬"},
    "ZARA": {"display": "ZARA", "emoji": "<:zara:1519907265681948773>", "emoji_ch": "👕"},
    "SEPHORA": {"display": "SEPHORA", "emoji": "<:sephora:1519907492862103742>", "emoji_ch": "💄"},
    "UBEREATS": {"display": "UBER EATS", "emoji": "<:ubereats:1519907186636099604>", "emoji_ch": "🍔"},
    "APPLE": {"display": "APPLE", "emoji": "<:apple:1519906800411869204>", "emoji_ch": "🍎"},
    "GOOGLE_PLAY": {"display": "GOOGLE PLAY", "emoji": "<:googleplay:1519907060555186278>", "emoji_ch": "🎮"},
    "STEAM": {"display": "STEAM", "emoji": "<:steam:1519907154545610873>", "emoji_ch": "🎮"},
    "NETFLIX": {"display": "NETFLIX", "emoji": "<:netflix:1519907125160316928>", "emoji_ch": "🎬"},
    "SMYTHS_TOYS": {"display": "SMYTHS TOYS", "emoji": "<:smythstoys:1519907368429944832>", "emoji_ch": "🧸"},
    "ZALANDO": {"display": "ZALANDO", "emoji": "<:zalando:1519907231812816906>", "emoji_ch": "👟"},
    "KING_JOUET": {"display": "KING JOUET", "emoji": "<:kingjouet:1519907322783338557>", "emoji_ch": "🧸"},
    "LEGO": {"display": "LEGO", "emoji": "<:lego:1519907470854852720>", "emoji_ch": "🧱"},
    "ADIDAS": {"display": "ADIDAS", "emoji": "<:adidas:1519906784515588116>", "emoji_ch": "👟"},
    "FOOT_LOCKER": {"display": "FOOT LOCKER", "emoji": "<:footlocker:1519907296342310952>", "emoji_ch": "👟"},
    "DELIVEROO": {"display": "DELIVEROO", "emoji": "<:deliveroo:1519906860356993174>", "emoji_ch": "🍽️"},
    "CLAUDE": {"display": "CLAUDE", "emoji": "<:claude:1519906842006913065>", "emoji_ch": "✨"},
    "AIRBNB": {"display": "AIRBNB", "emoji": "<:airbnb:1519906701900386344>", "emoji_ch": "🏠"},
    "XBOX": {"display": "XBOX", "emoji": "<:xbox:1519907418836828230>", "emoji_ch": "🎮"},
    "PLAYSTATION": {"display": "PLAYSTATION", "emoji": "<:playstation:1519906767268741200>", "emoji_ch": "🎮"},
    "PAYSAFECARD": {"display": "PAYSAFECARD", "emoji": "<:paysafecard:1519906750571085995>", "emoji_ch": "💳"},
    "FNAC": {"display": "FNAC", "emoji": "<:fnac:1519906718140727387>", "emoji_ch": "📚"},
    "NINTENDO": {"display": "NINTENDO", "emoji": "<:nintendo:1519907394157678632>", "emoji_ch": "🎮"},
    "NIKE": {"display": "NIKE", "emoji": "<:nike:1519906735589167164>", "emoji_ch": "👟"},
    "VALORANT": {"display": "VALORANT", "emoji": "🎮", "emoji_ch": "🎮"},
}

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
            "Choisis une option puis clique sur le bouton pour ouvrir un ticket avec le staff. Toutes les cartes cadeaux à -30%.",
            "",
            "📦 **Amazon**", "🛒 **Carrefour**", "🏬 **Intermarché**", "👕 **Zara**", "💄 **Sephora**",
            "🍔 **Uber Eats**", "🍎 **Apple**", "🎮 **Google Play**", "🎮 **Steam**", "🎬 **Netflix**",
            "🧸 **Smyths Toys**", "<:zalando:1519907231812816906> **Zalando**", "🧸 **King Jouet**", "🧱 **LEGO**", "👟 **Adidas**",
            "👟 **Foot Locker**", "🍽️ **Deliveroo**", "✨ **Claude**", "🏠 **Airbnb**", "🎮 **Xbox**",
            "🎮 **PlayStation**", "💳 **Paysafecard**", "📚 **Fnac**", "🎮 **Nintendo**", "👟 **Nike**",
            "",
            "🎫 Clique sur le bouton Commander ci-dessous pour choisir ta marque et ton montant en privé."
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
    "paiements_embed": {
        "title": "💳 Moyens de paiement",
        "description": [
            "Pour finaliser votre achat chez **PinkGift**, nous acceptons :",
            "",
            "<:paypal:1517582845315649751> **PayPal**",
            "🏦 **Virements bancaires**",
            "₿ **Cryptomonnaies**",
            "",
            "Merci d'indiquer le moyen de paiement souhaite dans le ticket."
        ],
        "color_rgb": [255, 192, 203],
        "footer": "PinkGift — Paiements"
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
                "value": "!tarifs : affiche les cartes cadeaux et les menus de commande.\n!valo : envoie l'embed Valorant avec son bouton ticket.\n!paiements : envoie les moyens de paiement.\n!maj_tarifs, !maj_valo, !maj_paiements : mettent à jour sans ping.\n!maj_categories : met à jour tous les embeds publics sans ping.\n!close_button : ajoute un bouton Close persistant.",
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

DEFAULT_EMBED_DATA.update({"balance_embed":{"title":"💰 Solde PinkGift","description":["{user}, ton solde actuel est de **{balance} €**.","","Utilise les boutons ci-dessous pour consulter ou recharger ton solde."],"color_rgb":[255,192,203]},"balance_ticket_embed":{"title":"➕ Recharge de solde","description":["Bonjour {user} !","","Ton solde actuel est de **{balance} €**.","Indique au staff le montant et le moyen de paiement souhaités."],"color_rgb":[255,192,203],"image_key":"paiement_securise"}})

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
        await interaction.followup.send("❌ Impossible de creer ce ticket.", ephemeral=True)
        return

    category = guild.get_channel(TICKET_CATEGORY_ID)
    if category is None:
        await interaction.followup.send("❌ Categorie ticket introuvable.", ephemeral=True)
        return

    for channel in category.text_channels:
        if channel.topic == f"pinkgift-owner:{user.id}" and not channel.name.startswith("closed-"):
            await interaction.followup.send(f"ℹ️ Tu as deja un ticket ouvert : {channel.mention}", ephemeral=True)
            return

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
        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{product_key.lower().replace('_', '-')}-{safe_user}"[:95],
            category=category,
            topic=f"pinkgift-owner:{user.id}",
            overwrites=overwrites,
            reason=f"Commande {cfg['display']} {amount} euros par {user}"
        )
    except discord.HTTPException as error:
        if error.status == 429:
            message = "⏳ Discord limite temporairement la creation de salons. Attends quelques minutes avant de reessayer."
        else:
            message = "❌ Discord a refuse la creation du ticket. Verifie les permissions du bot."
        await interaction.followup.send(message, ephemeral=True)
        print(f"Erreur creation ticket menu pour {user}: {error}")
        return

    paid_amount = round(amount * 0.70, 2)
    embed = build_json_embed("menu_ticket_embed", {
        "user": user.mention,
        "service": cfg["display"],
        "emoji": cfg["emoji"],
        "amount": amount,
        "paid": f"{paid_amount:g}"
    })
    order_message = await ticket_channel.send(
        content=f"{user.mention} | <@&{STAFF_ROLE_ID}>",
        embed=embed,
        view=CloseTicketView(user.id)
    )
    save_order(guild.id, ticket_channel.id, order_message.id, user.id, cfg["display"], amount, paid_amount)
    await interaction.followup.send(f"✅ Ton ticket a ete cree : {ticket_channel.mention}", ephemeral=True)


class ProductAmountSelect(discord.ui.Select):
    def __init__(self, product_key):
        self.product_key = product_key
        options = [
            discord.SelectOption(label=f"Carte cadeau {amount} €", value=str(amount), emoji="💳")
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
        await interaction.response.send_message(
            f"{cfg['emoji']} **{cfg['display']}** — choisis maintenant le montant :",
            view=ProductAmountView(product_key),
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
            if channel.topic == f"pinkgift-balance:{user.id}" and not channel.name.startswith("closed-"):
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
        channel = await guild.create_text_channel(name=f"solde-{user.name}"[:95], category=category, topic=f"pinkgift-balance:{user.id}", overwrites=overwrites, reason=f"Recharge solde de {user}")
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
        is_client = self.client_id and interaction.user.id == self.client_id
        if not is_staff and not is_client:
            await interaction.response.send_message("❌ Tu n as pas la permission de fermer ce ticket.", ephemeral=True)
            return
        if client:
            await channel.set_permissions(client, view_channel=False, send_messages=False, read_message_history=False)
        elif guild:
            for target, overwrite in channel.overwrites.items():
                if isinstance(target, discord.Member):
                    has_staff_role = staff_role in target.roles if staff_role else False
                    if not target.bot and not has_staff_role:
                        await channel.set_permissions(target, view_channel=False, send_messages=False, read_message_history=False)
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

def build_paiements_embed():
    texts = load_embed_texts().get("paiements_embed", DEFAULT_EMBED_DATA["paiements_embed"])
    rgb = texts.get("color_rgb", [255, 192, 203])
    desc_raw = texts.get("description", [])
    description = "\n".join(desc_raw) if isinstance(desc_raw, list) else str(desc_raw)
    embed = discord.Embed(title=texts.get("title", "💳 Moyens de paiement"), description=description, color=discord.Color.from_rgb(rgb[0], rgb[1], rgb[2]))
    footer = texts.get("footer", "PinkGift — Paiements")
    if footer:
        embed.set_footer(text=footer)
    image_url = texts.get("image_url", "") or get_image_url("paiement_securise", "")
    if image_url:
        embed.set_image(url=image_url)
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
        (["VALORANT", "VALORANT POINTS"], build_valo_embed, None),
        (["Moyens de paiement", "Paiements"], build_paiements_embed, None),
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


@bot.command(name="maj_categories")
@commands.has_role(PURGE_ROLE_ID)
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


@bot.command(name="debug_embed")
@commands.has_role(PURGE_ROLE_ID)
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


@bot.command(name="close_button")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_close_button(ctx):
    embed = build_json_embed("close_ticket_embed")
    await ctx.send(embed=embed, view=CloseTicketView())

@bot.command(name="tarifs")
@commands.has_role(PURGE_ROLE_ID)
async def send_tarifs(ctx):
    embed = build_tarifs_embed()
    await ctx.send(content="||@everyone||", embed=embed, view=OrderLauncherView())

@bot.command(name="maj_tarifs")
@commands.has_role(PURGE_ROLE_ID)
async def update_tarifs(ctx):
    await update_last_embed(ctx, build_tarifs_embed, ["COMMANDES PINKGIFT", "CARTE CADEAUX"], OrderLauncherView())

@bot.command(name="valo")
@commands.has_role(PURGE_ROLE_ID)
async def cmd_valo(ctx):
    embed = build_valo_embed()
    await ctx.send(content="||@everyone||", embed=embed, view=ValoTicketButton())

@bot.command(name="maj_valo")
@commands.has_role(PURGE_ROLE_ID)
async def update_valo(ctx):
    await update_last_embed(ctx, build_valo_embed, ["VALORANT", "VALORANT POINTS"])

@bot.command(name="purge_all")
@commands.has_role(PURGE_ROLE_ID)
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

@bot.command(name="clear", aliases=["purge"])
@commands.has_role(PURGE_ROLE_ID)
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

@bot.command(name="ban")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_ban(ctx, member: discord.Member, *, reason: str = "Aucune raison fournie"):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 {member.name} a ete banni. Raison : {reason}")

@bot.command(name="tempban")
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

@bot.command(name="tempmute")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_tempmute(ctx, member: discord.Member, duration: str, *, reason: str = "Aucune raison fournie"):
    seconds = parse_duration(duration)
    if not seconds:
        await ctx.send("❌ Format invalide. Exemple : 10m, 2h.")
        return
    await member.timeout(datetime.timedelta(seconds=seconds), reason=reason)
    await ctx.send(f"🔇 {member.name} mute pendant {duration}.")

@bot.command(name="solde")
async def cmd_solde(ctx):
    balance = get_balance(ctx.guild.id, ctx.author.id)
    embed = build_json_embed("balance_embed", {"user": ctx.author.mention, "balance": f"{balance:.2f}"})
    await ctx.send(embed=embed, view=BalanceView())


@bot.command(name="ajouter_solde")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_ajouter_solde(ctx, member: discord.Member, montant: float):
    if montant <= 0:
        await ctx.send("❌ Le montant doit être positif.", delete_after=5)
        return
    balance = change_balance(ctx.guild.id, member.id, montant, ctx.author.id)
    await ctx.send(f"✅ **{montant:.2f} €** ajoutés à {member.mention}. Nouveau solde : **{balance:.2f} €**.")


@bot.command(name="retirer_solde")
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


@bot.command(name="paiements")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_paiements(ctx):
    try:
        await ctx.message.delete()
    except:
        pass
    embed = build_paiements_embed()
    await ctx.send(content="||@everyone||", embed=embed)

@bot.command(name="maj_paiements")
@commands.has_role(STAFF_ROLE_ID)
async def update_paiements(ctx):
    await update_last_embed(ctx, build_paiements_embed, ["Moyens de paiement", "Paiements"])

async def process_order(ctx, product_name, amount_paid: int, card_code: str = "En attente..."):
    try:
        await ctx.message.delete()
    except:
        pass
    cfg = PRODUCT_CONFIG.get(product_name)
    if cfg is None:
        await ctx.send("❌ Article introuvable.", delete_after=5)
        return
    display_name = cfg["display"]
    emoji = cfg["emoji_ch"]
    paid_amount = round(amount_paid * 0.7, 2)
    paid_display = int(paid_amount) if paid_amount.is_integer() else paid_amount
    new_name = ticket_channel_name(emoji, display_name, f"{amount_paid}€")
    try:
        await ctx.channel.edit(name=new_name)
    except Exception as e:
        await ctx.send(f"❌ Impossible de renommer le ticket : {e}", delete_after=5)
        return
    client_user = ctx.author
    async for msg in ctx.channel.history(oldest_first=True, limit=8):
        if msg.author != bot.user and not msg.author.bot:
            client_user = msg.author
            break
    embed = build_json_embed("commande_embed", {
        "emoji": emoji, "user": client_user.mention, "service": display_name,
        "amount": amount_paid, "paid": paid_display,
        "code": (chr(96) * 3) + "\n" + card_code + "\n" + (chr(96) * 3)
    })
    order_message = await ctx.send(content=f"{client_user.mention} commande enregistree : **{display_name}-{amount_paid}€**", embed=embed)
    save_order(ctx.guild.id, ctx.channel.id, order_message.id, client_user.id, display_name, amount_paid, paid_display)


async def process_vp_order(ctx, amount_paid: int, code: str = "En attente..."):
    try:
        await ctx.message.delete()
    except:
        pass

    vp_packs = {
        30: "3650 VP",
        40: "5350 VP",
        60: "8700 VP",
        15: "2925 VP",
        20: "4325 VP",
        45: "8900 VP",
    }
    pack = vp_packs.get(amount_paid)
    if pack is None:
        await ctx.send("❌ Pack Valorant introuvable. Montants disponibles : 15, 20, 30, 40, 45 ou 60 euros.", delete_after=8)
        return

    cfg = PRODUCT_CONFIG.get("VALORANT")
    emoji = cfg["emoji_ch"] if cfg else "🎮"
    try:
        await ctx.channel.edit(name=ticket_channel_name(emoji, "VALORANT", pack))
    except Exception as e:
        await ctx.send(f"❌ Impossible de renommer le ticket : {e}", delete_after=5)
        return

    client_user = ctx.author
    async for msg in ctx.channel.history(oldest_first=True, limit=8):
        if msg.author != bot.user and not msg.author.bot:
            client_user = msg.author
            break

    embed = build_json_embed("commande_vp_embed", {
        "emoji": emoji, "user": client_user.mention, "pack": pack,
        "amount": amount_paid,
        "code": (chr(96) * 3) + "\n" + code + "\n" + (chr(96) * 3)
    })
    order_message = await ctx.send(content=f"{client_user.mention} commande Valorant enregistree : **{pack} — {amount_paid}€**", embed=embed)
    save_order(ctx.guild.id, ctx.channel.id, order_message.id, client_user.id, "Valorant " + pack, amount_paid, amount_paid)

@bot.command(name="amazon")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_amazon(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "AMAZON", amount, code)

@bot.command(name="carrefour")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_carrefour(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "CARREFOUR", amount, code)

@bot.command(name="intermarche")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_intermarche(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "INTERMARCHE", amount, code)

@bot.command(name="zara")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_zara(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "ZARA", amount, code)

@bot.command(name="sephora")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_sephora(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "SEPHORA", amount, code)

@bot.command(name="ubereats")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_ubereats(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "UBEREATS", amount, code)

@bot.command(name="apple")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_apple(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "APPLE", amount, code)

@bot.command(name="googleplay")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_googleplay(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "GOOGLE_PLAY", amount, code)

@bot.command(name="steam")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_steam(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "STEAM", amount, code)

@bot.command(name="netflix")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_netflix(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "NETFLIX", amount, code)

@bot.command(name="smyths")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_smyths(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "SMYTHS_TOYS", amount, code)

@bot.command(name="zalando")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_zalando(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "ZALANDO", amount, code)

@bot.command(name="kingjouet")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_kingjouet(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "KING_JOUET", amount, code)

@bot.command(name="lego")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_lego(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "LEGO", amount, code)

@bot.command(name="adidas")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_adidas(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "ADIDAS", amount, code)

@bot.command(name="footlocker")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_footlocker(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "FOOT_LOCKER", amount, code)

@bot.command(name="deliveroo")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_deliveroo(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "DELIVEROO", amount, code)

@bot.command(name="claude")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_claude(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "CLAUDE", amount, code)

@bot.command(name="airbnb")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_airbnb(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "AIRBNB", amount, code)

@bot.command(name="xbox")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_xbox(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "XBOX", amount, code)

@bot.command(name="playstation")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_playstation(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "PLAYSTATION", amount, code)

@bot.command(name="paysafecard")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_paysafecard(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "PAYSAFECARD", amount, code)

@bot.command(name="fnac")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_fnac(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "FNAC", amount, code)

@bot.command(name="nintendo")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_nintendo(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "NINTENDO", amount, code)

@bot.command(name="nike")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_nike(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "NIKE", amount, code)

@bot.command(name="vp")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_vp(ctx, amount: int, *, code: str = "En attente..."): await process_vp_order(ctx, amount, code)

@bot.command(name="finish")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_finish(ctx, *, code_carte: str):
    try:
        await ctx.message.delete()
    except:
        pass
    embed_message = None
    async for msg in ctx.channel.history(limit=30):
        if msg.author == bot.user and msg.embeds:
            embed_message = msg
            break
    if not embed_message:
        await ctx.send("❌ Aucun embed de commande trouve dans ce salon.", delete_after=5)
        return
    old_embed = embed_message.embeds[0]
    finish_data = load_embed_texts().get("commande_finalisee", DEFAULT_EMBED_DATA["commande_finalisee"])
    finish_rgb = finish_data.get("color_rgb", [46, 204, 113])
    new_embed = discord.Embed(title=old_embed.title, description=old_embed.description, color=discord.Color.from_rgb(*finish_rgb))
    code_updated = False
    for field in old_embed.fields:
        if "code" in field.name.lower():
            new_embed.add_field(name=field.name, value=f"```\n{code_carte}\n```", inline=False)
            code_updated = True
        else:
            new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
    if not code_updated:
        new_embed.add_field(name="Code", value=f"```\n{code_carte}\n```", inline=False)
    finish_image_key = finish_data.get("image_key", "commande_livree")
    finish_image_url = finish_data.get("image_url", ORDER_FINISHED_IMAGE_URL)
    new_embed.set_image(url=get_image_url(finish_image_key, finish_image_url))
    new_embed.set_footer(text=finish_data.get("footer", "PinkGift — Commande finalisee"))
    await embed_message.edit(embed=new_embed)
    await ctx.send("✅ Commande finalisee avec succes.", delete_after=5)

@bot.command(name="commandes")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_directory(ctx):
    await ctx.send(embed=build_json_embed("commandes_embed"))

def panel_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("panel_authenticated"):
            return redirect(url_for("panel_login"))
        return view(*args, **kwargs)
    return wrapped


PANEL_TEMPLATE = """
<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Commandes</title>
<style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:22px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}h1{margin:0;color:#ff8fc8;font-size:24px}main{padding:24px 5%}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}table{width:100%;border-collapse:collapse;background:#171419}th,td{text-align:left;padding:12px;border-bottom:1px solid #332630}th{color:#ff9dce}input{background:#0e0d11;color:white;border:1px solid #5a3a4d;padding:9px;min-width:180px}button{background:#e8509a;color:white;border:0;padding:10px 14px;cursor:pointer}.done{color:#74d99f}.pending{color:#ffd27b}@media(max-width:800px){table,thead,tbody,tr,td{display:block}thead{display:none}tr{padding:12px;border-bottom:1px solid #332630}td{border:0;padding:6px}}</style></head><body>
<header><h1>PinkGift — Commandes</h1><a href="{{ url_for('panel_logout') }}" style="color:#ff9dce">Déconnexion</a></header><main>
{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}
<table><thead><tr><th>ID</th><th>Client</th><th>Service</th><th>Reçu</th><th>Payé</th><th>État</th><th>Code cadeau</th></tr></thead><tbody>
{% for order in orders %}<tr><td>#{{ order.id }}</td><td>{{ order.user_id }}</td><td>{{ order.service }}</td><td>{{ order.amount }} €</td><td>{{ order.paid }} €</td><td class="{{ order.status }}">{{ order.status }}</td><td><form method="post" action="{{ url_for('panel_set_code', order_id=order.id) }}"><input name="code" required placeholder="Code de la carte" value="{{ order.code or '' }}"><button type="submit">Livrer</button></form></td></tr>{% else %}<tr><td colspan="7">Aucune commande enregistrée.</td></tr>{% endfor %}
</tbody></table></main></body></html>"""


LOGIN_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift</title><style>body{background:#0e0d11;color:#fff;font-family:Arial;display:grid;place-items:center;height:100vh;margin:0}form{background:#19151b;padding:28px;border:1px solid #4a3040;width:min(340px,80vw)}h1{color:#ff8fc8}input,button{box-sizing:border-box;width:100%;padding:12px;margin-top:10px}input{background:#0e0d11;color:#fff;border:1px solid #5a3a4d}button{background:#e8509a;color:#fff;border:0}</style></head><body><form method="post"><h1>PinkGift Staff</h1><input type="password" name="password" placeholder="Mot de passe" required><button>Connexion</button></form></body></html>"""


@app.route("/panel/login", methods=["GET", "POST"])
def panel_login():
    if request.method == "POST" and PANEL_PASSWORD and secrets.compare_digest(request.form.get("password", ""), PANEL_PASSWORD):
        session["panel_authenticated"] = True
        return redirect(url_for("panel_orders"))
    return render_template_string(LOGIN_TEMPLATE)


@app.route("/panel/logout")
def panel_logout():
    session.clear()
    return redirect(url_for("panel_login"))


@app.route("/panel")
@panel_required
def panel_orders():
    try:
        if USE_SUPABASE:
            orders = supabase_request("GET", "orders?select=*&order=id.desc&limit=300")
        else:
            with db_connect() as db:
                orders = db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 300").fetchall()
    except Exception as error:
        print(f"Erreur chargement panneau : {error}")
        flash("Connexion à Supabase impossible. Vérifie SUPABASE_URL, SUPABASE_SECRET_KEY et le script SQL.")
        orders = []
    return render_template_string(PANEL_TEMPLATE, orders=orders)


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


@app.post("/panel/orders/<int:order_id>/code")
@panel_required
def panel_set_code(order_id):
    code = request.form.get("code", "").strip()
    if USE_SUPABASE:
        rows = supabase_request("GET", f"orders?id=eq.{order_id}&select=*")
        order = rows[0] if rows else None
    else:
        with db_connect() as db:
            order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order or not code:
        flash("Commande ou code invalide.")
        return redirect(url_for("panel_orders"))
    if BOT_LOOP is None:
        flash("Le bot Discord n'est pas encore prêt.")
        return redirect(url_for("panel_orders"))
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
    return redirect(url_for("panel_orders"))


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        try: await ctx.message.delete()
        except: pass
        await ctx.send(f"❌ {ctx.author.mention}, tu n as pas la permission requise.", delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Argument manquant. Exemple : !deliveroo 60", delete_after=5)
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Format invalide. Exemple : !deliveroo 60", delete_after=5)
    else:
        print(f"Erreur commande [{ctx.command}] par [{ctx.author}] : {error}")

Thread(target=run_web, daemon=True).start()

token_discord = os.environ.get("TOKEN")
bot.run(token_discord)
