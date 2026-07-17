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
import io
import traceback
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
        # Toutes les vues persistantes doivent être enregistrées ici, avant
        # la connexion complète du bot. Cela permet aux boutons déjà publiés
        # de continuer à fonctionner après un redémarrage.
        persistent_views = (
            OrderLauncherView(),
            ValoOrderLauncherView(),
            BalanceView(),
            OpenTicketView(),
            ValoTicketButton(),
            CloseTicketView(),
            GiveawayJoinView(),
        )
        for view in persistent_views:
            self.add_view(view)

        print(f"✅ {len(persistent_views)} vues persistantes enregistrées.")


bot = PinkGiftBot(command_prefix="!", intents=intents)
BOT_LOOP = None
DISCORD_STATE = "démarrage"
DISCORD_LAST_ERROR = ""
ORDER_LOCKS = {}
INVITE_USAGE_CACHE = {}
INVITE_TRACKING_LOCKS = {}
RECENTLY_DELETED_INVITES = {}
DISCORD_THREAD_STARTED = False
COMMAND_SYNC_DONE = False
PUBLIC_VIEWS_REPAIRED = False
SERVER_COUNTER_REFRESH_TASK = None
SERVER_COUNTER_UPDATE_TASKS = {}
SERVER_COUNTER_UPDATE_FLAGS = {}
SERVER_COUNTER_LOCKS = {}
SERVER_COUNTER_REFRESH_SECONDS = 300
SERVER_COUNTER_CATEGORY_NAME = "📊・STATISTIQUES"
MUTED_ROLE_ID = 1525614378580312165
AUTO_REACTION_CHANNEL_IDS = {1525601407825084436, 1517525842111234088}
AUTO_REACTION_EMOJIS = ("<:verify:1525796690899108000>", "<:waylaylove:1517582297736413284>")
VERIFIED_REVIEWS_CHANNEL_IDS = {1525601407825084436, 1517525842111234088}
REFERRAL_TRACKING_CHANNEL_ID = 1525601870561935391
STOCK_OK_EMOJI = "<:verify:1525796690899108000>"
STOCK_KO_EMOJI = "<:crossmark:1525798036276514887>"

GIVEAWAY_JOIN_EMOJI = "🎉"
BOT_AUTH_KEY = os.environ.get("BOT_AUTH_KEY", "").strip()
AUTHORIZED_GUILD_IDS_ENV = os.environ.get("AUTHORIZED_GUILD_IDS", "").strip()
GUILD_AUTH_GRACE_SECONDS = int(os.environ.get("GUILD_AUTH_GRACE_SECONDS", "600") or 600)

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "pinkgift.db"))
PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
if SUPABASE_URL.endswith("/rest/v1"):
    SUPABASE_URL = SUPABASE_URL[:-8]
SUPABASE_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)
DISCORD_ENABLED = os.environ.get("DISCORD_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
PANEL_AUDIT_KEY = os.environ.get("PANEL_AUDIT_KEY", "").strip()



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
        db.execute("CREATE TABLE IF NOT EXISTS panel_access_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT NOT NULL DEFAULT '', path TEXT NOT NULL DEFAULT '', method TEXT NOT NULL DEFAULT '', device TEXT NOT NULL DEFAULT '', user_agent TEXT NOT NULL DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        db.execute("CREATE TABLE IF NOT EXISTS panel_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT '{}', updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
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


def decode_setting_value(value, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def get_panel_setting(key, default=None):
    try:
        if USE_SUPABASE:
            safe_key = urllib.parse.quote(str(key), safe="")
            rows = supabase_request("GET", f"panel_settings?key=eq.{safe_key}&select=value&limit=1") or []
            return decode_setting_value(rows[0].get("value") if rows else None, default)
        with db_connect() as db:
            row = db.execute("SELECT value FROM panel_settings WHERE key=?", (key,)).fetchone()
            return decode_setting_value(row["value"] if row else None, default)
    except Exception as error:
        print(f"Erreur lecture setting panel {key}: {error}")
        return default


def set_panel_setting(key, value):
    if USE_SUPABASE:
        supabase_request("POST", "panel_settings?on_conflict=key", {"key": key, "value": value}, "resolution=merge-duplicates")
        return
    with db_connect() as db:
        db.execute(
            "INSERT INTO panel_settings(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
            (key, json.dumps(value, ensure_ascii=False))
        )


def list_panel_settings(prefix=""):
    try:
        if USE_SUPABASE:
            rows = supabase_request("GET", "panel_settings?select=key,value&limit=1000") or []
            result = []
            for row in rows:
                key = str(row.get("key", ""))
                if not prefix or key.startswith(prefix):
                    result.append({"key": key, "value": decode_setting_value(row.get("value"), {})})
            return result
        with db_connect() as db:
            if prefix:
                rows = db.execute("SELECT key,value FROM panel_settings WHERE key LIKE ?", (f"{prefix}%",)).fetchall()
            else:
                rows = db.execute("SELECT key,value FROM panel_settings").fetchall()
            return [{"key": row["key"], "value": decode_setting_value(row["value"], {})} for row in rows]
    except Exception as error:
        print(f"Erreur liste settings panel {prefix}: {error}")
        return []


def normalize_referral_code(value):
    return re.sub(r"[^A-Z0-9_-]", "", str(value or "").strip().upper())[:32]


def valid_referral_percentage(value, fallback=0):
    try:
        percentage = round(float(value), 2)
        if 0 <= percentage <= 100:
            return percentage
    except (TypeError, ValueError):
        pass
    return round(float(fallback), 2)


def get_referral_codes():
    saved = get_panel_setting("referral_codes", {}) or {}
    if not isinstance(saved, dict):
        return {}
    codes = {}
    for raw_code, raw_data in saved.items():
        code = normalize_referral_code(raw_code)
        if len(code) < 3 or not isinstance(raw_data, dict):
            continue
        sponsor_id = re.sub(r"\D", "", str(raw_data.get("sponsor_id") or ""))[:25]
        try:
            paid = max(0.0, round(float(raw_data.get("paid") or 0), 2))
        except (TypeError, ValueError):
            paid = 0.0
        codes[code] = {
            "code": code,
            "sponsor_name": str(raw_data.get("sponsor_name") or code).strip()[:80],
            "sponsor_id": sponsor_id,
            "percentage": valid_referral_percentage(raw_data.get("percentage"), 0),
            "paid": paid,
            "active": bool(raw_data.get("active", True)),
            "created_at": str(raw_data.get("created_at") or ""),
        }
    return codes


def save_referral_codes(codes):
    set_panel_setting("referral_codes", codes)


def get_active_referral_code(value):
    code = normalize_referral_code(value)
    data = get_referral_codes().get(code)
    return data if data and data.get("active") else None


def referral_ledger_setting_key(guild_id, user_id):
    return f"referral_ledger:{int(guild_id)}:{int(user_id)}"


def get_referral_ledger(guild_id, user_id):
    data = get_panel_setting(referral_ledger_setting_key(guild_id, user_id), {}) or {}
    if not isinstance(data, dict):
        data = {}
    lots = data.get("lots") if isinstance(data.get("lots"), list) else []
    events = data.get("events") if isinstance(data.get("events"), list) else []
    return {"lots": lots, "events": events}


def save_referral_ledger(guild_id, user_id, ledger):
    set_panel_setting(referral_ledger_setting_key(guild_id, user_id), ledger)


def load_referral_ledgers():
    if USE_SUPABASE:
        items = []
        offset = 0
        while True:
            prefix = urllib.parse.quote("referral_ledger:", safe="")
            page = supabase_request(
                "GET",
                f"panel_settings?key=like.{prefix}*&select=key,value&order=key&limit=1000&offset={offset}",
            ) or []
            items.extend(page)
            if len(page) < 1000:
                break
            offset += len(page)
    else:
        items = list_panel_settings("referral_ledger:")
    ledgers = []
    for item in items:
        value = item.get("value", {})
        if not isinstance(value, dict):
            continue
        parts = str(item.get("key") or "").split(":")
        try:
            guild_id = int(parts[1])
            user_id = int(parts[2])
        except (IndexError, TypeError, ValueError):
            continue
        ledgers.append({
            "guild_id": guild_id,
            "user_id": user_id,
            "lots": value.get("lots") if isinstance(value.get("lots"), list) else [],
            "events": value.get("events") if isinstance(value.get("events"), list) else [],
        })
    return ledgers


def load_referral_events(ledgers=None):
    events = []
    for ledger in ledgers or load_referral_ledgers():
        for raw_event in ledger.get("events", []):
            if not isinstance(raw_event, dict):
                continue
            event = dict(raw_event)
            event["user_id"] = int(event.get("user_id") or ledger.get("user_id") or 0)
            event["code"] = normalize_referral_code(event.get("code"))
            for key in ("referred_used", "sale_amount", "purchase_cost", "attributed_profit", "commission"):
                try:
                    event[key] = round(float(event.get(key) or 0), 2)
                except (TypeError, ValueError):
                    event[key] = 0.0
            events.append(event)
    return sorted(events, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def build_referral_summaries(codes, ledgers):
    summaries = {}
    for code, data in codes.items():
        summaries[code] = {
            **data,
            "uses": 0,
            "_orders": set(),
            "credited": 0.0,
            "remaining": 0.0,
            "amount": 0.0,
            "profit": 0.0,
            "commission": 0.0,
        }
    for ledger in ledgers:
        for lot in ledger.get("lots", []):
            if not isinstance(lot, dict):
                continue
            code = normalize_referral_code(lot.get("code"))
            if not code:
                continue
            item = summaries.setdefault(code, {
                "code": code, "sponsor_name": str(lot.get("sponsor_name") or code),
                "sponsor_id": str(lot.get("sponsor_id") or ""),
                "percentage": valid_referral_percentage(lot.get("percentage"), 0),
                "paid": 0.0, "active": False, "created_at": "", "uses": 0, "_orders": set(),
                "credited": 0.0, "remaining": 0.0, "amount": 0.0,
                "profit": 0.0, "commission": 0.0,
            })
            item["credited"] += float(lot.get("credited") or 0)
            item["remaining"] += float(lot.get("remaining") or 0)
    for event in load_referral_events(ledgers):
        code = normalize_referral_code(event.get("code"))
        if not code:
            continue
        item = summaries.setdefault(code, {
            "code": code, "sponsor_name": str(event.get("sponsor_name") or code),
            "sponsor_id": str(event.get("sponsor_id") or ""),
            "percentage": valid_referral_percentage(event.get("percentage"), 0),
            "paid": 0.0, "active": False, "created_at": "", "uses": 0, "_orders": set(),
            "credited": 0.0, "remaining": 0.0, "amount": 0.0,
            "profit": 0.0, "commission": 0.0,
        })
        order_key = str(event.get("order_message_id") or event.get("created_at") or len(item["_orders"]))
        item["_orders"].add(order_key)
        item["amount"] += float(event.get("referred_used") or 0)
        item["profit"] += float(event.get("attributed_profit") or 0)
        item["commission"] += float(event.get("commission") or 0)
    result = []
    for item in summaries.values():
        item["uses"] = len(item.pop("_orders", set()))
        for key in ("credited", "remaining", "amount", "profit", "commission"):
            item[key] = round(item[key], 2)
        item["due"] = round(max(0.0, item["commission"] - float(item.get("paid") or 0)), 2)
        result.append(item)
    return sorted(result, key=lambda item: (-item["due"], item["code"]))




def invite_setting_key(guild_id: int) -> str:
    return f"invite_tracking:{int(guild_id)}"


def get_invite_tracking_data(guild_id: int) -> dict:
    data = get_panel_setting(invite_setting_key(guild_id), {}) or {}
    if not isinstance(data, dict):
        data = {}
    inviters = data.get("inviters")
    members = data.get("members")
    if not isinstance(inviters, dict):
        inviters = {}
    if not isinstance(members, dict):
        members = {}
    return {"inviters": inviters, "members": members}


def save_invite_tracking_data(guild_id: int, data: dict) -> None:
    set_panel_setting(invite_setting_key(guild_id), data)


def invite_user_stats(guild_id: int, user_id: int) -> dict:
    data = get_invite_tracking_data(guild_id)
    raw = data["inviters"].get(str(user_id), {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "total": max(0, int(raw.get("total", 0) or 0)),
        "active": max(0, int(raw.get("active", 0) or 0)),
        "left": max(0, int(raw.get("left", 0) or 0)),
    }


async def fetch_invite_snapshot(guild: discord.Guild):
    try:
        invites = await guild.invites()
    except discord.Forbidden:
        print(
            f"Tracking invitations impossible sur {guild.name} ({guild.id}) : "
            "le bot doit avoir la permission Gérer le serveur."
        )
        return None
    except discord.HTTPException as error:
        print(f"Erreur récupération invitations sur {guild.id}: {error}")
        return None

    snapshot = {}
    for invite in invites:
        snapshot[invite.code] = {
            "uses": int(invite.uses or 0),
            "inviter_id": invite.inviter.id if invite.inviter else None,
            "max_uses": int(invite.max_uses or 0),
        }
    return snapshot


async def refresh_invite_cache(guild: discord.Guild) -> bool:
    snapshot = await fetch_invite_snapshot(guild)
    if snapshot is None:
        return False
    INVITE_USAGE_CACHE[guild.id] = snapshot
    return True


async def initialize_invite_tracking() -> None:
    initialized = 0
    for guild in bot.guilds:
        if await refresh_invite_cache(guild):
            initialized += 1
    print(f"✅ Cache des invitations initialisé pour {initialized} serveur(s).")


async def detect_used_invite(guild: discord.Guild):
    lock = INVITE_TRACKING_LOCKS.setdefault(guild.id, asyncio.Lock())
    async with lock:
        current = await fetch_invite_snapshot(guild)
        if current is None:
            return None

        previous = INVITE_USAGE_CACHE.get(guild.id)
        INVITE_USAGE_CACHE[guild.id] = current
        if previous is None:
            # Première observation : on crée seulement une référence, sans
            # attribuer à tort d'anciennes utilisations au nouveau membre.
            return None

        candidates = []
        for code, current_data in current.items():
            previous_data = previous.get(code)
            if not previous_data:
                continue
            delta = int(current_data.get("uses", 0)) - int(previous_data.get("uses", 0))
            if delta > 0:
                candidates.append((delta, code, current_data))

        if candidates:
            _, code, data = max(candidates, key=lambda item: item[0])
            return {"code": code, **data}

        # Certaines invitations à usage unique disparaissent juste après leur
        # utilisation. on_invite_delete les conserve brièvement ici.
        recent = RECENTLY_DELETED_INVITES.get(guild.id, {})
        now = time.monotonic()
        expired_codes = []
        deleted_candidates = []
        for code, data in recent.items():
            if now - float(data.get("deleted_at", 0)) > 15:
                expired_codes.append(code)
                continue
            max_uses = int(data.get("max_uses", 0) or 0)
            uses = int(data.get("uses", 0) or 0)
            if max_uses > 0 and uses + 1 >= max_uses:
                deleted_candidates.append((code, data))
        for code in expired_codes:
            recent.pop(code, None)

        if deleted_candidates:
            code, data = max(deleted_candidates, key=lambda item: float(item[1].get("deleted_at", 0)))
            recent.pop(code, None)
            return {"code": code, **data}
        return None


async def register_invited_member(member: discord.Member) -> None:
    if member.bot:
        return
    used_invite = await detect_used_invite(member.guild)
    if not used_invite:
        return
    inviter_id = used_invite.get("inviter_id")
    if not inviter_id or int(inviter_id) == member.id:
        return

    lock = INVITE_TRACKING_LOCKS.setdefault(member.guild.id, asyncio.Lock())
    async with lock:
        data = get_invite_tracking_data(member.guild.id)
        member_key = str(member.id)
        previous_member_data = data["members"].get(member_key)

        # Évite un double comptage si Discord renvoie deux événements proches.
        if isinstance(previous_member_data, dict) and previous_member_data.get("active"):
            return

        inviter_key = str(inviter_id)
        inviter_stats = data["inviters"].get(inviter_key, {})
        if not isinstance(inviter_stats, dict):
            inviter_stats = {}
        inviter_stats["total"] = max(0, int(inviter_stats.get("total", 0) or 0)) + 1
        inviter_stats["active"] = max(0, int(inviter_stats.get("active", 0) or 0)) + 1
        inviter_stats["left"] = max(0, int(inviter_stats.get("left", 0) or 0))
        data["inviters"][inviter_key] = inviter_stats
        data["members"][member_key] = {
            "inviter_id": int(inviter_id),
            "invite_code": str(used_invite.get("code", "")),
            "active": True,
            "joined_at": utc_now().isoformat(),
        }
        save_invite_tracking_data(member.guild.id, data)


async def register_departed_member(member: discord.Member) -> None:
    if member.bot:
        return
    lock = INVITE_TRACKING_LOCKS.setdefault(member.guild.id, asyncio.Lock())
    async with lock:
        data = get_invite_tracking_data(member.guild.id)
        member_key = str(member.id)
        member_data = data["members"].get(member_key)
        if not isinstance(member_data, dict) or not member_data.get("active"):
            return
        inviter_id = member_data.get("inviter_id")
        if not inviter_id:
            return

        inviter_key = str(inviter_id)
        inviter_stats = data["inviters"].get(inviter_key, {})
        if not isinstance(inviter_stats, dict):
            inviter_stats = {}
        inviter_stats["total"] = max(0, int(inviter_stats.get("total", 0) or 0))
        inviter_stats["active"] = max(0, int(inviter_stats.get("active", 0) or 0) - 1)
        inviter_stats["left"] = max(0, int(inviter_stats.get("left", 0) or 0)) + 1
        data["inviters"][inviter_key] = inviter_stats
        member_data["active"] = False
        member_data["left_at"] = utc_now().isoformat()
        data["members"][member_key] = member_data
        save_invite_tracking_data(member.guild.id, data)


def build_invite_leaderboard_embed(guild: discord.Guild) -> discord.Embed:
    config = load_embed_texts().get("invites_leaderboard_embed", {})
    rgb = config.get("color_rgb", [255, 192, 203])
    data = get_invite_tracking_data(guild.id)
    ranking = []
    for user_id, stats in data["inviters"].items():
        if not isinstance(stats, dict):
            continue
        try:
            parsed_user_id = int(user_id)
            total = max(0, int(stats.get("total", 0) or 0))
            active = max(0, int(stats.get("active", 0) or 0))
        except (TypeError, ValueError):
            continue
        if total > 0:
            ranking.append((total, active, parsed_user_id))
    ranking.sort(reverse=True)

    if ranking:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        for position, (total, active, user_id) in enumerate(ranking[:10], start=1):
            prefix = medals.get(position, f"**{position}.**")
            lines.append(f"{prefix} <@{user_id}> — **{total}** invitation(s) · **{active}** présente(s)")
        description = "\n".join(lines)
    else:
        description = "Aucune invitation enregistrée pour le moment."

    embed = discord.Embed(
        title=config.get("title", "🏆 Classement des invitations"),
        description=description,
        color=discord.Color.from_rgb(*rgb),
    )
    footer = config.get("footer", "PinkGift — Invitations")
    if footer:
        embed.set_footer(text=footer)
    return embed


def apply_embed_overrides(data):
    merged = dict(data)
    overrides = get_panel_setting("embed_overrides", {}) or {}
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            if isinstance(value, dict):
                base = dict(merged.get(key, {})) if isinstance(merged.get(key), dict) else {}
                base.update(value)
                merged[key] = base
    return merged


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


def find_balance_ticket(guild, user_id):
    if guild is None:
        return None
    prefix = f"pinkgift-balance:{int(user_id)}"
    channels = [
        channel for channel in guild.text_channels
        if (channel.topic or "").startswith(prefix) and not channel.name.startswith("closed-")
    ]
    return max(channels, key=lambda channel: channel.id, default=None)


def balance_referral_setting_key(channel_id):
    return f"balance_referral:{int(channel_id)}"


def save_balance_ticket_referral(channel, user_id, referral):
    if channel is None or not referral:
        return
    set_panel_setting(balance_referral_setting_key(channel.id), {
        "channel_id": channel.id,
        "user_id": int(user_id),
        "code": referral["code"],
        "sponsor_name": referral.get("sponsor_name", referral["code"]),
        "sponsor_id": referral.get("sponsor_id", ""),
        "percentage": valid_referral_percentage(referral.get("percentage"), 0),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })


def get_balance_ticket_referral(channel):
    if channel is None:
        return None
    data = get_panel_setting(balance_referral_setting_key(channel.id), {}) or {}
    return data if isinstance(data, dict) and normalize_referral_code(data.get("code")) else None


def track_referral_balance_credit(guild, user_id, amount, staff_id):
    channel = find_balance_ticket(guild, user_id)
    referral = get_balance_ticket_referral(channel)
    if not referral:
        return None
    amount = round(float(amount), 2)
    if amount <= 0:
        return None
    percentage = valid_referral_percentage(referral.get("percentage"), 0)
    ledger = get_referral_ledger(guild.id, user_id)
    lot = {
        "id": f"{int(time.time() * 1000)}-{secrets.token_hex(3)}",
        "channel_id": channel.id,
        "user_id": int(user_id),
        "staff_id": int(staff_id or 0),
        "code": normalize_referral_code(referral.get("code")),
        "sponsor_name": str(referral.get("sponsor_name") or referral.get("code") or ""),
        "sponsor_id": str(referral.get("sponsor_id") or ""),
        "percentage": percentage,
        "credited": amount,
        "remaining": amount,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    ledger["lots"].append(lot)
    save_referral_ledger(guild.id, user_id, ledger)
    return lot


async def send_referral_tracking_notification(guild, user, staff, lot, new_balance):
    channel = guild.get_channel(REFERRAL_TRACKING_CHANNEL_ID) or bot.get_channel(REFERRAL_TRACKING_CHANNEL_ID)
    if channel is None:
        channel = await bot.fetch_channel(REFERRAL_TRACKING_CHANNEL_ID)
    if not hasattr(channel, "send"):
        raise RuntimeError("Le salon de suivi parrainage n'accepte pas les messages")
    sponsor_name = str(lot.get("sponsor_name") or lot.get("code") or "Inconnu")
    sponsor_id = str(lot.get("sponsor_id") or "").strip()
    sponsor_label = sponsor_name + (f" (`{sponsor_id}`)" if sponsor_id else "")
    embed = discord.Embed(
        title="Recharge parrainée enregistrée",
        description="Cette recharge est suivie en interne pour calculer la commission sur le bénéfice des achats.",
        color=discord.Color.from_rgb(232, 80, 154),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    embed.add_field(name="Client", value=f"{user.mention} (`{user.id}`)", inline=False)
    embed.add_field(name="Montant ajouté", value=f"**{float(lot.get('credited') or 0):.2f} €**", inline=True)
    embed.add_field(name="Nouveau solde", value=f"**{float(new_balance):.2f} €**", inline=True)
    embed.add_field(name="Code", value=f"**{lot.get('code') or 'Inconnu'}**", inline=True)
    embed.add_field(name="Parrain", value=sponsor_label, inline=True)
    embed.add_field(name="Commission", value=f"**{valid_referral_percentage(lot.get('percentage'), 0):g} %** du bénéfice", inline=True)
    embed.add_field(name="Ajout effectué par", value=f"{staff.mention} (`{staff.id}`)", inline=False)
    await channel.send(embed=embed)


def record_referral_purchase(guild_id, user_id, order_message_id, sale_amount, purchase_cost, service):
    sale_amount = round(float(sale_amount), 2)
    purchase_cost = round(float(purchase_cost), 2)
    if sale_amount <= 0:
        return []
    ledger = get_referral_ledger(guild_id, user_id)
    existing = [
        event for event in ledger["events"]
        if isinstance(event, dict) and str(event.get("order_message_id")) == str(order_message_id)
    ]
    if existing:
        return existing

    amount_left = sale_amount
    profit = max(0.0, round(sale_amount - purchase_cost, 2))
    allocations = {}
    for lot in ledger["lots"]:
        if amount_left <= 0:
            break
        if not isinstance(lot, dict):
            continue
        remaining = max(0.0, round(float(lot.get("remaining") or 0), 2))
        if remaining <= 0:
            continue
        used = min(remaining, amount_left)
        lot["remaining"] = round(remaining - used, 2)
        amount_left = round(amount_left - used, 2)
        code = normalize_referral_code(lot.get("code"))
        percentage = valid_referral_percentage(lot.get("percentage"), 0)
        allocation_key = (code, percentage, str(lot.get("sponsor_id") or ""))
        item = allocations.setdefault(allocation_key, {
            "code": code,
            "sponsor_name": str(lot.get("sponsor_name") or code),
            "sponsor_id": str(lot.get("sponsor_id") or ""),
            "percentage": percentage,
            "referred_used": 0.0,
        })
        item["referred_used"] += used

    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    new_events = []
    for item in allocations.values():
        referred_used = round(item["referred_used"], 2)
        attributed_profit = round(profit * referred_used / sale_amount, 2)
        commission = round(attributed_profit * item["percentage"] / 100, 2)
        event = {
            **item,
            "guild_id": int(guild_id),
            "user_id": int(user_id),
            "order_message_id": int(order_message_id),
            "service": str(service),
            "sale_amount": sale_amount,
            "purchase_cost": purchase_cost,
            "attributed_profit": attributed_profit,
            "commission": commission,
            "created_at": created_at,
        }
        ledger["events"].append(event)
        new_events.append(event)
    if new_events:
        save_referral_ledger(guild_id, user_id, ledger)
    return new_events


def remove_referral_purchase(guild_id, user_id, order_message_id):
    """Retire du suivi parrainage la commission associée à une commande supprimée."""
    ledger = get_referral_ledger(guild_id, user_id)
    kept_events = []
    removed_events = []
    order_key = str(order_message_id)
    for event in ledger["events"]:
        if isinstance(event, dict) and str(event.get("order_message_id")) == order_key:
            removed_events.append(event)
        else:
            kept_events.append(event)
    if not removed_events:
        return {"events": 0, "commission": 0.0}
    ledger["events"] = kept_events
    save_referral_ledger(guild_id, user_id, ledger)
    return {
        "events": len(removed_events),
        "commission": round(sum(float(event.get("commission") or 0) for event in removed_events), 2),
    }


def reduce_referral_balance(guild_id, user_id, amount):
    """Retire une correction de solde des réserves parrainées sans créer de commission."""
    amount_left = max(0.0, round(float(amount), 2))
    if amount_left <= 0:
        return 0.0
    ledger = get_referral_ledger(guild_id, user_id)
    removed = 0.0
    for lot in ledger["lots"]:
        if amount_left <= 0:
            break
        if not isinstance(lot, dict):
            continue
        remaining = max(0.0, round(float(lot.get("remaining") or 0), 2))
        used = min(remaining, amount_left)
        lot["remaining"] = round(remaining - used, 2)
        amount_left = round(amount_left - used, 2)
        removed += used
    if removed:
        save_referral_ledger(guild_id, user_id, ledger)
    return round(removed, 2)


def reconcile_referral_balance(guild_id, user_id, current_balance):
    ledger = get_referral_ledger(guild_id, user_id)
    tracked = sum(
        max(0.0, float(lot.get("remaining") or 0))
        for lot in ledger["lots"] if isinstance(lot, dict)
    )
    excess = max(0.0, round(tracked - max(0.0, float(current_balance)), 2))
    return reduce_referral_balance(guild_id, user_id, excess) if excess else 0.0


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

GIFT_CARD_AMOUNTS = (100, 200, 400, 800)
UBEREATS_PACKS = {
    "pack_20": {"default_price": 20, "drop": "28–42"},
    "pack_65": {"default_price": 65, "drop": "85–115"},
    "pack_125": {"default_price": 125, "drop": "165–225"},
    "pack_350": {"default_price": 350, "drop": "501–680"},
}
NITRO_PRICE = 8
VALO_REGIONS = {
    "EUROPE": {
        "label": "Europe", "emoji": "🇪🇺",
        "packs": {
            "3650": {"label": "3650 VP", "default_price": 30},
            "5350": {"label": "5350 VP", "default_price": 40},
            "8700": {"label": "8700 VP", "default_price": 60},
            "11000": {"label": "11000 VP", "default_price": 80},
        }
    },
    "TURQUIE": {
        "label": "Turquie", "emoji": "🇹🇷",
        "packs": {
            "2925": {"label": "2925 VP", "default_price": 15},
            "4325": {"label": "4325 VP", "default_price": 20},
            "8900": {"label": "8900 VP", "default_price": 45},
            "11000": {"label": "11000 VP", "default_price": 55},
        }
    }
}


def valid_price(value, fallback):
    try:
        price = round(float(value), 2)
        if 0 < price <= 100000:
            return price
    except (TypeError, ValueError):
        pass
    return round(float(fallback), 2)


def default_pricing_config():
    return {
        "gift_cards": {str(amount): round(amount * 0.70, 2) for amount in GIFT_CARD_AMOUNTS},
        "uber_eats": {pack_key: float(pack["default_price"]) for pack_key, pack in UBEREATS_PACKS.items()},
        "discord_nitro": float(NITRO_PRICE),
        "valorant": {
            region_key: {pack_key: float(pack["default_price"]) for pack_key, pack in region["packs"].items()}
            for region_key, region in VALO_REGIONS.items()
        },
    }


def get_pricing_config():
    """Retourne une grille complète et validée, relue en base à chaque utilisation."""
    prices = default_pricing_config()
    saved = get_panel_setting("pricing", {}) or {}
    if not isinstance(saved, dict):
        return prices

    saved_gifts = saved.get("gift_cards", {}) if isinstance(saved.get("gift_cards"), dict) else {}
    for amount, fallback in list(prices["gift_cards"].items()):
        prices["gift_cards"][amount] = valid_price(saved_gifts.get(amount), fallback)

    saved_uber = saved.get("uber_eats", {}) if isinstance(saved.get("uber_eats"), dict) else {}
    for pack_key, fallback in list(prices["uber_eats"].items()):
        # Compatibilité avec une éventuelle ancienne clé basée sur le prix d'origine.
        legacy_key = str(int(UBEREATS_PACKS[pack_key]["default_price"]))
        prices["uber_eats"][pack_key] = valid_price(saved_uber.get(pack_key, saved_uber.get(legacy_key)), fallback)

    prices["discord_nitro"] = valid_price(saved.get("discord_nitro"), prices["discord_nitro"])

    saved_valorant = saved.get("valorant", {}) if isinstance(saved.get("valorant"), dict) else {}
    for region_key, packs in prices["valorant"].items():
        saved_packs = saved_valorant.get(region_key, {}) if isinstance(saved_valorant.get(region_key), dict) else {}
        for pack_key, fallback in list(packs.items()):
            legacy_key = str(int(VALO_REGIONS[region_key]["packs"][pack_key]["default_price"]))
            packs[pack_key] = valid_price(saved_packs.get(pack_key, saved_packs.get(legacy_key)), fallback)
    return prices


def format_price(value):
    return f"{float(value):g}"


def valid_purchase_cost(value, fallback=0):
    try:
        cost = round(float(value), 2)
        if 0 <= cost <= 100000:
            return cost
    except (TypeError, ValueError):
        pass
    return round(float(fallback), 2)


def regular_gift_product_keys():
    return tuple(key for key in PRODUCT_CONFIG if key not in {"VALORANT", "UBEREATS", "DISCORD_NITRO"})


def default_purchase_cost_config():
    return {
        "gift_cards": {
            product_key: {str(amount): 0.0 for amount in GIFT_CARD_AMOUNTS}
            for product_key in regular_gift_product_keys()
        },
        "uber_eats": {pack_key: 0.0 for pack_key in UBEREATS_PACKS},
        "discord_nitro": 0.0,
        "valorant": {
            region_key: {pack_key: 0.0 for pack_key in region["packs"]}
            for region_key, region in VALO_REGIONS.items()
        },
    }


def get_purchase_cost_config():
    costs = default_purchase_cost_config()
    saved = get_panel_setting("purchase_costs", {}) or {}
    if not isinstance(saved, dict):
        return costs

    saved_gifts = saved.get("gift_cards", {}) if isinstance(saved.get("gift_cards"), dict) else {}
    for product_key, amounts in costs["gift_cards"].items():
        saved_amounts = saved_gifts.get(product_key, {}) if isinstance(saved_gifts.get(product_key), dict) else {}
        for amount in amounts:
            amounts[amount] = valid_purchase_cost(saved_amounts.get(amount), amounts[amount])

    saved_uber = saved.get("uber_eats", {}) if isinstance(saved.get("uber_eats"), dict) else {}
    for pack_key in costs["uber_eats"]:
        costs["uber_eats"][pack_key] = valid_purchase_cost(saved_uber.get(pack_key), 0)

    costs["discord_nitro"] = valid_purchase_cost(saved.get("discord_nitro"), 0)

    saved_valorant = saved.get("valorant", {}) if isinstance(saved.get("valorant"), dict) else {}
    for region_key, packs in costs["valorant"].items():
        saved_packs = saved_valorant.get(region_key, {}) if isinstance(saved_valorant.get(region_key), dict) else {}
        for pack_key in packs:
            packs[pack_key] = valid_purchase_cost(saved_packs.get(pack_key), 0)
    return costs


def save_order_purchase_cost(message_id, cost):
    set_panel_setting(f"order_cost:{int(message_id)}", {"cost": valid_purchase_cost(cost), "saved_at": utc_now().isoformat()})

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
            "Ta commande a bien été enregistrée et ton solde a été débité.",
            "La livraison est automatique : ton code sera envoyé ici dès qu'il sera disponible.",
            "Le staff intervient uniquement pour les recharges de solde."
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
                "name": "Montant débité",
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
        "description": [
            "Bonjour {user} !", "",
            "Ta commande Discord Nitro a bien été enregistrée et ton solde a été débité.",
            "La livraison est automatique : ton Nitro sera envoyé ici dès qu'il sera disponible.",
            "Le staff intervient uniquement pour les recharges de solde."
        ],
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
            "La livraison est automatique : ton code Valorant sera envoyé dans ce ticket dès qu'il sera disponible.",
            "Le staff intervient uniquement pour les recharges de solde."
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
        "title": "{emoji} Livraison automatique en cours",
        "description": [
            "Merci pour ta confiance {user} !",
            "Ta commande est traitée automatiquement. Ton code apparaîtra ci-dessous dès qu'il sera prêt."
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
        "title": "{emoji} Livraison Valorant automatique en cours",
        "description": [
            "Merci pour ta confiance {user} !",
            "Ta commande est traitée automatiquement. Ton code Valorant apparaîtra ci-dessous dès qu'il sera prêt."
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
        "title": "✅ Commande livrée automatiquement",
        "description": [
            "Ta commande a été livrée automatiquement.",
            "Ton code est disponible ci-dessous."
        ],
        "color_rgb": [
            46,
            204,
            113
        ],
        "image_key": "commande_livree",
        "footer": "PinkGift — Livraison automatique terminée",
        "code_field_name": "Code livré automatiquement"
    },
    "commandes_embed": {
        "title": "📜 COMMANDES STAFF — PinkGift",
        "description": [
            "Liste des commandes actuellement actives sur le bot."
        ],
        "fields": [
            {
                "name": "🎫 Tickets",
                "value": "!tarifs : affiche les cartes cadeaux et les menus de commande.\n!valo : envoie l'embed Valorant avec son bouton ticket.\n!maj_embed : met à jour tous les embeds publics du serveur sans ping.\n!close_button : ajoute un bouton Close persistant.\n!faq : publie la FAQ PinkGift.",
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
                "name": "🎉 Giveaways",
                "value": "!giveaway <durée> <nom> [invitations] [tag_serveur] : crée un giveaway avec conditions.\n!reroll <ID ou lien> : tire un nouveau gagnant éligible.",
                "inline": False
            },
            {
                "name": "📊 Compteurs serveur",
                "value": "!config_compteurs #salon-avis : configure le salon contenant les avis vérifiés.",
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

DEFAULT_EMBED_DATA.update({"uber_eats_ticket_embed": {"title": "🍔 Commande — UBER EATS", "description": ["Bonjour {user} !", "", "Ta commande Uber Eats a bien été enregistrée et ton solde a été débité.", "La livraison est automatique : les informations seront envoyées ici dès qu'elles seront disponibles.", "Le staff intervient uniquement pour les recharges de solde."], "fields": [{"name": "Service sélectionné", "value": "{emoji} **{service}**", "inline": False}, {"name": "Prix payé", "value": "**{paid} €**", "inline": True}, {"name": "Drop estimé", "value": "**{drop}**", "inline": True}, {"name": "Solde restant", "value": "**{balance} €**", "inline": False}], "color_rgb": [255, 192, 203], "image_key": "ticket_cree"}})

DEFAULT_EMBED_DATA.update({
    "faq_embed": {
        "title": "🎀 FAQ PinkGift",
        "description": [
            "**<:questionmark:1525869342506614784> Qu’est-ce que PinkGift ?**",
            "PinkGift est une boutique proposant des cartes cadeaux et produits numériques à prix réduit.",
            "",
            "**<:questionmark:1525869342506614784> Où voir les produits disponibles ?**",
            "Les produits sont affichés dans les salons de la boutique : cartes cadeaux, Valorant, privilèges et autres. Le catalogue peut changer selon les stocks.",
            "",
            "**<:questionmark:1525869342506614784> Comment passer commande ?**",
            "Choisis un produit, suis les instructions du bot, vérifie ta commande puis paie avec ton solde PinkGift.",
            "",
            "**<:questionmark:1525869342506614784> Quand vais-je recevoir ma commande ?**",
            "Le délai dépend du produit et du stock. Certaines commandes sont rapides, d’autres peuvent nécessiter une vérification manuelle.",
            "",
            "**<:questionmark:1525869342506614784> Où vais-je recevoir ma commande ?**",
            "Dans le fil de ta commande, via le bot PinkGift.",
            "",
            "**<:questionmark:1525869342506614784> Comment recharger mon solde ?**",
            "Va dans le salon 💳・solde et suis les instructions du bot. Une fois le paiement vérifié, ton solde est crédité.",
            "",
            "**<:questionmark:1525869342506614784> Quels paiements sont acceptés ?**",
            "Les moyens disponibles sont indiqués dans 💳・solde : Revolut, PayPal, virement bancaire et cryptomonnaies, méthode prioritaire.",
            "",
            "**<:questionmark:1525869342506614784> Puis-je retirer ou transférer mon solde ?**",
            "Non. Le solde PinkGift sert uniquement aux achats sur la boutique, sauf exception validée par le support.",
            "",
            "**<:questionmark:1525869342506614784> Les cartes cadeaux fonctionnent-elles partout ?**",
            "Non. Certaines sont limitées à une région ou un pays. Vérifie toujours les informations du produit avant de commander.",
            "",
            "**<:questionmark:1525869342506614784> Que faire si mon code ne fonctionne pas ?**",
            "N’envoie jamais ton code publiquement. Ouvre un ticket avec ton numéro de commande, le produit, une capture de l’erreur, la date et l’heure de l’essai.",
            "",
            "**<:questionmark:1525869342506614784> Puis-je modifier ou annuler une commande ?**",
            "Une commande validée ne peut normalement plus être modifiée ou annulée. Contacte vite le support en cas d’erreur, mais aucune modification n’est garantie.",
            "",
            "**<:questionmark:1525869342506614784> Les commandes sont-elles remboursables ?**",
            "Non. Les commandes PinkGift ne sont pas remboursables en cas de changement d’avis, erreur de sélection, mauvaise région ou produit déjà livré/révélé/utilisé.",
            "",
            "**<:questionmark:1525869342506614784> Et si le problème vient de PinkGift ?**",
            "Un souci causé par PinkGift, comme un code invalide ou une erreur de livraison, sera étudié en ticket pour trouver une solution adaptée.",
            "",
            "**<:questionmark:1525869342506614784> Que faire si ma commande tarde ?**",
            "Vérifie le fil et le statut de commande. Si l’attente est anormale, ping une seule fois @› Pink Teams. Évite les pings répétés.",
            "",
            "**<:questionmark:1525869342506614784> Comment contacter le support ?**",
            "Ouvre un ticket et explique clairement ta demande avec le numéro de commande, le produit, la date d’achat et une capture si besoin.",
            "",
            "**<:questionmark:1525869342506614784> Comment participer aux giveaways ?**",
            "Lis les conditions du giveaway, clique sur le bouton de participation et attends le tirage.",
            "",
            "**<:questionmark:1525869342506614784> Dois-je payer pour récupérer un lot ?**",
            "Non. PinkGift ne demandera jamais de payer pour recevoir un lot gagné, sauf condition annoncée dès le départ.",
            "",
            "**<:questionmark:1525869342506614784> Comment éviter les arnaques ?**",
            "Vérifie les rôles officiels, ne partage jamais tes mots de passe, codes cadeaux, infos bancaires ou données sensibles.",
            "",
            "**<:questionmark:1525869342506614784> Comment signaler un faux compte ?**",
            "Ouvre un ticket avec le profil, l’identifiant Discord si possible et une capture de la conversation.",
            "",
            "**<:questionmark:1525869342506614784> J’ai une autre question, que faire ?**",
            "Ouvre un ticket dans le salon prévu. L’équipe PinkGift t’aidera dès que possible.",
            "",
            "Merci d’utiliser PinkGift ! 🎀"
        ],
        "color_rgb": [255, 192, 203],
        "footer": "PinkGift — FAQ"
    },
    "rules_embed": {
        "title": "📜 Règlement PinkGift",
        "description": [
            "En restant sur le serveur, tu acceptes ces règles.",
            "",
            "**Respect** : aucune insulte, menace, provocation ou discrimination.",
            "**Commandes** : utilise uniquement les salons et tickets prévus.",
            "**Paiements** : fausses preuves, fraude ou arnaque = bannissement.",
            "**Tickets** : sois clair, patient et évite le spam.",
            "**Livraison** : vérifie tes informations avant validation. Code livré = commande finalisée.",
            "**Pub & spam** : publicité non autorisée, flood et liens suspects interdits.",
            "",
            "Le staff peut sanctionner tout comportement nuisible pour protéger la communauté."
        ],
        "color_rgb": [255, 192, 203],
        "footer": "PinkGift — Merci de respecter le serveur"
    },
    "leaderboard_embed": {
        "title": "🏆 Classement PinkGift",
        "description": [
            "Classement synchronisé avec les commandes du panel."
        ],
        "color_rgb": [255, 192, 203],
        "footer": "PinkGift — Top clients"
    },
    "giveaway_embed": {
        "title": "🎉 Giveaway — {name}",
        "description": [
            "Clique sur **Je participe** pour entrer dans le giveaway.",
            "",
            "Fin : <t:{end_ts}:R>",
            "Participants : **{count}**"
        ],
        "color_rgb": [255, 192, 203],
        "footer": "PinkGift — Giveaway"
    },
    "giveaway_ended_embed": {
        "title": "🎉 Giveaway terminé — {name}",
        "description": [
            "Le giveaway est terminé.",
            "",
            "Gagnant : {winner}",
            "Participants : **{count}**"
        ],
        "color_rgb": [255, 192, 203],
        "footer": "PinkGift — Giveaway terminé"
    }
})

DEFAULT_EMBED_DATA.update({
    "invites_embed": {
        "title": "📨 Invitations de {member}",
        "description": [
            "**Invitations totales :** {total}",
            "**Membres encore présents :** {active}",
            "**Membres partis :** {left}"
        ],
        "color_rgb": [255, 192, 203],
        "footer": "PinkGift — Invitations"
    },
    "invites_leaderboard_embed": {
        "title": "🏆 Classement des invitations",
        "color_rgb": [255, 192, 203],
        "footer": "PinkGift — Invitations"
    }
})

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
            return apply_embed_overrides(data)
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
                return apply_embed_overrides(data)
            except Exception as e:
                print(f"Erreur chargement config_embeds.json local : {e}")
    return apply_embed_overrides(DEFAULT_EMBED_DATA)


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


def parse_datetime_value(value):
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value if value.tzinfo else value.replace(tzinfo=datetime.timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        try:
            return datetime.datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            return None


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def parse_giveaway_duration(value):
    match = re.fullmatch(r"\s*(\d+)\s*(s|m|h|d|j)?\s*", str(value or "").lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2) or "m"
    if unit == "s":
        return amount
    if unit == "m":
        return amount * 60
    if unit == "h":
        return amount * 3600
    if unit in ("d", "j"):
        return amount * 86400
    return None


def load_orders_for_stats(limit=5000):
    try:
        if USE_SUPABASE:
            return supabase_request("GET", f"orders?select=*&order=id.desc&limit={limit}") or []
        with db_connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    except Exception as error:
        print(f"Erreur chargement classement : {error}")
        return []


def build_client_totals(orders, month_only=False):
    now = utc_now()
    month_start = datetime.datetime(now.year, now.month, 1, tzinfo=datetime.timezone.utc)
    totals = {}
    for order in orders:
        status = str(order.get("status") or "").lower()
        if status not in ("done", "livre", "livré", "delivered"):
            continue
        if month_only:
            created_at = parse_datetime_value(order.get("created_at"))
            if not created_at or created_at.astimezone(datetime.timezone.utc) < month_start:
                continue
        try:
            user_id = int(order.get("user_id") or 0)
        except (TypeError, ValueError):
            user_id = 0
        if not user_id:
            continue
        item = totals.setdefault(user_id, {"user_id": user_id, "user_name": order.get("user_name") or str(user_id), "total": 0.0})
        if order.get("user_name"):
            item["user_name"] = order.get("user_name")
        try:
            item["total"] += float(order.get("paid") or 0)
        except (TypeError, ValueError):
            pass
    return sorted(totals.values(), key=lambda item: item["total"], reverse=True)


DELIVERED_ORDER_STATUSES = {"done", "livre", "livré", "delivered"}
FRENCH_MONTH_NAMES = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def normalize_finance_month(value, now=None):
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", text):
        return text
    current = now or utc_now()
    return f"{current.year:04d}-{current.month:02d}"


def finance_month_bounds(month_key):
    year, month = (int(part) for part in month_key.split("-", 1))
    start = datetime.datetime(year, month, 1, tzinfo=datetime.timezone.utc)
    if month == 12:
        end = datetime.datetime(year + 1, 1, 1, tzinfo=datetime.timezone.utc)
    else:
        end = datetime.datetime(year, month + 1, 1, tzinfo=datetime.timezone.utc)
    return start, end


def load_order_purchase_costs():
    snapshots = {}
    if USE_SUPABASE:
        items = []
        offset = 0
        while True:
            prefix = urllib.parse.quote("order_cost:", safe="")
            page = supabase_request(
                "GET",
                f"panel_settings?key=like.{prefix}*&select=key,value&order=key&limit=1000&offset={offset}",
            ) or []
            items.extend(page)
            if len(page) < 1000:
                break
            offset += len(page)
    else:
        items = list_panel_settings("order_cost:")
    for item in items:
        try:
            message_id = int(str(item.get("key", "")).split(":", 1)[1])
        except (IndexError, TypeError, ValueError):
            continue
        value = item.get("value", {})
        raw_cost = value.get("cost", 0) if isinstance(value, dict) else value
        snapshots[message_id] = valid_purchase_cost(raw_cost)
    return snapshots


def infer_order_purchase_cost(order, costs=None):
    """Reconstitue le coût des anciennes commandes qui n'ont pas encore de snapshot."""
    costs = costs or get_purchase_cost_config()
    service = str(order.get("service") or "")
    service_upper = service.upper()

    if service_upper.startswith("VALORANT"):
        for region_key, region in VALO_REGIONS.items():
            if region["label"].upper() not in service_upper:
                continue
            for pack_key, pack in region["packs"].items():
                if pack["label"].upper() in service_upper:
                    return costs["valorant"][region_key][pack_key]
        return 0.0

    product_key = next(
        (key for key, config in PRODUCT_CONFIG.items() if config["display"].upper() == service_upper),
        None,
    )
    if product_key == "DISCORD_NITRO":
        return costs["discord_nitro"]
    if product_key == "UBEREATS":
        received = str(order.get("received_label") or "")
        for pack_key, pack in UBEREATS_PACKS.items():
            if pack["drop"] in received:
                return costs["uber_eats"][pack_key]
        return 0.0
    if product_key in costs["gift_cards"]:
        try:
            amount_key = str(int(float(order.get("amount") or 0)))
        except (TypeError, ValueError):
            return 0.0
        return costs["gift_cards"][product_key].get(amount_key, 0.0)
    return 0.0


def calculate_month_finances(orders, month_key, purchase_cost_snapshots=None, purchase_costs=None):
    """Calcule le CA sur les commandes livrées pendant le mois demandé."""
    month_key = normalize_finance_month(month_key)
    start, end = finance_month_bounds(month_key)
    revenue = 0.0
    total_costs = 0.0
    order_count = 0
    services = {}
    nitro = {"orders": 0, "revenue": 0.0, "costs": 0.0, "profit": 0.0}
    purchase_cost_snapshots = purchase_cost_snapshots or {}
    purchase_costs = purchase_costs or get_purchase_cost_config()
    for order in orders:
        if str(order.get("status") or "").lower() not in DELIVERED_ORDER_STATUSES:
            continue
        delivered_at = parse_datetime_value(order.get("updated_at") or order.get("created_at"))
        if delivered_at is None:
            continue
        delivered_at = delivered_at.astimezone(datetime.timezone.utc)
        if not start <= delivered_at < end:
            continue
        try:
            paid = round(float(order.get("paid") or 0), 2)
        except (TypeError, ValueError):
            paid = 0.0
        if paid < 0:
            continue
        try:
            message_id = int(order.get("message_id") or 0)
        except (TypeError, ValueError):
            message_id = 0
        purchase_cost = purchase_cost_snapshots.get(message_id)
        if purchase_cost is None:
            purchase_cost = infer_order_purchase_cost(order, purchase_costs)
        purchase_cost = valid_purchase_cost(purchase_cost)
        revenue += paid
        total_costs += purchase_cost
        order_count += 1
        service = str(order.get("service") or "Service inconnu")
        item = services.setdefault(service, {"service": service, "orders": 0, "revenue": 0.0, "costs": 0.0, "profit": 0.0})
        item["orders"] += 1
        item["revenue"] += paid
        item["costs"] += purchase_cost
        item["profit"] += paid - purchase_cost
        if service.upper() == PRODUCT_CONFIG["DISCORD_NITRO"]["display"].upper():
            nitro["orders"] += 1
            nitro["revenue"] += paid
            nitro["costs"] += purchase_cost
            nitro["profit"] += paid - purchase_cost

    revenue = round(revenue, 2)
    total_costs = round(total_costs, 2)
    breakdown = sorted(services.values(), key=lambda item: item["revenue"], reverse=True)
    for item in breakdown:
        item["revenue"] = round(item["revenue"], 2)
        item["costs"] = round(item["costs"], 2)
        item["profit"] = round(item["profit"], 2)
    for key in ("revenue", "costs", "profit"):
        nitro[key] = round(nitro[key], 2)
    return {
        "month": month_key,
        "revenue": revenue,
        "costs": total_costs,
        "profit": round(revenue - total_costs, 2),
        "orders": order_count,
        "average_order": round(revenue / order_count, 2) if order_count else 0.0,
        "breakdown": breakdown,
        "nitro": nitro,
    }


def finance_month_label(month_key):
    year, month = (int(part) for part in month_key.split("-", 1))
    return f"{FRENCH_MONTH_NAMES[month - 1].capitalize()} {year}"


def leaderboard_lines(items):
    if not items:
        return "Aucun client classé pour le moment."
    lines = []
    for index, item in enumerate(items[:10], start=1):
        user_id = item.get("user_id")
        mention = f"<@{user_id}>" if user_id else f"@{item.get('user_name', 'client')}"
        lines.append(f"**{index}.** {mention} **- {item.get('total', 0):.2f}Euros**")
    return "\n".join(lines)


def build_leaderboard_embed():
    data = load_embed_texts().get("leaderboard_embed", DEFAULT_EMBED_DATA["leaderboard_embed"])
    rgb = data.get("color_rgb", [255, 192, 203])
    description_raw = data.get("description", [])
    description = "\n".join(description_raw) if isinstance(description_raw, list) else str(description_raw or "")
    embed = discord.Embed(title=data.get("title", "🏆 Classement PinkGift"), description=description, color=discord.Color.from_rgb(*rgb))
    orders = load_orders_for_stats()
    embed.add_field(name="Top all time", value=leaderboard_lines(build_client_totals(orders, month_only=False)), inline=False)
    embed.add_field(name="Top du mois", value=leaderboard_lines(build_client_totals(orders, month_only=True)), inline=False)
    footer = data.get("footer")
    if footer:
        embed.set_footer(text=footer)
    image_url = data.get("image_url") or get_image_url(data.get("image_key", ""), "")
    if image_url:
        embed.set_image(url=image_url)
    return embed

async def create_product_ticket(interaction, product_key, amount):
    guild = interaction.guild
    user = interaction.user
    cfg = PRODUCT_CONFIG.get(product_key)
    if guild is None or cfg is None:
        await interaction.followup.send("❌ Impossible de créer cette commande.", ephemeral=True)
        return
    if not product_is_available(product_key):
        await interaction.followup.send(f"{STOCK_KO_EMOJI} **{cfg['display']}** est actuellement en rupture.", ephemeral=True)
        return
    uber_pack_key = None
    if product_key == "UBEREATS":
        candidate = str(amount)
        if candidate in UBEREATS_PACKS:
            uber_pack_key = candidate
        else:
            # Les menus éphémères ouverts avant cette mise à jour envoyaient l'ancien prix.
            uber_pack_key = next(
                (key for key, pack in UBEREATS_PACKS.items() if str(int(pack["default_price"])) == candidate),
                None
            )
        if uber_pack_key is None:
            await interaction.followup.send("❌ Pack Uber Eats invalide.", ephemeral=True)
            return
    elif product_key != "DISCORD_NITRO":
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            amount = 0
        if amount not in GIFT_CARD_AMOUNTS:
            await interaction.followup.send("❌ Montant de carte cadeau invalide.", ephemeral=True)
            return

    lock = ORDER_LOCKS.setdefault((guild.id, user.id), asyncio.Lock())
    async with lock:
        pricing = get_pricing_config()
        purchase_costs = get_purchase_cost_config()
        if product_key == "DISCORD_NITRO":
            paid_amount = pricing["discord_nitro"]
            purchase_cost = purchase_costs["discord_nitro"]
            amount = paid_amount
            received_display = "Discord Nitro"
        elif product_key == "UBEREATS":
            paid_amount = pricing["uber_eats"][uber_pack_key]
            purchase_cost = purchase_costs["uber_eats"][uber_pack_key]
            amount = paid_amount
            received_display = f"{UBEREATS_PACKS[uber_pack_key]['drop']} € estimés"
        else:
            paid_amount = pricing["gift_cards"][str(amount)]
            purchase_cost = purchase_costs["gift_cards"][product_key][str(amount)]
            received_display = f"{amount} €"
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
            save_order_purchase_cost(order_message.id, purchase_cost)
        except Exception as error:
            print(f"Erreur sauvegarde commande panneau: {error}")
        try:
            record_referral_purchase(guild.id, user.id, order_message.id, paid_amount, purchase_cost, cfg["display"])
        except Exception as error:
            print(f"Erreur calcul parrainage commande de {user}: {error}")
        await interaction.followup.send(f"✅ Commande ajoutée dans {ticket_channel.mention}. Nouveau solde : **{remaining_balance:.2f} €**.", ephemeral=True)
def default_stock_config():
    return {
        "products": {key: True for key in PRODUCT_CONFIG if key != "VALORANT"},
        "valorant": {region_key: {pack_key: True for pack_key in region["packs"]} for region_key, region in VALO_REGIONS.items()}
    }


def get_stock_config():
    defaults = default_stock_config()
    saved = get_panel_setting("stock_status", {}) or {}
    if not isinstance(saved, dict):
        return defaults
    products = saved.get("products", {}) if isinstance(saved.get("products"), dict) else {}
    valorant = saved.get("valorant", {}) if isinstance(saved.get("valorant"), dict) else {}
    for key in defaults["products"]:
        defaults["products"][key] = bool(products.get(key, defaults["products"][key]))
    for region_key, packs in defaults["valorant"].items():
        saved_packs = valorant.get(region_key, {}) if isinstance(valorant.get(region_key), dict) else {}
        for pack_key in list(packs):
            legacy_price = str(int(VALO_REGIONS[region_key]["packs"][pack_key]["default_price"]))
            packs[pack_key] = bool(saved_packs.get(pack_key, saved_packs.get(legacy_price, packs[pack_key])))
    return defaults


def set_stock_available(kind, key, available, region_key=None):
    stock = get_stock_config()
    if kind == "product" and key in stock["products"]:
        stock["products"][key] = bool(available)
    elif kind == "valorant" and region_key in stock["valorant"] and str(key) in stock["valorant"][region_key]:
        stock["valorant"][region_key][str(key)] = bool(available)
    else:
        raise ValueError("Stock introuvable")
    set_panel_setting("stock_status", stock)


def product_is_available(product_key):
    return get_stock_config()["products"].get(product_key, True)


def valo_pack_is_available(region_key, pack_key):
    return get_stock_config()["valorant"].get(region_key, {}).get(str(pack_key), True)


def stock_partial_emoji(available):
    return discord.PartialEmoji.from_str(STOCK_OK_EMOJI if available else STOCK_KO_EMOJI)


def stock_label(available):
    return "Disponible" if available else "Rupture"


def resolve_valo_pack_key(region_key, value):
    region = VALO_REGIONS.get(region_key)
    candidate = str(value)
    if region is None:
        return None
    if candidate in region["packs"]:
        return candidate
    return next(
        (key for key, pack in region["packs"].items() if str(int(pack["default_price"])) == candidate),
        None
    )


async def create_valo_order(interaction, region_key, pack_key):
    guild = interaction.guild
    user = interaction.user
    region = VALO_REGIONS.get(region_key)
    pack_key = resolve_valo_pack_key(region_key, pack_key)
    pack_data = region["packs"].get(pack_key) if region and pack_key else None
    if guild is None or pack_data is None:
        await interaction.followup.send("❌ Région ou pack Valorant invalide.", ephemeral=True)
        return
    if not valo_pack_is_available(region_key, pack_key):
        await interaction.followup.send(f"{STOCK_KO_EMOJI} Ce pack Valorant est actuellement en rupture.", ephemeral=True)
        return
    pack = pack_data["label"]
    region_label = region["label"]
    region_emoji = region["emoji"]
    lock = ORDER_LOCKS.setdefault((guild.id, user.id), asyncio.Lock())
    async with lock:
        price = get_pricing_config()["valorant"][region_key][pack_key]
        purchase_cost = get_purchase_cost_config()["valorant"][region_key][pack_key]
        current_balance = get_balance(guild.id, user.id)
        if current_balance < price:
            await interaction.followup.send(f"❌ Solde insuffisant. Il faut **{format_price(price)} €**, ton solde est de **{current_balance:.2f} €**.", ephemeral=True)
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
            save_order_purchase_cost(order_message.id, purchase_cost)
        except Exception as error:
            print(f"Erreur sauvegarde commande Valorant: {error}")
        try:
            record_referral_purchase(guild.id, user.id, order_message.id, price, purchase_cost, f"Valorant {region_label} {pack}")
        except Exception as error:
            print(f"Erreur calcul parrainage Valorant de {user}: {error}")
        await interaction.followup.send(f"✅ {region_emoji} **{pack} ({region_label})** commandés dans {ticket_channel.mention}. Nouveau solde : **{remaining_balance:.2f} €**.", ephemeral=True)


class ValoRegionSelect(discord.ui.Select):
    def __init__(self):
        stock = get_stock_config()
        options = []
        for key, data in VALO_REGIONS.items():
            available = any(stock["valorant"].get(key, {}).values())
            options.append(discord.SelectOption(label=data["label"], value=key, emoji=stock_partial_emoji(available), description=stock_label(available)))
        super().__init__(placeholder="Choisis ta région Valorant", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        region_key = self.values[0]
        region = VALO_REGIONS[region_key]
        if not any(get_stock_config()["valorant"].get(region_key, {}).values()):
            await interaction.edit_original_response(
                content=f"{STOCK_KO_EMOJI} Aucun pack disponible pour cette région actuellement.",
                view=None
            )
            return
        await interaction.edit_original_response(
            content=f"{region['emoji']} **{region['label']}** — choisis ton pack :",
            view=ValoPackView(region_key)
        )


class ValoRegionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(ValoRegionSelect())


class ValoPackSelect(discord.ui.Select):
    def __init__(self, region_key):
        self.region_key = region_key
        packs = VALO_REGIONS[region_key]["packs"]
        region_stock = get_stock_config().get("valorant", {}).get(region_key, {})
        prices = get_pricing_config()["valorant"][region_key]
        options = []
        for pack_key, pack in packs.items():
            available = region_stock.get(pack_key, True)
            options.append(discord.SelectOption(label=f"{pack['label']} — {format_price(prices[pack_key])} €", value=pack_key, emoji=stock_partial_emoji(available), description=stock_label(available)))
        super().__init__(placeholder="Choisis ton pack Valorant Points", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await create_valo_order(interaction, self.region_key, self.values[0])


class ValoPackView(discord.ui.View):
    def __init__(self, region_key):
        super().__init__(timeout=180)
        self.add_item(ValoPackSelect(region_key))


class ValoOrderLauncherView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Commander des VP", emoji="<:vp:1519915966476320901>", style=discord.ButtonStyle.success, custom_id="pinkgift_start_valo_order")
    async def start_valo_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Répond immédiatement à Discord avant toute lecture de stock.
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.edit_original_response(
            content="Choisis d'abord ta région Valorant :",
            view=ValoRegionView()
        )


class UberEatsAmountSelect(discord.ui.Select):
    def __init__(self):
        available = product_is_available("UBEREATS")
        prices = get_pricing_config()["uber_eats"]
        options = [
            discord.SelectOption(label=f"{format_price(prices[pack_key])} € → {pack['drop']} € estimés", value=pack_key, emoji=stock_partial_emoji(available), description=stock_label(available))
            for pack_key, pack in UBEREATS_PACKS.items()
        ]
        super().__init__(placeholder="Choisis ton pack Uber Eats", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await create_product_ticket(interaction, "UBEREATS", self.values[0])


class UberEatsAmountView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(UberEatsAmountSelect())


class NitroOrderView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.children[0].label = f"Commander Discord Nitro — {format_price(get_pricing_config()['discord_nitro'])} €"

    @discord.ui.button(
        label="Commander Discord Nitro — 8 €",
        emoji="<:nitroboost:1524439577656561846>",
        style=discord.ButtonStyle.success
    )
    async def confirm_nitro(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await create_product_ticket(interaction, "DISCORD_NITRO", "nitro")


class ProductAmountSelect(discord.ui.Select):
    def __init__(self, product_key):
        self.product_key = product_key
        available = product_is_available(product_key)
        prices = get_pricing_config()["gift_cards"]
        options = [
            discord.SelectOption(label=f"Carte cadeau {amount} € → {format_price(prices[str(amount)])} € débités", value=str(amount), emoji=stock_partial_emoji(available), description=stock_label(available))
            for amount in GIFT_CARD_AMOUNTS
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
        # Ce menu doit pouvoir être construit instantanément au clic.
        # Les emojis viennent de la configuration locale et ne déclenchent
        # aucune requête Discord, SQLite ou Supabase.
        options = [
            discord.SelectOption(
                label=cfg["display"][:100],
                value=key,
                description="Sélectionner ce produit",
                emoji=discord.PartialEmoji.from_str(cfg["emoji"]),
            )
            for key, cfg in PRODUCT_CONFIG.items()
            if key != "VALORANT"
        ]
        super().__init__(
            placeholder="Choisis une marque",
            custom_id="pinkgift_product_service",
            min_values=1,
            max_values=1,
            options=options[:25]
        )

    async def callback(self, interaction: discord.Interaction):
        # On accuse immédiatement réception avant toute lecture du stock.
        await interaction.response.defer()
        try:
            product_key = self.values[0]
            cfg = PRODUCT_CONFIG.get(product_key)
            if cfg is None:
                await interaction.edit_original_response(
                    content="❌ Produit introuvable. Relance le bouton **Commander**.",
                    view=None
                )
                return

            if not product_is_available(product_key):
                await interaction.edit_original_response(
                    content=f"{STOCK_KO_EMOJI} **{cfg['display']}** est actuellement en rupture.",
                    view=None
                )
                return

            if product_key == "UBEREATS":
                amount_view = UberEatsAmountView()
                prompt = "choisis maintenant ton pack :"
            elif product_key == "DISCORD_NITRO":
                amount_view = NitroOrderView()
                prompt = f"confirme l'achat du produit à **{format_price(get_pricing_config()['discord_nitro'])} €** :"
            else:
                amount_view = ProductAmountView(product_key)
                prompt = "choisis maintenant le montant :"

            await interaction.edit_original_response(
                content=f"{cfg['emoji']} **{cfg['display']}** — {prompt}",
                view=amount_view
            )
        except Exception as error:
            print(f"Erreur menu produit pour {interaction.user}: {error}")
            traceback.print_exc()
            try:
                await interaction.edit_original_response(
                    content="❌ Une erreur est survenue pendant l'ouverture du produit. Réessaie avec **Commander**.",
                    view=None
                )
            except Exception:
                pass


class ProductSelectView(discord.ui.View):
    def __init__(self):
        # Les réponses éphémères ne sont pas destinées à survivre à un redémarrage.
        super().__init__(timeout=900)
        self.add_item(ProductServiceSelect())

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        print(f"Erreur ProductSelectView sur {getattr(item, 'custom_id', 'inconnu')}: {error}")
        traceback.print_exc()
        try:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Le menu de commande a rencontré une erreur. Relance **Commander**.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Le menu de commande a rencontré une erreur. Relance **Commander**.", ephemeral=True)
        except Exception:
            pass


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
        try:
            # Le menu est désormais entièrement local et peut être envoyé directement.
            await interaction.response.send_message(
                "Choisis d'abord la marque que tu souhaites commander :",
                view=ProductSelectView(),
                ephemeral=True
            )
        except Exception as error:
            print(f"Erreur bouton Commander pour {interaction.user}: {error}")
            traceback.print_exc()
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "❌ Impossible d'ouvrir le menu de commande. Réessaie dans quelques secondes.",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        "❌ Impossible d'ouvrir le menu de commande. Réessaie dans quelques secondes.",
                        ephemeral=True
                    )
            except Exception:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        print(f"Erreur OrderLauncherView sur {getattr(item, 'custom_id', 'inconnu')}: {error}")
        traceback.print_exc()
        try:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Le bouton Commander a rencontré une erreur.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Le bouton Commander a rencontré une erreur.", ephemeral=True)
        except Exception:
            pass


async def create_balance_recharge_ticket(interaction, referral=None):
    guild = interaction.guild
    user = interaction.user
    category = guild.get_channel(BALANCE_CATEGORY_ID) if guild else None
    if category is None:
        await interaction.followup.send("❌ Catégorie de recharge introuvable.", ephemeral=True)
        return
    existing = find_balance_ticket(guild, user.id)
    if existing:
        await interaction.followup.send(f"ℹ️ Ton ticket de recharge existe déjà : {existing.mention}", ephemeral=True)
        return
    staff_role = guild.get_role(STAFF_ROLE_ID)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    try:
        channel = await guild.create_text_channel(
            name=f"solde-{user.name}"[:95],
            category=category,
            topic=f"pinkgift-balance:{user.id}:pending",
            overwrites=overwrites,
            reason=f"Recharge solde de {user}",
        )
        if referral:
            save_balance_ticket_referral(channel, user.id, referral)
        embed = build_json_embed("balance_ticket_embed", {"user": user.mention, "balance": f"{get_balance(guild.id, user.id):.2f}"})
        await channel.send(content=f"{user.mention} | <@&{STAFF_ROLE_ID}>", embed=embed, view=CloseTicketView(user.id))
        await interaction.followup.send(f"✅ Ticket de recharge créé : {channel.mention}", ephemeral=True)
    except Exception as error:
        print(f"Erreur création ticket solde pour {user}: {error}")
        await interaction.followup.send("❌ Impossible de créer le ticket de recharge actuellement.", ephemeral=True)


class ReferralCodeModal(discord.ui.Modal, title="Code de parrainage"):
    code_input = discord.ui.TextInput(
        label="Ton code de parrainage",
        placeholder="Exemple : PINKY10",
        min_length=3,
        max_length=32,
        required=True,
    )

    def __init__(self, user_id):
        super().__init__()
        self.user_id = int(user_id)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ Ce formulaire ne t'appartient pas.", ephemeral=True)
            return
        referral = get_active_referral_code(self.code_input.value)
        if referral is None:
            await interaction.response.send_message("❌ Ce code de parrainage est invalide ou désactivé.", ephemeral=True)
            return
        if referral.get("sponsor_id") and referral["sponsor_id"] == str(interaction.user.id):
            await interaction.response.send_message("❌ Tu ne peux pas utiliser ton propre code de parrainage.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await create_balance_recharge_ticket(interaction, referral)


class ReferralChoiceView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = int(user_id)

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message("❌ Ce choix ne t'appartient pas.", ephemeral=True)
        return False

    @discord.ui.button(label="Oui, j'ai un code", emoji="<:verify:1525796690899108000>", style=discord.ButtonStyle.success)
    async def yes_referral(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReferralCodeModal(self.user_id))

    @discord.ui.button(label="Non", emoji="<:crossmark:1525798036276514887>", style=discord.ButtonStyle.secondary)
    async def no_referral(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await create_balance_recharge_ticket(interaction)


class BalanceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Voir mon solde", emoji="💰", style=discord.ButtonStyle.secondary, custom_id="pinkgift_view_balance")
    async def view_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        balance = get_balance(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(f"💰 Ton solde PinkGift est de **{balance:.2f} €**.", ephemeral=True)

    @discord.ui.button(label="Recharger mon solde", emoji="➕", style=discord.ButtonStyle.success, custom_id="pinkgift_recharge_balance")
    async def recharge_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        existing = find_balance_ticket(interaction.guild, interaction.user.id)
        if existing:
            await interaction.response.send_message(f"ℹ️ Ton ticket de recharge existe déjà : {existing.mention}", ephemeral=True)
            return
        await interaction.response.send_message(
            "🤝 As-tu un code de parrainage ?",
            view=ReferralChoiceView(interaction.user.id),
            ephemeral=True,
        )


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


def giveaway_storage_key(message_id):
    return f"giveaway:{message_id}"


def load_giveaway(message_id):
    data = get_panel_setting(giveaway_storage_key(message_id), {}) or {}
    return data if isinstance(data, dict) else {}


def save_giveaway(message_id, data):
    set_panel_setting(giveaway_storage_key(message_id), data)


def parse_giveaway_message_id(value):
    matches = re.findall(r"\d{15,25}", str(value or ""))
    return int(matches[-1]) if matches else None


def normalize_giveaway_participants(participants):
    normalized = []
    seen = set()
    for item in participants or []:
        try:
            user_id = int(item)
        except (TypeError, ValueError):
            continue
        if user_id > 0 and user_id not in seen:
            normalized.append(user_id)
            seen.add(user_id)
    return normalized


def select_giveaway_winner(participants, winner_history=None):
    participants = normalize_giveaway_participants(participants)
    if not participants:
        return None

    history = normalize_giveaway_participants(winner_history)
    already_selected = set(history)
    candidates = [user_id for user_id in participants if user_id not in already_selected]
    if not candidates:
        # Quand tout le monde a déjà gagné, on recommence un cycle en évitant
        # uniquement de reprendre immédiatement le dernier gagnant.
        last_winner = history[-1] if history else None
        candidates = [user_id for user_id in participants if user_id != last_winner]
    return secrets.choice(candidates or participants)


def member_has_server_tag(member, guild_id):
    primary_guild = getattr(member, "primary_guild", None)
    if primary_guild is None or getattr(primary_guild, "identity_enabled", False) is not True:
        return False
    try:
        return int(getattr(primary_guild, "id", 0) or 0) == int(guild_id)
    except (TypeError, ValueError):
        return False


def giveaway_requirement_failures(guild, member, data):
    failures = []
    min_invites = max(0, int(data.get("min_invites", 0) or 0))
    if min_invites:
        stats = invite_user_stats(guild.id, member.id)
        active_invites = max(0, int(stats.get("active", 0) or 0))
        if active_invites < min_invites:
            failures.append(f"**{min_invites} invitation(s) active(s)** requise(s), tu en as **{active_invites}**")
    if data.get("require_server_tag") and not member_has_server_tag(member, guild.id):
        failures.append("le **tag de ce serveur** doit être affiché sur ton profil Discord")
    return failures


async def eligible_giveaway_participants(guild, data):
    eligible = []
    rejected = []
    for user_id in normalize_giveaway_participants(data.get("participants", [])):
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                rejected.append(user_id)
                continue
        if giveaway_requirement_failures(guild, member, data):
            rejected.append(user_id)
        else:
            eligible.append(user_id)
    return eligible, rejected


def giveaway_conditions_text(min_invites=0, require_server_tag=False):
    conditions = []
    min_invites = max(0, int(min_invites or 0))
    if min_invites:
        conditions.append(f"• Avoir au moins **{min_invites} invitation(s) active(s)**")
    if require_server_tag:
        conditions.append("• Afficher le **tag de ce serveur** sur son profil Discord")
    return "\n".join(conditions)


def format_embed_description(raw, variables):
    if isinstance(raw, list):
        return "\n".join(format_embed_text(line, variables) for line in raw)
    return format_embed_text(raw or "", variables)


def build_giveaway_embed(
    name,
    end_ts,
    participants_count=0,
    image_url="",
    ended=False,
    winner="Aucun gagnant",
    min_invites=0,
    require_server_tag=False,
):
    key = "giveaway_ended_embed" if ended else "giveaway_embed"
    data = load_embed_texts().get(key, DEFAULT_EMBED_DATA[key])
    variables = {"name": name, "end_ts": end_ts, "count": participants_count, "winner": winner}
    rgb = data.get("color_rgb", [255, 192, 203])
    embed = discord.Embed(
        title=format_embed_text(data.get("title", "🎉 Giveaway"), variables),
        description=format_embed_description(data.get("description", []), variables),
        color=discord.Color.from_rgb(*rgb)
    )
    footer = data.get("footer")
    if footer:
        embed.set_footer(text=format_embed_text(footer, variables))
    conditions = giveaway_conditions_text(min_invites, require_server_tag)
    if conditions:
        embed.add_field(name="✅ Conditions de participation", value=conditions, inline=False)
    final_image = image_url or data.get("image_url") or get_image_url(data.get("image_key", ""), "")
    if final_image:
        embed.set_image(url=final_image)
    return embed


def build_saved_giveaway_embed(data, participants_count, ended=False, winner="Aucun gagnant"):
    return build_giveaway_embed(
        data.get("name", "Giveaway"),
        data.get("end_ts", 0),
        participants_count,
        data.get("image_url", ""),
        ended=ended,
        winner=winner,
        min_invites=data.get("min_invites", 0),
        require_server_tag=bool(data.get("require_server_tag")),
    )


class GiveawayJoinView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Je participe", style=discord.ButtonStyle.success, emoji=GIVEAWAY_JOIN_EMOJI, custom_id="pinkgift_giveaway_join")
    async def join_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        message = interaction.message
        if message is None:
            await interaction.response.send_message("❌ Giveaway introuvable.", ephemeral=True)
            return
        data = load_giveaway(message.id)
        if not data:
            await interaction.response.send_message("❌ Ce giveaway n'est plus actif.", ephemeral=True)
            return
        if data.get("ended"):
            await interaction.response.send_message("❌ Ce giveaway est déjà terminé.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Cette participation doit être faite sur le serveur.", ephemeral=True)
            return
        failures = giveaway_requirement_failures(guild, interaction.user, data)
        if failures:
            details = "\n".join(f"• {failure}" for failure in failures)
            await interaction.response.send_message(
                f"❌ Tu ne remplis pas encore les conditions :\n{details}",
                ephemeral=True,
            )
            return
        participants = normalize_giveaway_participants(data.get("participants", []))
        if interaction.user.id in participants:
            await interaction.response.send_message("✅ Tu participes déjà à ce giveaway.", ephemeral=True)
            return
        participants.append(interaction.user.id)
        data["participants"] = participants
        save_giveaway(message.id, data)
        try:
            await message.edit(
                embed=build_saved_giveaway_embed(data, len(participants)),
                view=GiveawayJoinView(),
            )
        except discord.HTTPException as error:
            print(f"Erreur mise à jour giveaway {message.id}: {error}")
        await interaction.response.send_message("✅ Participation enregistrée.", ephemeral=True)


async def finish_giveaway(message_id):
    data = load_giveaway(message_id)
    if not data or data.get("ended"):
        return
    participants = normalize_giveaway_participants(data.get("participants", []))
    channel_id = int(data.get("channel_id") or 0)
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        guild = getattr(channel, "guild", None) or bot.get_guild(int(data.get("guild_id") or 0))
        if guild is None:
            raise RuntimeError("Serveur du giveaway introuvable")
        eligible_participants, rejected = await eligible_giveaway_participants(guild, data)
        winner_text = "Aucun participant éligible" if participants else "Aucun participant"
        winner_id = select_giveaway_winner(eligible_participants)
        if winner_id is not None:
            winner_text = f"<@{winner_id}>"
            data["winner_id"] = winner_id
            data["winner_history"] = [winner_id]
        data["ended"] = True
        data["ineligible_participant_ids"] = rejected
        save_giveaway(message_id, data)
        message = await channel.fetch_message(message_id)
        await message.edit(
            embed=build_saved_giveaway_embed(data, len(participants), ended=True, winner=winner_text),
            view=None,
        )
        excluded_text = f" · **{len(rejected)}** participation(s) non éligible(s) écartée(s)" if rejected else ""
        await channel.send(
            f"🎉 Giveaway **{data.get('name', 'Giveaway')}** terminé ! "
            f"Gagnant : {winner_text}{excluded_text}"
        )
    except Exception as error:
        print(f"Erreur fin giveaway {message_id}: {error}")


async def finish_giveaway_later(message_id, delay_seconds):
    await asyncio.sleep(max(0, int(delay_seconds)))
    await finish_giveaway(message_id)


async def schedule_active_giveaways():
    now_ts = int(time.time())
    for item in list_panel_settings("giveaway:"):
        data = item.get("value") or {}
        if not isinstance(data, dict) or data.get("ended"):
            continue
        message_id = int(str(item.get("key", "")).split(":", 1)[1] or 0)
        end_ts = int(data.get("end_ts") or 0)
        asyncio.create_task(finish_giveaway_later(message_id, max(0, end_ts - now_ts)))


def server_counter_setting_key(guild_id):
    return f"server_counters:{int(guild_id)}"


def get_server_counter_data(guild_id):
    data = get_panel_setting(server_counter_setting_key(guild_id), {}) or {}
    return data if isinstance(data, dict) else {}


def save_server_counter_data(guild_id, data):
    set_panel_setting(server_counter_setting_key(guild_id), data)


def verified_reviews_channel_ids(guild_id):
    data = get_server_counter_data(guild_id)
    channel_ids = set(VERIFIED_REVIEWS_CHANNEL_IDS)
    configured_ids = data.get("reviews_channel_ids", [])
    if not isinstance(configured_ids, (list, tuple, set)):
        configured_ids = []
    configured_ids = [*configured_ids, data.get("reviews_channel_id")]
    for value in configured_ids:
        try:
            channel_id = int(value or 0)
        except (TypeError, ValueError):
            continue
        if channel_id:
            channel_ids.add(channel_id)
    return channel_ids


async def count_verified_reviews(guild, data):
    count = 0
    for channel_id in verified_reviews_channel_ids(guild.id):
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            continue
        async for message in channel.history(limit=None, oldest_first=False):
            if not message.author.bot:
                count += 1
    return count


async def ensure_server_counter_channels(guild):
    data = get_server_counter_data(guild.id)
    old_category = guild.get_channel(int(data.get("category_id") or 0))
    if not isinstance(old_category, discord.CategoryChannel):
        old_category = discord.utils.get(guild.categories, name=SERVER_COUNTER_CATEGORY_NAME)

    me = guild.me or (guild.get_member(bot.user.id) if bot.user else None)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=False),
    }
    if me is not None:
        overwrites[me] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            manage_channels=True,
            read_message_history=True,
        )

    counter_specs = (
        ("members_channel_id", "👥・Membres"),
        ("tags_channel_id", "🏷️・Tags serveur"),
        ("reviews_counter_channel_id", "⭐・Avis vérifiés"),
    )
    channels = {}
    for key, prefix in counter_specs:
        channel = guild.get_channel(int(data.get(key) or 0))
        if not isinstance(channel, discord.VoiceChannel):
            channel = next(
                (item for item in guild.voice_channels if item.name.startswith(prefix)),
                None,
            )
        if channel is None:
            channel = await guild.create_voice_channel(
                f"{prefix} : 0",
                category=None,
                position=0,
                overwrites=overwrites,
                reason="Création automatique d'un compteur PinkGift",
            )
        elif channel.category_id is not None:
            await channel.edit(
                category=None,
                position=0,
                reason="Placement des compteurs PinkGift hors catégorie",
            )
        channels[key] = channel
        data[key] = channel.id

    for position, (key, _) in enumerate(counter_specs):
        channel = channels[key]
        if channel.position != position:
            await channel.edit(
                position=position,
                reason="Placement des compteurs PinkGift en haut du serveur",
            )

    if old_category is not None and not old_category.channels:
        await old_category.delete(reason="Ancienne catégorie de compteurs PinkGift devenue inutile")
    data.pop("category_id", None)
    save_server_counter_data(guild.id, data)
    return data, channels


async def refresh_server_counters(guild, refresh_reviews=False):
    if guild is None or not guild_is_authorized(guild.id):
        return
    lock = SERVER_COUNTER_LOCKS.setdefault(guild.id, asyncio.Lock())
    async with lock:
        if not guild.chunked:
            try:
                await guild.chunk(cache=True)
            except discord.HTTPException as error:
                print(f"Chargement membres incomplet pour les compteurs de {guild.id}: {error}")

        data, channels = await ensure_server_counter_channels(guild)
        members_count = sum(1 for member in guild.members if not member.bot)
        tags_count = sum(
            1
            for member in guild.members
            if not member.bot and member_has_server_tag(member, guild.id)
        )

        if refresh_reviews or "verified_reviews_count" not in data:
            data["verified_reviews_count"] = await count_verified_reviews(guild, data)
            save_server_counter_data(guild.id, data)
        reviews_count = max(0, int(data.get("verified_reviews_count", 0) or 0))

        names = {
            "members_channel_id": f"👥・Membres : {members_count}",
            "tags_channel_id": f"🏷️・Tags serveur : {tags_count}",
            "reviews_counter_channel_id": f"⭐・Avis vérifiés : {reviews_count}",
        }
        for key, channel in channels.items():
            if channel.name != names[key]:
                await channel.edit(name=names[key], reason="Actualisation automatique des compteurs PinkGift")


async def delayed_server_counter_refresh(guild):
    await asyncio.sleep(5)
    refresh_reviews = bool(SERVER_COUNTER_UPDATE_FLAGS.pop(guild.id, False))
    try:
        await refresh_server_counters(guild, refresh_reviews=refresh_reviews)
    except (discord.Forbidden, discord.HTTPException) as error:
        print(f"Actualisation compteurs impossible sur {guild.id}: {error}")
    except Exception as error:
        print(f"Erreur compteurs serveur {guild.id}: {error}")
    finally:
        SERVER_COUNTER_UPDATE_TASKS.pop(guild.id, None)


def schedule_server_counter_refresh(guild, refresh_reviews=False):
    if guild is None:
        return
    SERVER_COUNTER_UPDATE_FLAGS[guild.id] = bool(
        SERVER_COUNTER_UPDATE_FLAGS.get(guild.id) or refresh_reviews
    )
    task = SERVER_COUNTER_UPDATE_TASKS.get(guild.id)
    if task is None or task.done():
        SERVER_COUNTER_UPDATE_TASKS[guild.id] = asyncio.create_task(
            delayed_server_counter_refresh(guild)
        )


async def server_counter_refresh_loop():
    while not bot.is_closed():
        for guild in bot.guilds:
            if guild_is_authorized(guild.id):
                try:
                    await refresh_server_counters(guild, refresh_reviews=True)
                except (discord.Forbidden, discord.HTTPException) as error:
                    print(f"Actualisation périodique compteurs impossible sur {guild.id}: {error}")
                except Exception as error:
                    print(f"Erreur périodique compteurs serveur {guild.id}: {error}")
        await asyncio.sleep(SERVER_COUNTER_REFRESH_SECONDS)


def authorized_guild_ids():
    ids = set()
    for raw in AUTHORIZED_GUILD_IDS_ENV.replace(";", ",").split(","):
        raw = raw.strip()
        if raw.isdigit():
            ids.add(int(raw))
    stored = get_panel_setting("authorized_guild_ids", []) or []
    for raw in stored:
        try:
            ids.add(int(raw))
        except (TypeError, ValueError):
            pass
    return ids


def guild_authorization_enabled():
    return bool(BOT_AUTH_KEY)


def guild_is_authorized(guild_id):
    return not guild_authorization_enabled() or int(guild_id) in authorized_guild_ids()


def add_authorized_guild(guild_id):
    ids = sorted(authorized_guild_ids() | {int(guild_id)})
    set_panel_setting("authorized_guild_ids", ids)


async def leave_unauthorized_guild_later(guild, delay=GUILD_AUTH_GRACE_SECONDS):
    await asyncio.sleep(max(5, int(delay)))
    if guild and not guild_is_authorized(guild.id):
        try:
            await guild.leave()
            print(f"Serveur non autorisé quitté : {guild.name} ({guild.id})")
        except discord.HTTPException as error:
            print(f"Impossible de quitter le serveur non autorisé {guild.id}: {error}")


async def warn_unauthorized_guild(guild):
    if guild is None or guild_is_authorized(guild.id):
        return
    message = (
        "🔐 **PinkSoftware est protégé.**\n"
        f"Ce serveur n'est pas autorisé. Un administrateur doit exécuter /autoriser_serveur clé dans les {max(1, GUILD_AUTH_GRACE_SECONDS // 60)} prochaines minutes, sinon le bot quittera le serveur."
    )
    for channel in guild.text_channels:
        me = guild.me or (guild.get_member(bot.user.id) if bot.user else None)
        if me and channel.permissions_for(me).send_messages:
            try:
                await channel.send(message)
                break
            except discord.HTTPException:
                pass
    asyncio.create_task(leave_unauthorized_guild_later(guild))


async def sync_commands_to_guilds():
    guild_synced = 0
    for guild in bot.guilds:
        try:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            guild_synced += len(synced)
            print(f"{len(synced)} commande(s) slash serveur synchronisée(s) pour {guild.name} ({guild.id}).")
            await asyncio.sleep(1)
        except discord.HTTPException as error:
            print(f"Synchronisation slash serveur impossible pour {guild.id}: {error}")
    try:
        bot.tree.clear_commands(guild=None)
        removed = await bot.tree.sync()
        print(f"Commandes slash globales nettoyées ({len(removed)} restante(s)).")
    except discord.HTTPException as error:
        print(f"Nettoyage des commandes slash globales impossible : {error}")
    return guild_synced


@bot.event
async def on_ready():
    global BOT_LOOP, COMMAND_SYNC_DONE, PUBLIC_VIEWS_REPAIRED, SERVER_COUNTER_REFRESH_TASK
    BOT_LOOP = asyncio.get_running_loop()
    if not COMMAND_SYNC_DONE:
        await sync_commands_to_guilds()
        COMMAND_SYNC_DONE = True

    # Les vues sont déjà enregistrées dans setup_hook. Les réenregistrer à
    # chaque on_ready peut créer des doublons après une reconnexion.
    if not PUBLIC_VIEWS_REPAIRED:
        try:
            repaired = await repair_public_launcher_views()
            print(f"✅ {repaired} panneau(x) Tarifs/Valorant réparé(s).")
        except Exception as error:
            print(f"Erreur réparation automatique des boutons publics : {error}")
        PUBLIC_VIEWS_REPAIRED = True

    await schedule_active_giveaways()
    await initialize_invite_tracking()
    for guild in bot.guilds:
        if not guild_is_authorized(guild.id):
            await warn_unauthorized_guild(guild)
    if SERVER_COUNTER_REFRESH_TASK is None or SERVER_COUNTER_REFRESH_TASK.done():
        SERVER_COUNTER_REFRESH_TASK = asyncio.create_task(server_counter_refresh_loop())
    await bot.change_presence(activity=discord.Game(name="🎀 PinkGift | Tickets ouverts"))
    print("Le bot PinkSoftware est en ligne et fonctionnel !")

@bot.event
async def on_guild_join(guild):
    await warn_unauthorized_guild(guild)
    await refresh_invite_cache(guild)
    schedule_server_counter_refresh(guild, refresh_reviews=True)


@bot.event
async def on_invite_create(invite):
    guild = invite.guild
    if guild is not None:
        await refresh_invite_cache(guild)


@bot.event
async def on_invite_delete(invite):
    guild = invite.guild
    if guild is None:
        return
    cached = INVITE_USAGE_CACHE.get(guild.id, {}).pop(invite.code, None)
    data = cached or {
        "uses": int(invite.uses or 0),
        "inviter_id": invite.inviter.id if invite.inviter else None,
        "max_uses": int(invite.max_uses or 0),
    }
    data = dict(data)
    data["deleted_at"] = time.monotonic()
    RECENTLY_DELETED_INVITES.setdefault(guild.id, {})[invite.code] = data


@bot.event
async def on_member_join(member):
    await register_invited_member(member)
    schedule_server_counter_refresh(member.guild)
    role = member.guild.get_role(NEW_MEMBER_ROLE_ID)
    if role:
        try:
            await member.add_roles(role, reason="Attribution automatique nouveau membre")
        except Exception as e:
            print(f"Erreur attribution role : {e}")


@bot.event
async def on_member_remove(member):
    await register_departed_member(member)
    schedule_server_counter_refresh(member.guild)


@bot.event
async def on_member_update(before, after):
    before_active = timeout_is_active(before)
    after_active = timeout_is_active(after)
    if after_active and not before_active:
        await add_muted_role(after, reason="Mute détecté automatiquement")
    elif before_active and not after_active:
        await remove_muted_role(after, reason="Fin du mute détectée automatiquement")
    if getattr(before, "primary_guild", None) != getattr(after, "primary_guild", None):
        schedule_server_counter_refresh(after.guild)


@bot.event
async def on_user_update(before, after):
    if getattr(before, "primary_guild", None) == getattr(after, "primary_guild", None):
        return
    guilds = {guild.id: guild for guild in (*before.mutual_guilds, *after.mutual_guilds)}
    for guild in guilds.values():
        schedule_server_counter_refresh(guild)


@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if getattr(message.channel, "id", None) in AUTO_REACTION_CHANNEL_IDS:
        for emoji in AUTO_REACTION_EMOJIS:
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException as error:
                print(f"Erreur réaction auto dans {message.channel}: {error}")
    guild = getattr(message, "guild", None)
    if guild is not None and message.channel.id in verified_reviews_channel_ids(guild.id):
        schedule_server_counter_refresh(guild, refresh_reviews=True)
    await bot.process_commands(message)


@bot.event
async def on_raw_message_delete(payload):
    guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
    if guild is not None and payload.channel_id in verified_reviews_channel_ids(guild.id):
        schedule_server_counter_refresh(guild, refresh_reviews=True)


@bot.event
async def on_raw_bulk_message_delete(payload):
    guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
    if guild is not None and payload.channel_id in verified_reviews_channel_ids(guild.id):
        schedule_server_counter_refresh(guild, refresh_reviews=True)


@bot.event
async def on_guild_channel_delete(channel):
    data = get_server_counter_data(channel.guild.id)
    managed_ids = {
        int(data.get("category_id") or 0),
        int(data.get("members_channel_id") or 0),
        int(data.get("tags_channel_id") or 0),
        int(data.get("reviews_counter_channel_id") or 0),
    }
    if channel.id in managed_ids:
        schedule_server_counter_refresh(channel.guild, refresh_reviews=True)


def build_tarifs_embed():
    texts = load_embed_texts()["tarifs_embed"]
    rgb = texts.get("color_rgb", [255, 192, 203])
    desc_raw = texts.get("description", [])
    description = "\n".join(desc_raw) if isinstance(desc_raw, list) else str(desc_raw)
    description = re.sub(
        r"Cartes cadeaux à \*\*-30\s*%\*\*, sauf Uber Eats avec sa grille fixe et Discord Nitro à \*\*\d+(?:[.,]\d+)?\s*€\*\*\.?",
        "Les prix à jour sont affichés ci-dessous.",
        description,
        flags=re.IGNORECASE,
    )
    description = re.sub(r"(\*\*Discord Nitro)(?:\s+—\s+[^*]+)(\*\*)", r"\1\2", description, flags=re.IGNORECASE)
    description = apply_custom_brand_emojis(description)
    embed = discord.Embed(title=texts.get("title", "🎟️ COMMANDES PINKGIFT"), description=description, color=discord.Color.from_rgb(rgb[0], rgb[1], rgb[2]))
    prices = get_pricing_config()
    gift_lines = [f"**{amount} € reçus** → {format_price(prices['gift_cards'][str(amount)])} € débités" for amount in GIFT_CARD_AMOUNTS]
    uber_lines = [f"**{pack['drop']} € estimés** → {format_price(prices['uber_eats'][pack_key])} € débités" for pack_key, pack in UBEREATS_PACKS.items()]
    embed.add_field(name="💳 Cartes cadeaux — toutes les marques", value="\n".join(gift_lines), inline=False)
    embed.add_field(name="🍔 Uber Eats", value="\n".join(uber_lines), inline=False)
    embed.add_field(name="💎 Discord Nitro", value=f"**{format_price(prices['discord_nitro'])} €** débités", inline=False)
    image_url = texts.get("image_url", TARIFS_IMAGE_URL)
    if image_url:
        embed.set_image(url=image_url)
    return embed

def build_valo_embed():
    texts = load_embed_texts().get("valo_embed", DEFAULT_EMBED_DATA["valo_embed"])
    rgb = texts.get("color_rgb", [255, 192, 203])
    desc_raw = texts.get("description", [])
    description = "\n".join(desc_raw) if isinstance(desc_raw, list) else str(desc_raw)
    kept_lines = []
    region_labels = tuple(region["label"].lower() for region in VALO_REGIONS.values())
    for line in description.splitlines():
        lowered = line.lower()
        if any(label in lowered for label in region_labels) and "**" in line:
            continue
        if "vp" in lowered and re.search(r"\d+(?:[.,]\d+)?\s*€", line):
            continue
        kept_lines.append(line)
    description = "\n".join(kept_lines).strip()
    embed = discord.Embed(title=texts.get("title", "💘 VALORANT POINTS 💘"), description=description, color=discord.Color.from_rgb(rgb[0], rgb[1], rgb[2]))
    prices = get_pricing_config()["valorant"]
    for region_key, region in VALO_REGIONS.items():
        lines = [
            f"<:vp:1519915966476320901> **{pack['label']}** — {format_price(prices[region_key][pack_key])} €"
            for pack_key, pack in region["packs"].items()
        ]
        embed.add_field(name=f"{region['emoji']} {region['label']}", value="\n".join(lines), inline=False)
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


def public_embed_builders():
    return [
        (["COMMANDES PINKGIFT", "CARTE CADEAUX"], build_tarifs_embed, OrderLauncherView()),
        (["VALORANT", "VALORANT POINTS"], build_valo_embed, ValoOrderLauncherView()),
        (["Solde PinkGift", "Solde & paiements"], lambda: build_json_embed("balance_embed"), BalanceView()),
        (["Règlement", "REGLEMENT", "RÈGLEMENT"], lambda: build_json_embed("rules_embed"), None),
        (["FAQ PinkGift", "FAQ"], lambda: build_json_embed("faq_embed"), None),
        (["Classement", "CLASSEMENT"], build_leaderboard_embed, None),
    ]


async def repair_public_launcher_views():
    """Réattache les boutons actuels aux anciens panneaux publics du bot."""
    repaired = 0
    launcher_rules = (
        (("commandes pinkgift", "carte cadeaux"), OrderLauncherView),
        (("valorant", "valorant points"), ValoOrderLauncherView),
    )

    for guild in bot.guilds:
        me = guild.me or (guild.get_member(bot.user.id) if bot.user else None)
        if me is None:
            continue
        for channel in guild.text_channels:
            permissions = channel.permissions_for(me)
            if not permissions.view_channel or not permissions.read_message_history:
                continue
            try:
                async for message in channel.history(limit=500):
                    if message.author.id != bot.user.id or not message.embeds:
                        continue
                    title = (message.embeds[0].title or "").lower()
                    for keywords, view_factory in launcher_rules:
                        if any(keyword in title for keyword in keywords):
                            await message.edit(view=view_factory())
                            repaired += 1
                            break
            except (discord.Forbidden, discord.NotFound):
                continue
            except discord.HTTPException as error:
                print(f"Erreur réparation boutons dans {channel}: {error}")
    return repaired


async def update_public_embeds_without_ping(ctx):
    builders = public_embed_builders()
    updated_count = 0
    scanned_channels = 0
    for channel in ctx.guild.text_channels:
        # Un ticket de recharge contient lui aussi le mot « solde » : il ne doit
        # jamais être traité comme le panneau public publié avec /solde.
        if is_balance_ticket(channel):
            continue
        permissions = channel.permissions_for(ctx.guild.me or ctx.guild.default_role)
        if not permissions.read_message_history or not permissions.view_channel:
            continue
        scanned_channels += 1
        try:
            async for msg in channel.history(limit=150):
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
        except discord.Forbidden:
            continue
        except discord.HTTPException as error:
            print(f"Erreur mise à jour embeds dans {channel}: {error}")
    return updated_count, scanned_channels


async def refresh_price_embeds_from_panel():
    """Actualise les panneaux /tarifs et /valo déjà publiés, sans envoyer de message."""
    rules = (
        (("commandes pinkgift", "carte cadeaux"), build_tarifs_embed, OrderLauncherView),
        (("valorant", "valorant points"), build_valo_embed, ValoOrderLauncherView),
    )
    updated = 0
    for guild in bot.guilds:
        me = guild.me or (guild.get_member(bot.user.id) if bot.user else None)
        if me is None:
            continue
        for channel in guild.text_channels:
            permissions = channel.permissions_for(me)
            if not permissions.view_channel or not permissions.read_message_history:
                continue
            try:
                async for message in channel.history(limit=500):
                    if message.author.id != bot.user.id or not message.embeds:
                        continue
                    title = (message.embeds[0].title or "").lower()
                    for keywords, builder, view_factory in rules:
                        if any(keyword in title for keyword in keywords):
                            await message.edit(embed=builder(), view=view_factory())
                            updated += 1
                            break
            except (discord.Forbidden, discord.NotFound):
                continue
            except discord.HTTPException as error:
                print(f"Erreur actualisation prix dans {channel}: {error}")
    return updated


@bot.hybrid_command(name="maj_embed", description="Mettre à jour tous les embeds publics du serveur")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def update_all_embeds(ctx):
    if ctx.guild is None:
        await ctx.send("❌ Cette commande doit être utilisée dans un serveur.", delete_after=6)
        return
    status = await ctx.send("🔄 Mise à jour des embeds du serveur en cours...")
    updated_count, scanned_channels = await update_public_embeds_without_ping(ctx)
    if updated_count:
        await status.edit(content=f"✅ {updated_count} embed(s) mis à jour dans {scanned_channels} salon(s), sans ping.")
    else:
        await status.edit(content=f"❌ Aucun embed public trouvé dans les {scanned_channels} salon(s) vérifiés.")
    await asyncio.sleep(10)
    try:
        await status.delete()
    except:
        pass
    try:
        await ctx.message.delete()
    except:
        pass


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

@bot.hybrid_command(name="valo", description="Publier le panneau des Valorant Points")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_valo(ctx):
    embed = build_valo_embed()
    await ctx.send(content="||@everyone||", embed=embed, view=ValoOrderLauncherView())

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


def member_timeout_until(member):
    return getattr(member, "timed_out_until", None) or getattr(member, "communication_disabled_until", None)


def timeout_is_active(member):
    until = member_timeout_until(member)
    return bool(until and until > datetime.datetime.now(datetime.timezone.utc))


async def add_muted_role(member, reason="Mute PinkGift"):
    role = member.guild.get_role(MUTED_ROLE_ID)
    if role and role not in member.roles:
        try:
            await member.add_roles(role, reason=reason)
        except discord.HTTPException as error:
            print(f"Erreur ajout rôle mute à {member}: {error}")


async def remove_muted_role(member, reason="Fin du mute PinkGift"):
    role = member.guild.get_role(MUTED_ROLE_ID)
    if role and role in member.roles:
        try:
            await member.remove_roles(role, reason=reason)
        except discord.HTTPException as error:
            print(f"Erreur retrait rôle mute à {member}: {error}")


async def remove_muted_role_later(member, seconds):
    await asyncio.sleep(seconds)
    try:
        fresh = member.guild.get_member(member.id) or await member.guild.fetch_member(member.id)
        if not timeout_is_active(fresh):
            await remove_muted_role(fresh)
    except Exception as error:
        print(f"Erreur vérification fin mute {member}: {error}")

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
    await add_muted_role(member, reason=f"Mute {duration}: {reason}")
    asyncio.create_task(remove_muted_role_later(member, seconds))
    await ctx.send(f"🔇 {member.name} mute pendant {duration}. Rôle mute appliqué automatiquement.")

@bot.hybrid_command(name="invites", description="Afficher le nombre de membres invités")
@discord.app_commands.describe(member="Membre dont tu veux consulter les invitations")
@commands.guild_only()
async def cmd_invites(ctx, member: discord.Member = None):
    target = member or ctx.author
    stats = invite_user_stats(ctx.guild.id, target.id)
    embed = build_json_embed(
        "invites_embed",
        {
            "member": target.display_name,
            "total": stats["total"],
            "active": stats["active"],
            "left": stats["left"],
        },
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    await ctx.send(embed=embed)


@bot.hybrid_command(name="classement_invites", aliases=["top_invites"], description="Afficher le classement des invitations")
@commands.guild_only()
async def cmd_classement_invites(ctx):
    await ctx.send(embed=build_invite_leaderboard_embed(ctx.guild))


@bot.hybrid_command(name="solde", description="Publier le panneau de consultation et recharge du solde")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_solde(ctx):
    await ctx.send(embed=build_json_embed("balance_embed"), view=BalanceView())


@bot.hybrid_command(name="ajouter_solde", description="Ajouter un montant au solde d'un client")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.describe(member="Client concerné", montant="Montant à ajouter en euros")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_ajouter_solde(ctx, member: discord.Member, montant: float):
    if montant <= 0:
        await ctx.send("❌ Le montant doit être positif.", delete_after=5)
        return
    balance = change_balance(ctx.guild.id, member.id, montant, ctx.author.id)
    referral_lot = None
    try:
        referral_lot = track_referral_balance_credit(ctx.guild, member.id, montant, ctx.author.id)
    except Exception as error:
        print(f"Erreur tracking solde parrainé pour {member}: {error}")
    await mark_balance_ticket_credited(ctx.guild, member.id)
    if referral_lot:
        try:
            await send_referral_tracking_notification(ctx.guild, member, ctx.author, referral_lot, balance)
        except Exception as error:
            print(f"Erreur notification recharge parrainée pour {member}: {error}")
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
    try:
        reconcile_referral_balance(ctx.guild.id, member.id, balance)
    except Exception as error:
        print(f"Erreur réconciliation solde parrainé de {member}: {error}")
    await ctx.send(f"✅ **{montant:.2f} €** retirés à {member.mention}. Nouveau solde : **{balance:.2f} €**.")



@bot.hybrid_command(name="commandes", description="Afficher le répertoire des commandes réservées au staff")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_directory(ctx):
    await ctx.send(
    embed=build_json_embed("commandes_embed"),
    view=OrderLauncherView()
)

def panel_auth_token():
    return hashlib.sha256(("pinkgift-panel:" + PANEL_PASSWORD).encode("utf-8")).hexdigest()


def panel_client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or "inconnue"
    real_ip = request.headers.get("X-Real-IP", "").strip()
    return real_ip or request.remote_addr or "inconnue"


def panel_device_type(user_agent):
    ua = (user_agent or "").lower()
    if any(marker in ua for marker in ("bot", "curl", "python", "httpclient", "postman", "uptime")):
        return "Script/API"
    if any(marker in ua for marker in ("ipad", "tablet")):
        return "Tablette"
    if any(marker in ua for marker in ("mobi", "iphone", "android", "windows phone")):
        return "Téléphone"
    if any(marker in ua for marker in ("windows", "macintosh", "linux", "x11", "cros")):
        return "PC"
    return "Inconnu"


def panel_logged_path():
    query_items = [(key, value) for key, value in request.args.items(multi=True) if key.lower() != "key"]
    query = urllib.parse.urlencode(query_items)
    return request.path + (f"?{query}" if query else "")


def log_panel_access():
    if not request.path.startswith("/panel"):
        return
    user_agent = request.headers.get("User-Agent", "")[:500]
    values = {
        "ip": panel_client_ip()[:80],
        "path": panel_logged_path()[:300],
        "method": request.method[:20],
        "device": panel_device_type(user_agent),
        "user_agent": user_agent
    }
    try:
        if USE_SUPABASE:
            supabase_request("POST", "panel_access_logs", values, "return=minimal")
        else:
            with db_connect() as db:
                db.execute("INSERT INTO panel_access_logs(ip,path,method,device,user_agent) VALUES(?,?,?,?,?)", (values["ip"], values["path"], values["method"], values["device"], values["user_agent"]))
    except Exception as error:
        print(f"Journal panel indisponible : {error}")


def panel_audit_allowed():
    if not PANEL_AUDIT_KEY:
        return True
    if session.get("panel_audit_ok"):
        return True
    key = request.args.get("key", "")
    if key and secrets.compare_digest(key, PANEL_AUDIT_KEY):
        session["panel_audit_ok"] = True
        return True
    return False


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
<style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}h1{margin:0;color:#ff8fc8;font-size:23px}main{padding:22px 5%}nav{display:flex;gap:8px;margin-bottom:18px}.tab{color:#e8dce3;text-decoration:none;padding:10px 14px;border:1px solid #4c3543}.tab.active{background:#e8509a;color:white;border-color:#e8509a}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}table{width:100%;border-collapse:collapse;background:#171419}th,td{text-align:left;padding:11px;border-bottom:1px solid #332630}th{color:#ff9dce}input,select{background:#0e0d11;color:white;border:1px solid #5a3a4d;padding:9px;min-width:160px}select{cursor:pointer}.filters{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 16px 0}.filters label{color:#ff9dce;font-weight:bold}button{background:#e8509a;color:white;border:0;padding:10px 13px;cursor:pointer}.delete{background:#9d294b;margin-left:5px}.done{color:#74d99f}.pending{color:#ffd27b}.muted{color:#aa98a4;font-size:12px}@media(max-width:800px){table,thead,tbody,tr,td{display:block}thead{display:none}tr{padding:12px;border-bottom:1px solid #332630}td{border:0;padding:6px}}</style></head><body>
<header><h1>PinkGift — Panel staff</h1><a href="{{ url_for('panel_logout') }}" style="color:#ff9dce">Déconnexion</a></header><main>
<nav><a class="tab {{ 'active' if tab == 'orders' else '' }}" href="{{ url_for('panel_orders', tab='orders') }}">Commandes</a><a class="tab {{ 'active' if tab == 'valorant' else '' }}" href="{{ url_for('panel_orders', tab='valorant') }}">Valorant</a><a class="tab {{ 'active' if tab == 'clients' else '' }}" href="{{ url_for('panel_orders', tab='clients') }}">Clients</a><a class="tab" href="{{ url_for('panel_finances') }}">Statistiques</a><a class="tab" href="{{ url_for('panel_referrals') }}">Parrainage</a><a class="tab" href="{{ url_for('panel_prices') }}">Prix</a><a class="tab" href="{{ url_for('panel_stock') }}">Stock</a><a class="tab" href="{{ url_for('panel_embeds') }}">Embeds</a></nav>
{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}
{% if tab == 'clients' %}<table><thead><tr><th>Client</th><th>ID Discord</th><th>Commandes</th><th>Total dépensé</th></tr></thead><tbody>{% for client in clients %}<tr><td><a href="https://discord.com/users/{{ client.user_id }}" target="_blank" style="color:#ff9dce;text-decoration:none"><strong>@{{ client.user_name }}</strong></a></td><td class="muted">{{ client.user_id }}</td><td>{{ client.order_count }}</td><td><strong>{{ '%.2f'|format(client.total_spent) }} €</strong></td></tr>{% else %}<tr><td colspan="4">Aucun client enregistré.</td></tr>{% endfor %}</tbody></table>
{% else %}{% if tab == 'orders' %}<form class="filters" method="get" action="{{ url_for('panel_orders') }}"><input type="hidden" name="tab" value="orders"><label for="service-filter">Service</label><select id="service-filter" name="service" onchange="this.form.submit()"><option value="">Tous les services</option>{% for service in service_options %}<option value="{{ service }}" {% if service == service_filter %}selected{% endif %}>{{ service }}</option>{% endfor %}</select><label for="amount-filter">Montant</label><select id="amount-filter" name="amount" onchange="this.form.submit()"><option value="">Tous les montants</option>{% for amount in amount_options %}<option value="{{ amount }}" {% if amount == amount_filter %}selected{% endif %}>{{ amount }}</option>{% endfor %}</select></form>{% elif tab == 'valorant' %}<form class="filters" method="get" action="{{ url_for('panel_orders') }}"><input type="hidden" name="tab" value="valorant"><label for="region-filter">Région</label><select id="region-filter" name="region" onchange="this.form.submit()"><option value="">Toutes les régions</option>{% for region in region_options %}<option value="{{ region }}" {% if region == region_filter %}selected{% endif %}>{{ region }}</option>{% endfor %}</select><label for="pack-filter">Pack VP</label><select id="pack-filter" name="pack" onchange="this.form.submit()"><option value="">Tous les packs</option>{% for pack in pack_options %}<option value="{{ pack }}" {% if pack == pack_filter %}selected{% endif %}>{{ pack }}</option>{% endfor %}</select></form>{% endif %}<table><thead><tr><th>ID</th><th>Client</th><th>Service</th><th>Reçu</th><th>Payé</th><th>État</th><th>Actions</th></tr></thead><tbody>{% for order in orders %}<tr><td>#{{ loop.index }}</td><td><a href="https://discord.com/users/{{ order.user_id }}" target="_blank" style="color:#ff9dce;text-decoration:none">@{{ order.user_name or order.user_id }}</a></td><td>{{ order.service }}</td><td>{{ order.received_label or ((order.amount|string) + " €") }}</td><td>{{ order.paid }} €</td><td class="{{ order.status }}">{{ order.status }}</td><td><form method="post" action="{{ url_for('panel_set_code', order_id=order.id) }}" style="display:inline"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="return_tab" value="{{ tab }}"><input type="hidden" name="return_service" value="{{ service_filter }}"><input type="hidden" name="return_amount" value="{{ amount_filter }}"><input type="hidden" name="return_region" value="{{ region_filter }}"><input type="hidden" name="return_pack" value="{{ pack_filter }}"><input name="code" required placeholder="Code cadeau" value="{{ order.code or '' }}"><button type="submit">Livrer</button></form><form method="post" action="{{ url_for('panel_delete_order', order_id=order.id) }}" style="display:inline" onsubmit="return confirm('Supprimer cette commande du panel ?')"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="return_tab" value="{{ tab }}"><input type="hidden" name="return_service" value="{{ service_filter }}"><input type="hidden" name="return_amount" value="{{ amount_filter }}"><input type="hidden" name="return_region" value="{{ region_filter }}"><input type="hidden" name="return_pack" value="{{ pack_filter }}"><button class="delete" type="submit" title="Supprimer">Supprimer</button></form></td></tr>{% else %}<tr><td colspan="7">Aucune commande enregistrée.</td></tr>{% endfor %}</tbody></table>{% endif %}
</main></body></html>"""


PANEL_STOCK_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Stock</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}main{padding:22px 5%}h1{color:#ff8fc8}table{width:100%;border-collapse:collapse;background:#171419;margin-bottom:28px}th,td{text-align:left;padding:11px;border-bottom:1px solid #332630}th{color:#ff9dce}select,button{background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:9px}button{background:#e8509a;border:0;cursor:pointer}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}a{color:#ff9dce}</style></head><body><header><h1>PinkGift — Stock</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main>{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}<h2>Cartes cadeaux / produits</h2><table><thead><tr><th>Service</th><th>État</th><th>Action</th></tr></thead><tbody>{% for item in products %}<tr><td>{{ item.display }}</td><td>{{ ok_emoji if item.available else ko_emoji }} {{ 'Disponible' if item.available else 'Rupture' }}</td><td><form method="post"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="kind" value="product"><input type="hidden" name="key" value="{{ item.key }}"><select name="available"><option value="1" {% if item.available %}selected{% endif %}>Disponible</option><option value="0" {% if not item.available %}selected{% endif %}>Rupture</option></select><button>Enregistrer</button></form></td></tr>{% endfor %}</tbody></table><h2>Valorant Points</h2><table><thead><tr><th>Région</th><th>Pack</th><th>État</th><th>Action</th></tr></thead><tbody>{% for item in valorant %}<tr><td>{{ item.region }}</td><td>{{ item.pack }} — {{ item.price }} €</td><td>{{ ok_emoji if item.available else ko_emoji }} {{ 'Disponible' if item.available else 'Rupture' }}</td><td><form method="post"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="kind" value="valorant"><input type="hidden" name="region" value="{{ item.region_key }}"><input type="hidden" name="key" value="{{ item.pack_key }}"><select name="available"><option value="1" {% if item.available %}selected{% endif %}>Disponible</option><option value="0" {% if not item.available %}selected{% endif %}>Rupture</option></select><button>Enregistrer</button></form></td></tr>{% endfor %}</tbody></table></main></body></html>"""

PANEL_PRICES_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Prix</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}main{padding:22px 5%;max-width:1000px}h1{color:#ff8fc8}.card{background:#171419;border:1px solid #332630;padding:16px;margin-bottom:18px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:13px}.field{display:flex;flex-direction:column;gap:6px}.field span{color:#ff9dce;font-weight:bold}.field small,.muted{color:#aa98a4}input{background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:11px;font-size:16px}button{background:#e8509a;color:#fff;border:0;padding:13px 18px;cursor:pointer;font-weight:bold}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}a{color:#ff9dce}</style></head><body><header><h1>PinkGift — Prix</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main>{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}<p class="muted">Les nouveaux prix sont utilisés immédiatement dans les menus, les embeds et le débit du solde. Aucun redémarrage du bot n'est nécessaire.</p><form method="post"><input type="hidden" name="csrf" value="{{ session.csrf }}"><section class="card"><h2>Cartes cadeaux — toutes les marques</h2><div class="grid">{% for item in gift_cards %}<label class="field"><span>{{ item.amount }} € reçus</span><input type="number" name="gift_{{ item.amount }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01" required><small>Montant débité en euros</small></label>{% endfor %}</div></section><section class="card"><h2>Uber Eats</h2><div class="grid">{% for item in uber_eats %}<label class="field"><span>{{ item.drop }} € estimés</span><input type="number" name="uber_{{ item.key }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01" required><small>Montant débité en euros</small></label>{% endfor %}</div></section><section class="card"><h2>Discord Nitro</h2><div class="grid"><label class="field"><span>Discord Nitro</span><input type="number" name="discord_nitro" value="{{ discord_nitro }}" min="0.01" max="100000" step="0.01" required><small>Montant débité en euros</small></label></div></section><section class="card"><h2>Valorant Points</h2><div class="grid">{% for item in valorant %}<label class="field"><span>{{ item.region }} — {{ item.pack }}</span><input type="number" name="valo_{{ item.region_key }}_{{ item.pack_key }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01" required><small>Montant débité en euros</small></label>{% endfor %}</div></section><button type="submit">Enregistrer tous les prix</button></form></main></body></html>"""

PANEL_FINANCES_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Statistiques</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}main{padding:22px 5%;max-width:1100px}h1{color:#ff8fc8}.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin-bottom:20px}.toolbar label,.cost-form label{display:flex;flex-direction:column;gap:6px;color:#ff9dce;font-weight:bold}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-bottom:22px}.card{background:#171419;border:1px solid #332630;padding:18px}.card span{display:block;color:#aa98a4;font-size:13px}.card strong{display:block;margin-top:8px;color:#fff;font-size:30px}.card.profit strong.positive{color:#74d99f}.card.profit strong.negative{color:#ff718f}input,button{background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:10px;font-size:15px}button{background:#e8509a;border:0;cursor:pointer;font-weight:bold}table{width:100%;border-collapse:collapse;background:#171419;margin-top:18px}th,td{text-align:left;padding:11px;border-bottom:1px solid #332630}th{color:#ff9dce}.cost-form{display:flex;flex-wrap:wrap;gap:10px;align-items:end;background:#171419;border:1px solid #332630;padding:16px}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}.muted{color:#aa98a4;font-size:13px}a{color:#ff9dce}</style></head><body><header><h1>PinkGift — Statistiques</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main>{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}<form class="toolbar" method="get"><label>Mois<input type="month" name="month" value="{{ stats.month }}" required></label><button type="submit">Afficher</button></form><h2>{{ month_label }}</h2><div class="cards"><article class="card"><span>Chiffre d'affaires</span><strong>{{ '%.2f'|format(stats.revenue) }} €</strong></article><article class="card"><span>Coûts renseignés</span><strong>{{ '%.2f'|format(stats.costs) }} €</strong></article><article class="card profit"><span>Bénéfice</span><strong class="{{ 'positive' if stats.profit >= 0 else 'negative' }}">{{ '%.2f'|format(stats.profit) }} €</strong></article><article class="card"><span>Commandes livrées</span><strong>{{ stats.orders }}</strong></article><article class="card"><span>Panier moyen</span><strong>{{ '%.2f'|format(stats.average_order) }} €</strong></article></div><form class="cost-form" method="post"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="month" value="{{ stats.month }}"><label>Coûts d'achat et dépenses du mois<input type="number" name="costs" value="{{ stats.costs }}" min="0" max="100000" step="0.01" required></label><button type="submit">Recalculer le bénéfice</button><span class="muted">Bénéfice = chiffre d'affaires des commandes livrées − coûts renseignés.</span></form><h2>Détail par produit</h2><table><thead><tr><th>Produit</th><th>Commandes livrées</th><th>Chiffre d'affaires</th></tr></thead><tbody>{% for item in stats.breakdown %}<tr><td>{{ item.service }}</td><td>{{ item.orders }}</td><td>{{ '%.2f'|format(item.revenue) }} €</td></tr>{% else %}<tr><td colspan="3">Aucune commande livrée pendant ce mois.</td></tr>{% endfor %}</tbody></table></main></body></html>"""

PANEL_PRICES_COSTS_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Prix et coûts</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}main{padding:22px 5%;max-width:1100px}h1{color:#ff8fc8}.card,details{background:#171419;border:1px solid #332630;padding:16px;margin-bottom:16px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:13px}.field{display:flex;flex-direction:column;gap:6px}.field span,summary{color:#ff9dce;font-weight:bold}.field small,.muted{color:#aa98a4}summary{cursor:pointer}details .grid{margin-top:15px}input{background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:10px;font-size:15px}button{background:#e8509a;color:#fff;border:0;padding:13px 18px;cursor:pointer;font-weight:bold}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}a{color:#ff9dce}</style></head><body><header><h1>PinkGift — Prix et coûts d'achat</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main>{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}<p class="muted">Le prix de vente détermine le débit client. Le coût d'achat est enregistré avec chaque nouvelle commande pour calculer le bénéfice sans modifier l'historique.</p><form method="post"><input type="hidden" name="csrf" value="{{ session.csrf }}"><section class="card"><h2>Prix de vente des cartes cadeaux</h2><div class="grid">{% for item in gift_cards %}<label class="field"><span>{{ item.amount }} € reçus</span><input type="number" name="gift_{{ item.amount }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01" required><small>Débit client</small></label>{% endfor %}</div></section><h2>Coûts d'achat des cartes par marque</h2>{% for product in gift_cost_products %}<details><summary>{{ product.display }}</summary><div class="grid">{% for item in product.amounts %}<label class="field"><span>Carte {{ item.amount }} €</span><input type="number" name="cost_gift_{{ product.key }}_{{ item.amount }}" value="{{ item.cost }}" min="0" max="100000" step="0.01" required><small>Coût d'achat</small></label>{% endfor %}</div></details>{% endfor %}<section class="card"><h2>Uber Eats</h2><div class="grid">{% for item in uber_eats %}<label class="field"><span>{{ item.drop }} € estimés — prix de vente</span><input type="number" name="uber_{{ item.key }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01" required></label><label class="field"><span>{{ item.drop }} € estimés — coût d'achat</span><input type="number" name="cost_uber_{{ item.key }}" value="{{ item.cost }}" min="0" max="100000" step="0.01" required></label>{% endfor %}</div></section><section class="card"><h2>Discord Nitro</h2><div class="grid"><label class="field"><span>Prix de vente</span><input type="number" name="discord_nitro" value="{{ discord_nitro }}" min="0.01" max="100000" step="0.01" required></label><label class="field"><span>Coût d'achat</span><input type="number" name="cost_discord_nitro" value="{{ discord_nitro_cost }}" min="0" max="100000" step="0.01" required></label></div></section><section class="card"><h2>Valorant Points</h2><div class="grid">{% for item in valorant %}<label class="field"><span>{{ item.region }} — {{ item.pack }} — prix de vente</span><input type="number" name="valo_{{ item.region_key }}_{{ item.pack_key }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01" required></label><label class="field"><span>{{ item.region }} — {{ item.pack }} — coût d'achat</span><input type="number" name="cost_valo_{{ item.region_key }}_{{ item.pack_key }}" value="{{ item.cost }}" min="0" max="100000" step="0.01" required></label>{% endfor %}</div></section><button type="submit">Enregistrer les prix et les coûts</button></form></main></body></html>"""

PANEL_FINANCES_PRODUCT_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Statistiques</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}main{padding:22px 5%;max-width:1100px}h1{color:#ff8fc8}.toolbar{display:flex;gap:10px;align-items:end;margin-bottom:20px}.toolbar label{display:flex;flex-direction:column;gap:6px;color:#ff9dce;font-weight:bold}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-bottom:22px}.card{background:#171419;border:1px solid #332630;padding:18px}.card span{display:block;color:#aa98a4;font-size:13px}.card strong{display:block;margin-top:8px;font-size:30px}.positive{color:#74d99f}.negative{color:#ff718f}input,button{background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:10px}button{background:#e8509a;border:0;cursor:pointer}table{width:100%;border-collapse:collapse;background:#171419}th,td{text-align:left;padding:11px;border-bottom:1px solid #332630}th{color:#ff9dce}.muted{color:#aa98a4;font-size:13px}a{color:#ff9dce}</style></head><body><header><h1>PinkGift — Statistiques</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main><form class="toolbar" method="get"><label>Mois<input type="month" name="month" value="{{ stats.month }}" required></label><button>Afficher</button></form><h2>{{ month_label }}</h2><div class="cards"><article class="card"><span>Chiffre d'affaires</span><strong>{{ '%.2f'|format(stats.revenue) }} €</strong></article><article class="card"><span>Coûts d'achat</span><strong>{{ '%.2f'|format(stats.costs) }} €</strong></article><article class="card"><span>Bénéfice</span><strong class="{{ 'positive' if stats.profit >= 0 else 'negative' }}">{{ '%.2f'|format(stats.profit) }} €</strong></article><article class="card"><span>Commandes livrées</span><strong>{{ stats.orders }}</strong></article><article class="card"><span>Panier moyen</span><strong>{{ '%.2f'|format(stats.average_order) }} €</strong></article></div><p class="muted">Le bénéfice utilise le coût d'achat enregistré au moment de chaque commande. <a href="{{ url_for('panel_prices') }}">Modifier les coûts d'achat</a>.</p><h2>Détail par produit</h2><table><thead><tr><th>Produit</th><th>Ventes</th><th>CA</th><th>Coûts</th><th>Bénéfice</th></tr></thead><tbody>{% for item in stats.breakdown %}<tr><td>{{ item.service }}</td><td>{{ item.orders }}</td><td>{{ '%.2f'|format(item.revenue) }} €</td><td>{{ '%.2f'|format(item.costs) }} €</td><td class="{{ 'positive' if item.profit >= 0 else 'negative' }}">{{ '%.2f'|format(item.profit) }} €</td></tr>{% else %}<tr><td colspan="5">Aucune commande livrée pendant ce mois.</td></tr>{% endfor %}</tbody></table></main></body></html>"""

NITRO_FINANCE_BLOCK = """<h2>Discord Nitro — ventes du tiers</h2><div class="cards"><article class="card"><span>Nitro livrés</span><strong>{{ stats.nitro.orders }}</strong></article><article class="card"><span>Chiffre d'affaires Nitro</span><strong>{{ '%.2f'|format(stats.nitro.revenue) }} €</strong></article><article class="card"><span>Coûts d'achat Nitro</span><strong>{{ '%.2f'|format(stats.nitro.costs) }} €</strong></article><article class="card"><span>Bénéfice Nitro généré</span><strong class="{{ 'positive' if stats.nitro.profit >= 0 else 'negative' }}">{{ '%.2f'|format(stats.nitro.profit) }} €</strong></article></div>"""
PANEL_FINANCES_NITRO_TEMPLATE = PANEL_FINANCES_PRODUCT_TEMPLATE.replace(
    "</div><p class=\"muted\">",
    f"</div>{NITRO_FINANCE_BLOCK}<p class=\"muted\">",
    1,
)

PANEL_REFERRALS_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Parrainage</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}main{padding:22px 5%;max-width:1200px}h1{color:#ff8fc8}.card{background:#171419;border:1px solid #332630;padding:16px;margin-bottom:18px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:11px}.field{display:flex;flex-direction:column;gap:5px}.field span{color:#ff9dce;font-weight:bold}.field small,.muted{color:#aa98a4}input,button{background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:10px}button{background:#e8509a;border:0;cursor:pointer;font-weight:bold}table{width:100%;border-collapse:collapse;background:#171419;margin:18px 0}th,td{text-align:left;padding:10px;border-bottom:1px solid #332630;vertical-align:top}th{color:#ff9dce}.inline-form{display:flex;flex-wrap:wrap;gap:7px;align-items:center}.inline-form input{min-width:90px}.positive{color:#74d99f;font-weight:bold}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}a{color:#ff9dce}</style></head><body><header><h1>PinkGift — Parrainage</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main>{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}<section class="card"><h2>Créer un code</h2><form method="post"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="action" value="save"><div class="grid"><label class="field"><span>Code</span><input name="code" minlength="3" maxlength="32" placeholder="PINKY10" required></label><label class="field"><span>Nom du parrain</span><input name="sponsor_name" maxlength="80" required></label><label class="field"><span>ID Discord du parrain</span><input name="sponsor_id" inputmode="numeric" placeholder="Optionnel"></label><label class="field"><span>Commission (%)</span><input type="number" name="percentage" min="0" max="100" step="0.01" required></label><label class="field"><span>Déjà versé (€)</span><input type="number" name="paid" value="0" min="0" step="0.01" required></label></div><p><label><input type="checkbox" name="active" value="1" checked> Code actif</label></p><button>Créer le code</button></form></section><h2>Suivi des parrains</h2><table><thead><tr><th>Code / Parrain</th><th>Utilisations</th><th>Solde ajouté</th><th>Commission générée</th><th>Déjà versé</th><th>Reste à verser</th><th>Configuration</th></tr></thead><tbody>{% for item in summaries %}<tr><td><strong>{{ item.code }}</strong><br>{{ item.sponsor_name }}{% if item.sponsor_id %}<br><a href="https://discord.com/users/{{ item.sponsor_id }}" target="_blank">{{ item.sponsor_id }}</a>{% endif %}<br>{{ 'Actif' if item.active else 'Désactivé' }}</td><td>{{ item.uses }}</td><td>{{ '%.2f'|format(item.amount) }} €</td><td>{{ '%.2f'|format(item.commission) }} €</td><td>{{ '%.2f'|format(item.paid) }} €</td><td class="positive">{{ '%.2f'|format(item.due) }} €</td><td><form class="inline-form" method="post"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="action" value="save"><input type="hidden" name="code" value="{{ item.code }}"><input name="sponsor_name" value="{{ item.sponsor_name }}" title="Nom" required><input name="sponsor_id" value="{{ item.sponsor_id }}" title="ID Discord"><input type="number" name="percentage" value="{{ item.percentage }}" min="0" max="100" step="0.01" title="Pourcentage" required><input type="number" name="paid" value="{{ item.paid }}" min="0" step="0.01" title="Déjà versé" required><label><input type="checkbox" name="active" value="1" {% if item.active %}checked{% endif %}> actif</label><button>Enregistrer</button></form></td></tr>{% else %}<tr><td colspan="7">Aucun code créé.</td></tr>{% endfor %}</tbody></table><h2>Historique récent</h2><table><thead><tr><th>Date</th><th>Code</th><th>Client</th><th>Solde ajouté</th><th>Taux</th><th>Commission</th></tr></thead><tbody>{% for event in events %}<tr><td>{{ event.created_at }}</td><td>{{ event.code }}</td><td><a href="https://discord.com/users/{{ event.user_id }}" target="_blank">{{ event.user_id }}</a></td><td>{{ '%.2f'|format(event.amount) }} €</td><td>{{ event.percentage }} %</td><td>{{ '%.2f'|format(event.commission) }} €</td></tr>{% else %}<tr><td colspan="6">Aucune commission enregistrée.</td></tr>{% endfor %}</tbody></table></main></body></html>"""

PANEL_REFERRALS_PROFIT_TEMPLATE = (
    PANEL_REFERRALS_TEMPLATE
    .replace("Reste à verser", "À verser manuellement au parrain")
    .replace("<span>Commission (%)</span>", "<span>% du bénéfice</span>")
    .replace(
        "<span>ID Discord du parrain</span>",
        "<span>ID Discord du parrain (information interne)</span>",
    )
    .replace(
        "<section class=\"card\"><h2>Créer un code</h2>",
        "<p class=\"muted\">Seuls les codes actifs que tu crées dans ce panel sont acceptés. Un client ne peut pas devenir parrain en indiquant un ID Discord : l'ID renseigné ici est uniquement une information interne associée au code. Le solde obtenu avec un code est suivi jusqu'aux achats. La commission porte uniquement sur le bénéfice réel généré par la part de solde parrainée. Aucun solde n'est crédité automatiquement au parrain : le panel indique seulement le montant que tu dois lui verser manuellement.</p><section class=\"card\"><h2>Créer un code</h2>",
    )
    .replace(
        "<th>Utilisations</th><th>Solde ajouté</th><th>Commission générée</th>",
        "<th>Achats</th><th>Solde parrainé crédité</th><th>Solde parrainé restant</th><th>Solde utilisé</th><th>Bénéfice généré</th><th>Commission générée</th>",
    )
    .replace(
        "<td>{{ item.uses }}</td><td>{{ '%.2f'|format(item.amount) }} €</td><td>{{ '%.2f'|format(item.commission) }} €</td>",
        "<td>{{ item.uses }}</td><td>{{ '%.2f'|format(item.credited) }} €</td><td>{{ '%.2f'|format(item.remaining) }} €</td><td>{{ '%.2f'|format(item.amount) }} €</td><td>{{ '%.2f'|format(item.profit) }} €</td><td>{{ '%.2f'|format(item.commission) }} €</td>",
    )
    .replace('colspan="7">Aucun code créé.', 'colspan="10">Aucun code créé.')
    .replace(
        "<th>Date</th><th>Code</th><th>Client</th><th>Solde ajouté</th><th>Taux</th><th>Commission</th>",
        "<th>Date</th><th>Code</th><th>Client</th><th>Produit</th><th>Solde utilisé</th><th>Bénéfice attribué</th><th>Taux</th><th>Commission</th>",
    )
    .replace(
        "<td>{{ '%.2f'|format(event.amount) }} €</td><td>{{ event.percentage }} %</td>",
        "<td>{{ event.service }}</td><td>{{ '%.2f'|format(event.referred_used) }} €</td><td>{{ '%.2f'|format(event.attributed_profit) }} €</td><td>{{ event.percentage }} %</td>",
    )
    .replace('colspan="6">Aucune commission enregistrée.', 'colspan="8">Aucune commission enregistrée.')
)

PANEL_EMBEDS_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Embeds</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}main{padding:22px 5%}h1{color:#ff8fc8}details{background:#171419;border:1px solid #332630;margin-bottom:14px;padding:12px}summary{cursor:pointer;color:#ff9dce;font-weight:bold}textarea{box-sizing:border-box;width:100%;min-height:260px;background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:10px;font-family:Consolas,monospace}input,button{background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:9px;margin-top:8px}button{background:#e8509a;border:0;cursor:pointer}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}.muted{color:#aa98a4;font-size:13px}a{color:#ff9dce}</style></head><body><header><h1>PinkGift — Embeds</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main>{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}<p class="muted">Modifie le JSON d'un embed puis clique sur Enregistrer. Pour uploader une image, choisis un fichier : le bot l'envoie dans le salon configuré par EMBED_UPLOAD_CHANNEL_ID et remplit automatiquement image_url.</p>{% for item in embeds %}<details><summary>{{ item.key }}</summary><form method="post" enctype="multipart/form-data"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="embed_key" value="{{ item.key }}"><textarea name="embed_json">{{ item.json }}</textarea><br><input type="file" name="image_file" accept="image/*"><button>Enregistrer</button></form></details>{% endfor %}</main></body></html>"""

LOGIN_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift</title><style>body{background:#0e0d11;color:#fff;font-family:Arial;display:grid;place-items:center;height:100vh;margin:0}form{background:#19151b;padding:28px;border:1px solid #4a3040;width:min(340px,80vw)}h1{color:#ff8fc8}input,button{box-sizing:border-box;width:100%;padding:12px;margin-top:10px}input{background:#0e0d11;color:#fff;border:1px solid #5a3a4d}button{background:#e8509a;color:#fff;border:0}</style></head><body><form method="post"><h1>PinkGift Staff</h1><input type="password" name="password" placeholder="Mot de passe" required><button>Connexion</button></form></body></html>"""

PANEL_ACCESS_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Accès panel</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}h1{margin:0;color:#ff8fc8;font-size:23px}main{padding:22px 5%}table{width:100%;border-collapse:collapse;background:#171419}th,td{text-align:left;padding:11px;border-bottom:1px solid #332630;vertical-align:top}th{color:#ff9dce}.muted{color:#aa98a4;font-size:12px}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}input{background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:11px;min-width:260px}button{background:#e8509a;color:#fff;border:0;padding:12px 14px;cursor:pointer}a{color:#ff9dce}.ua{max-width:520px;word-break:break-word}</style></head><body><header><h1>PinkGift — Accès panel</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main>{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}{% if locked %}<form method="get"><h2>Accès protégé</h2><p class="muted">Entre la clé privée configurée dans PANEL_AUDIT_KEY.</p><input type="password" name="key" placeholder="Clé privée" required><button type="submit">Ouvrir</button></form>{% else %}<table><thead><tr><th>Heure</th><th>IP</th><th>Mode</th><th>Page</th><th>Méthode</th><th>User-agent</th></tr></thead><tbody>{% for log in logs %}<tr><td>{{ log.created_at }}</td><td>{{ log.ip }}</td><td>{{ log.device }}</td><td>{{ log.path }}</td><td>{{ log.method }}</td><td class="ua muted">{{ log.user_agent }}</td></tr>{% else %}<tr><td colspan="6">Aucun accès enregistré.</td></tr>{% endfor %}</tbody></table>{% endif %}</main></body></html>"""


@app.before_request
def track_panel_access():
    log_panel_access()


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


def panel_filter_redirect():
    return redirect(url_for(
        "panel_orders",
        tab=request.form.get("return_tab", "orders"),
        service=request.form.get("return_service", ""),
        amount=request.form.get("return_amount", ""),
        region=request.form.get("return_region", ""),
        pack=request.form.get("return_pack", "")
    ))


def panel_order_id(order):
    try:
        return int(order.get("id") or 0)
    except (TypeError, ValueError):
        return 0


def panel_order_sort_key(order):
    status = str(order.get("status") or "pending").lower()
    return (1 if status in ("done", "livre", "livré", "delivered") else 0, panel_order_id(order) if status not in ("done", "livre", "livré", "delivered") else -panel_order_id(order))


def panel_amount_label(order):
    amount = order.get("amount")
    try:
        return f"{float(amount):g} €"
    except (TypeError, ValueError):
        return f"{amount} €" if amount not in (None, "") else "Montant inconnu"


def panel_amount_sort_key(label):
    match = re.search(r"\d+(?:[.,]\d+)?", str(label))
    return float(match.group(0).replace(",", ".")) if match else 999999


def panel_valorant_region(order):
    service = str(order.get("service") or "")
    if not service.lower().startswith("valorant"):
        return ""
    details = service[len("Valorant"):].strip()
    for region in VALO_REGIONS.values():
        label = region.get("label", "")
        if label and details.lower().startswith(label.lower()):
            return label
    return details.split()[0] if details else "Région inconnue"


def panel_valorant_pack(order):
    received_label = str(order.get("received_label") or "").strip()
    if received_label:
        return received_label
    service = str(order.get("service") or "")
    match = re.search(r"(\d+\s*VP)", service, re.IGNORECASE)
    if match:
        number_match = re.search(r"\d+", match.group(1))
        if number_match:
            return f"{number_match.group(0)} VP"
    return "Pack inconnu"


@app.route("/panel/acces")
@panel_required
def panel_access_logs():
    if not panel_audit_allowed():
        return render_template_string(PANEL_ACCESS_TEMPLATE, logs=[], locked=True)
    try:
        if USE_SUPABASE:
            logs = supabase_request("GET", "panel_access_logs?select=*&order=id.desc&limit=500") or []
        else:
            with db_connect() as db:
                logs = [dict(row) for row in db.execute("SELECT * FROM panel_access_logs ORDER BY id DESC LIMIT 500").fetchall()]
    except Exception as error:
        print(f"Erreur lecture journal panel : {error}")
        flash("Journal indisponible. Vérifie que la table Supabase panel_access_logs existe.")
        logs = []
    return render_template_string(PANEL_ACCESS_TEMPLATE, logs=logs, locked=False)


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
    amount_filter = request.args.get("amount", "").strip()
    region_filter = request.args.get("region", "").strip()
    pack_filter = request.args.get("pack", "").strip()
    command_orders = [order for order in all_orders if not str(order.get("service", "")).lower().startswith("valorant")]
    valorant_orders = [order for order in all_orders if str(order.get("service", "")).lower().startswith("valorant")]
    service_options = sorted({str(order.get("service") or "Service inconnu") for order in command_orders})
    amount_options = sorted({panel_amount_label(order) for order in command_orders}, key=panel_amount_sort_key)
    region_order = {region.get("label", ""): index for index, region in enumerate(VALO_REGIONS.values())}
    region_options = sorted({panel_valorant_region(order) for order in valorant_orders}, key=lambda label: region_order.get(label, 999))
    pack_options = sorted({panel_valorant_pack(order) for order in valorant_orders}, key=panel_amount_sort_key)
    if tab == "valorant":
        orders = valorant_orders
        service_filter = ""
        amount_filter = ""
        if region_filter:
            orders = [order for order in orders if panel_valorant_region(order) == region_filter]
        if pack_filter:
            orders = [order for order in orders if panel_valorant_pack(order) == pack_filter]
    elif tab == "orders":
        orders = command_orders
        region_filter = ""
        pack_filter = ""
        if service_filter:
            orders = [order for order in orders if str(order.get("service") or "Service inconnu") == service_filter]
        if amount_filter:
            orders = [order for order in orders if panel_amount_label(order) == amount_filter]
    else:
        orders = []
        service_filter = amount_filter = region_filter = pack_filter = ""
    orders = sorted(orders, key=panel_order_sort_key)
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
    return render_template_string(PANEL_TEMPLATE, orders=orders, clients=clients, tab=tab, service_options=service_options, service_filter=service_filter, amount_options=amount_options, amount_filter=amount_filter, region_options=region_options, region_filter=region_filter, pack_options=pack_options, pack_filter=pack_filter)


async def upload_panel_image_to_discord(filename, content):
    channel_id = int(os.environ.get("EMBED_UPLOAD_CHANNEL_ID", "0") or 0)
    if not channel_id:
        raise RuntimeError("EMBED_UPLOAD_CHANNEL_ID manquant")
    channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", filename or "embed.png")[:80] or "embed.png"
    message = await channel.send(file=discord.File(io.BytesIO(content), filename=safe_name))
    if not message.attachments:
        raise RuntimeError("Upload Discord sans pièce jointe")
    return message.attachments[0].url


def panel_price_value(field_name):
    raw = request.form.get(field_name, "").strip().replace(",", ".")
    try:
        value = round(float(raw), 2)
    except ValueError as error:
        raise ValueError(f"Prix invalide pour {field_name}") from error
    if not 0 < value <= 100000:
        raise ValueError(f"Le prix {field_name} doit être compris entre 0,01 et 100 000 €")
    return value


def panel_cost_value(field_name):
    raw = request.form.get(field_name, "").strip().replace(",", ".")
    try:
        value = round(float(raw), 2)
    except ValueError as error:
        raise ValueError(f"Coût invalide pour {field_name}") from error
    if not 0 <= value <= 100000:
        raise ValueError(f"Le coût {field_name} doit être compris entre 0 et 100 000 €")
    return value


def panel_percentage_value(field_name):
    raw = request.form.get(field_name, "").strip().replace(",", ".")
    try:
        value = round(float(raw), 2)
    except ValueError as error:
        raise ValueError("Pourcentage invalide") from error
    if not 0 <= value <= 100:
        raise ValueError("Le pourcentage doit être compris entre 0 et 100")
    return value


def log_price_embed_refresh(future):
    try:
        print(f"Prix enregistrés : {future.result()} panneau(x) Discord actualisé(s).")
    except Exception as error:
        print(f"Erreur actualisation automatique des embeds de prix : {error}")


@app.route("/panel/parrainage", methods=["GET", "POST"])
@panel_required
def panel_referrals():
    if request.method == "POST":
        if not valid_panel_csrf():
            flash("Session invalide. Recharge la page.")
            return redirect(url_for("panel_referrals"))
        try:
            code = normalize_referral_code(request.form.get("code"))
            if len(code) < 3:
                raise ValueError("Le code doit contenir au moins 3 caractères")
            sponsor_name = request.form.get("sponsor_name", "").strip()[:80]
            if not sponsor_name:
                raise ValueError("Le nom du parrain est obligatoire")
            sponsor_id = request.form.get("sponsor_id", "").strip()
            if sponsor_id and not re.fullmatch(r"\d{15,25}", sponsor_id):
                raise ValueError("L'ID Discord du parrain est invalide")
            percentage = panel_percentage_value("percentage")
            paid = panel_cost_value("paid")
            codes = get_referral_codes()
            previous = codes.get(code, {})
            codes[code] = {
                "code": code,
                "sponsor_name": sponsor_name,
                "sponsor_id": sponsor_id,
                "percentage": percentage,
                "paid": paid,
                "active": request.form.get("active") == "1",
                "created_at": previous.get("created_at") or datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            save_referral_codes(codes)
            flash(f"Code {code} enregistré à {percentage:g} % du bénéfice attribué.")
        except Exception as error:
            print(f"Erreur configuration parrainage : {error}")
            flash(f"Impossible d'enregistrer le code : {error}")
        return redirect(url_for("panel_referrals"))

    codes = get_referral_codes()
    ledgers = load_referral_ledgers()
    events = load_referral_events(ledgers)
    summaries = build_referral_summaries(codes, ledgers)
    return render_template_string(
        PANEL_REFERRALS_PROFIT_TEMPLATE,
        summaries=summaries,
        events=events[:200],
    )


@app.route("/panel/statistiques")
@panel_required
def panel_finances():
    month_key = normalize_finance_month(request.args.get("month"))
    orders = load_orders_for_stats(limit=10000)
    stats = calculate_month_finances(
        orders,
        month_key,
        purchase_cost_snapshots=load_order_purchase_costs(),
        purchase_costs=get_purchase_cost_config(),
    )
    return render_template_string(
        PANEL_FINANCES_NITRO_TEMPLATE,
        stats=stats,
        month_label=finance_month_label(month_key),
    )


@app.route("/panel/prix", methods=["GET", "POST"])
@panel_required
def panel_prices():
    if request.method == "POST":
        if not valid_panel_csrf():
            flash("Session invalide. Recharge la page.")
            return redirect(url_for("panel_prices"))
        try:
            pricing = {
                "gift_cards": {str(amount): panel_price_value(f"gift_{amount}") for amount in GIFT_CARD_AMOUNTS},
                "uber_eats": {pack_key: panel_price_value(f"uber_{pack_key}") for pack_key in UBEREATS_PACKS},
                "discord_nitro": panel_price_value("discord_nitro"),
                "valorant": {
                    region_key: {
                        pack_key: panel_price_value(f"valo_{region_key}_{pack_key}")
                        for pack_key in region["packs"]
                    }
                    for region_key, region in VALO_REGIONS.items()
                },
            }
            purchase_costs = {
                "gift_cards": {
                    product_key: {
                        str(amount): panel_cost_value(f"cost_gift_{product_key}_{amount}")
                        for amount in GIFT_CARD_AMOUNTS
                    }
                    for product_key in regular_gift_product_keys()
                },
                "uber_eats": {
                    pack_key: panel_cost_value(f"cost_uber_{pack_key}")
                    for pack_key in UBEREATS_PACKS
                },
                "discord_nitro": panel_cost_value("cost_discord_nitro"),
                "valorant": {
                    region_key: {
                        pack_key: panel_cost_value(f"cost_valo_{region_key}_{pack_key}")
                        for pack_key in region["packs"]
                    }
                    for region_key, region in VALO_REGIONS.items()
                },
            }
            set_panel_setting("purchase_costs", purchase_costs)
            set_panel_setting("pricing", pricing)
            if BOT_LOOP is not None:
                future = asyncio.run_coroutine_threadsafe(refresh_price_embeds_from_panel(), BOT_LOOP)
                future.add_done_callback(log_price_embed_refresh)
                flash("Prix et coûts d'achat enregistrés. Les débits, les statistiques et les panneaux Discord sont actualisés sans redémarrage.")
            else:
                flash("Prix et coûts d'achat enregistrés. Ils seront utilisés dès que le bot Discord sera connecté.")
        except Exception as error:
            print(f"Erreur mise à jour prix : {error}")
            flash(f"Impossible d'enregistrer les prix : {error}")
        return redirect(url_for("panel_prices"))

    pricing = get_pricing_config()
    purchase_costs = get_purchase_cost_config()
    gift_cards = [
        {"amount": amount, "price": format_price(pricing["gift_cards"][str(amount)])}
        for amount in GIFT_CARD_AMOUNTS
    ]
    uber_eats = [
        {"key": pack_key, "drop": pack["drop"], "price": format_price(pricing["uber_eats"][pack_key]), "cost": format_price(purchase_costs["uber_eats"][pack_key])}
        for pack_key, pack in UBEREATS_PACKS.items()
    ]
    gift_cost_products = [
        {
            "key": product_key,
            "display": PRODUCT_CONFIG[product_key]["display"],
            "amounts": [
                {"amount": amount, "cost": format_price(purchase_costs["gift_cards"][product_key][str(amount)])}
                for amount in GIFT_CARD_AMOUNTS
            ],
        }
        for product_key in regular_gift_product_keys()
    ]
    valorant = []
    for region_key, region in VALO_REGIONS.items():
        for pack_key, pack in region["packs"].items():
            valorant.append({
                "region_key": region_key,
                "region": region["label"],
                "pack_key": pack_key,
                "pack": pack["label"],
                "price": format_price(pricing["valorant"][region_key][pack_key]),
                "cost": format_price(purchase_costs["valorant"][region_key][pack_key]),
            })
    return render_template_string(
        PANEL_PRICES_COSTS_TEMPLATE,
        gift_cards=gift_cards,
        gift_cost_products=gift_cost_products,
        uber_eats=uber_eats,
        discord_nitro=format_price(pricing["discord_nitro"]),
        discord_nitro_cost=format_price(purchase_costs["discord_nitro"]),
        valorant=valorant,
    )


@app.route("/panel/stock", methods=["GET", "POST"])
@panel_required
def panel_stock():
    if request.method == "POST":
        if not valid_panel_csrf():
            flash("Session invalide. Recharge la page.")
            return redirect(url_for("panel_stock"))
        try:
            set_stock_available(
                request.form.get("kind", ""),
                request.form.get("key", ""),
                request.form.get("available") == "1",
                request.form.get("region") or None
            )
            flash("Stock mis à jour. Les prochains menus afficheront le nouvel état.")
        except Exception as error:
            print(f"Erreur mise à jour stock : {error}")
            flash("Impossible de mettre à jour ce stock.")
        return redirect(url_for("panel_stock"))
    stock = get_stock_config()
    pricing = get_pricing_config()
    products = [{"key": key, "display": cfg["display"], "available": stock["products"].get(key, True)} for key, cfg in PRODUCT_CONFIG.items() if key != "VALORANT"]
    valorant = []
    for region_key, region in VALO_REGIONS.items():
        for pack_key, pack in region["packs"].items():
            valorant.append({"region_key": region_key, "region": region["label"], "pack_key": pack_key, "price": format_price(pricing["valorant"][region_key][pack_key]), "pack": pack["label"], "available": stock["valorant"].get(region_key, {}).get(pack_key, True)})
    return render_template_string(PANEL_STOCK_TEMPLATE, products=products, valorant=valorant, ok_emoji=STOCK_OK_EMOJI, ko_emoji=STOCK_KO_EMOJI)


@app.route("/panel/embeds", methods=["GET", "POST"])
@panel_required
def panel_embeds():
    if request.method == "POST":
        if not valid_panel_csrf():
            flash("Session invalide. Recharge la page.")
            return redirect(url_for("panel_embeds"))
        embed_key = request.form.get("embed_key", "").strip()
        try:
            embed_data = json.loads(request.form.get("embed_json", "{}"))
            if not isinstance(embed_data, dict):
                raise ValueError("Le contenu doit être un objet JSON")
            image_file = request.files.get("image_file")
            if image_file and image_file.filename:
                if BOT_LOOP is None:
                    raise RuntimeError("Bot Discord pas encore prêt pour l'upload")
                image_url = asyncio.run_coroutine_threadsafe(
                    upload_panel_image_to_discord(image_file.filename, image_file.read()),
                    BOT_LOOP
                ).result(timeout=30)
                embed_data["image_url"] = image_url
            overrides = get_panel_setting("embed_overrides", {}) or {}
            if not isinstance(overrides, dict):
                overrides = {}
            overrides[embed_key] = embed_data
            set_panel_setting("embed_overrides", overrides)
            flash(f"Embed {embed_key} enregistré. Utilise /maj_embed pour mettre à jour les messages déjà postés.")
        except Exception as error:
            print(f"Erreur sauvegarde embed {embed_key}: {error}")
            flash(f"Sauvegarde impossible : {error}")
        return redirect(url_for("panel_embeds"))
    data = load_embed_texts()
    embeds = []
    for key in sorted(k for k, value in data.items() if isinstance(value, dict)):
        embeds.append({"key": key, "json": json.dumps(data[key], ensure_ascii=False, indent=2)})
    return render_template_string(PANEL_EMBEDS_TEMPLATE, embeds=embeds)


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
    finish_description_raw = finish_data.get("description", [])
    finish_description = "\n".join(finish_description_raw) if isinstance(finish_description_raw, list) else str(finish_description_raw or "")
    updated = discord.Embed(
        title=finish_data.get("title", old.title),
        description=finish_description or old.description,
        color=discord.Color.from_rgb(*rgb),
    )
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
        return panel_filter_redirect()
    order = None
    try:
        if USE_SUPABASE:
            rows = supabase_request("GET", f"orders?id=eq.{order_id}&select=guild_id,user_id,message_id") or []
            order = rows[0] if rows else None
            if order is None:
                raise RuntimeError("Commande introuvable")
            deleted = supabase_request("DELETE", f"orders?id=eq.{order_id}", prefer="return=representation")
            if not deleted:
                raise RuntimeError("Aucune ligne supprimée. Vérifie que SUPABASE_SECRET_KEY est bien une clé secrète et non la clé publishable/anon.")
        else:
            with db_connect() as db:
                row = db.execute("SELECT guild_id,user_id,message_id FROM orders WHERE id=?", (order_id,)).fetchone()
                order = dict(row) if row else None
                if order is None:
                    raise RuntimeError("Commande introuvable")
                cursor = db.execute("DELETE FROM orders WHERE id=?", (order_id,))
                if cursor.rowcount == 0:
                    raise RuntimeError("Commande introuvable")
    except Exception as error:
        print(f"Erreur suppression commande {order_id}: {error}")
        flash("La suppression a échoué.")
        return panel_filter_redirect()
    try:
        referral_sync = remove_referral_purchase(order["guild_id"], order["user_id"], order["message_id"])
        removed_commission = referral_sync["commission"]
        if referral_sync["events"]:
            flash(
                f"Commande supprimée du panel et commission parrain retirée "
                f"({removed_commission:.2f} €). Les numéros ont été recalculés."
            )
        else:
            flash("Commande supprimée du panel. Les numéros ont été recalculés.")
    except Exception as error:
        print(f"Erreur synchronisation parrainage après suppression commande {order_id}: {error}")
        flash("Commande supprimée, mais la synchronisation du parrainage a échoué.")
    return panel_filter_redirect()


@app.post("/panel/orders/<int:order_id>/code")
@panel_required
def panel_set_code(order_id):
    if not valid_panel_csrf():
        flash("Session invalide. Recharge la page.")
        return panel_filter_redirect()
    code = request.form.get("code", "").strip()
    if USE_SUPABASE:
        rows = supabase_request("GET", f"orders?id=eq.{order_id}&select=*")
        order = rows[0] if rows else None
    else:
        with db_connect() as db:
            order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order or not code:
        flash("Commande ou code invalide.")
        return panel_filter_redirect()
    if BOT_LOOP is None:
        flash("Le bot Discord n'est pas encore prêt.")
        return panel_filter_redirect()
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
    return panel_filter_redirect()



@bot.hybrid_command(name="config_compteurs", description="Configurer le salon des avis vérifiés")
@discord.app_commands.default_permissions(administrator=True)
@discord.app_commands.describe(avis_channel="Salon réservé aux avis vérifiés")
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def cmd_config_compteurs(ctx, avis_channel: discord.TextChannel):
    data = get_server_counter_data(ctx.guild.id)
    data["reviews_channel_id"] = avis_channel.id
    data.pop("verified_reviews_count", None)
    save_server_counter_data(ctx.guild.id, data)
    schedule_server_counter_refresh(ctx.guild, refresh_reviews=True)
    await ctx.send(
        f"✅ Le compteur des avis vérifiés utilise maintenant {avis_channel.mention}. "
        "Les salons statistiques seront actualisés dans quelques secondes.",
        ephemeral=True,
    )


@bot.hybrid_command(name="giveaway", aliases=["gw"], description="Créer un giveaway avec bouton de participation")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.describe(
    duration="Durée, par exemple 30m, 2h ou 1d",
    nom="Nom du giveaway",
    invitations="Nombre minimum d'invitations actives requis",
    tag_serveur="Exiger que le membre affiche le tag de ce serveur",
    image_url="Lien direct d'une image optionnelle",
)
@commands.guild_only()
@commands.has_role(STAFF_ROLE_ID)
async def cmd_giveaway(
    ctx,
    duration: str,
    nom: str,
    invitations: int = 0,
    tag_serveur: bool = False,
    image_url: str = "",
):
    seconds = parse_giveaway_duration(duration)
    if not seconds or seconds < 10:
        await ctx.send("❌ Durée invalide. Exemple : `/giveaway duration:2h nom:Nitro invitations:2 tag_serveur:Oui`.", delete_after=8)
        return
    if seconds > 60 * 60 * 24 * 30:
        await ctx.send("❌ Durée trop longue. Maximum : 30 jours.", delete_after=8)
        return
    if invitations < 0 or invitations > 1000:
        await ctx.send("❌ Le nombre d'invitations requis doit être compris entre 0 et 1000.", ephemeral=True)
        return
    if tag_serveur and not hasattr(discord.Member, "primary_guild"):
        await ctx.send("❌ La vérification du tag serveur nécessite discord.py 2.6 ou plus récent.", ephemeral=True)
        return
    image_url = (image_url or "").strip()
    if not image_url and getattr(ctx, "message", None) and ctx.message.attachments:
        image_url = ctx.message.attachments[0].url
    end_ts = int(time.time()) + seconds
    embed = build_giveaway_embed(
        nom,
        end_ts,
        0,
        image_url,
        min_invites=invitations,
        require_server_tag=tag_serveur,
    )
    message = await ctx.send(embed=embed, view=GiveawayJoinView())
    save_giveaway(message.id, {
        "guild_id": ctx.guild.id if ctx.guild else 0,
        "channel_id": message.channel.id,
        "message_id": message.id,
        "name": nom,
        "image_url": image_url,
        "end_ts": end_ts,
        "min_invites": invitations,
        "require_server_tag": tag_serveur,
        "participants": [],
        "ended": False,
        "created_at": utc_now().isoformat()
    })
    asyncio.create_task(finish_giveaway_later(message.id, seconds))


@bot.hybrid_command(name="reroll", description="Tirer un nouveau gagnant pour un giveaway terminé")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.describe(message_id="ID ou lien du message du giveaway (facultatif si tu réponds au message)")
@commands.guild_only()
@commands.has_role(STAFF_ROLE_ID)
async def cmd_reroll(ctx, message_id: str = ""):
    giveaway_message_id = parse_giveaway_message_id(message_id)
    if giveaway_message_id is None and getattr(ctx, "message", None):
        reference = getattr(ctx.message, "reference", None)
        giveaway_message_id = getattr(reference, "message_id", None)
    if giveaway_message_id is None:
        await ctx.send(
            "❌ Indique l'ID ou le lien du message du giveaway, ou réponds au message avec `!reroll`.",
            ephemeral=True,
        )
        return

    data = load_giveaway(giveaway_message_id)
    if not data:
        await ctx.send("❌ Giveaway introuvable.", ephemeral=True)
        return
    if not data.get("ended"):
        await ctx.send("❌ Ce giveaway n'est pas encore terminé.", ephemeral=True)
        return

    stored_guild_id = int(data.get("guild_id") or 0)
    if ctx.guild is None or (stored_guild_id and stored_guild_id != ctx.guild.id):
        await ctx.send("❌ Ce giveaway n'appartient pas à ce serveur.", ephemeral=True)
        return

    participants = normalize_giveaway_participants(data.get("participants", []))
    if not participants:
        await ctx.send("❌ Impossible de reroll : aucun participant enregistré.", ephemeral=True)
        return
    eligible_participants, rejected = await eligible_giveaway_participants(ctx.guild, data)
    if not eligible_participants:
        await ctx.send(
            "❌ Impossible de reroll : aucun participant ne remplit encore toutes les conditions.",
            ephemeral=True,
        )
        return

    winner_history = normalize_giveaway_participants(data.get("winner_history", []))
    current_winner_id = data.get("winner_id")
    if current_winner_id is not None:
        try:
            current_winner_id = int(current_winner_id)
        except (TypeError, ValueError):
            current_winner_id = None
    if current_winner_id and current_winner_id not in winner_history:
        winner_history.append(current_winner_id)

    winner_id = select_giveaway_winner(eligible_participants, winner_history)
    winner_text = f"<@{winner_id}>"
    data["winner_id"] = winner_id
    data["winner_history"] = [*winner_history, winner_id]
    data["rerolled_at"] = utc_now().isoformat()
    data["rerolled_by"] = ctx.author.id

    channel_id = int(data.get("channel_id") or 0)
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        message = await channel.fetch_message(giveaway_message_id)
        save_giveaway(giveaway_message_id, data)
        await message.edit(
            embed=build_saved_giveaway_embed(data, len(participants), ended=True, winner=winner_text),
            view=None,
        )
        excluded_text = f" · **{len(rejected)}** participation(s) non éligible(s) écartée(s)" if rejected else ""
        await channel.send(
            f"🔄 Nouveau tirage pour le giveaway **{data.get('name', 'Giveaway')}** ! "
            f"Nouveau gagnant : {winner_text}{excluded_text}"
        )
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as error:
        print(f"Erreur reroll giveaway {giveaway_message_id}: {error}")
        await ctx.send("❌ Impossible de retrouver ou modifier le message du giveaway.", ephemeral=True)


@bot.hybrid_command(name="reglement", description="Publier le règlement PinkGift")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_reglement(ctx):
    await ctx.send(embed=build_json_embed("rules_embed"))


@bot.hybrid_command(name="faq", description="Publier la FAQ PinkGift")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_faq(ctx):
    await ctx.send(embed=build_json_embed("faq_embed"))


@bot.hybrid_command(name="classement", description="Publier le classement clients PinkGift")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_classement(ctx):
    await ctx.send(embed=build_leaderboard_embed())


@bot.hybrid_command(name="autoriser_serveur", description="Autoriser ce serveur à utiliser PinkSoftware")
@discord.app_commands.default_permissions(administrator=True)
@discord.app_commands.describe(cle="Clé privée configurée dans BOT_AUTH_KEY")
async def cmd_autoriser_serveur(ctx, cle: str):
    if not guild_authorization_enabled():
        await ctx.send("ℹ️ Protection désactivée : ajoute BOT_AUTH_KEY dans Render pour l'activer.", ephemeral=True)
        return
    if not ctx.guild:
        await ctx.send("❌ Cette commande doit être exécutée dans un serveur.", ephemeral=True)
        return
    is_admin = getattr(getattr(ctx, "author", None), "guild_permissions", None) and ctx.author.guild_permissions.administrator
    if not is_admin:
        await ctx.send("❌ Seul un administrateur peut autoriser ce serveur.", ephemeral=True)
        return
    if not secrets.compare_digest(str(cle), BOT_AUTH_KEY):
        await ctx.send("❌ Clé d'autorisation invalide.", ephemeral=True)
        return
    add_authorized_guild(ctx.guild.id)
    schedule_server_counter_refresh(ctx.guild, refresh_reviews=True)
    await ctx.send("✅ Serveur autorisé. PinkSoftware restera ici.", ephemeral=True)

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
            DISCORD_LAST_ERROR = ""
            DISCORD_STATE = "connexion à la passerelle Discord"
            bot.run(token_discord, reconnect=True)
            DISCORD_STATE = "déconnecté"
            return
        except discord.LoginFailure:
            DISCORD_STATE = "token invalide"
            DISCORD_LAST_ERROR = "Discord refuse le token."
            print(DISCORD_LAST_ERROR)
            return
        except discord.HTTPException as error:
            status = getattr(error, "status", None)
            if status == 429:
                wait_seconds = 900
                DISCORD_STATE = f"bloqué par Discord, nouvel essai dans {wait_seconds // 60} min"
                DISCORD_LAST_ERROR = "Discord 429 Too Many Requests"
                print(f"{DISCORD_LAST_ERROR}. Nouvel essai dans {wait_seconds} secondes.")
                time.sleep(wait_seconds)
                continue
            DISCORD_STATE = "nouvel essai dans 1 min"
            DISCORD_LAST_ERROR = f"Discord HTTP {status or 'inconnu'}"
            print(f"Connexion Discord impossible : {DISCORD_LAST_ERROR}")
            time.sleep(60)
        except Exception as error:
            DISCORD_STATE = "nouvel essai dans 1 min"
            DISCORD_LAST_ERROR = str(error)[:200]
            print(f"Connexion Discord impossible : {DISCORD_LAST_ERROR}")
            time.sleep(60)

def start_discord_background():
    global DISCORD_THREAD_STARTED
    if DISCORD_THREAD_STARTED:
        return
    DISCORD_THREAD_STARTED = True
    if DISCORD_ENABLED:
        Thread(target=run_discord, daemon=True).start()
    else:
        print("Connexion Discord désactivée par DISCORD_ENABLED=false")


@app.before_request
def ensure_discord_background_started():
    start_discord_background()

if __name__ == "__main__":
    # Démarre Discord immédiatement. Auparavant, le bot ne se lançait qu'après
    # la première requête HTTP reçue par Flask, ce qui pouvait laisser les
    # boutons inactifs après un redémarrage du service.
    start_discord_background()
    run_web()
