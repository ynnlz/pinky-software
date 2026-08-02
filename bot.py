import discord
from discord.ext import commands
from flask import Flask, request, session, redirect, url_for, render_template_string, flash
from threading import Lock, Thread
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
import unicodedata
from decimal import Decimal, InvalidOperation
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
            CPOrderLauncherView(),
            OtherServicesView(),
            CPPendingOrderView(),
            PendingOrderActionsView(),
            BalanceView(),
            ReferralApplicationView(),
            RecruitmentApplicationView(),
            PrivilegesLauncherView(),
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
ORDER_REFUND_LOCK = Lock()
INVITE_USAGE_CACHE = {}
INVITE_TRACKING_LOCKS = {}
RECENTLY_DELETED_INVITES = {}
DISCORD_THREAD_STARTED = False
COMMAND_SYNC_DONE = False
PUBLIC_VIEWS_REPAIRED = False
DECORATION_ACCESS_REPAIRED = False
SERVER_COUNTER_REFRESH_TASK = None
SERVER_COUNTER_UPDATE_TASKS = {}
SERVER_COUNTER_UPDATE_FLAGS = {}
SERVER_COUNTER_LOCKS = {}
SERVER_COUNTER_REFRESH_SECONDS = 900
SERVER_COUNTER_INITIAL_DELAY_SECONDS = 60
SERVER_COUNTER_RATE_LIMIT_BACKOFF_SECONDS = 900
SERVER_COUNTER_BACKOFF_UNTIL = 0.0
SERVER_COUNTER_CATEGORY_NAME = "📊・STATISTIQUES"
MUTED_ROLE_ID = 1525614378580312165
CUSTOMER_ROLE_ID = 1517607603323011152
TOP_CUSTOMER_ROLE_ID = 1525605483648516207
CUSTOMER_SPENDING_ROLE_THRESHOLDS = (
    (50.0, 1525604775947927832),
    (150.0, 1525604775146553486),
    (300.0, 1517580949532053735),
    (500.0, 1525604774341513296),
    (1000.0, 1525604773854970027),
    (2000.0, 1525604772487630858),
)
CUSTOMER_ROLES_SYNCED = False
CUSTOMER_ROLE_SYNC_LOCKS = {}
AUTO_REACTION_CHANNEL_IDS = {1525601407825084436, 1517525842111234088}
AUTO_REACTION_EMOJIS = ("<:verify:1525796690899108000>", "<:waylaylove:1517582297736413284>")
VERIFIED_REVIEWS_CHANNEL_IDS = {1525601407825084436, 1517525842111234088}
REFERRAL_TRACKING_CHANNEL_ID = 1525601870561935391
MEMBER_ACTIVITY_CHANNEL_ID = 1525601870561935391
DISCORD_DECORATION_ACCESS_USER_IDS = set()
DISCORD_DECORATION_REVOKED_USER_IDS = {1518303260178649328}
ANTI_RAID_CONFIG_CACHE = {}
ANTI_RAID_RECENT_JOINS = {}
ANTI_RAID_LOCKS = {}
MIN_INVITE_ACCOUNT_AGE_DAYS = 30
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
        if updated < 0: raise ValueError("PinkCoins insuffisants")
        db.execute("INSERT INTO balances(guild_id,user_id,cents) VALUES(?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET cents=excluded.cents", (guild_id, user_id, updated))
        db.execute("INSERT INTO balance_history(guild_id,user_id,delta_cents,staff_id) VALUES(?,?,?,?)", (guild_id, user_id, delta_cents, staff_id))
        return updated / 100


def customer_deposit_role_ids(total_added):
    """Rôles cumulés correspondant aux euros réellement déposés par le client."""
    try:
        total_added = max(0.0, float(total_added or 0))
    except (TypeError, ValueError):
        total_added = 0.0
    role_ids = {CUSTOMER_ROLE_ID} if total_added > 0 else set()
    role_ids.update(
        role_id
        for threshold, role_id in CUSTOMER_SPENDING_ROLE_THRESHOLDS
        if total_added >= threshold
    )
    return role_ids


def customer_highest_tier(total_added):
    try:
        total_added = max(0.0, float(total_added or 0))
    except (TypeError, ValueError):
        total_added = 0.0
    reached = [
        (threshold, role_id)
        for threshold, role_id in CUSTOMER_SPENDING_ROLE_THRESHOLDS
        if total_added >= threshold
    ]
    if not reached:
        return {"threshold": 0.0, "role_id": CUSTOMER_ROLE_ID if total_added > 0 else 0, "label": "Client" if total_added > 0 else "Aucun"}
    threshold, role_id = reached[-1]
    return {"threshold": threshold, "role_id": role_id, "label": f"{threshold:,.0f} €+".replace(",", " ")}


def stored_discord_bot_user_id():
    current_id = int(getattr(getattr(bot, "user", None), "id", 0) or 0)
    if current_id:
        return current_id
    try:
        return int(get_panel_setting("discord_bot_user_id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def get_customer_deposit_totals(guild_id):
    """Calcule les dépôts staff nets, retraits compris, sans les achats/remboursements du bot."""
    guild_id = int(guild_id)
    bot_user_id = stored_discord_bot_user_id()
    totals_cents = {}
    if USE_SUPABASE:
        offset = 0
        page_size = 1000
        while True:
            rows = supabase_request(
                "GET",
                f"balance_history?guild_id=eq.{guild_id}"
                f"&select=id,user_id,delta_cents,staff_id&order=id.asc&limit={page_size}&offset={offset}",
            ) or []
            for row in rows:
                try:
                    user_id = int(row.get("user_id") or 0)
                    staff_id = int(row.get("staff_id") or 0)
                    delta_cents = int(row.get("delta_cents") or 0)
                except (TypeError, ValueError):
                    continue
                if user_id <= 0 or (bot_user_id and staff_id == bot_user_id):
                    continue
                totals_cents[user_id] = totals_cents.get(user_id, 0) + delta_cents
            if len(rows) < page_size:
                break
            offset += page_size
    else:
        query = "SELECT user_id, SUM(delta_cents) AS total_cents FROM balance_history WHERE guild_id=?"
        params = [guild_id]
        if bot_user_id:
            query += " AND (staff_id IS NULL OR staff_id<>?)"
            params.append(bot_user_id)
        query += " GROUP BY user_id"
        with db_connect() as db:
            rows = db.execute(query, params).fetchall()
        for row in rows:
            try:
                totals_cents[int(row["user_id"])] = max(0, int(row["total_cents"] or 0))
            except (TypeError, ValueError):
                continue
    return {
        user_id: round(max(0, cents) / 100, 2)
        for user_id, cents in totals_cents.items()
        if cents > 0
    }


def remove_customer_net_deposit(guild_id, user_id, amount, staff_id):
    """Corrige les dépôts nets historiques sans modifier le PinkWallet."""
    guild_id = int(guild_id)
    user_id = int(user_id)
    staff_id = int(staff_id)
    amount_cents = round(float(amount) * 100)
    if amount_cents <= 0:
        raise ValueError("Le montant à retirer doit être positif")

    current_amount = get_customer_deposit_totals(guild_id).get(user_id, 0.0)
    current_cents = round(float(current_amount) * 100)
    if amount_cents > current_cents:
        raise ValueError(
            f"Le client possède seulement {current_amount:.2f} € de dépôts nets"
        )

    values = {
        "guild_id": guild_id,
        "user_id": user_id,
        "delta_cents": -amount_cents,
        "staff_id": staff_id,
    }
    if USE_SUPABASE:
        supabase_request("POST", "balance_history", values, "return=minimal")
    else:
        with db_connect() as db:
            db.execute(
                "INSERT INTO balance_history(guild_id,user_id,delta_cents,staff_id) VALUES(?,?,?,?)",
                (guild_id, user_id, -amount_cents, staff_id),
            )
    return round((current_cents - amount_cents) / 100, 2)


NON_REVENUE_ORDER_STATUSES = {
    "cancelled", "canceled", "annule", "annulé",
    "refunded", "refunding", "rembourse", "remboursé",
    "failed", "rejected", "void",
}


def order_counts_as_purchase(order):
    status = str(order.get("status") or "pending").strip().lower()
    if status in NON_REVENUE_ORDER_STATUSES:
        return False
    try:
        return float(order.get("paid") or 0) > 0
    except (TypeError, ValueError):
        return False


def get_customer_spending_totals(guild_id, orders=None):
    totals = {}
    for order in orders if orders is not None else load_orders_for_stats():
        try:
            if int(order.get("guild_id") or 0) != int(guild_id) or not order_counts_as_purchase(order):
                continue
            user_id = int(order.get("user_id") or 0)
            paid = float(order.get("paid") or 0)
        except (TypeError, ValueError):
            continue
        if user_id > 0:
            totals[user_id] = round(totals.get(user_id, 0.0) + paid, 2)
    return totals


def customer_top_user_id(guild, spending_totals):
    candidates = [
        (float(total), int(user_id))
        for user_id, total in (spending_totals or {}).items()
        if float(total or 0) > 0 and guild.get_member(int(user_id)) is not None
    ]
    if not candidates:
        return None
    highest_total = max(total for total, _ in candidates)
    return min(user_id for total, user_id in candidates if total == highest_total)


async def sync_customer_roles(
    guild,
    target_user_id=None,
    deposit_totals=None,
    spending_totals=None,
    target_member=None,
):
    """Sérialise les mises à jour afin qu'une ancienne suppression ne gagne pas sur une nouvelle vente."""
    if guild is None:
        return await _sync_customer_roles_unlocked(
            guild,
            target_user_id,
            deposit_totals,
            spending_totals,
            target_member,
        )
    lock = CUSTOMER_ROLE_SYNC_LOCKS.setdefault(int(guild.id), asyncio.Lock())
    async with lock:
        return await _sync_customer_roles_unlocked(
            guild,
            target_user_id,
            deposit_totals,
            spending_totals,
            target_member,
        )


async def _sync_customer_roles_unlocked(
    guild,
    target_user_id=None,
    deposit_totals=None,
    spending_totals=None,
    target_member=None,
):
    """Synchronise les paliers de dépôts nets et le rôle du meilleur acheteur."""
    if guild is None:
        return {
            "total_added": 0.0,
            "total_spent": 0.0,
            "tier": customer_highest_tier(0),
            "is_top": False,
            "errors": ["Serveur Discord introuvable"],
        }
    deposit_totals = deposit_totals if isinstance(deposit_totals, dict) else get_customer_deposit_totals(guild.id)
    spending_totals = spending_totals if isinstance(spending_totals, dict) else get_customer_spending_totals(guild.id)
    leader_id = customer_top_user_id(guild, spending_totals)
    managed_tier_ids = {CUSTOMER_ROLE_ID, *(role_id for _, role_id in CUSTOMER_SPENDING_ROLE_THRESHOLDS)}
    sync_errors = []

    if target_user_id is None:
        target_ids = set(deposit_totals)
        for role_id in managed_tier_ids:
            role = guild.get_role(role_id)
            if role is not None:
                target_ids.update(member.id for member in role.members)
    else:
        target_ids = {int(target_user_id)}
    if leader_id:
        target_ids.add(leader_id)

    for user_id in target_ids:
        member = target_member if target_member is not None and int(target_member.id) == int(user_id) else guild.get_member(int(user_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(user_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as error:
                if int(user_id) == int(target_user_id or 0):
                    sync_errors.append(f"Membre Discord introuvable ou inaccessible ({error})")
                continue
        if member.bot:
            continue
        desired_ids = customer_deposit_role_ids(deposit_totals.get(int(user_id), 0))
        current_ids = {role.id for role in member.roles}
        missing_role_ids = [role_id for role_id in desired_ids if guild.get_role(role_id) is None]
        if missing_role_ids and int(user_id) == int(target_user_id or 0):
            sync_errors.append(
                "Rôle(s) Discord configuré(s) introuvable(s) : "
                + ", ".join(str(role_id) for role_id in sorted(missing_role_ids))
            )
        roles_to_add = [guild.get_role(role_id) for role_id in desired_ids - current_ids]
        roles_to_remove = [guild.get_role(role_id) for role_id in (current_ids & managed_tier_ids) - desired_ids]
        roles_to_add = [role for role in roles_to_add if role is not None]
        roles_to_remove = [role for role in roles_to_remove if role is not None]
        bot_member = getattr(guild, "me", None)
        permissions = getattr(bot_member, "guild_permissions", None)
        if (roles_to_add or roles_to_remove) and permissions is not None and not (
            getattr(permissions, "administrator", False)
            or getattr(permissions, "manage_roles", False)
        ):
            if int(user_id) == int(target_user_id or 0):
                sync_errors.append("Le bot n'a pas la permission Gérer les rôles")
            continue
        manageable_add = []
        manageable_remove = []
        for role, destination in (
            *((role, manageable_add) for role in roles_to_add),
            *((role, manageable_remove) for role in roles_to_remove),
        ):
            if getattr(role, "managed", False):
                if int(user_id) == int(target_user_id or 0):
                    sync_errors.append(f"Le rôle {role.id} est géré par une intégration")
                continue
            if bot_member is not None and role >= bot_member.top_role:
                if int(user_id) == int(target_user_id or 0):
                    sync_errors.append(f"Le rôle {role.id} est placé au-dessus du rôle du bot")
                continue
            destination.append(role)
        try:
            if manageable_add:
                await member.add_roles(*manageable_add, reason="Palier de dépôts PinkGift atteint")
            if manageable_remove:
                await member.remove_roles(*manageable_remove, reason="Synchronisation des paliers PinkGift")
        except discord.HTTPException as error:
            print(f"Erreur synchronisation rôles client {user_id}: {error}")
            if int(user_id) == int(target_user_id or 0):
                sync_errors.append(f"Discord a refusé la modification des rôles ({error})")

    top_role = guild.get_role(TOP_CUSTOMER_ROLE_ID)
    if top_role is not None:
        for member in list(top_role.members):
            if member.id != leader_id:
                try:
                    await member.remove_roles(top_role, reason="Nouveau meilleur client PinkGift")
                except discord.HTTPException as error:
                    print(f"Erreur retrait rôle meilleur client {member.id}: {error}")
                    if member.id == int(target_user_id or 0):
                        sync_errors.append(f"Impossible de retirer le rôle meilleur client ({error})")
        leader = guild.get_member(leader_id) if leader_id else None
        if leader is not None and top_role not in leader.roles:
            try:
                await leader.add_roles(top_role, reason="Meilleur total d'achats PinkGift")
            except discord.HTTPException as error:
                print(f"Erreur attribution rôle meilleur client {leader.id}: {error}")
                if leader.id == int(target_user_id or 0):
                    sync_errors.append(f"Impossible d'attribuer le rôle meilleur client ({error})")

    target_id = int(target_user_id or 0)
    total_added = float(deposit_totals.get(target_id, 0) or 0)
    return {
        "total_added": total_added,
        "total_spent": float(spending_totals.get(target_id, 0) or 0),
        "tier": customer_highest_tier(total_added),
        "is_top": bool(target_id and target_id == leader_id),
        "errors": sync_errors,
    }


def schedule_customer_role_sync(guild_id, target_user_id=None):
    loop = BOT_LOOP
    if loop is None or not loop.is_running():
        return None

    async def run_sync():
        guild = bot.get_guild(int(guild_id))
        if guild is not None:
            await sync_customer_roles(guild, target_user_id)

    future = asyncio.run_coroutine_threadsafe(run_sync(), loop)

    def log_sync_error(done):
        try:
            result = done.result()
            errors = result.get("errors", []) if isinstance(result, dict) else []
            if errors:
                print("Erreur recalcul automatique des rôles clients : " + " ; ".join(errors))
        except Exception as error:
            print(f"Erreur recalcul automatique des rôles clients : {error}")

    future.add_done_callback(log_sync_error)
    return future


def sync_customer_roles_from_panel(guild_id, target_user_id=None, timeout=25):
    """Attend la réponse Discord afin que le panel ne confirme jamais une fausse synchronisation."""
    loop = BOT_LOOP
    if loop is None or not loop.is_running():
        raise RuntimeError("Le bot Discord n'est pas connecté")

    async def run_sync():
        guild = bot.get_guild(int(guild_id))
        if guild is None:
            raise RuntimeError("Serveur Discord introuvable")
        return await sync_customer_roles(guild, target_user_id)

    result = asyncio.run_coroutine_threadsafe(run_sync(), loop).result(timeout=timeout)
    errors = result.get("errors", []) if isinstance(result, dict) else []
    if errors:
        raise RuntimeError(" ; ".join(str(error) for error in errors))
    return result


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


def delete_panel_setting(key):
    if USE_SUPABASE:
        safe_key = urllib.parse.quote(str(key), safe="")
        deleted = supabase_request(
            "DELETE",
            f"panel_settings?key=eq.{safe_key}",
            prefer="return=representation",
        )
        return bool(deleted)
    with db_connect() as db:
        cursor = db.execute("DELETE FROM panel_settings WHERE key=?", (key,))
        return cursor.rowcount > 0


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


def purge_referral_code_data(value):
    """Efface définitivement toutes les données internes associées à un code."""
    code = normalize_referral_code(value)
    result = {
        "ledgers": 0,
        "lots": 0,
        "events": 0,
        "commission": 0.0,
        "tickets": 0,
        "notifications": 0,
        "notification_messages": [],
    }
    for ledger in load_referral_ledgers():
        lots = ledger.get("lots", [])
        events = ledger.get("events", [])
        removed_lots = [
            lot for lot in lots
            if isinstance(lot, dict) and normalize_referral_code(lot.get("code")) == code
        ]
        kept_lots = [
            lot for lot in lots
            if not isinstance(lot, dict) or normalize_referral_code(lot.get("code")) != code
        ]
        removed_events = [
            event for event in events
            if isinstance(event, dict) and normalize_referral_code(event.get("code")) == code
        ]
        kept_events = [
            event for event in events
            if not isinstance(event, dict) or normalize_referral_code(event.get("code")) != code
        ]
        removed_lots_count = len(removed_lots)
        if not removed_lots_count and not removed_events:
            continue
        result["ledgers"] += 1
        result["lots"] += removed_lots_count
        result["events"] += len(removed_events)
        for lot in removed_lots:
            try:
                channel_id = int(lot.get("notification_channel_id") or 0)
                message_id = int(lot.get("notification_message_id") or 0)
            except (TypeError, ValueError):
                continue
            if channel_id and message_id:
                result["notification_messages"].append({"channel_id": channel_id, "message_id": message_id})
                result["notifications"] += 1
        for event in removed_events:
            try:
                result["commission"] += float(event.get("commission") or 0)
            except (TypeError, ValueError):
                pass
        guild_id = ledger["guild_id"]
        user_id = ledger["user_id"]
        if kept_lots or kept_events:
            save_referral_ledger(guild_id, user_id, {"lots": kept_lots, "events": kept_events})
        else:
            delete_panel_setting(referral_ledger_setting_key(guild_id, user_id))

    for item in list_panel_settings("balance_referral:"):
        data = item.get("value")
        if not isinstance(data, dict) or normalize_referral_code(data.get("code")) != code:
            continue
        if delete_panel_setting(item.get("key")):
            result["tickets"] += 1
    result["commission"] = round(result["commission"], 2)
    return result


def build_referral_summaries(codes, ledgers):
    summaries = {}
    for code, data in codes.items():
        summaries[code] = {
            **data,
            "configured": True,
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
                "paid": 0.0, "active": False, "configured": False, "created_at": "", "uses": 0, "_orders": set(),
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
            "paid": 0.0, "active": False, "configured": False, "created_at": "", "uses": 0, "_orders": set(),
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


def discord_account_created_ts(user_id: int) -> float:
    """Retrouve la date de création publique contenue dans l'identifiant Discord."""
    try:
        return (((int(user_id) >> 22) + 1420070400000) / 1000)
    except (TypeError, ValueError):
        return 0.0


def invite_account_age_days(member: discord.Member, reference_ts=None) -> int:
    reference_ts = float(reference_ts or time.time())
    created_ts = member.created_at.timestamp() if getattr(member, "created_at", None) else discord_account_created_ts(member.id)
    return max(0, int((reference_ts - created_ts) // 86400)) if created_ts > 0 else 0


def tracked_invite_is_eligible(member_id, member_data, min_age_days=MIN_INVITE_ACCOUNT_AGE_DAYS) -> bool:
    if not isinstance(member_data, dict) or member_data.get("eligible") is False:
        return False
    try:
        joined_ts = float(member_data.get("first_joined_ts") or member_data.get("joined_ts") or 0)
        created_ts = float(member_data.get("account_created_ts") or 0)
    except (TypeError, ValueError):
        return False
    if created_ts <= 0:
        created_ts = discord_account_created_ts(member_id)
    if joined_ts <= 0:
        try:
            joined_ts = datetime.datetime.fromisoformat(
                str(member_data.get("joined_at") or "").replace("Z", "+00:00")
            ).timestamp()
        except (TypeError, ValueError):
            return False
    return created_ts > 0 and joined_ts - created_ts >= max(1, int(min_age_days)) * 86400


def get_invite_tracking_data(guild_id: int) -> dict:
    data = get_panel_setting(invite_setting_key(guild_id), {}) or {}
    if not isinstance(data, dict):
        data = {}
    inviters = data.get("inviters")
    members = data.get("members")
    reset_blocked_members = data.get("reset_blocked_members")
    if not isinstance(inviters, dict):
        inviters = {}
    if not isinstance(members, dict):
        members = {}
    if not isinstance(reset_blocked_members, dict):
        reset_blocked_members = {}
    return {
        "inviters": inviters,
        "members": members,
        "reset_blocked_members": reset_blocked_members,
    }


def save_invite_tracking_data(guild_id: int, data: dict) -> None:
    set_panel_setting(invite_setting_key(guild_id), data)


def reset_invite_tracking_data(guild_id: int, inviter_id=None) -> dict:
    data = get_invite_tracking_data(guild_id)
    target_id = int(inviter_id) if inviter_id is not None else None
    previous_total = 0
    previous_active = 0
    affected_members = 0

    if target_id is None:
        for stats in data["inviters"].values():
            if not isinstance(stats, dict):
                continue
            previous_total += max(0, int(stats.get("total", 0) or 0))
            previous_active += max(0, int(stats.get("active", 0) or 0))
        data["inviters"] = {}
    else:
        stats = data["inviters"].pop(str(target_id), {})
        if isinstance(stats, dict):
            previous_total = max(0, int(stats.get("total", 0) or 0))
            previous_active = max(0, int(stats.get("active", 0) or 0))

    reset_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for member_id, member_data in data["members"].items():
        if not isinstance(member_data, dict):
            continue
        try:
            member_inviter_id = int(member_data.get("inviter_id") or 0)
        except (TypeError, ValueError):
            continue
        if target_id is not None and member_inviter_id != target_id:
            continue
        if member_data.get("counted", True):
            affected_members += 1
        member_data["counted"] = False
        member_data["reset_at"] = reset_at
        data["reset_blocked_members"][str(member_id)] = {
            "inviter_id": member_inviter_id,
            "reset_at": reset_at,
        }

    save_invite_tracking_data(guild_id, data)
    return {
        "previous_total": previous_total,
        "previous_active": previous_active,
        "affected_members": affected_members,
    }


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


async def register_invited_member(member: discord.Member) -> dict:
    if member.bot:
        return {}
    used_invite = await detect_used_invite(member.guild)
    if not used_invite:
        return {}
    inviter_id = used_invite.get("inviter_id")
    if not inviter_id or int(inviter_id) == member.id:
        return {
            "inviter_id": None,
            "invite_code": str(used_invite.get("code", "")),
        }

    lock = INVITE_TRACKING_LOCKS.setdefault(member.guild.id, asyncio.Lock())
    async with lock:
        data = get_invite_tracking_data(member.guild.id)
        member_key = str(member.id)
        previous_member_data = data["members"].get(member_key)
        reset_block = data["reset_blocked_members"].get(member_key)

        # Évite un double comptage si Discord renvoie deux événements proches.
        if isinstance(previous_member_data, dict) and previous_member_data.get("active"):
            return dict(previous_member_data)

        now_ts = time.time()
        account_created_ts = member.created_at.timestamp()
        account_age_days = invite_account_age_days(member, now_ts)

        # Un compte déjà vu ne crée jamais une nouvelle invitation totale.
        # S'il revient après être parti, on restaure seulement son état actif,
        # sauf si un reset l'a explicitement marqué comme non comptabilisé.
        if isinstance(previous_member_data, dict):
            member_data = dict(previous_member_data)
            original_inviter_id = int(member_data.get("inviter_id") or inviter_id)
            counted = bool(member_data.get("counted", True)) and not isinstance(reset_block, dict)
            if counted:
                inviter_key = str(original_inviter_id)
                inviter_stats = data["inviters"].get(inviter_key, {})
                if not isinstance(inviter_stats, dict):
                    inviter_stats = {}
                inviter_stats["total"] = max(0, int(inviter_stats.get("total", 0) or 0))
                inviter_stats["active"] = max(0, int(inviter_stats.get("active", 0) or 0)) + 1
                inviter_stats["left"] = max(0, int(inviter_stats.get("left", 0) or 0) - 1)
                data["inviters"][inviter_key] = inviter_stats
            member_data.update({
                "active": True,
                "last_joined_at": utc_now().isoformat(),
                "last_joined_ts": now_ts,
                "last_invite_code": str(used_invite.get("code", "")),
                "last_inviter_id": int(inviter_id),
                "account_created_ts": float(member_data.get("account_created_ts") or account_created_ts),
                "account_age_days_at_first_join": int(member_data.get("account_age_days_at_first_join", account_age_days)),
            })
            if isinstance(reset_block, dict):
                member_data["counted"] = False
                member_data["rejection_reason"] = "Compte déjà invité avant la remise à zéro"
            data["members"][member_key] = member_data
            save_invite_tracking_data(member.guild.id, data)
            return dict(member_data)

        inviter_key = str(inviter_id)
        inviter_stats = data["inviters"].get(inviter_key, {})
        if not isinstance(inviter_stats, dict):
            inviter_stats = {}
        already_blocked_after_reset = isinstance(reset_block, dict)
        eligible = account_age_days >= MIN_INVITE_ACCOUNT_AGE_DAYS and not already_blocked_after_reset
        if eligible:
            inviter_stats["total"] = max(0, int(inviter_stats.get("total", 0) or 0)) + 1
            inviter_stats["active"] = max(0, int(inviter_stats.get("active", 0) or 0)) + 1
        inviter_stats["left"] = max(0, int(inviter_stats.get("left", 0) or 0))
        data["inviters"][inviter_key] = inviter_stats
        member_data = {
            "inviter_id": int(inviter_id),
            "invite_code": str(used_invite.get("code", "")),
            "active": True,
            "joined_at": utc_now().isoformat(),
            "joined_ts": now_ts,
            "first_joined_ts": now_ts,
            "account_created_ts": account_created_ts,
            "account_age_days_at_first_join": account_age_days,
            "eligible": eligible,
            "counted": eligible,
            "rejection_reason": (
                "Compte déjà invité avant la remise à zéro"
                if already_blocked_after_reset
                else ("Compte Discord trop récent" if not eligible else "")
            ),
        }
        data["members"][member_key] = member_data
        save_invite_tracking_data(member.guild.id, data)
        return dict(member_data)


async def register_departed_member(member: discord.Member) -> dict:
    if member.bot:
        return {}
    lock = INVITE_TRACKING_LOCKS.setdefault(member.guild.id, asyncio.Lock())
    async with lock:
        data = get_invite_tracking_data(member.guild.id)
        member_key = str(member.id)
        member_data = data["members"].get(member_key)
        if not isinstance(member_data, dict) or not member_data.get("active"):
            return dict(member_data) if isinstance(member_data, dict) else {}
        inviter_id = member_data.get("inviter_id")
        if inviter_id and member_data.get("counted", True):
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
        return dict(member_data)


async def send_member_activity_log(member: discord.Member, joined: bool, invite_data=None) -> None:
    if member.bot:
        return
    invite_data = invite_data if isinstance(invite_data, dict) else {}
    inviter_id = invite_data.get("inviter_id")
    invite_code = str(invite_data.get("invite_code") or "").strip()
    inviter_text = f"<@{int(inviter_id)}> (`{int(inviter_id)}`)" if inviter_id else "Inviteur non détecté"
    if inviter_id:
        counted = bool(invite_data.get("counted", True))
        count_status = "✅ Oui" if counted else f"❌ Non — {invite_data.get('rejection_reason') or 'déjà vu ou compteur réinitialisé'}"
    else:
        count_status = "⚠️ Non vérifiable"
    try:
        channel = member.guild.get_channel(MEMBER_ACTIVITY_CHANNEL_ID) or bot.get_channel(MEMBER_ACTIVITY_CHANNEL_ID)
        if channel is None:
            channel = await bot.fetch_channel(MEMBER_ACTIVITY_CHANNEL_ID)
        if not hasattr(channel, "send"):
            raise RuntimeError("Le salon de suivi des membres n'accepte pas les messages")
        embed = discord.Embed(
            title="📥 Membre arrivé" if joined else "📤 Membre parti",
            color=discord.Color.from_rgb(74, 222, 128) if joined else discord.Color.from_rgb(248, 113, 113),
            timestamp=utc_now(),
        )
        embed.add_field(name="Membre", value=f"{member.mention} (`{member.id}`)", inline=False)
        embed.add_field(name="Invité par", value=inviter_text, inline=True)
        embed.add_field(name="Invitation", value=f"`{invite_code}`" if invite_code else "Non détectée", inline=True)
        embed.add_field(name="Invitation comptabilisée", value=count_status, inline=False)
        embed.add_field(name="Membres sur le serveur", value=f"**{member.guild.member_count or 0}**", inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="PinkGift — Suivi des arrivées et départs")
        await channel.send(embed=embed)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, RuntimeError, TypeError, ValueError) as error:
        print(f"Erreur journal arrivée/départ pour {member.id}: {error}")


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


def is_managed_private_ticket(channel) -> bool:
    topic = str(getattr(channel, "topic", "") or "")
    return topic.startswith((
        "pinkgift-balance:",
        "pinkgift-cp-manual:",
        "pinkgift-cp-owner:",
        "pinkgift-special:",
        "pinkgift-application:",
    ))


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


def resolve_ticket_client_id(channel, configured_client_id=0):
    """Retrouve le client d'un ticket, y compris après un redémarrage du bot."""
    try:
        configured_client_id = int(configured_client_id or 0)
    except (TypeError, ValueError):
        configured_client_id = 0
    if configured_client_id > 0:
        return configured_client_id

    balance_user_id = get_balance_ticket_user_id(channel)
    if balance_user_id:
        return balance_user_id

    topic = str(getattr(channel, "topic", "") or "")
    ticket_topic_prefixes = (
        "pinkgift-cp-manual:",
        "pinkgift-cp-owner:",
        "pinkgift-special:",
        "pinkgift-application:",
    )
    if topic.startswith(ticket_topic_prefixes):
        matches = re.findall(r"\d{15,25}", topic)
        if matches:
            return int(matches[-1])

    guild = getattr(channel, "guild", None)
    overwrites = getattr(channel, "overwrites", {}) or {}
    staff_role = guild.get_role(STAFF_ROLE_ID) if guild else None
    candidates = []
    for target in overwrites:
        if not isinstance(target, discord.Member) or target.bot:
            continue
        if staff_role and staff_role in target.roles:
            continue
        candidates.append(target.id)
    return candidates[0] if len(candidates) == 1 else 0


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
    embed.add_field(name="PinkCoins crédités", value=f"**{format_pinkcoins(float(lot.get('credited') or 0))}**", inline=True)
    embed.add_field(name="PinkWallet", value=f"**{format_pinkcoins(new_balance)}**", inline=True)
    embed.add_field(name="Code", value=f"**{lot.get('code') or 'Inconnu'}**", inline=True)
    embed.add_field(name="Parrain", value=sponsor_label, inline=True)
    embed.add_field(name="Commission", value=f"**{valid_referral_percentage(lot.get('percentage'), 0):g} %** du bénéfice", inline=True)
    embed.add_field(name="Ajout effectué par", value=f"{staff.mention} (`{staff.id}`)", inline=False)
    message = await channel.send(embed=embed)
    ledger = get_referral_ledger(guild.id, user.id)
    for saved_lot in ledger["lots"]:
        if isinstance(saved_lot, dict) and str(saved_lot.get("id")) == str(lot.get("id")):
            saved_lot["notification_channel_id"] = channel.id
            saved_lot["notification_message_id"] = message.id
            save_referral_ledger(guild.id, user.id, ledger)
            break
    return message


async def delete_referral_tracking_notifications(messages):
    deleted = 0
    for item in messages:
        try:
            channel_id = int(item.get("channel_id") or 0)
            message_id = int(item.get("message_id") or 0)
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            message = await channel.fetch_message(message_id)
            await message.delete()
            deleted += 1
        except discord.NotFound:
            deleted += 1
        except (discord.Forbidden, discord.HTTPException, AttributeError, TypeError, ValueError) as error:
            print(f"Erreur suppression notification parrainage : {error}")
    return deleted


def log_referral_notification_deletion(future):
    try:
        print(f"{future.result()} notification(s) de parrainage supprimée(s) de Discord.")
    except Exception as error:
        print(f"Erreur purge des notifications de parrainage : {error}")


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
                await channel.edit(topic=f"{expected_prefix}:credited", reason="PinkCoins crédités au client")
            except discord.HTTPException as error:
                print(f"Erreur marquage ticket solde credite pour {user_id}: {error}")

def save_order(guild_id, channel_id, message_id, user_id, service, amount, paid, user_name="", received_label=""):
    values = {"guild_id": guild_id, "channel_id": channel_id, "message_id": message_id, "user_id": user_id, "service": service, "amount": amount, "paid": paid, "user_name": user_name, "received_label": received_label}
    if USE_SUPABASE:
        rows = supabase_request("POST", "orders", values, "return=representation")
        order_id = rows[0]["id"]
    else:
        with db_connect() as db:
            cursor = db.execute("INSERT INTO orders(guild_id,channel_id,message_id,user_id,service,amount,paid,user_name,received_label) VALUES(?,?,?,?,?,?,?,?,?)", tuple(values.values()))
            order_id = cursor.lastrowid
    schedule_customer_role_sync(guild_id, user_id)
    return order_id


MANUAL_SALE_CODE_PREFIX = "manual_sale:"


def delete_order_record(order_id):
    order_id = int(order_id)
    if USE_SUPABASE:
        deleted = supabase_request("DELETE", f"orders?id=eq.{order_id}", prefer="return=representation")
        if not deleted:
            raise RuntimeError(
                "Aucune ligne supprimée. Vérifie que SUPABASE_SECRET_KEY est bien une clé secrète "
                "et non la clé publishable/anon."
            )
        return
    with db_connect() as db:
        cursor = db.execute("DELETE FROM orders WHERE id=?", (order_id,))
        if cursor.rowcount == 0:
            raise RuntimeError("Commande introuvable")


def manual_sale_staff_id(order):
    code = str((order or {}).get("code") or "")
    if not code.startswith(MANUAL_SALE_CODE_PREFIX):
        return None
    try:
        staff_id = int(code[len(MANUAL_SALE_CODE_PREFIX):])
    except (TypeError, ValueError):
        return None
    return staff_id if staff_id > 0 else None


def apply_manual_sale_deposit(guild_id, user_id, amount, staff_id):
    """Ajoute un dépôt client consommé immédiatement, sans modifier son PinkWallet."""
    guild_id = int(guild_id)
    user_id = int(user_id)
    staff_id = int(staff_id)
    amount = round(float(amount), 2)
    bot_user_id = stored_discord_bot_user_id()
    if bot_user_id <= 0:
        raise RuntimeError("L'identité Discord du bot n'est pas encore disponible")
    change_balance(guild_id, user_id, amount, staff_id)
    try:
        wallet = change_balance(guild_id, user_id, -amount, bot_user_id)
    except Exception:
        try:
            change_balance(guild_id, user_id, -amount, staff_id)
        except Exception as rollback_error:
            print(f"ERREUR rollback dépôt vente manuelle {user_id}: {rollback_error}")
        raise
    return wallet


def reverse_manual_sale_deposit(order):
    """Retire le dépôt synthétique lié à une vente manuelle, sans toucher au PinkWallet."""
    staff_id = manual_sale_staff_id(order)
    if staff_id is None:
        return False
    guild_id = int(order["guild_id"])
    user_id = int(order["user_id"])
    amount = round(float(order.get("paid") or 0), 2)
    bot_user_id = stored_discord_bot_user_id()
    if amount <= 0 or bot_user_id <= 0:
        raise RuntimeError("Vente manuelle invalide ou bot Discord indisponible")
    change_balance(guild_id, user_id, amount, bot_user_id)
    try:
        change_balance(guild_id, user_id, -amount, staff_id)
    except Exception:
        try:
            change_balance(guild_id, user_id, -amount, bot_user_id)
        except Exception as rollback_error:
            print(f"ERREUR rollback suppression vente manuelle {user_id}: {rollback_error}")
        raise
    return True



init_database()


PAYPAL_EMOJI = "<:paypal:1517582845315649751>"
STAFF_ROLE_ID = 1517487833886228550
PURGE_ROLE_ID = 1517495087825817691
NEW_MEMBER_ROLE_ID = 1517580901356277921
TICKET_CATEGORY_ID = 1519898899047776336
VALO_TICKET_CATEGORY_ID = 1519913523440779404
CP_TICKET_CATEGORY_ID = 1528115477501706300
GIFT_CARD_THREAD_CHANNEL_ID = int(os.environ.get("GIFT_CARD_THREAD_CHANNEL_ID", "1517855734195290213"))
VALORANT_THREAD_CHANNEL_ID = int(os.environ.get("VALORANT_THREAD_CHANNEL_ID", "1517609836026532022"))
PRIVATE_ORDER_THREAD_AUTO_ARCHIVE_MINUTES = 10080
SPECIAL_TICKET_CATEGORY_ID = int(os.environ.get("SPECIAL_TICKET_CATEGORY_ID", "1528329867790123041"))
COMMUNITY_APPLICATION_CATEGORY_ID = int(os.environ.get("COMMUNITY_APPLICATION_CATEGORY_ID", "1526152407376068699"))
BALANCE_CATEGORY_ID = int(os.environ.get("BALANCE_CATEGORY_ID", TICKET_CATEGORY_ID))
CLOSED_TICKET_CATEGORY_ID = 1517526916549181612
EMBED_CONFIG_URL = os.environ.get("EMBED_CONFIG_URL", "https://raw.githubusercontent.com/ynnlz/pinky-software/main/config_embeds.json")
TICKET_IMAGE_URL = "https://media.discordapp.net/attachments/1517516946390908949/1517517071217332424/Ticket_cree.png?ex=6a369167&is=6a353fe7&hm=ce29c76d8a92020dd78c32b4ef8c7a7a41338df78ecf9455f930b9c0dcb1bd08&=&format=webp&quality=lossless"
TARIFS_THUMBNAIL_URL = "https://media.discordapp.net/attachments/1517516946390908949/1517517070894502108/Produits.png?ex=6a369167&is=6a353fe7&hm=06c63f7fb8cca01a4b847fd53b228c2442a158c7fe04c5f61c858a015c517c24&=&format=webp&quality=lossless"
TARIFS_IMAGE_URL = "https://media.discordapp.net/attachments/1517516946390908949/1517517070554890385/Photo_accueil.png?ex=6a369167&is=6a353fe7&hm=07fe98ebafb4108c5c5288ea0d18e1ce113aeebd25d71c4b433033e914d21e44&=&format=webp&quality=lossless"
ORDER_PENDING_IMAGE_URL = "https://media.discordapp.net/attachments/1517516946390908949/1517517069657309204/Commande_recu.png?ex=6a369167&is=6a353fe7&hm=5a401706a47f8c7571510f5112ea122b3061eca7382f31d077c7bdbe7c690d9a&=&format=webp&quality=lossless"
ORDER_FINISHED_IMAGE_URL = "https://media.discordapp.net/attachments/1517516946390908949/1517517069061456102/commande_fini.png?ex=6a369167&is=6a353fe7&hm=e736d0cec28bfc2192e4f360738654e7b4e446adb36b81d33273845a462ce4b8&=&format=webp&quality=lossless"

PRODUCT_CONFIG = {
    "GOOGLE_PLAY": {"display": "GOOGLE PLAY", "emoji": "<:googleplay:1528362570681946263>", "emoji_ch": "🎮"},
    "STEAM": {"display": "STEAM", "emoji": "<:steam:1528359731100647434>", "emoji_ch": "🎮"},
    "DISCORD_NITRO": {"display": "DISCORD NITRO", "emoji": "<:nitro:1528358484972671096>", "emoji_ch": "💎"},
    "PLAYSTATION": {"display": "PLAYSTATION", "emoji": "<:playstation:1528357122520387584>", "emoji_ch": "🎮"},
    "NINTENDO": {"display": "NINTENDO", "emoji": "<:nintendo:1528357096922419281>", "emoji_ch": "🎮"},
    "ZARA": {"display": "ZARA", "emoji": "<:zara:1528775696347037697>", "emoji_ch": "👕"},
    "SEPHORA": {"display": "SEPHORA", "emoji": "<:sephora:1528775577757159454>", "emoji_ch": "💄"},
    "ZALANDO": {"display": "ZALANDO", "emoji": "<:zalando:1528666033911500840>", "emoji_ch": "👟"},
    "ADIDAS": {"display": "ADIDAS", "emoji": "<:adidas:1528662905418158120>", "emoji_ch": "👟"},
    "FOOT_LOCKER": {"display": "FOOT LOCKER", "emoji": "<:footlocker:1528661139410387054>", "emoji_ch": "👟"},
    "SHEIN": {"display": "SHEIN", "emoji": "<:shein:1528659562196897822>", "emoji_ch": "👗"},
    "NIKE": {"display": "NIKE", "emoji": "<:nike:1528368092084699299>", "emoji_ch": "👟"},
    "UBEREATS": {"display": "UBER EATS", "emoji": "<:ubereats:1528671351668211722>", "emoji_ch": "🍔"},
    "DELIVEROO": {"display": "DELIVEROO", "emoji": "<:deliveroo:1528678242167427214>", "emoji_ch": "🍽️"},
    "AMAZON": {"display": "AMAZON", "emoji": "<:amazon:1528686924473172110>", "emoji_ch": "📦"},
    "CARREFOUR": {"display": "CARREFOUR", "emoji": "<:carrefour:1528688036995665950>", "emoji_ch": "🛒"},
    "INTERMARCHE": {"display": "INTERMARCHE", "emoji": "<:intermarche:1528689263800094740>", "emoji_ch": "🏬"},
    "APPLE": {"display": "APPLE", "emoji": "<:apple:1528690433482424435>", "emoji_ch": "🍎"},
    "JOYBUY": {"display": "JOYBUY", "emoji": "<:joybuy:1528691385140514926>", "emoji_ch": "🛍️"},
    "SMYTHS_TOYS": {"display": "SMYTHS TOYS", "emoji": "<:smyths:1528693626442350702>", "emoji_ch": "🧸"},
    "LEGO": {"display": "LEGO", "emoji": "<:lego:1528694473612066826>", "emoji_ch": "🧱"},
    "TESLA": {"display": "TESLA", "emoji": "<:tesla:1528695367137366053>", "emoji_ch": "🚗"},
    "AIRBNB": {"display": "AIRBNB", "emoji": "<:airbnb:1528696272796516434>", "emoji_ch": "🏠"},
    "SKRILL": {"display": "SKRILL", "emoji": "<:skrill:1528697675279765604>", "emoji_ch": "💳"},
    "PAYSAFECARD": {"display": "PAYSAFECARD", "emoji": "<:paysafe:1528698901836726354>", "emoji_ch": "💳"},
    "VALORANT": {"display": "VALORANT", "emoji": "🎮", "emoji_ch": "🎮"},
}

PRODUCT_CATEGORY_CONFIG = {
    "GAMING": {
        "label": "Gaming",
        "emoji": "<:gaming:1528336678450892852>",
        "products": ("GOOGLE_PLAY", "STEAM", "DISCORD_NITRO", "PLAYSTATION", "NINTENDO"),
    },
    "MODE_BEAUTE": {
        "label": "Mode & beauté",
        "emoji": "<:robe:1528337986096336947>",
        "products": ("ZARA", "SEPHORA", "ZALANDO", "ADIDAS", "FOOT_LOCKER", "SHEIN", "NIKE"),
    },
    "FOOD": {
        "label": "Food & livraison",
        "emoji": "<:burger:1528339745464389662>",
        "products": ("UBEREATS", "DELIVEROO"),
    },
    "COURSES": {
        "label": "Shopping & courses",
        "emoji": "<:sacs:1528341171833929848>",
        "products": ("AMAZON", "CARREFOUR", "INTERMARCHE", "APPLE", "JOYBUY"),
    },
    "JOUETS": {
        "label": "Jouets",
        "emoji": "<:nounours:1528343442604691596>",
        "products": ("SMYTHS_TOYS", "LEGO"),
    },
    "VOYAGE": {
        "label": "Voyage & auto",
        "emoji": "<:voyage:1528344840293847130>",
        "products": ("TESLA", "AIRBNB"),
    },
    "PREPAYES": {
        "label": "Prépayés",
        "emoji": "<:carte:1528346097276420271>",
        "products": ("SKRILL", "PAYSAFECARD"),
    },
}

GIFT_CARD_AMOUNTS = (100, 200, 400, 800)
UBEREATS_PACKS = {
    "pack_20": {"default_price": 20, "drop": "28–42"},
    "pack_65": {"default_price": 65, "drop": "85–115"},
    "pack_125": {"default_price": 125, "drop": "165–225"},
    "pack_350": {"default_price": 350, "drop": "501–680"},
}
NITRO_PRICE = 8
CP_PACKS = {
    "2400": {"points": 2400, "default_price": 12, "default_cost": 5, "official_price": 19.99},
    "4800": {"points": 4800, "default_price": 20, "default_cost": 8, "official_price": 39.98},
    "9500": {"points": 9500, "default_price": 35, "default_cost": 15, "official_price": 74.99},
    "14400": {"points": 14400, "default_price": 50, "default_cost": 22, "official_price": 113.92},
    "21000": {"points": 21000, "default_price": 70, "default_cost": 31, "official_price": 165.94},
    "30000": {"points": 30000, "default_price": 95, "default_cost": 42, "official_price": 234.95},
    "40800": {"points": 40800, "default_price": 125, "default_cost": 55, "official_price": 316.94},
}
OTHER_SERVICES = {
    "BASIC_FIT": {
        "label": "Basic-Fit",
        "emoji": "<:basicfit:1528704864446578789>",
        "description": "Abonnement Basic-Fit",
    },
    "DISCORD_DECORATIONS": {
        "label": "Décorations Discord",
        "emoji": "<:nitro:1528358484972671096>",
        "description": "Décorations et cosmétiques Discord",
    },
}
SUBSCRIPTION_SERVICES = {
    "NETFLIX": {
        "label": "Netflix",
        "emoji": "<:netflix:1528701811215569016>",
        "description": "Abonnement Netflix",
    },
    "SPOTIFY": {
        "label": "Spotify",
        "emoji": "<:spotify:1528703633724674089>",
        "description": "Abonnement Spotify Premium",
    },
    "YOUTUBE_PREMIUM": {
        "label": "YouTube Premium",
        "emoji": "<:youtube:1528704255844946011>",
        "description": "Abonnement YouTube Premium",
    },
}
VALO_REGIONS = {
    "EUROPE": {
        "label": "Europe", "emoji": "🇪🇺",
        "packs": {
            "3650": {"label": "3650 VP", "default_price": 30, "original_price": 35},
            "5350": {"label": "5350 VP", "default_price": 40, "original_price": 50},
            "8700": {"label": "8700 VP", "default_price": 60, "original_price": 80},
            "11000": {"label": "11000 VP", "default_price": 80, "original_price": 100},
        }
    },
    "TURQUIE": {
        "label": "Turquie", "emoji": "🇹🇷",
        "packs": {
            "2925": {"label": "2925 VP", "default_price": 15, "original_price": 15.75},
            "4325": {"label": "4325 VP", "default_price": 20, "original_price": 22.80},
            "8900": {"label": "8900 VP", "default_price": 45, "original_price": 45.41},
            "11000": {"label": "11000 VP", "default_price": 55, "original_price": 57.45},
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
        "cp": {pack_key: float(pack["default_price"]) for pack_key, pack in CP_PACKS.items()},
        "valorant": {
            region_key: {pack_key: float(pack["default_price"]) for pack_key, pack in region["packs"].items()}
            for region_key, region in VALO_REGIONS.items()
        },
        "valorant_original": {
            region_key: {pack_key: float(pack["original_price"]) for pack_key, pack in region["packs"].items()}
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

    saved_cp = saved.get("cp", {}) if isinstance(saved.get("cp"), dict) else {}
    for pack_key, fallback in list(prices["cp"].items()):
        prices["cp"][pack_key] = valid_price(saved_cp.get(pack_key), fallback)

    saved_valorant = saved.get("valorant", {}) if isinstance(saved.get("valorant"), dict) else {}
    for region_key, packs in prices["valorant"].items():
        saved_packs = saved_valorant.get(region_key, {}) if isinstance(saved_valorant.get(region_key), dict) else {}
        for pack_key, fallback in list(packs.items()):
            legacy_key = str(int(VALO_REGIONS[region_key]["packs"][pack_key]["default_price"]))
            packs[pack_key] = valid_price(saved_packs.get(pack_key, saved_packs.get(legacy_key)), fallback)

    saved_valorant_original = saved.get("valorant_original", {}) if isinstance(saved.get("valorant_original"), dict) else {}
    obsolete_turkish_originals = {"2925": 30, "4325": 40, "8900": 80, "11000": 100}
    for region_key, packs in prices["valorant_original"].items():
        saved_packs = saved_valorant_original.get(region_key, {}) if isinstance(saved_valorant_original.get(region_key), dict) else {}
        for pack_key, fallback in list(packs.items()):
            saved_price = saved_packs.get(pack_key)
            if (
                region_key == "TURQUIE"
                and valid_price(saved_price, fallback) == obsolete_turkish_originals.get(pack_key)
            ):
                saved_price = None
            packs[pack_key] = valid_price(saved_price, fallback)
    return prices


def format_price(value):
    return f"{float(value):g}"


PINKCOINS_PER_EURO = 100


def euros_to_pinkcoins(value):
    """Convertit un montant interne en euros vers l'affichage PinkCoins."""
    return int(round(float(value) * PINKCOINS_PER_EURO))


def pinkcoins_to_euros(value):
    """Convertit un montant saisi en PinkCoins vers le stockage historique en euros."""
    return round(float(value) / PINKCOINS_PER_EURO, 2)


def parse_pinkcoin_amount(value):
    """Accepte les formats usuels Discord : 1250, 1 250, 2.500 ou 1,25k."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = re.sub(r"\s*(?:pink\s*coins?|pinkcoins?|pcs?)\s*$", "", text).strip()
    multiplier = Decimal("1000") if text.endswith("k") else Decimal("1")
    if text.endswith("k"):
        text = text[:-1].strip()
    text = re.sub(r"[\s_]", "", text)
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", text):
        text = re.sub(r"[.,]", "", text)
    else:
        text = text.replace(",", ".")
    try:
        amount = Decimal(text) * multiplier
    except (InvalidOperation, ValueError):
        raise ValueError("Montant de PinkCoins invalide")
    if not amount.is_finite() or amount <= 0 or amount != amount.to_integral_value():
        raise ValueError("Le montant doit contenir un nombre entier positif de PinkCoins")
    return int(amount)


def format_pinkcoins(value, short=False):
    amount = f"{euros_to_pinkcoins(value):,}".replace(",", " ")
    return f"{amount} {'PC' if short else 'PinkCoins'}"


def pinkcoin_number(value):
    return f"{euros_to_pinkcoins(value):,}".replace(",", " ")


def pinkcoin_input_value(value):
    """Retourne un entier sans séparateur, accepté par les champs HTML number."""
    return str(euros_to_pinkcoins(value))


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
        "cp": {pack_key: float(pack["default_cost"]) for pack_key, pack in CP_PACKS.items()},
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

    saved_cp = saved.get("cp", {}) if isinstance(saved.get("cp"), dict) else {}
    for pack_key, fallback in list(costs["cp"].items()):
        costs["cp"][pack_key] = valid_purchase_cost(saved_cp.get(pack_key), fallback)

    saved_valorant = saved.get("valorant", {}) if isinstance(saved.get("valorant"), dict) else {}
    for region_key, packs in costs["valorant"].items():
        saved_packs = saved_valorant.get(region_key, {}) if isinstance(saved_valorant.get(region_key), dict) else {}
        for pack_key in packs:
            packs[pack_key] = valid_purchase_cost(saved_packs.get(pack_key), 0)
    return costs


def save_order_purchase_cost(message_id, cost):
    set_panel_setting(f"order_cost:{int(message_id)}", {"cost": valid_purchase_cost(cost), "saved_at": utc_now().isoformat()})


def normalize_order_supplier(value):
    return " ".join(str(value or "").split())[:100]


def save_order_supplier(message_id, supplier):
    supplier = normalize_order_supplier(supplier)
    if not supplier:
        raise ValueError("Le nom du fournisseur est obligatoire pour une livraison Nitro")
    set_panel_setting(
        f"order_supplier:{int(message_id)}",
        {"name": supplier, "saved_at": utc_now().isoformat()},
    )
    return supplier


def load_order_suppliers():
    suppliers = {}
    if USE_SUPABASE:
        items = []
        offset = 0
        while True:
            prefix = urllib.parse.quote("order_supplier:", safe="")
            page = supabase_request(
                "GET",
                f"panel_settings?key=like.{prefix}*&select=key,value&order=key&limit=1000&offset={offset}",
            ) or []
            items.extend(page)
            if len(page) < 1000:
                break
            offset += len(page)
    else:
        items = list_panel_settings("order_supplier:")
    for item in items:
        try:
            message_id = int(str(item.get("key", "")).split(":", 1)[1])
        except (IndexError, TypeError, ValueError):
            continue
        value = item.get("value", {})
        if not isinstance(value, dict):
            continue
        supplier = normalize_order_supplier(value.get("name"))
        if supplier:
            suppliers[message_id] = supplier
    return suppliers


def normalize_cp_code(value):
    return str(value or "").strip()[:500]


def get_order_record(message_id=None, order_id=None):
    if message_id is None and order_id is None:
        return None
    if USE_SUPABASE:
        if order_id is not None:
            query = f"orders?id=eq.{int(order_id)}&select=*"
        else:
            query = f"orders?message_id=eq.{int(message_id)}&select=*"
        rows = supabase_request("GET", query) or []
        order = rows[0] if rows else None
    else:
        with db_connect() as db:
            if order_id is not None:
                row = db.execute("SELECT * FROM orders WHERE id=?", (int(order_id),)).fetchone()
            else:
                row = db.execute("SELECT * FROM orders WHERE message_id=?", (int(message_id),)).fetchone()
            order = dict(row) if row else None
    return order


def is_nitro_order(order):
    return (
        str((order or {}).get("service") or "").strip().upper()
        == PRODUCT_CONFIG["DISCORD_NITRO"]["display"].upper()
    )


def get_cp_order(message_id=None, order_id=None):
    order = get_order_record(message_id=message_id, order_id=order_id)
    if not order or not str(order.get("service") or "").upper().startswith("COD POINTS"):
        return None
    return order


def mark_order_status(order_id, status):
    status = str(status or "pending")[:30]
    values = {
        "status": status,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if USE_SUPABASE:
        supabase_request("PATCH", f"orders?id=eq.{int(order_id)}", values)
        return
    with db_connect() as db:
        db.execute(
            "UPDATE orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, int(order_id)),
        )


def mark_order_cancelled(order_id):
    mark_order_status(order_id, "cancelled")


def refund_pending_order(order, staff_id):
    if not order:
        raise ValueError("Commande introuvable")
    # Tous les points d'entrée (Discord et panel) passent par ce verrou afin
    # qu'un double clic ne puisse jamais créditer deux fois la même commande.
    with ORDER_REFUND_LOCK:
        order = get_order_record(order_id=order["id"])
        if not order or str(order.get("status") or "pending").lower() != "pending":
            raise ValueError("Cette commande n'est plus en attente")
        mark_order_status(order["id"], "refunding")
        try:
            new_balance = change_balance(
                int(order["guild_id"]),
                int(order["user_id"]),
                float(order.get("paid") or 0),
                int(staff_id or 0),
            )
        except Exception:
            mark_order_status(order["id"], "pending")
            raise
        mark_order_cancelled(order["id"])
        try:
            remove_referral_purchase(order["guild_id"], order["user_id"], order["message_id"])
        except Exception as error:
            print(f"Erreur retrait parrainage remboursement commande #{order['id']}: {error}")
        schedule_customer_role_sync(order["guild_id"], order["user_id"])
        return new_balance


def mark_order_delivered(order_id, code):
    values = {
        "code": normalize_cp_code(code),
        "status": "done",
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if USE_SUPABASE:
        supabase_request("PATCH", f"orders?id=eq.{int(order_id)}", values)
        return
    with db_connect() as db:
        db.execute(
            "UPDATE orders SET code=?, status='done', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (values["code"], int(order_id)),
        )

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
            "<:gaming:1528336678450892852> **GAMING**",
            "<:googleplay:1528362570681946263> **Google Play**", "<:steam:1528359731100647434> **Steam**",
            "<:nitro:1528358484972671096> **Discord Nitro — 8 €**", "<:playstation:1528357122520387584> **PlayStation**", "<:nintendo:1528357096922419281> **Nintendo**",
            "",
            "<:robe:1528337986096336947> **MODE & BEAUTÉ**",
            "<:zara:1528775696347037697> **Zara**", "<:sephora:1528775577757159454> **Sephora**", "<:zalando:1528666033911500840> **Zalando**",
            "<:adidas:1528662905418158120> **Adidas**", "<:footlocker:1528661139410387054> **Foot Locker**", "<:shein:1528659562196897822> **Shein**", "<:nike:1528368092084699299> **Nike**",
            "",
            "<:burger:1528339745464389662> **FOOD & LIVRAISON**", "<:ubereats:1528671351668211722> **Uber Eats**", "<:deliveroo:1528678242167427214> **Deliveroo**",
            "",
            "<:sacs:1528341171833929848> **SHOPPING & COURSES**", "<:amazon:1528686924473172110> **Amazon**", "<:carrefour:1528688036995665950> **Carrefour**",
            "<:intermarche:1528689263800094740> **Intermarché**", "<:apple:1528690433482424435> **Apple**", "<:joybuy:1528691385140514926> **Joybuy**",
            "",
            "<:nounours:1528343442604691596> **JOUETS**", "<:smyths:1528693626442350702> **Smyths Toys**", "<:lego:1528694473612066826> **LEGO**",
            "",
            "<:voyage:1528344840293847130> **VOYAGE & AUTO**", "<:tesla:1528695367137366053> **Tesla**", "<:airbnb:1528696272796516434> **Airbnb**",
            "",
            "<:carte:1528346097276420271> **PRÉPAYÉ**", "<:skrill:1528697675279765604> **Skrill**", "<:paysafe:1528698901836726354> **Paysafecard**",
            "",
            "🎫 Clique sur le bouton **Commander** ci-dessous. Les menus sont visibles uniquement par toi."
        ],
        "color_rgb": [255, 192, 203],
        "image_url": "",
        "footer": "PinkGift — Tarifs",
        "menu_button_label": "Commander",
        "menu_button_emoji": "🛍️",
        "menu_button_style": "success"
    },
    "valo_embed": {
        "title": "<:vp:1519915966476320901> VALORANT POINTS",
        "description": [
            "Choisis ta région puis ton pack.",
            "Le prix est débité automatiquement de ton solde.",
            "",
            "🛒 Clique sur **Commander des VP**, puis choisis ta région et ton pack."
        ],
        "region_emojis": {"EUROPE": "🇪🇺", "TURQUIE": "🇹🇷"},
        "region_field_name_template": "{emoji} {region}",
        "pack_line_template": "<:vp:1519915966476320901> **{pack}** — **{price} €** · origine ≈ ~~{official} €~~",
        "dynamic_fields_inline": False,
        "color_rgb": [255, 192, 203],
        "image_url": "",
        "footer": "PinkGift — Valorant Points",
        "menu_button_label": "Commander des VP",
        "menu_button_emoji": "🎮",
        "menu_button_style": "success"
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
        ]
    },
    "nitro_ticket_embed": {
        "title": "<:nitro:1528358484972671096> Commande — DISCORD NITRO",
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
        "color_rgb": [255, 192, 203]
    },
    "valo_ticket_bienvenue_embed": {
        "title": "<:vp:1519915966476320901> Ticket d'achat — VALORANT",
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
                "value": "!tarifs : affiche les cartes cadeaux et les menus de commande.\n!valo : envoie l'embed Valorant avec son bouton ticket.\n!cp : publie les COD Points avec commande et livraison automatiques.\n!teams : publie l’embed de l’équipe et des grades.\n!maj_embed : met à jour uniquement l’embed public du salon actuel, sans ping.\n!close_button : ajoute un bouton Close persistant.\n!faq : publie la FAQ PinkGift.",
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
                "value": "!giveaway <durée> <nom> [invitations] [chances_invitations] [tag_serveur] [nombre_gagnants] : crée un giveaway ; les conditions sont vérifiées au tirage et les chances peuvent augmenter avec les invitations valides.\n!reroll <ID ou lien> : refait le tirage avec le même nombre de gagnants.\n!reset_invitations [membre] confirmation:Oui : remet les invitations à zéro sans recomptage des anciens invités.",
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

DEFAULT_EMBED_DATA.update({"balance_embed":{"title":"<:cash:1525568414117134528> Solde & paiements PinkGift","description":["Consulte ton solde personnel ou ouvre un ticket pour le recharger.","","> Minimum dépôt : 20€","Les informations de chaque client restent privées.","","<:cashapp:1525570860189225112> Moyens de paiement acceptés","","<:revolut:1525568035392459023> **Revolut**","<:paypal:1517582845315649751> **PayPal**","<:banque:1523803303253905590> **Virements bancaires**","<:litecoin:1523802843352531147> **Cryptomonnaies**","","Clique sur les boutons ci-dessous pour consulter ton solde ou ouvrir un ticket de recharge."],"color_rgb":[255,192,203],"image_key":"paiement_securise","footer":"PinkGift — Solde & paiements"},"balance_ticket_embed":{"title":"➕ Recharge de solde","description":["Bonjour {user} !","","Ton solde actuel est de **{balance} €**.","Indique au staff le montant et le moyen de paiement souhaités."],"color_rgb":[255,192,203],"image_key":"paiement_securise"}})

DEFAULT_EMBED_DATA.update({
    "parrainages_embed": {
        "title": "🤝 PARRAINAGES PINKGIFT",
        "description": [
            "Tu es **streamer Twitch**, créateur de contenu ou responsable d'une communauté ? PinkGift propose un programme de parrainage simple pour récompenser les partenaires qui nous présentent à leur audience.",
            "",
            "🎟️ **Un code personnalisé**",
            "Nous créons un code unique au nom du partenaire. Les membres de sa communauté peuvent l'indiquer lorsqu'ils rechargent leur solde PinkGift.",
            "",
            "📊 **Un suivi automatique**",
            "Le solde ajouté avec ce code est suivi en interne. Lorsqu'un client effectue un achat, le système calcule la part de bénéfice réellement générée grâce au parrainage.",
            "",
            "💸 **Une commission sur le bénéfice**",
            "Le partenaire reçoit le pourcentage convenu sur le bénéfice attribué à ses clients. Le taux et les modalités sont définis avec PinkGift avant l'activation du code.",
            "",
            "✨ **Pour quels partenaires ?**",
            "Streamers Twitch, créateurs TikTok ou YouTube, influenceurs, serveurs communautaires et autres partenaires capables de présenter PinkGift à une audience engagée.",
            "",
            "📩 **Intéressé par un partenariat ?**",
            "Contacte l'équipe PinkGift afin de présenter ton activité, ton audience et discuter des conditions de collaboration."
        ],
        "color_rgb": [255, 192, 203],
        "footer": "PinkGift — Programme de parrainage",
        "image_url": ""
    },
    "parrainage_ticket_embed": {
        "title": "🤝 Candidature au programme de parrainage",
        "description": [
            "Bonjour {user} !",
            "",
            "Merci pour ton intérêt envers le programme de parrainage PinkGift.",
            "Présente ton activité, ta communauté et les réseaux sur lesquels tu crées du contenu.",
            "",
            "Indique également tes statistiques principales et la manière dont tu souhaites promouvoir PinkGift.",
            "L'équipe étudiera ensuite ta demande avec toi dans ce ticket."
        ],
        "color_rgb": [255, 192, 203],
        "footer": "PinkGift — Candidature parrainage"
    },
    "recrutement_embed": {
        "title": "📋 RECRUTEMENT PINKGIFT",
        "description": [
            "Tu souhaites rejoindre l'équipe PinkGift ?",
            "",
            "Nous recherchons des personnes sérieuses, disponibles et motivées pour accompagner la communauté et participer au développement du shop.",
            "",
            "Clique sur le bouton ci-dessous pour ouvrir ta candidature."
        ],
        "color_rgb": [255, 192, 203],
        "footer": "PinkGift — Recrutement"
    },
    "recrutement_ticket_embed": {
        "title": "📋 Candidature au recrutement PinkGift",
        "description": [
            "Bonjour {user} !",
            "",
            "Pour que l'équipe puisse étudier ta candidature, indique :",
            "• ton âge ;",
            "• tes disponibilités ;",
            "• ton expérience sur Discord ;",
            "• le poste ou les missions qui t'intéressent ;",
            "• tes motivations pour rejoindre PinkGift.",
            "",
            "Une réponse te sera apportée directement dans ce ticket."
        ],
        "color_rgb": [255, 192, 203],
        "footer": "PinkGift — Candidature recrutement"
    },
    "privileges_embed": {
        "title": "✨ PRIVILÈGES PINKGIFT",
        "description": [
            "Bienvenue dans l’espace **Privilèges PinkGift**.",
            "",
            "Retrouve ici les avantages et offres réservés aux membres de la communauté.",
            "Ce contenu est provisoire : il peut être entièrement modifié depuis le panel."
        ],
        "fields": [
            {
                "name": "💎 Avantages exclusifs",
                "value": "Des avantages spéciaux seront bientôt présentés ici.",
                "inline": False
            },
            {
                "name": "🎁 Offres réservées",
                "value": "Des offres privées pourront être ajoutées pour les membres éligibles.",
                "inline": False
            },
            {
                "name": "🚀 Accès prioritaire",
                "value": "Les conditions d’accès seront annoncées prochainement.",
                "inline": False
            }
        ],
        "color_rgb": [255, 192, 203],
        "footer": "PinkGift — Privilèges",
        "image_url": "",
        "menu_button_label": "Découvrir les privilèges",
        "menu_button_emoji": "✨",
        "menu_button_style": "primary",
        "menu_placeholder": "Choisis une catégorie",
        "menu_categories": [
            {
                "label": "Avantages exclusifs",
                "value": "avantages-exclusifs",
                "emoji": "💎",
                "description": "Voir les avantages réservés",
                "options": [
                    {"label": "Option à configurer", "value": "option-1", "emoji": "✨"}
                ]
            },
            {
                "label": "Offres réservées",
                "value": "offres-reservees",
                "emoji": "🎁",
                "description": "Voir les offres disponibles",
                "options": [
                    {"label": "Option à configurer", "value": "option-1", "emoji": "✨"}
                ]
            }
        ]
    },
    "team_embed": {
        "title": "👥 ÉQUIPE PINKGIFT",
        "description": [
            "Découvre les membres qui font vivre **PinkGift**.",
            "",
            "La composition de l’équipe et les différents grades peuvent être modifiés depuis le panel."
        ],
        "fields": [
            {
                "name": "👑 Direction",
                "value": "Ajoute ici les membres de la direction.",
                "inline": False
            },
            {
                "name": "🛡️ Administration",
                "value": "Ajoute ici les administrateurs.",
                "inline": False
            },
            {
                "name": "🎫 Support",
                "value": "Ajoute ici les membres du support.",
                "inline": False
            }
        ],
        "color_rgb": [255, 192, 203],
        "footer": "PinkGift — Notre équipe",
        "image_url": ""
    }
})

DEFAULT_EMBED_DATA.update({"uber_eats_ticket_embed": {"title": "🍔 Commande — UBER EATS", "description": ["Bonjour {user} !", "", "Ta commande Uber Eats a bien été enregistrée et ton solde a été débité.", "La livraison est automatique : les informations seront envoyées ici dès qu'elles seront disponibles.", "Le staff intervient uniquement pour les recharges de solde."], "fields": [{"name": "Service sélectionné", "value": "{emoji} **{service}**", "inline": False}, {"name": "Prix payé", "value": "**{paid} €**", "inline": True}, {"name": "Drop estimé", "value": "**{drop}**", "inline": True}, {"name": "Solde restant", "value": "**{balance} €**", "inline": False}], "color_rgb": [255, 192, 203]}})

DEFAULT_EMBED_DATA["uber_eats_ticket_embed"]["title"] = "<:ubereats:1528671351668211722> Commande — UBER EATS"

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

DEFAULT_EMBED_DATA.update({
    "cp_embed": {
        "title": "<:cp:1528128623117205624> CALL OF DUTY POINTS — PINKGIFT",
        "description": [
            "Ouvre un ticket privé pour demander tes **COD Points**.",
            "",
            "📝 Indique le nombre de CP que tu souhaites",
            "💶 Indique combien tu souhaites payer",
            "🤝 Le staff te répondra directement dans le ticket",
            "",
            "**Aucun solde PinkGift n'est débité.**"
        ],
        "packs_field_name": "<:cp:1528128623117205624> Packs disponibles",
        "pack_line_template": "<:cp:1528128623117205624> **{points} CP** — **{price} €** · officiel ≈ ~~{official} €~~",
        "dynamic_fields_inline": False,
        "color_rgb": [255, 103, 174],
        "image_url": "https://web-production-d686c.up.railway.app/static/cod-standard_v2-1x.webp",
        "footer": "PinkGift — COD Points"
    },
    "cp_manual_ticket_embed": {
        "title": "<:cp:1528128623117205624> Demande de COD Points",
        "description": [
            "Bonjour {user} !",
            "",
            "Écris dans ce ticket :",
            "1. **Le nombre de CP souhaité**",
            "2. **Le montant que tu proposes de payer**",
            "",
            "Le staff te confirmera ensuite la disponibilité et le prix.",
            "**Aucun solde PinkGift n'a été débité.**"
        ],
        "fields": [
            {"name": "Exemple", "value": "Je souhaite **9 500 CP** et je propose **35 €**.", "inline": False}
        ],
        "color_rgb": [255, 192, 203],
        "image_key": "ticket_cree",
        "footer": "PinkGift — Demande CP sans débit"
    },
    "cp_order_pending_embed": {
        "title": "<:cp:1528128623117205624> Commande COD Points en attente",
        "description": [
            "Merci pour ta commande {user} !",
            "Le pack est maintenant commandé auprès du fournisseur. Le code sera envoyé ici dès sa réception."
        ],
        "fields": [
            {"name": "Pack", "value": "**{points} CP**", "inline": True},
            {"name": "Prix débité", "value": "**{paid} €**", "inline": True},
            {"name": "Solde restant", "value": "**{balance} €**", "inline": True},
            {"name": "Statut", "value": "⏳ Commande fournisseur en cours", "inline": False}
        ],
        "color_rgb": [255, 170, 64],
        "footer": "PinkGift — Commande CP à la demande"
    },
    "cp_delivery_embed": {
        "title": "<:cp:1528128623117205624> COD Points livrés",
        "description": [
            "Merci pour ta commande {user} !",
            "Ton code est disponible ci-dessous. Conserve-le jusqu'à son activation."
        ],
        "fields": [
            {"name": "Pack", "value": "**{points} CP**", "inline": True},
            {"name": "Prix débité", "value": "**{paid} €**", "inline": True},
            {"name": "Solde restant", "value": "**{balance} €**", "inline": True},
            {"name": "Code COD Points", "value": "{code}", "inline": False}
        ],
        "color_rgb": [46, 204, 113],
        "footer": "PinkGift — Livraison CP"
    }
})

DEFAULT_EMBED_DATA.update({
    "autres_embed": {
        "title": "✨ AUTRES SERVICES & ABONNEMENTS — PINKGIFT",
        "description": [
            "Choisis ce qui t'intéresse dans le menu ci-dessous.",
            "",
            "**✨ Autres services**",
            "<:basicfit:1528704864446578789> **Basic-Fit**",
            "<:nitro:1528358484972671096> **Décorations Discord**",
            "",
            "**📺 Abonnements**",
            "<:netflix:1528701811215569016> **Netflix**",
            "<:spotify:1528703633724674089> **Spotify Premium**",
            "<:youtube:1528704255844946011> **YouTube Premium**",
            "",
            "Un ticket privé sera créé pour organiser ta demande avec le staff.",
            "**Aucun solde ne sera débité à l'ouverture du ticket.**"
        ],
        "color_rgb": [255, 103, 174],
        "footer": "PinkGift — Services & abonnements",
        "menu_button_label": "Voir les services",
        "menu_button_emoji": "✨",
        "menu_button_style": "primary",
        "menu_placeholder": "Choisis une catégorie",
        "menu_categories": [
            {
                "label": "Autres services",
                "value": "autres-services",
                "emoji": "✨",
                "description": "Basic-Fit et décorations Discord",
                "placeholder": "Choisis un autre service",
                "catalog_key": "autres",
                "options": [
                    {
                        "label": "Basic-Fit",
                        "value": "basic-fit",
                        "emoji": "<:basicfit:1528704864446578789>",
                        "description": "Abonnement Basic-Fit",
                        "service_key": "BASIC_FIT"
                    },
                    {
                        "label": "Décorations Discord",
                        "value": "decorations-discord",
                        "emoji": "<:nitro:1528358484972671096>",
                        "description": "Décorations et cosmétiques Discord",
                        "service_key": "DISCORD_DECORATIONS"
                    }
                ]
            },
            {
                "label": "Abonnements",
                "value": "abonnements",
                "emoji": "📺",
                "description": "Netflix, Spotify et YouTube Premium",
                "placeholder": "Choisis un abonnement",
                "catalog_key": "abonnements",
                "options": [
                    {
                        "label": "Netflix",
                        "value": "netflix",
                        "emoji": "<:netflix:1528701811215569016>",
                        "description": "Abonnement Netflix",
                        "service_key": "NETFLIX"
                    },
                    {
                        "label": "Spotify Premium",
                        "value": "spotify-premium",
                        "emoji": "<:spotify:1528703633724674089>",
                        "description": "Abonnement Spotify Premium",
                        "service_key": "SPOTIFY"
                    },
                    {
                        "label": "YouTube Premium",
                        "value": "youtube-premium",
                        "emoji": "<:youtube:1528704255844946011>",
                        "description": "Abonnement YouTube Premium",
                        "service_key": "YOUTUBE_PREMIUM"
                    }
                ]
            }
        ]
    },
    "subscription_request_ticket_embed": {
        "title": "{emoji} Abonnement — {service}",
        "description": [
            "Bonjour {user} !",
            "",
            "Ton choix **{service}** est bien enregistré.",
            "L'offre et la durée sont déjà associées à cet abonnement : tu n'as rien d'autre à sélectionner.",
            "Le staff prendra la suite de ta demande directement dans ce ticket.",
            "",
            "**Aucun solde PinkGift n'a été débité.**"
        ],
        "fields": [
            {"name": "Service", "value": "{emoji} **{service}**", "inline": True},
            {"name": "Offre et durée", "value": "**Prédéfinies pour ce service**", "inline": True}
        ],
        "color_rgb": [255, 192, 203],
        "image_key": "ticket_cree",
        "footer": "PinkGift — Abonnement sans débit"
    },
    "basic_fit_request_ticket_embed": {
        "title": "<:basicfit:1528704864446578789> Demande — Basic-Fit",
        "description": [
            "Bonjour {user} !",
            "",
            "Basic-Fit possède plusieurs offres et plusieurs durées.",
            "Indique dans ce ticket **l'offre Basic-Fit** et **la durée** que tu souhaites.",
            "Le staff te répondra ensuite avec les informations correspondantes.",
            "",
            "**Aucun solde PinkGift n'a été débité.**"
        ],
        "fields": [
            {"name": "À préciser", "value": "1. L'offre souhaitée\n2. La durée souhaitée", "inline": False}
        ],
        "color_rgb": [255, 192, 203],
        "image_key": "ticket_cree",
        "footer": "PinkGift — Basic-Fit sans débit"
    },
    "discord_decoration_request_ticket_embed": {
        "title": "<:nitro:1528358484972671096> Demande — Décoration Discord",
        "description": [
            "Bonjour {user} !",
            "",
            "Envoie dans ce ticket **une capture d'écran ou le lien de la décoration Discord/Nitro** que tu souhaites acheter.",
            "Les décorations ont un prix fixe : le staff te donnera le prix correspondant à ton choix.",
            "",
            "**Aucun solde PinkGift n'a été débité.**"
        ],
        "fields": [
            {"name": "À envoyer", "value": "La capture ou le lien de la décoration souhaitée", "inline": False}
        ],
        "color_rgb": [255, 192, 203],
        "image_key": "ticket_cree",
        "footer": "PinkGift — Décoration sans débit"
    }
})

def normalize_embed_configuration(data):
    """Applique les migrations visuelles aux anciens overrides enregistrés dans le panel."""
    if not isinstance(data, dict):
        return data

    legacy_emojis = {
        "<:googleplay:1519907060555186278>": "<:googleplay:1528362570681946263>",
        "<:steam:1519907154545610873>": "<:steam:1528359731100647434>",
        "<:nitroboost:1524439577656561846>": "<:nitro:1528358484972671096>",
        "<:playstation:1519906767268741200>": "<:playstation:1528357122520387584>",
        "<:nintendo:1519907394157678632>": "<:nintendo:1528357096922419281>",
        "<:zara:1519907265681948773>": "<:zara:1528775696347037697>",
        "<:sephora:1519907492862103742>": "<:sephora:1528775577757159454>",
        "<:zalando:1519907231812816906>": "<:zalando:1528666033911500840>",
        "<:adidas:1519906784515588116>": "<:adidas:1528662905418158120>",
        "<:footlocker:1519907296342310952>": "<:footlocker:1528661139410387054>",
        "<:shein:1524439283367411793>": "<:shein:1528659562196897822>",
        "<:nike:1519906735589167164>": "<:nike:1528368092084699299>",
        "<:ubereats:1519907186636099604>": "<:ubereats:1528671351668211722>",
        "<:deliveroo:1519906860356993174>": "<:deliveroo:1528678242167427214>",
        "<:amazon:1519907450403160104>": "<:amazon:1528686924473172110>",
        "<:carrefour:1519906825494073414>": "<:carrefour:1528688036995665950>",
        "<:intermarche:1519907100057276546>": "<:intermarche:1528689263800094740>",
        "<:apple:1519906800411869204>": "<:apple:1528690433482424435>",
        "<:Joybuy:1524439360638943242>": "<:joybuy:1528691385140514926>",
        "<:smythstoys:1519907368429944832>": "<:smyths:1528693626442350702>",
        "<:lego:1519907470854852720>": "<:lego:1528694473612066826>",
        "<:tesla:1524439914811359293>": "<:tesla:1528695367137366053>",
        "<:airbnb:1519906701900386344>": "<:airbnb:1528696272796516434>",
        "<:skrill:1524440310489288755>": "<:skrill:1528697675279765604>",
    }

    def migrate_value(value):
        if isinstance(value, str):
            for old_emoji, new_emoji in legacy_emojis.items():
                value = value.replace(old_emoji, new_emoji)
            value = re.sub(r"\bsoldes?\b", "PinkWallet", value, flags=re.IGNORECASE)
            return value
        if isinstance(value, list):
            return [migrate_value(item) for item in value]
        if isinstance(value, dict):
            return {key: migrate_value(item) for key, item in value.items()}
        return value

    data = migrate_value(data)

    # Les anciens embeds sauvegardés dans le panel restent compatibles, mais leur
    # vocabulaire et leurs unités sont automatiquement migrés vers PinkCoins.
    pinkcoin_embed_keys = {
        "menu_ticket_embed", "uber_eats_ticket_embed", "nitro_ticket_embed", "commande_embed",
        "commande_vp_embed", "cp_order_pending_embed", "cp_delivery_embed",
        "balance_ticket_embed",
    }
    for embed_key in pinkcoin_embed_keys:
        embed_data = data.get(embed_key)
        if not isinstance(embed_data, dict):
            continue
        embed_data = migrate_value(embed_data)
        def migrate_pinkcoin_units(value):
            if isinstance(value, str):
                value = value.replace("{paid} €", "{paid} PC")
                value = value.replace("{paid}€", "{paid} PC")
                value = value.replace("{balance} €", "{balance} PC")
                value = value.replace("{amount}€", "{amount} PC")
                return value
            if isinstance(value, list):
                return [migrate_pinkcoin_units(item) for item in value]
            if isinstance(value, dict):
                return {key: migrate_pinkcoin_units(item) for key, item in value.items()}
            return value
        data[embed_key] = migrate_pinkcoin_units(embed_data)

    # Les embeds de commande et de livraison doivent rester compacts. On retire
    # aussi les images provenant d'anciens réglages sauvegardés depuis le panel.
    delivery_embed_keys = {
        "menu_ticket_embed", "uber_eats_ticket_embed", "nitro_ticket_embed",
        "commande_embed", "commande_vp_embed", "commande_finalisee",
        "cp_order_pending_embed", "cp_delivery_embed",
    }
    for embed_key in delivery_embed_keys:
        embed_data = data.get(embed_key)
        if isinstance(embed_data, dict):
            embed_data.pop("image_key", None)
            embed_data.pop("image_url", None)

    tarifs_data = data.get("tarifs_embed")
    if isinstance(tarifs_data, dict):
        tarifs_data["title"] = "🎟️ PINKSHOP — COMMANDES"
        tarifs_data["gift_card_line_template"] = "**{amount} € reçus** → **{price} PC**"
        tarifs_data["uber_eats_line_template"] = "**{drop} € estimés** → **{price} PC**"
        tarifs_data["nitro_value_template"] = "**{price} PC**"

    emoji_catalog = data.get("emojis", {}) if isinstance(data.get("emojis"), dict) else {}
    # Ces identifiants sont la source officielle PinkGift : ils remplacent aussi
    # les anciens IDs encore présents dans une configuration sauvegardée du panel.
    for product_key, product in PRODUCT_CONFIG.items():
        emoji_catalog.setdefault(product_key, product["emoji"])
    for product_key in {
        "GOOGLE_PLAY", "STEAM", "DISCORD_NITRO", "PLAYSTATION", "NINTENDO",
        "ZARA", "SEPHORA", "ZALANDO", "ADIDAS",
        "FOOT_LOCKER", "SHEIN", "NIKE", "UBEREATS", "DELIVEROO", "AMAZON",
        "CARREFOUR", "INTERMARCHE", "APPLE", "JOYBUY", "SMYTHS_TOYS", "LEGO",
        "TESLA", "AIRBNB", "SKRILL",
    }:
        emoji_catalog[product_key] = PRODUCT_CONFIG[product_key]["emoji"]
    for category_key, category in PRODUCT_CATEGORY_CONFIG.items():
        emoji_catalog[f"CATEGORY_{category_key}"] = category["emoji"]
    emoji_catalog.update({
        "BASIC_FIT": OTHER_SERVICES["BASIC_FIT"]["emoji"],
        "DISCORD_DECORATIONS": OTHER_SERVICES["DISCORD_DECORATIONS"]["emoji"],
        "NETFLIX": SUBSCRIPTION_SERVICES["NETFLIX"]["emoji"],
        "SPOTIFY": SUBSCRIPTION_SERVICES["SPOTIFY"]["emoji"],
        "YOUTUBE_PREMIUM": SUBSCRIPTION_SERVICES["YOUTUBE_PREMIUM"]["emoji"],
    })
    emoji_catalog.setdefault("CP", "<:cp:1528128623117205624>")
    emoji_catalog.setdefault("QUESTION", "<:questionmark:1525869342506614784>")
    data["emojis"] = emoji_catalog

    tarifs = data.get("tarifs_embed")
    if isinstance(tarifs, dict) and isinstance(tarifs.get("description"), list):
        product_by_name = {
            "".join(c for c in unicodedata.normalize("NFD", product["display"].lower()) if unicodedata.category(c) != "Mn").replace(" ", "").replace("_", ""): product_key
            for product_key, product in PRODUCT_CONFIG.items()
        }
        category_by_name = {
            "gaming": PRODUCT_CATEGORY_CONFIG["GAMING"]["emoji"],
            "mode&beaute": PRODUCT_CATEGORY_CONFIG["MODE_BEAUTE"]["emoji"],
            "food&livraison": PRODUCT_CATEGORY_CONFIG["FOOD"]["emoji"],
            "shopping&courses": PRODUCT_CATEGORY_CONFIG["COURSES"]["emoji"],
            "jouets": PRODUCT_CATEGORY_CONFIG["JOUETS"]["emoji"],
            "voyage&auto": PRODUCT_CATEGORY_CONFIG["VOYAGE"]["emoji"],
            "prepaye": PRODUCT_CATEGORY_CONFIG["PREPAYES"]["emoji"],
        }
        synced_lines = []
        for raw_line in tarifs["description"]:
            line = str(raw_line)
            label_match = re.search(r"\*\*([^*]+)\*\*", line)
            if label_match:
                normalized_label = "".join(c for c in unicodedata.normalize("NFD", label_match.group(1).lower()) if unicodedata.category(c) != "Mn").replace(" ", "").replace("_", "")
                product_key = product_by_name.get(normalized_label)
                if product_key:
                    line = f"{emoji_catalog[product_key]} **{label_match.group(1)}**"
                elif normalized_label in category_by_name:
                    line = f"{category_by_name[normalized_label]} **{label_match.group(1)}**"
            synced_lines.append(line)
        tarifs["description"] = synced_lines
        if tarifs.get("uber_eats_field_name") in {None, "", "🍔 Uber Eats"}:
            tarifs["uber_eats_field_name"] = f"{emoji_catalog['UBEREATS']} Uber Eats"
        if tarifs.get("nitro_field_name") in {None, "", "💎 Discord Nitro"}:
            tarifs["nitro_field_name"] = f"{emoji_catalog['DISCORD_NITRO']} Discord Nitro"

    valo = data.get("valo_embed")
    if isinstance(valo, dict):
        valo.setdefault("region_emojis", {"EUROPE": "🇪🇺", "TURQUIE": "🇹🇷"})
        template = str(valo.get("pack_line_template") or "")
        template = re.sub(r"\{price\}\s*€", "{price} PC", template)
        if "{official}" not in template:
            valo["pack_line_template"] = f"{template} · origine ≈ ~~{{official}} €~~".strip()
        else:
            valo["pack_line_template"] = template
        description = valo.get("description")
        if isinstance(description, list):
            cleaned = []
            region_labels = tuple(region["label"].lower() for region in VALO_REGIONS.values())
            for raw_line in description:
                line = str(raw_line)
                lowered = line.lower()
                if any(label in lowered for label in region_labels) and "**" in line:
                    continue
                if "vp" in lowered and re.search(r"\d+(?:[.,]\d+)?\s*€", line):
                    continue
                if not line and (not cleaned or not cleaned[-1]):
                    continue
                cleaned.append(line)
            while cleaned and not cleaned[-1]:
                cleaned.pop()
            valo["description"] = cleaned

    wallet_embed = data.get("balance_embed")
    if isinstance(wallet_embed, dict):
        wallet_embed["title"] = "<:cash:1525568414117134528> PinkWallet & PinkCoins"
        description = wallet_embed.get("description")
        if isinstance(description, list) and not any("100 PinkCoins" in str(line) for line in description):
            insert_at = 1 if description else 0
            description[insert_at:insert_at] = ["", "> 1 € = 100 PinkCoins", "> Minimum : 2 000 PinkCoins (20 €)"]
        elif isinstance(description, str) and "100 PinkCoins" not in description:
            wallet_embed["description"] = description + "\n\n> 1 € = 100 PinkCoins\n> Minimum : 2 000 PinkCoins (20 €)"

    wallet_ticket = data.get("balance_ticket_embed")
    if isinstance(wallet_ticket, dict):
        description = wallet_ticket.get("description")
        if isinstance(description, list) and not any("100 PinkCoins" in str(line) for line in description):
            description.append("Chaque euro déposé est converti en **100 PinkCoins**.")
        elif isinstance(description, str) and "100 PinkCoins" not in description:
            wallet_ticket["description"] = description + "\nChaque euro déposé est converti en **100 PinkCoins**."
    return data


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
            return normalize_embed_configuration(apply_embed_overrides(data))
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
                return normalize_embed_configuration(apply_embed_overrides(data))
            except Exception as e:
                print(f"Erreur chargement config_embeds.json local : {e}")
    return normalize_embed_configuration(apply_embed_overrides(DEFAULT_EMBED_DATA))


def get_emoji_catalog():
    configured = load_embed_texts().get("emojis", {})
    return configured if isinstance(configured, dict) else {}


def get_product_emoji(product_key, catalog=None):
    """Garde les emojis des menus et embeds synchronisés avec un seul chargement JSON."""
    configured = catalog if isinstance(catalog, dict) else get_emoji_catalog()
    if configured.get(product_key):
        return str(configured[product_key])
    return PRODUCT_CONFIG.get(product_key, {}).get("emoji", "🎁")


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


def build_json_embed(embed_key, variables=None, data_override=None):
    data = data_override if isinstance(data_override, dict) else load_embed_texts().get(embed_key, DEFAULT_EMBED_DATA.get(embed_key, {}))
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
        "📦 **Amazon**": f"{PRODUCT_CONFIG['AMAZON']['emoji']} **Amazon**",
        "🛒 **Carrefour**": f"{PRODUCT_CONFIG['CARREFOUR']['emoji']} **Carrefour**",
        "🏬 **Intermarché**": f"{PRODUCT_CONFIG['INTERMARCHE']['emoji']} **Intermarché**",
        "🏬 **Intermarche**": f"{PRODUCT_CONFIG['INTERMARCHE']['emoji']} **Intermarche**",
        "👕 **Zara**": "<:zara:1528775696347037697> **Zara**",
        "💄 **Sephora**": "<:sephora:1528775577757159454> **Sephora**",
        "🍔 **Uber Eats**": f"{PRODUCT_CONFIG['UBEREATS']['emoji']} **Uber Eats**",
        "🍎 **Apple**": f"{PRODUCT_CONFIG['APPLE']['emoji']} **Apple**",
        "🎮 **Google Play**": f"{PRODUCT_CONFIG['GOOGLE_PLAY']['emoji']} **Google Play**",
        "🎮 **Steam**": f"{PRODUCT_CONFIG['STEAM']['emoji']} **Steam**",
        "🎬 **Netflix**": f"{SUBSCRIPTION_SERVICES['NETFLIX']['emoji']} **Netflix**",
        "🧸 **Smyths Toys**": f"{PRODUCT_CONFIG['SMYTHS_TOYS']['emoji']} **Smyths Toys**",
        "👟 **Zalando**": f"{PRODUCT_CONFIG['ZALANDO']['emoji']} **Zalando**",
        "🧸 **King Jouet**": "<:kingjouet:1519907322783338557> **King Jouet**",
        "🧱 **LEGO**": f"{PRODUCT_CONFIG['LEGO']['emoji']} **LEGO**",
        "👟 **Adidas**": f"{PRODUCT_CONFIG['ADIDAS']['emoji']} **Adidas**",
        "👟 **Foot Locker**": f"{PRODUCT_CONFIG['FOOT_LOCKER']['emoji']} **Foot Locker**",
        "🍽️ **Deliveroo**": f"{PRODUCT_CONFIG['DELIVEROO']['emoji']} **Deliveroo**",
        "✨ **Claude**": "<:claude:1519906842006913065> **Claude**",
        "🏠 **Airbnb**": f"{PRODUCT_CONFIG['AIRBNB']['emoji']} **Airbnb**",
        "🎮 **Xbox**": "<:xbox:1519907418836828230> **Xbox**",
        "🎮 **PlayStation**": "<:playstation:1528357122520387584> **PlayStation**",
        "💳 **Paysafecard**": "<:paysafe:1528698901836726354> **Paysafecard**",
        "📚 **Fnac**": "<:fnac:1519906718140727387> **Fnac**",
        "🎮 **Nintendo**": f"{PRODUCT_CONFIG['NINTENDO']['emoji']} **Nintendo**",
        "👟 **Nike**": f"{PRODUCT_CONFIG['NIKE']['emoji']} **Nike**",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def ticket_channel_name(emoji: str, label: str, suffix: str) -> str:
    clean_label = label.upper().replace(" ", "-").replace("_", "-")
    clean_suffix = str(suffix).replace(" ", "-")
    return f"{emoji}-{clean_label}-{clean_suffix}"[:95]


async def pin_first_bot_ticket_message(channel, fallback_message=None):
    """Épingle le plus ancien message normal du bot dans un ticket ou un fil de commande."""
    try:
        bot_user_id = bot.user.id if bot.user else 0
        first_bot_message = None
        created_at = getattr(channel, "created_at", None)
        after = created_at - datetime.timedelta(seconds=2) if created_at else None
        async for candidate in channel.history(limit=100, after=after, oldest_first=True):
            if (
                bot_user_id
                and candidate.author.id == bot_user_id
                and candidate.type is discord.MessageType.default
            ):
                first_bot_message = candidate
                break
        target = first_bot_message or fallback_message
        if target is not None and not target.pinned:
            await target.pin(reason="Premier message du ticket PinkGift")
        return target
    except (discord.Forbidden, discord.NotFound, discord.HTTPException, AttributeError, TypeError) as error:
        print(f"Erreur épinglage premier message du ticket {getattr(channel, 'id', 0)}: {error}")
        return fallback_message


def bot_ticket_permission_overwrite():
    permissions = {
        "view_channel": True,
        "send_messages": True,
        "read_message_history": True,
        "manage_messages": True,
    }
    if hasattr(discord.Permissions.none(), "pin_messages"):
        permissions["pin_messages"] = True
    return discord.PermissionOverwrite(**permissions)


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
        if not order_counts_as_purchase(order):
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

    if service_upper.startswith("COD POINTS") or service_upper.startswith("CALL OF DUTY POINTS"):
        received = f"{order.get('received_label') or ''} {service}"
        for pack_key, pack in CP_PACKS.items():
            if re.search(rf"(?<!\d){pack['points']}(?!\d)", received.replace(" ", "")):
                return costs["cp"][pack_key]
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
    """Calcule le CA dès l'achat, sans attendre la livraison."""
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
        if not order_counts_as_purchase(order):
            continue
        purchased_at = parse_datetime_value(order.get("created_at"))
        if purchased_at is None:
            continue
        purchased_at = purchased_at.astimezone(datetime.timezone.utc)
        if not start <= purchased_at < end:
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


def private_order_thread_setting_key(guild_id: int, user_id: int, parent_channel_id: int) -> str:
    return f"private_order_thread:{int(guild_id)}:{int(user_id)}:{int(parent_channel_id)}"


def save_private_order_thread_reference(guild_id: int, user_id: int, parent_channel_id: int, channel_id: int):
    try:
        set_panel_setting(
            private_order_thread_setting_key(guild_id, user_id, parent_channel_id),
            {"channel_id": int(channel_id), "updated_at": utc_now().isoformat()},
        )
    except Exception as error:
        print(f"Erreur sauvegarde fil privé de commande {channel_id}: {error}")


def recent_private_order_thread_ids(guild_id: int, user_id: int, parent_channel_id: int, limit=25):
    candidate_ids = []
    setting_key = private_order_thread_setting_key(guild_id, user_id, parent_channel_id)
    saved = get_panel_setting(setting_key, {}) or {}
    try:
        saved_channel_id = int(saved.get("channel_id") if isinstance(saved, dict) else saved)
    except (TypeError, ValueError):
        saved_channel_id = 0
    if saved_channel_id:
        candidate_ids.append(saved_channel_id)

    try:
        if USE_SUPABASE:
            rows = supabase_request(
                "GET",
                f"orders?guild_id=eq.{int(guild_id)}&user_id=eq.{int(user_id)}"
                f"&select=channel_id&order=id.desc&limit={max(1, int(limit))}",
            ) or []
        else:
            with db_connect() as db:
                rows = [
                    dict(row)
                    for row in db.execute(
                        "SELECT channel_id FROM orders WHERE guild_id=? AND user_id=? "
                        "ORDER BY id DESC LIMIT ?",
                        (int(guild_id), int(user_id), max(1, int(limit))),
                    ).fetchall()
                ]
        for row in rows:
            try:
                channel_id = int(row.get("channel_id") or 0)
            except (AttributeError, TypeError, ValueError):
                continue
            if channel_id and channel_id not in candidate_ids:
                candidate_ids.append(channel_id)
    except Exception as error:
        print(f"Erreur recherche ancien fil de commande pour {user_id}: {error}")
    return candidate_ids


async def reusable_private_order_thread(guild, user, parent):
    setting_key = private_order_thread_setting_key(guild.id, user.id, parent.id)
    for channel_id in recent_private_order_thread_ids(guild.id, user.id, parent.id):
        thread = bot.get_channel(channel_id)
        if thread is None:
            try:
                thread = await bot.fetch_channel(channel_id)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                continue
        if (
            not isinstance(thread, discord.Thread)
            or thread.guild.id != guild.id
            or thread.parent_id != parent.id
        ):
            continue
        try:
            edit_options = {}
            if thread.archived or thread.locked:
                edit_options["archived"] = False
                if thread.locked:
                    edit_options["locked"] = False
            if thread.auto_archive_duration != PRIVATE_ORDER_THREAD_AUTO_ARCHIVE_MINUTES:
                edit_options["auto_archive_duration"] = PRIVATE_ORDER_THREAD_AUTO_ARCHIVE_MINUTES
            if edit_options:
                await thread.edit(
                    **edit_options,
                    reason=f"Nouvelle commande PinkGift de {user}",
                )
            await thread.add_user(user)
            save_private_order_thread_reference(guild.id, user.id, parent.id, thread.id)
            return thread
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
            print(f"Fil privé {channel_id} non réutilisable pour {user}: {error}")
    try:
        delete_panel_setting(setting_key)
    except Exception as error:
        print(f"Erreur nettoyage référence de fil privé pour {user}: {error}")
    return None


async def create_private_order_thread(guild, user, parent_channel_id: int, order_kind: str):
    """Réutilise le fil privé du client dans ce salon ou en crée un nouveau."""
    parent = guild.get_channel(parent_channel_id)
    if parent is None:
        try:
            parent = await bot.fetch_channel(parent_channel_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            parent = None
    if not isinstance(parent, discord.TextChannel):
        raise RuntimeError("Le salon parent des fils privés est introuvable ou n'est pas un salon textuel")

    existing_thread = await reusable_private_order_thread(guild, user, parent)
    if existing_thread is not None:
        return existing_thread

    thread_user = re.sub(r"[\r\n]+", " ", user.display_name).strip() or str(user.id)
    thread_prefixes = {
        "commande-carte": "🎀・",
        "commande-valorant": "💎・",
    }
    thread_prefix = thread_prefixes.get(order_kind, f"{order_kind}-")
    thread = await parent.create_thread(
        name=f"{thread_prefix}{thread_user}"[:100],
        type=discord.ChannelType.private_thread,
        auto_archive_duration=PRIVATE_ORDER_THREAD_AUTO_ARCHIVE_MINUTES,
        invitable=False,
        reason=f"Commande privée PinkGift de {user}",
    )
    try:
        await thread.add_user(user)
    except Exception:
        try:
            await thread.delete(reason="Client impossible à ajouter au fil privé")
        except discord.HTTPException:
            pass
        raise
    save_private_order_thread_reference(guild.id, user.id, parent.id, thread.id)
    return thread

async def create_product_ticket(interaction, product_key, amount):
    guild = interaction.guild
    user = interaction.user
    cfg = PRODUCT_CONFIG.get(product_key)
    if guild is None or cfg is None:
        await finish_ephemeral_flow(interaction, "❌ Impossible de créer cette commande.")
        return
    if not product_is_available(product_key):
        await finish_ephemeral_flow(
            interaction,
            f"{STOCK_KO_EMOJI} **{cfg['display']}** est actuellement en rupture.",
        )
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
            await finish_ephemeral_flow(interaction, "❌ Pack Uber Eats invalide.")
            return
    elif product_key != "DISCORD_NITRO":
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            amount = 0
        if amount not in GIFT_CARD_AMOUNTS:
            await finish_ephemeral_flow(interaction, "❌ Montant de carte cadeau invalide.")
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
            await finish_ephemeral_flow(
                interaction,
                f"❌ PinkCoins insuffisants. Il faut **{format_pinkcoins(paid_amount)}**, ton PinkWallet contient **{format_pinkcoins(current_balance)}**. Utilise le panneau `/pinkcoins` pour le recharger.",
            )
            return
        try:
            ticket_channel = await create_private_order_thread(
                guild,
                user,
                GIFT_CARD_THREAD_CHANNEL_ID,
                "commande-carte",
            )
        except Exception as error:
            await finish_ephemeral_flow(
                interaction,
                "⏳ Discord ne peut pas créer le fil privé de commande actuellement. Réessaie dans quelques minutes.",
            )
            print(f"Erreur création fil privé commande pour {user}: {error}")
            return
        try:
            remaining_balance = change_balance(guild.id, user.id, -paid_amount, bot.user.id if bot.user else 0)
        except Exception as error:
            print(f"Erreur débit PinkCoins de {user}: {error}")
            try:
                await ticket_channel.delete(reason="Débit des PinkCoins impossible")
            except discord.HTTPException:
                pass
            await finish_ephemeral_flow(
                interaction,
                "❌ Le débit des PinkCoins a échoué. Aucun PinkCoin n'a été retiré.",
            )
            return
        if product_key == "UBEREATS":
            embed_key = "uber_eats_ticket_embed"
        elif product_key == "DISCORD_NITRO":
            embed_key = "nitro_ticket_embed"
        else:
            embed_key = "menu_ticket_embed"
        embed = build_json_embed(embed_key, {
            "user": user.mention, "service": cfg["display"], "emoji": get_product_emoji(product_key),
            "amount": amount, "paid": pinkcoin_number(paid_amount), "drop": received_display, "balance": pinkcoin_number(remaining_balance)
        })
        try:
            order_message = await ticket_channel.send(content=user.mention, embed=embed)
            await pin_first_bot_ticket_message(ticket_channel, order_message)
        except Exception as error:
            try:
                change_balance(guild.id, user.id, paid_amount, bot.user.id if bot.user else 0)
            except Exception as refund_error:
                print(f"ERREUR REMBOURSEMENT {user}: {refund_error}")
            try:
                await ticket_channel.delete(reason="Commande impossible à publier")
            except discord.HTTPException:
                pass
            await finish_ephemeral_flow(
                interaction,
                "❌ L'envoi de la commande a échoué. Le montant a été recrédité.",
            )
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
        await finish_ephemeral_flow(
            interaction,
            f"✅ Commande ajoutée dans ton fil privé {ticket_channel.mention}. Ton PinkWallet contient maintenant **{format_pinkcoins(remaining_balance)}**.",
        )
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


def safe_component_emoji(value, fallback="🎁"):
    """N'envoie jamais à Discord un emoji custom supprimé ou inaccessible au bot."""
    try:
        parsed = discord.PartialEmoji.from_str(str(value or ""))
    except (TypeError, ValueError):
        return fallback
    if parsed.id is None:
        return parsed if parsed.name else fallback
    cached = bot.get_emoji(parsed.id)
    return cached if cached is not None else fallback


def discord_button_style(value, fallback=discord.ButtonStyle.primary):
    return {
        "primary": discord.ButtonStyle.primary,
        "secondary": discord.ButtonStyle.secondary,
        "success": discord.ButtonStyle.success,
        "danger": discord.ButtonStyle.danger,
    }.get(str(value or "").strip().lower(), fallback)


DISCORD_BUTTON_COLORS = {
    "primary": "#5865F2",
    "secondary": "#4E5058",
    "success": "#248046",
    "danger": "#DA373C",
}


def normalize_button_style(value, fallback="primary"):
    fallback = str(fallback or "primary").strip().lower()
    if fallback not in DISCORD_BUTTON_COLORS:
        fallback = "primary"
    candidate = str(value or "").strip().lower()
    if candidate in DISCORD_BUTTON_COLORS:
        return candidate
    legacy_color = candidate.upper()
    for style, color in DISCORD_BUTTON_COLORS.items():
        if legacy_color == color:
            return style
    return fallback


def get_menu_launcher_config(embed_key, label, emoji, style="primary"):
    data = load_embed_texts().get(embed_key, DEFAULT_EMBED_DATA.get(embed_key, {}))
    return {
        "label": str(data.get("menu_button_label") or label)[:80],
        "emoji": str(data.get("menu_button_emoji") or emoji),
        "style": normalize_button_style(
            data.get("menu_button_style") or data.get("menu_button_color"),
            style,
        ),
    }


def get_component_button_config(embed_key, button_key, label, emoji="", style="secondary"):
    data = load_embed_texts().get(embed_key, DEFAULT_EMBED_DATA.get(embed_key, {}))
    buttons = data.get("component_buttons", {}) if isinstance(data, dict) else {}
    configured = buttons.get(button_key, {}) if isinstance(buttons, dict) else {}
    return {
        "label": str(configured.get("label") or label)[:80],
        "emoji": str(configured.get("emoji") or emoji),
        "style": normalize_button_style(
            configured.get("style") or configured.get("color"),
            style,
        ),
    }


def apply_component_button_config(button, embed_key, button_key, label, emoji="", style="secondary"):
    config = get_component_button_config(embed_key, button_key, label, emoji, style)
    button.label = config["label"]
    button.emoji = safe_component_emoji(config["emoji"], emoji or "✨")
    button.style = discord_button_style(
        config["style"],
        discord_button_style(style),
    )
    return button


ACTIVE_EPHEMERAL_RESPONSES = {}


def ephemeral_response_key(interaction):
    guild_id = int(interaction.guild_id or 0)
    user_id = int(getattr(interaction.user, "id", 0) or 0)
    return guild_id, user_id


async def clear_previous_ephemeral(interaction):
    key = ephemeral_response_key(interaction)
    previous_entry = ACTIVE_EPHEMERAL_RESPONSES.pop(key, None)
    if isinstance(previous_entry, tuple):
        created_at, previous = previous_entry
        if time.time() - float(created_at or 0) > 900:
            return
    else:
        previous = previous_entry
    if previous is None or previous is interaction:
        return
    try:
        await previous.delete_original_response()
    except (discord.NotFound, discord.HTTPException):
        pass


async def send_single_ephemeral(interaction, content, view=None, embed=None):
    await clear_previous_ephemeral(interaction)
    kwargs = {"content": content, "view": view, "ephemeral": True}
    if embed is not None:
        kwargs["embed"] = embed
    await interaction.response.send_message(**kwargs)
    ACTIVE_EPHEMERAL_RESPONSES[ephemeral_response_key(interaction)] = (time.time(), interaction)


async def defer_single_ephemeral(interaction):
    await clear_previous_ephemeral(interaction)
    await interaction.response.defer(ephemeral=True, thinking=True)
    ACTIVE_EPHEMERAL_RESPONSES[ephemeral_response_key(interaction)] = (time.time(), interaction)


async def finish_ephemeral_flow(interaction, content):
    """Remplace le message éphémère du parcours au lieu d'en créer un second."""
    await interaction.edit_original_response(content=content, view=None)


def stock_partial_emoji(available):
    return safe_component_emoji(
        STOCK_OK_EMOJI if available else STOCK_KO_EMOJI,
        "✅" if available else "❌",
    )


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
        await finish_ephemeral_flow(interaction, "❌ Région ou pack Valorant invalide.")
        return
    if not valo_pack_is_available(region_key, pack_key):
        await finish_ephemeral_flow(
            interaction,
            f"{STOCK_KO_EMOJI} Ce pack Valorant est actuellement en rupture.",
        )
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
            await finish_ephemeral_flow(
                interaction,
                f"❌ PinkCoins insuffisants. Il faut **{format_pinkcoins(price)}**, ton PinkWallet contient **{format_pinkcoins(current_balance)}**.",
            )
            return
        try:
            ticket_channel = await create_private_order_thread(
                guild,
                user,
                VALORANT_THREAD_CHANNEL_ID,
                "commande-valorant",
            )
        except Exception as error:
            await finish_ephemeral_flow(
                interaction,
                "⏳ Discord ne peut pas créer le fil privé Valorant actuellement.",
            )
            print(f"Erreur création fil privé Valorant pour {user}: {error}")
            return
        try:
            remaining_balance = change_balance(guild.id, user.id, -price, bot.user.id if bot.user else 0)
        except Exception as error:
            print(f"Erreur débit Valorant de {user}: {error}")
            try:
                await ticket_channel.delete(reason="Débit des PinkCoins Valorant impossible")
            except discord.HTTPException:
                pass
            await finish_ephemeral_flow(
                interaction,
                "❌ Le débit des PinkCoins a échoué. Aucun PinkCoin n'a été retiré.",
            )
            return
        code_pending = (chr(96) * 3) + "\nEn attente...\n" + (chr(96) * 3)
        embed = build_json_embed("commande_vp_embed", {
            "emoji": get_product_emoji("VALORANT"), "user": user.mention,
            "region": f"{region_emoji} {region_label}", "pack": pack, "amount": pinkcoin_number(price),
            "code": code_pending, "balance": pinkcoin_number(remaining_balance)
        })
        try:
            order_message = await ticket_channel.send(content=user.mention, embed=embed)
            await pin_first_bot_ticket_message(ticket_channel, order_message)
        except Exception as error:
            try:
                change_balance(guild.id, user.id, price, bot.user.id if bot.user else 0)
            except Exception as refund_error:
                print(f"ERREUR REMBOURSEMENT VALORANT {user}: {refund_error}")
            try:
                await ticket_channel.delete(reason="Commande Valorant impossible à publier")
            except discord.HTTPException:
                pass
            await finish_ephemeral_flow(
                interaction,
                "❌ L'envoi a échoué. Le montant a été recrédité.",
            )
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
        await finish_ephemeral_flow(
            interaction,
            f"✅ {region_emoji} **{pack} ({region_label})** commandés dans ton fil privé {ticket_channel.mention}. Ton PinkWallet contient maintenant **{format_pinkcoins(remaining_balance)}**.",
        )


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
            options.append(discord.SelectOption(label=f"{pack['label']} — {format_pinkcoins(prices[pack_key], short=True)}", value=pack_key, emoji=stock_partial_emoji(available), description=stock_label(available)))
        super().__init__(placeholder="Choisis ton pack Valorant Points", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await create_valo_order(interaction, self.region_key, self.values[0])


class ValoPackView(discord.ui.View):
    def __init__(self, region_key):
        super().__init__(timeout=180)
        self.add_item(ValoPackSelect(region_key))


class ValoOrderLauncherView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        config = get_menu_launcher_config(
            "valo_embed",
            "Commander des VP",
            "🎮",
            "success",
        )
        button = discord.ui.Button(
            label=config["label"],
            emoji=safe_component_emoji(config["emoji"], "🎮"),
            style=discord_button_style(
                config["style"],
                discord.ButtonStyle.success,
            ),
            custom_id="pinkgift_start_valo_order",
        )
        button.callback = self.start_valo_order
        self.add_item(button)

    async def start_valo_order(self, interaction: discord.Interaction):
        # Répond immédiatement à Discord avant toute lecture de stock.
        await defer_single_ephemeral(interaction)
        await interaction.edit_original_response(
            content="Choisis d'abord ta région Valorant :",
            view=ValoRegionView()
        )


async def create_cp_manual_ticket(interaction):
    """Ouvre une demande CP manuelle sans lire ni modifier le PinkWallet du client."""
    guild = interaction.guild
    user = interaction.user
    if guild is None:
        await finish_ephemeral_flow(interaction, "❌ Cette demande doit être faite depuis le serveur.")
        return

    category = guild.get_channel(CP_TICKET_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        await finish_ephemeral_flow(
            interaction,
            "❌ La catégorie des tickets CP est introuvable ou mal configurée.",
        )
        return

    ticket_channel = next(
        (
            channel for channel in category.text_channels
            if channel.topic == f"pinkgift-cp-manual:{user.id}" and not channel.name.startswith("closed-")
        ),
        None,
    )
    if ticket_channel is None:
        staff_role = guild.get_role(STAFF_ROLE_ID)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        me = guild.me or (guild.get_member(bot.user.id) if bot.user else None)
        if me:
            overwrites[me] = bot_ticket_permission_overwrite()
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        try:
            ticket_channel = await guild.create_text_channel(
                name=f"🪙・cp-{user.display_name}"[:95],
                category=category,
                topic=f"pinkgift-cp-manual:{user.id}",
                overwrites=overwrites,
                reason=f"Demande manuelle COD Points de {user}",
            )
            opening_message = await ticket_channel.send(
                content=f"{user.mention} | <@&{STAFF_ROLE_ID}>",
                embed=build_json_embed("cp_manual_ticket_embed", {"user": user.mention}),
                view=CloseTicketView(user.id),
            )
            await pin_first_bot_ticket_message(ticket_channel, opening_message)
        except discord.HTTPException as error:
            print(f"Erreur création ticket CP manuel pour {user}: {error}")
            await finish_ephemeral_flow(
                interaction,
                "⏳ Discord ne peut pas créer le ticket CP actuellement.",
            )
            return

    await finish_ephemeral_flow(
        interaction,
        f"✅ Ton ticket CP est ouvert : {ticket_channel.mention}\n"
        "Indique le nombre de CP souhaité et combien tu proposes de payer. **Aucun PinkCoin n'a été débité.**",
    )


async def create_cp_order(interaction, pack_key):
    guild = interaction.guild
    user = interaction.user
    pack_key = str(pack_key)
    pack = CP_PACKS.get(pack_key)
    if guild is None or pack is None:
        await interaction.followup.send("❌ Pack COD Points invalide.", ephemeral=True)
        return

    lock = ORDER_LOCKS.setdefault((guild.id, user.id), asyncio.Lock())
    async with lock:
        pricing = get_pricing_config()
        purchase_costs = get_purchase_cost_config()
        price = pricing["cp"][pack_key]
        purchase_cost = purchase_costs["cp"][pack_key]
        current_balance = get_balance(guild.id, user.id)
        if current_balance < price:
            await interaction.followup.send(
                f"❌ PinkCoins insuffisants. Il faut **{format_pinkcoins(price)}**, ton PinkWallet contient **{format_pinkcoins(current_balance)}**. Recharge-le avec `/pinkcoins`.",
                ephemeral=True,
            )
            return

        category = guild.get_channel(CP_TICKET_CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.followup.send("❌ La catégorie des tickets CP est introuvable ou mal configurée.", ephemeral=True)
            return

        ticket_channel = next(
            (
                channel for channel in category.text_channels
                if channel.topic == f"pinkgift-cp-owner:{user.id}" and not channel.name.startswith("closed-")
            ),
            None,
        )
        if ticket_channel is None:
            staff_role = guild.get_role(STAFF_ROLE_ID)
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            }
            me = guild.me or (guild.get_member(bot.user.id) if bot.user else None)
            if me:
                overwrites[me] = bot_ticket_permission_overwrite()
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            try:
                ticket_channel = await guild.create_text_channel(
                    name=f"🪙・cp-{user.display_name}"[:95],
                    category=category,
                    topic=f"pinkgift-cp-owner:{user.id}",
                    overwrites=overwrites,
                    reason=f"Commande COD Points de {user}",
                )
            except discord.HTTPException as error:
                print(f"Erreur création ticket CP pour {user}: {error}")
                await interaction.followup.send("⏳ Discord ne peut pas créer le ticket CP actuellement.", ephemeral=True)
                return

        try:
            remaining_balance = change_balance(guild.id, user.id, -price, bot.user.id if bot.user else 0)
        except Exception as error:
            print(f"Erreur débit CP de {user}: {error}")
            await interaction.followup.send("❌ Le débit des PinkCoins a échoué. Aucun PinkCoin n'a été retiré.", ephemeral=True)
            return

        embed = build_json_embed("cp_order_pending_embed", {
            "user": user.mention,
            "points": f"{pack['points']:,}".replace(",", " "),
            "paid": pinkcoin_number(price),
            "balance": pinkcoin_number(remaining_balance),
        })
        try:
            order_message = await ticket_channel.send(
                content=f"{user.mention} | <@&{STAFF_ROLE_ID}>",
                embed=embed,
                view=CPPendingOrderView(),
            )
            await pin_first_bot_ticket_message(ticket_channel, order_message)
        except Exception as error:
            try:
                change_balance(guild.id, user.id, price, bot.user.id if bot.user else 0)
            except Exception as refund_error:
                print(f"ERREUR REMBOURSEMENT CP {user}: {refund_error}")
            print(f"Erreur création commande CP pour {user}: {error}")
            await interaction.followup.send("❌ La commande n'a pas pu être créée. Le montant a été recrédité.", ephemeral=True)
            return

        service = f"COD Points {pack['points']} CP"
        try:
            save_order(
                guild.id,
                ticket_channel.id,
                order_message.id,
                user.id,
                service,
                pack["points"],
                price,
                user.name,
                f"{pack['points']} CP",
            )
            save_order_purchase_cost(order_message.id, purchase_cost)
        except Exception as error:
            try:
                change_balance(guild.id, user.id, price, bot.user.id if bot.user else 0)
            except Exception as refund_error:
                print(f"ERREUR REMBOURSEMENT CP après sauvegarde {user}: {refund_error}")
            await order_message.edit(
                content=user.mention,
                embed=discord.Embed(
                    title="❌ Commande CP non enregistrée",
                    description="La commande n'a pas été enregistrée et le montant a été recrédité.",
                    color=discord.Color.red(),
                ),
                view=CloseTicketView(user.id),
            )
            print(f"Erreur sauvegarde commande CP: {error}")
            await interaction.followup.send("❌ La commande n'a pas été enregistrée. Le montant a été recrédité.", ephemeral=True)
            return
        try:
            record_referral_purchase(guild.id, user.id, order_message.id, price, purchase_cost, service)
        except Exception as error:
            print(f"Erreur calcul parrainage CP de {user}: {error}")
        await interaction.followup.send(
            f"✅ Commande de **{pack['points']:,} CP** enregistrée dans {ticket_channel.mention}. Le code sera livré dès sa réception. PinkWallet : **{format_pinkcoins(remaining_balance)}**.".replace(",", " "),
            ephemeral=True,
        )


def can_manage_cp_order(member):
    return bool(
        member
        and (
            member.guild_permissions.manage_guild
            or any(role.id == STAFF_ROLE_ID for role in getattr(member, "roles", []))
        )
    )


async def send_order_delivery_ghost_ping(channel, user_id):
    """Notifie discrètement le client dans son fil lorsqu'une livraison est prête."""
    ping_message = None
    try:
        ping_message = await channel.send(
            f"<@{int(user_id)}>",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
        await asyncio.sleep(1)
    except Exception as error:
        print(f"Erreur ghost ping livraison pour {user_id} dans {getattr(channel, 'id', '?')}: {error}")
    finally:
        if ping_message is not None:
            try:
                await ping_message.delete()
            except discord.HTTPException as error:
                print(f"Erreur suppression ghost ping livraison {ping_message.id}: {error}")


async def deliver_cp_order_to_discord(order, code):
    code = normalize_cp_code(code)
    if not code:
        raise ValueError("Le code est vide")
    channel = bot.get_channel(int(order["channel_id"]))
    if channel is None:
        channel = await bot.fetch_channel(int(order["channel_id"]))
    message = await channel.fetch_message(int(order["message_id"]))
    balance = get_balance(int(order["guild_id"]), int(order["user_id"]))
    displayed_code = code.replace("`", "ˋ")
    embed = build_json_embed("cp_delivery_embed", {
        "user": f"<@{int(order['user_id'])}>",
        "points": str(order.get("received_label") or order.get("amount") or "COD Points").replace(" CP", ""),
        "paid": pinkcoin_number(order.get("paid") or 0),
        "balance": pinkcoin_number(balance),
        "code": f"```\n{displayed_code}\n```",
    })
    await message.edit(
        content=f"<@{int(order['user_id'])}>",
        embed=embed,
        view=CloseTicketView(int(order["user_id"])),
    )
    await send_order_delivery_ghost_ping(channel, order["user_id"])
    mark_order_delivered(int(order["id"]), code)


async def show_order_refund_on_discord(order, new_balance):
    channel = bot.get_channel(int(order["channel_id"]))
    if channel is None:
        channel = await bot.fetch_channel(int(order["channel_id"]))
    message = await channel.fetch_message(int(order["message_id"]))
    cancelled = discord.Embed(
        title="↩️ Commande annulée et remboursée",
        description=(
            f"<@{int(order['user_id'])}>, la commande **{order.get('service') or 'PinkGift'}** a été annulée et "
            f"**{format_pinkcoins(order.get('paid') or 0)}** ont été recrédités.\n"
            f"Ton PinkWallet contient maintenant **{format_pinkcoins(new_balance)}**."
        ),
        color=discord.Color.red(),
    )
    cancelled.set_footer(text="PinkGift — Commande remboursée")
    await message.edit(
        content=f"<@{int(order['user_id'])}>",
        embed=cancelled,
        view=None if isinstance(channel, discord.Thread) else CloseTicketView(int(order["user_id"])),
    )


class CPCodeDeliveryModal(discord.ui.Modal, title="Livrer la commande COD Points"):
    code = discord.ui.TextInput(
        label="Code reçu du fournisseur",
        placeholder="Colle le code COD Points ici",
        min_length=2,
        max_length=500,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, message_id):
        super().__init__()
        self.message_id = int(message_id)

    async def on_submit(self, interaction: discord.Interaction):
        if not can_manage_cp_order(interaction.user):
            await send_single_ephemeral(interaction, "❌ Ce bouton est réservé au staff.")
            return
        await defer_single_ephemeral(interaction)
        order = get_cp_order(message_id=self.message_id)
        if not order or str(order.get("status") or "pending").lower() != "pending":
            await finish_ephemeral_flow(interaction, "❌ Cette commande n'est plus en attente.")
            return
        lock = ORDER_LOCKS.setdefault((int(order["guild_id"]), int(order["user_id"])), asyncio.Lock())
        async with lock:
            order = get_cp_order(order_id=order["id"])
            if not order or str(order.get("status") or "pending").lower() != "pending":
                await finish_ephemeral_flow(
                    interaction,
                    "❌ Cette commande vient déjà d'être traitée.",
                )
                return
            mark_order_status(order["id"], "delivering")
            try:
                await deliver_cp_order_to_discord(order, str(self.code.value))
            except Exception as error:
                mark_order_status(order["id"], "pending")
                print(f"Erreur livraison manuelle CP #{order['id']}: {error}")
                await finish_ephemeral_flow(
                    interaction,
                    f"❌ Livraison impossible : {error}",
                )
                return
        await finish_ephemeral_flow(
            interaction,
            "✅ Code livré au client et commande marquée comme terminée.",
        )


class CPPendingOrderView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        apply_component_button_config(
            self.children[0],
            "cp_order_pending_embed",
            "deliver_pending",
            "Livrer le code",
            "📩",
            "success",
        )

    @discord.ui.button(
        label="Livrer le code",
        emoji="📩",
        style=discord.ButtonStyle.success,
        custom_id="pinkgift_cp_deliver_pending",
    )
    async def deliver(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_manage_cp_order(interaction.user):
            await send_single_ephemeral(interaction, "❌ Ce bouton est réservé au staff.")
            return
        await interaction.response.send_modal(CPCodeDeliveryModal(interaction.message.id))

class CPPackSelect(discord.ui.Select):
    def __init__(self):
        prices = get_pricing_config()["cp"]
        options = []
        for pack_key, pack in CP_PACKS.items():
            points_label = f"{pack['points']:,}".replace(",", " ")
            options.append(discord.SelectOption(
                label=f"{points_label} CP — {format_price(prices[pack_key])} €",
                value=pack_key,
                emoji=safe_component_emoji("<:cp:1528128623117205624>", "🪙"),
                description="Commandé à la demande",
            ))
        super().__init__(placeholder="Choisis ton pack de COD Points", options=options, custom_id="pinkgift_cp_pack")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # Compatibilité avec un ancien menu encore ouvert au moment du déploiement :
        # aucune sélection CP ne peut désormais déclencher un débit de solde.
        await create_cp_manual_ticket(interaction)


class CPPackView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(CPPackSelect())


class CPOrderLauncherView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        apply_component_button_config(
            self.children[0],
            "cp_embed",
            "start_cp_order",
            "Commander des COD Points",
            "<:cp:1528128623117205624>",
            "success",
        )

    @discord.ui.button(
        label="Commander des COD Points",
        emoji="<:cp:1528128623117205624>",
        style=discord.ButtonStyle.success,
        custom_id="pinkgift_start_cp_order",
    )
    async def start_cp_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        await defer_single_ephemeral(interaction)
        await create_cp_manual_ticket(interaction)


def special_service_catalog(catalog_key):
    if catalog_key == "autres":
        return "Autres services", OTHER_SERVICES
    if catalog_key == "abonnements":
        return "Abonnements", SUBSCRIPTION_SERVICES
    return "", {}


async def resolve_discord_decoration_access_members(guild):
    members = []
    for user_id in DISCORD_DECORATION_ACCESS_USER_IDS:
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue
        members.append(member)
    return members


async def resolve_discord_decoration_revoked_members(guild):
    members = []
    for user_id in DISCORD_DECORATION_REVOKED_USER_IDS:
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue
        members.append(member)
    return members


async def grant_discord_decoration_ticket_access(ticket_channel, members):
    updated = 0
    for member in members:
        overwrite = ticket_channel.overwrites_for(member)
        if (
            overwrite.view_channel is True
            and overwrite.send_messages is True
            and overwrite.read_message_history is True
        ):
            continue
        overwrite.view_channel = True
        overwrite.send_messages = True
        overwrite.read_message_history = True
        try:
            await ticket_channel.set_permissions(
                member,
                overwrite=overwrite,
                reason="Accès aux tickets Décorations Discord/Nitro",
            )
            updated += 1
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
            print(f"Erreur accès décoration pour {member} dans {ticket_channel}: {error}")
    return updated


async def repair_discord_decoration_ticket_access():
    updated = 0
    for guild in bot.guilds:
        category = guild.get_channel(SPECIAL_TICKET_CATEGORY_ID)
        if not isinstance(category, discord.CategoryChannel):
            continue
        members = await resolve_discord_decoration_access_members(guild)
        revoked_members = await resolve_discord_decoration_revoked_members(guild)
        if not members and not revoked_members:
            continue
        for channel in category.text_channels:
            if not str(channel.topic or "").startswith("pinkgift-special:autres:"):
                continue
            is_decoration_ticket = False
            try:
                async for message in channel.history(limit=30):
                    if not message.embeds or (bot.user and message.author.id != bot.user.id):
                        continue
                    title = str(message.embeds[0].title or "")
                    normalized_title = "".join(
                        char
                        for char in unicodedata.normalize("NFD", title.lower())
                        if unicodedata.category(char) != "Mn"
                    )
                    if "decoration discord" in normalized_title:
                        is_decoration_ticket = True
                        break
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                continue
            if is_decoration_ticket:
                updated += await grant_discord_decoration_ticket_access(channel, members)
                try:
                    ticket_owner_id = int(str(channel.topic or "").rsplit(":", 1)[-1])
                except (TypeError, ValueError):
                    ticket_owner_id = 0
                for revoked_member in revoked_members:
                    if revoked_member.id == ticket_owner_id or revoked_member not in channel.overwrites:
                        continue
                    try:
                        await channel.set_permissions(
                            revoked_member,
                            overwrite=None,
                            reason="Retrait de l'accès spécial aux tickets Décorations Discord/Nitro",
                        )
                        updated += 1
                    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
                        print(f"Erreur retrait accès décoration pour {revoked_member} dans {channel}: {error}")
    return updated


COMMUNITY_APPLICATION_TYPES = {
    "parrainage": {
        "label": "parrainage",
        "channel_prefix": "🤝・parrainage",
        "ticket_embed": "parrainage_ticket_embed",
    },
    "recrutement": {
        "label": "recrutement",
        "channel_prefix": "📋・recrutement",
        "ticket_embed": "recrutement_ticket_embed",
    },
}


async def create_community_application_ticket(interaction, application_type):
    guild = interaction.guild
    user = interaction.user
    config = COMMUNITY_APPLICATION_TYPES.get(application_type)
    if guild is None or config is None:
        await finish_ephemeral_flow(interaction, "❌ Cette candidature est introuvable.")
        return

    category = guild.get_channel(COMMUNITY_APPLICATION_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        await finish_ephemeral_flow(
            interaction,
            "❌ La catégorie des candidatures est introuvable ou mal configurée.",
        )
        return

    lock = ORDER_LOCKS.setdefault(
        (guild.id, user.id, f"application:{application_type}"),
        asyncio.Lock(),
    )
    async with lock:
        topic = f"pinkgift-application:{application_type}:{user.id}"
        ticket_channel = next(
            (
                channel for channel in category.text_channels
                if channel.topic == topic and not channel.name.startswith("closed-")
            ),
            None,
        )
        if ticket_channel is not None:
            await finish_ephemeral_flow(
                interaction,
                f"ℹ️ Ta demande de {config['label']} existe déjà : {ticket_channel.mention}",
            )
            return

        staff_role = guild.get_role(STAFF_ROLE_ID)
        me = guild.me or (guild.get_member(bot.user.id) if bot.user else None)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            ),
        }
        if me:
            overwrites[me] = bot_ticket_permission_overwrite()
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

        safe_user = re.sub(r"[^a-z0-9-]", "", user.name.lower().replace(" ", "-")) or str(user.id)
        ticket_channel = None
        try:
            ticket_channel = await guild.create_text_channel(
                name=f"{config['channel_prefix']}-{safe_user}"[:95],
                category=category,
                topic=topic,
                overwrites=overwrites,
                reason=f"Candidature {config['label']} de {user}",
            )
            opening_message = await ticket_channel.send(
                content=f"{user.mention} | <@&{STAFF_ROLE_ID}>",
                embed=build_json_embed(config["ticket_embed"], {"user": user.mention}),
                view=CloseTicketView(user.id),
            )
            await pin_first_bot_ticket_message(ticket_channel, opening_message)
        except discord.HTTPException as error:
            print(f"Erreur création ticket {application_type} pour {user}: {error}")
            if ticket_channel is not None:
                try:
                    await ticket_channel.delete(reason="Candidature PinkGift incomplète")
                except discord.HTTPException:
                    pass
            await finish_ephemeral_flow(
                interaction,
                "❌ Discord ne peut pas créer cette candidature actuellement.",
            )
            return

        await finish_ephemeral_flow(
            interaction,
            f"✅ Ta demande de {config['label']} est ouverte : {ticket_channel.mention}",
        )


class ReferralApplicationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        apply_component_button_config(
            self.children[0],
            "parrainages_embed",
            "open_referral_ticket",
            "Devenir parrain",
            "🤝",
            "success",
        )

    @discord.ui.button(
        label="Devenir parrain",
        emoji="🤝",
        style=discord.ButtonStyle.success,
        custom_id="pinkgift_open_referral_application",
    )
    async def open_referral_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        await defer_single_ephemeral(interaction)
        await create_community_application_ticket(interaction, "parrainage")


class RecruitmentApplicationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        apply_component_button_config(
            self.children[0],
            "recrutement_embed",
            "open_recruitment_ticket",
            "Postuler",
            "📩",
            "primary",
        )

    @discord.ui.button(
        label="Postuler",
        emoji="📩",
        style=discord.ButtonStyle.primary,
        custom_id="pinkgift_open_recruitment_application",
    )
    async def open_recruitment_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        await defer_single_ephemeral(interaction)
        await create_community_application_ticket(interaction, "recrutement")


async def create_special_request_ticket(
    interaction,
    catalog_key,
    service_key,
    service_override=None,
    catalog_label_override=None,
):
    guild = interaction.guild
    user = interaction.user
    catalog_label, services = special_service_catalog(catalog_key)
    if catalog_label_override:
        catalog_label = str(catalog_label_override)[:100]
    service = service_override if isinstance(service_override, dict) else services.get(service_key)
    if guild is None or service is None:
        await finish_ephemeral_flow(interaction, "❌ Ce service est introuvable. Relance le menu.")
        return

    category = guild.get_channel(SPECIAL_TICKET_CATEGORY_ID)
    if not isinstance(category, discord.CategoryChannel):
        await finish_ephemeral_flow(
            interaction,
            "❌ La catégorie des tickets Autres et Abonnements est introuvable.",
        )
        return

    lock = ORDER_LOCKS.setdefault((guild.id, user.id, f"special:{catalog_key}"), asyncio.Lock())
    async with lock:
        decoration_access_members = (
            await resolve_discord_decoration_access_members(guild)
            if service_key == "DISCORD_DECORATIONS"
            else []
        )
        topic = f"pinkgift-special:{catalog_key}:{user.id}"
        ticket_channel = next(
            (
                channel for channel in category.text_channels
                if channel.topic == topic and not channel.name.startswith("closed-")
            ),
            None,
        )

        if ticket_channel is None:
            staff_role = guild.get_role(STAFF_ROLE_ID)
            me = guild.me or (guild.get_member(bot.user.id) if bot.user else None)
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            }
            if me:
                overwrites[me] = bot_ticket_permission_overwrite()
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )
            for access_member in decoration_access_members:
                overwrites[access_member] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )
            safe_user = re.sub(r"[^a-z0-9-]", "", user.name.lower().replace(" ", "-")) or str(user.id)
            prefix = "autres" if catalog_key == "autres" else "abonnement"
            try:
                ticket_channel = await guild.create_text_channel(
                    name=f"🎫・{prefix}-{safe_user}"[:95],
                    category=category,
                    topic=topic,
                    overwrites=overwrites,
                    reason=f"Demande {catalog_label} de {user}",
                )
            except discord.HTTPException as error:
                print(f"Erreur création ticket {catalog_key} pour {user}: {error}")
                await finish_ephemeral_flow(
                    interaction,
                    "⏳ Discord ne peut pas créer ce ticket actuellement. Réessaie dans quelques minutes.",
                )
                return

        if decoration_access_members:
            await grant_discord_decoration_ticket_access(ticket_channel, decoration_access_members)

        if catalog_key == "abonnements":
            embed_key = "subscription_request_ticket_embed"
        elif service_key == "BASIC_FIT":
            embed_key = "basic_fit_request_ticket_embed"
        elif service_key == "DISCORD_DECORATIONS":
            embed_key = "discord_decoration_request_ticket_embed"
        else:
            embed_key = "subscription_request_ticket_embed"

        embed = build_json_embed(embed_key, {
            "user": user.mention,
            "catalog": catalog_label,
            "service": service["label"],
            "emoji": service["emoji"],
        })
        try:
            opening_message = await ticket_channel.send(
                content=f"{user.mention} | <@&{STAFF_ROLE_ID}>",
                embed=embed,
                view=CloseTicketView(user.id),
            )
            await pin_first_bot_ticket_message(ticket_channel, opening_message)
        except discord.HTTPException as error:
            print(f"Erreur envoi demande {catalog_key} pour {user}: {error}")
            await finish_ephemeral_flow(
                interaction,
                "❌ Le ticket existe mais le message de demande n'a pas pu être envoyé.",
            )
            return

    await finish_ephemeral_flow(
        interaction,
        f"✅ Ton ticket pour {service['emoji']} **{service['label']}** est ouvert : {ticket_channel.mention}\n"
        "Aucun PinkCoin n'a été débité.",
    )


def get_other_services_menu_config():
    data = load_embed_texts().get("autres_embed", DEFAULT_EMBED_DATA["autres_embed"])
    raw_categories = data.get("menu_categories", [])
    categories = []
    used_category_values = set()
    if isinstance(raw_categories, list):
        for category_index, raw_category in enumerate(raw_categories[:25], start=1):
            if not isinstance(raw_category, dict):
                continue
            label = str(raw_category.get("label") or f"Catégorie {category_index}")[:100]
            value = str(raw_category.get("value") or f"categorie-{category_index}")[:100]
            if value in used_category_values:
                value = f"{value[:90]}-{category_index}"
            used_category_values.add(value)
            catalog_key = str(raw_category.get("catalog_key") or "autres").lower()
            if catalog_key not in {"autres", "abonnements"}:
                catalog_key = "autres"
            options = []
            used_option_values = set()
            raw_options = raw_category.get("options", [])
            if isinstance(raw_options, list):
                for option_index, raw_option in enumerate(raw_options[:25], start=1):
                    if not isinstance(raw_option, dict):
                        continue
                    option_label = str(raw_option.get("label") or f"Option {option_index}")[:100]
                    option_value = str(raw_option.get("value") or f"option-{option_index}")[:100]
                    if option_value in used_option_values:
                        option_value = f"{option_value[:90]}-{option_index}"
                    used_option_values.add(option_value)
                    service_key = str(
                        raw_option.get("service_key")
                        or f"CUSTOM_{option_value.upper().replace('-', '_')}"
                    )[:100]
                    options.append({
                        "label": option_label,
                        "value": option_value,
                        "emoji": str(raw_option.get("emoji") or "✨"),
                        "description": str(raw_option.get("description") or "")[:100],
                        "service_key": service_key,
                    })
            if not options:
                continue
            categories.append({
                "label": label,
                "value": value,
                "emoji": str(raw_category.get("emoji") or "📁"),
                "description": str(raw_category.get("description") or f"Ouvrir {label}")[:100],
                "placeholder": str(raw_category.get("placeholder") or f"Choisis une option — {label}")[:150],
                "catalog_key": catalog_key,
                "options": options,
            })
    if not categories:
        categories = [
            {
                "label": "Autres services",
                "value": "autres-services",
                "emoji": "✨",
                "description": "Basic-Fit et décorations Discord",
                "placeholder": "Choisis un autre service",
                "catalog_key": "autres",
                "options": [
                    {"value": key.lower().replace("_", "-"), "service_key": key, **service}
                    for key, service in OTHER_SERVICES.items()
                ],
            },
            {
                "label": "Abonnements",
                "value": "abonnements",
                "emoji": "📺",
                "description": "Netflix, Spotify et YouTube Premium",
                "placeholder": "Choisis un abonnement",
                "catalog_key": "abonnements",
                "options": [
                    {"value": key.lower().replace("_", "-"), "service_key": key, **service}
                    for key, service in SUBSCRIPTION_SERVICES.items()
                ],
            },
        ]
    return {
        "button_label": str(data.get("menu_button_label") or "Voir les services")[:80],
        "button_emoji": str(data.get("menu_button_emoji") or "✨"),
        "button_style": normalize_button_style(
            data.get("menu_button_style") or data.get("menu_button_color"),
            "primary",
        ),
        "placeholder": str(data.get("menu_placeholder") or "Choisis une catégorie")[:150],
        "categories": categories,
    }


class OtherServiceItemSelect(discord.ui.Select):
    def __init__(self, category):
        self.category = category
        options = [
            discord.SelectOption(
                label=option["label"],
                value=option["value"],
                emoji=safe_component_emoji(option.get("emoji"), "✨"),
                description=option.get("description") or None,
            )
            for option in category["options"]
        ]
        super().__init__(
            placeholder=category["placeholder"],
            custom_id=f"pinkgift_other_service_items_{category['value']}"[:100],
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        option = next(
            (item for item in self.category["options"] if item["value"] == self.values[0]),
            None,
        )
        if option is None:
            await interaction.response.edit_message(
                content="❌ Ce service n’existe plus.",
                view=None,
            )
            return
        await interaction.response.defer()
        await create_special_request_ticket(
            interaction,
            self.category["catalog_key"],
            option["service_key"],
            service_override=option,
            catalog_label_override=self.category["label"],
        )


class OtherServiceItemView(discord.ui.View):
    def __init__(self, category):
        super().__init__(timeout=300)
        back_button = next(item for item in self.children if isinstance(item, discord.ui.Button))
        apply_component_button_config(
            back_button,
            "autres_embed",
            "back_categories",
            "Retour aux catégories",
            "↩️",
            "secondary",
        )
        self.add_item(OtherServiceItemSelect(category))

    @discord.ui.button(label="Retour aux catégories", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="Choisis une catégorie de services :",
            view=OtherServicesCategoryView(),
        )


class OtherServicesCategorySelect(discord.ui.Select):
    def __init__(self):
        menu = get_other_services_menu_config()
        self.categories = menu["categories"]
        options = [
            discord.SelectOption(
                label=category["label"],
                value=category["value"],
                emoji=safe_component_emoji(category.get("emoji"), "📁"),
                description=category.get("description") or None,
            )
            for category in self.categories
        ]
        super().__init__(
            placeholder=menu["placeholder"],
            custom_id="pinkgift_other_services_categories",
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        category = next(
            (item for item in self.categories if item["value"] == self.values[0]),
            None,
        )
        if category is None:
            await interaction.response.edit_message(
                content="❌ Cette catégorie n’existe plus.",
                view=None,
            )
            return
        await interaction.response.edit_message(
            content=f"{category['emoji']} **{category['label']}** — choisis un service :",
            view=OtherServiceItemView(category),
        )


class OtherServicesCategoryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(OtherServicesCategorySelect())


class OtherServicesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        menu = get_other_services_menu_config()
        button = discord.ui.Button(
            label=menu["button_label"],
            emoji=safe_component_emoji(menu["button_emoji"], "✨"),
            style=discord_button_style(menu["button_style"]),
            custom_id="pinkgift_open_other_services_menu",
        )
        button.callback = self.open_other_services_menu
        self.add_item(button)

    async def open_other_services_menu(self, interaction: discord.Interaction):
        await send_single_ephemeral(
            interaction,
            "Choisis une catégorie de services :",
            view=OtherServicesCategoryView(),
        )


class UberEatsAmountSelect(discord.ui.Select):
    def __init__(self):
        available = product_is_available("UBEREATS")
        prices = get_pricing_config()["uber_eats"]
        options = [
            discord.SelectOption(label=f"{format_pinkcoins(prices[pack_key], short=True)} → {pack['drop']} € estimés", value=pack_key, emoji=stock_partial_emoji(available), description=stock_label(available))
            for pack_key, pack in UBEREATS_PACKS.items()
        ]
        super().__init__(placeholder="Choisis ton pack Uber Eats", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await create_product_ticket(interaction, "UBEREATS", self.values[0])


class UberEatsAmountView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(UberEatsAmountSelect())


class NitroOrderView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        apply_component_button_config(
            self.children[0],
            "tarifs_embed",
            "confirm_nitro",
            f"Commander Discord Nitro — {format_pinkcoins(get_pricing_config()['discord_nitro'], short=True)}",
            "💎",
            "success",
        )

    @discord.ui.button(
        label="Commander Discord Nitro",
        emoji="💎",
        style=discord.ButtonStyle.success
    )
    async def confirm_nitro(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await create_product_ticket(interaction, "DISCORD_NITRO", "nitro")


class ProductAmountSelect(discord.ui.Select):
    def __init__(self, product_key):
        self.product_key = product_key
        available = product_is_available(product_key)
        prices = get_pricing_config()["gift_cards"]
        options = [
            discord.SelectOption(label=f"Carte {amount} € → {format_pinkcoins(prices[str(amount)], short=True)}", value=str(amount), emoji=stock_partial_emoji(available), description=stock_label(available))
            for amount in GIFT_CARD_AMOUNTS
        ]
        super().__init__(placeholder="Choisis le montant de la carte", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await create_product_ticket(interaction, self.product_key, int(self.values[0]))


class ProductAmountView(discord.ui.View):
    def __init__(self, product_key):
        super().__init__(timeout=180)
        self.add_item(ProductAmountSelect(product_key))


class ProductServiceSelect(discord.ui.Select):
    def __init__(self):
        emoji_catalog = get_emoji_catalog()
        options = [
            discord.SelectOption(
                label=cfg["display"][:100],
                value=key,
                description="Sélectionner ce produit",
                emoji=safe_component_emoji(
                    get_product_emoji(key, emoji_catalog),
                    cfg.get("emoji_ch", "🎁"),
                ),
            )
            for key, cfg in PRODUCT_CONFIG.items()
            if key not in {"VALORANT", "SKRILL"}
        ]
        super().__init__(
            placeholder="Choisis une marque",
            custom_id="pinkgift_product_service",
            min_values=1,
            max_values=1,
            options=options,
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
                content=f"{get_product_emoji(product_key)} **{cfg['display']}** — {prompt}",
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
                await interaction.edit_original_response(
                    content="❌ Le menu de commande a rencontré une erreur. Relance **Commander**.",
                    view=None,
                )
            else:
                await interaction.response.edit_message(
                    content="❌ Le menu de commande a rencontré une erreur. Relance **Commander**.",
                    view=None,
                )
        except Exception:
            pass


class OrderLauncherView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        config = get_menu_launcher_config(
            "tarifs_embed",
            "Commander",
            "🛍️",
            "success",
        )
        button = discord.ui.Button(
            label=config["label"],
            emoji=safe_component_emoji(config["emoji"], "🛍️"),
            style=discord_button_style(
                config["style"],
                discord.ButtonStyle.success,
            ),
            custom_id="pinkgift_start_order",
        )
        button.callback = self.start_order
        self.add_item(button)

    async def start_order(self, interaction: discord.Interaction):
        try:
            # Le menu est désormais entièrement local et peut être envoyé directement.
            await send_single_ephemeral(
                interaction,
                "Choisis la marque que tu souhaites commander :",
                view=ProductSelectView(),
            )
        except Exception as error:
            print(f"Erreur bouton Commander pour {interaction.user}: {error}")
            traceback.print_exc()
            try:
                if interaction.response.is_done():
                    await interaction.edit_original_response(
                        content="❌ Impossible d'ouvrir le menu de commande. Réessaie dans quelques secondes.",
                        view=None,
                    )
                else:
                    await send_single_ephemeral(
                        interaction,
                        "❌ Impossible d'ouvrir le menu de commande. Réessaie dans quelques secondes.",
                    )
            except Exception:
                pass

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item):
        print(f"Erreur OrderLauncherView sur {getattr(item, 'custom_id', 'inconnu')}: {error}")
        traceback.print_exc()
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(
                    content="❌ Le bouton Commander a rencontré une erreur.",
                    view=None,
                )
            else:
                await send_single_ephemeral(
                    interaction,
                    "❌ Le bouton Commander a rencontré une erreur.",
                )
        except Exception:
            pass


def get_privileges_menu_config():
    data = load_embed_texts().get("privileges_embed", DEFAULT_EMBED_DATA["privileges_embed"])
    raw_categories = data.get("menu_categories", [])
    categories = []
    used_category_values = set()
    if isinstance(raw_categories, list):
        for category_index, raw_category in enumerate(raw_categories[:25], start=1):
            if not isinstance(raw_category, dict):
                continue
            label = str(raw_category.get("label") or f"Catégorie {category_index}")[:100]
            value = str(raw_category.get("value") or f"categorie-{category_index}")[:100]
            if value in used_category_values:
                value = f"{value[:90]}-{category_index}"
            used_category_values.add(value)
            raw_options = raw_category.get("options", [])
            options = []
            used_option_values = set()
            if isinstance(raw_options, list):
                for option_index, raw_option in enumerate(raw_options[:25], start=1):
                    if not isinstance(raw_option, dict):
                        continue
                    option_label = str(raw_option.get("label") or f"Option {option_index}")[:100]
                    option_value = str(raw_option.get("value") or f"option-{option_index}")[:100]
                    if option_value in used_option_values:
                        option_value = f"{option_value[:90]}-{option_index}"
                    used_option_values.add(option_value)
                    options.append({
                        "label": option_label,
                        "value": option_value,
                        "emoji": str(raw_option.get("emoji") or "✨"),
                        "description": str(raw_option.get("description") or "")[:100],
                        "response": str(raw_option.get("response") or ""),
                    })
            if not options:
                options.append({
                    "label": "Option à configurer",
                    "value": "option-1",
                    "emoji": "✨",
                    "description": "",
                    "response": "",
                })
            categories.append({
                "label": label,
                "value": value,
                "emoji": str(raw_category.get("emoji") or "📁"),
                "description": str(raw_category.get("description") or f"Ouvrir {label}")[:100],
                "placeholder": str(raw_category.get("placeholder") or f"Choisis une option — {label}")[:150],
                "options": options,
            })
    if not categories:
        categories = [{
            "label": "Catégorie à configurer",
            "value": "categorie-1",
            "emoji": "📁",
            "description": "Configuration disponible depuis le panel",
            "placeholder": "Choisis une option",
            "options": [{
                "label": "Option à configurer",
                "value": "option-1",
                "emoji": "✨",
                "description": "",
                "response": "",
            }],
        }]
    return {
        "button_label": str(data.get("menu_button_label") or "Découvrir les privilèges")[:80],
        "button_emoji": str(data.get("menu_button_emoji") or "✨"),
        "button_style": normalize_button_style(
            data.get("menu_button_style") or data.get("menu_button_color"),
            "primary",
        ),
        "placeholder": str(data.get("menu_placeholder") or "Choisis une catégorie")[:150],
        "categories": categories,
    }


class PrivilegeItemSelect(discord.ui.Select):
    def __init__(self, category):
        self.category = category
        options = [
            discord.SelectOption(
                label=option["label"],
                value=option["value"],
                emoji=safe_component_emoji(option.get("emoji"), "✨"),
                description=option.get("description") or None,
            )
            for option in category["options"]
        ]
        super().__init__(
            placeholder=category["placeholder"],
            options=options,
            custom_id=f"pinkgift_privilege_items_{category['value']}"[:100],
        )

    async def callback(self, interaction: discord.Interaction):
        option = next(
            (item for item in self.category["options"] if item["value"] == self.values[0]),
            None,
        )
        if option is None:
            await interaction.response.edit_message(
                content="❌ Cette option n’existe plus.",
                view=None,
            )
            return
        response = option.get("response") or (
            f"✨ Tu as sélectionné **{option['label']}** dans **{self.category['label']}**.\n"
            "Le contenu de cette option peut être configuré depuis le panel."
        )
        await interaction.response.edit_message(content=response, view=None)


class PrivilegeItemView(discord.ui.View):
    def __init__(self, category):
        super().__init__(timeout=300)
        back_button = next(item for item in self.children if isinstance(item, discord.ui.Button))
        apply_component_button_config(
            back_button,
            "privileges_embed",
            "back_categories",
            "Retour aux catégories",
            "↩️",
            "secondary",
        )
        self.add_item(PrivilegeItemSelect(category))

    @discord.ui.button(label="Retour aux catégories", emoji="↩️", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="Choisis une catégorie de privilèges :",
            view=PrivilegeCategoryView(),
        )


class PrivilegeCategorySelect(discord.ui.Select):
    def __init__(self):
        menu = get_privileges_menu_config()
        self.categories = menu["categories"]
        options = [
            discord.SelectOption(
                label=category["label"],
                value=category["value"],
                emoji=safe_component_emoji(category.get("emoji"), "📁"),
                description=category.get("description") or None,
            )
            for category in self.categories
        ]
        super().__init__(
            placeholder=menu["placeholder"],
            options=options,
            custom_id="pinkgift_privilege_categories",
        )

    async def callback(self, interaction: discord.Interaction):
        category = next(
            (item for item in self.categories if item["value"] == self.values[0]),
            None,
        )
        if category is None:
            await interaction.response.send_message("❌ Cette catégorie n’existe plus.", ephemeral=True)
            return
        await interaction.response.edit_message(
            content=f"{category['emoji']} **{category['label']}** — choisis une option :",
            view=PrivilegeItemView(category),
        )


class PrivilegeCategoryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(PrivilegeCategorySelect())


class PrivilegesLauncherView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        menu = get_privileges_menu_config()
        button = discord.ui.Button(
            label=menu["button_label"],
            emoji=safe_component_emoji(menu["button_emoji"], "✨"),
            style=discord_button_style(menu["button_style"]),
            custom_id="pinkgift_open_privileges_menu",
        )
        button.callback = self.open_privileges_menu
        self.add_item(button)

    async def open_privileges_menu(self, interaction: discord.Interaction):
        await send_single_ephemeral(
            interaction,
            "Choisis une catégorie de privilèges :",
            view=PrivilegeCategoryView(),
        )


async def create_balance_recharge_ticket(interaction, referral=None):
    guild = interaction.guild
    user = interaction.user
    category = guild.get_channel(BALANCE_CATEGORY_ID) if guild else None
    if category is None:
        await finish_ephemeral_flow(interaction, "❌ Catégorie de recharge introuvable.")
        return
    existing = find_balance_ticket(guild, user.id)
    if existing:
        await finish_ephemeral_flow(
            interaction,
            f"ℹ️ Ton ticket de recharge existe déjà : {existing.mention}",
        )
        return
    staff_role = guild.get_role(STAFF_ROLE_ID)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: bot_ticket_permission_overwrite()
    }
    if staff_role:
        overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
    try:
        channel = await guild.create_text_channel(
            name=f"pinkwallet-{user.name}"[:95],
            category=category,
            topic=f"pinkgift-balance:{user.id}:pending",
            overwrites=overwrites,
            reason=f"Recharge PinkWallet de {user}",
        )
        if referral:
            save_balance_ticket_referral(channel, user.id, referral)
        embed = build_json_embed("balance_ticket_embed", {"user": user.mention, "balance": pinkcoin_number(get_balance(guild.id, user.id))})
        opening_message = await channel.send(content=f"{user.mention} | <@&{STAFF_ROLE_ID}>", embed=embed, view=CloseTicketView(user.id))
        await pin_first_bot_ticket_message(channel, opening_message)
        await finish_ephemeral_flow(interaction, f"✅ Ticket de recharge créé : {channel.mention}")
    except Exception as error:
        print(f"Erreur création ticket solde pour {user}: {error}")
        await finish_ephemeral_flow(
            interaction,
            "❌ Impossible de créer le ticket de recharge actuellement.",
        )


class ReferralCodeModal(discord.ui.Modal, title="Code de parrainage"):
    code_input = discord.ui.TextInput(
        label="Ton code de parrainage",
        placeholder="Exemple : PINKY10",
        min_length=3,
        max_length=32,
        required=True,
    )

    def __init__(self, user_id, origin_interaction=None):
        super().__init__()
        self.user_id = int(user_id)
        self.origin_interaction = origin_interaction

    async def on_submit(self, interaction: discord.Interaction):
        if self.origin_interaction is not None:
            try:
                await self.origin_interaction.delete_original_response()
            except (discord.NotFound, discord.HTTPException):
                pass
        if interaction.user.id != self.user_id:
            await send_single_ephemeral(interaction, "❌ Ce formulaire ne t'appartient pas.")
            return
        referral = get_active_referral_code(self.code_input.value)
        if referral is None:
            await send_single_ephemeral(
                interaction,
                "❌ Ce code de parrainage est invalide ou désactivé.",
            )
            return
        if referral.get("sponsor_id") and referral["sponsor_id"] == str(interaction.user.id):
            await send_single_ephemeral(
                interaction,
                "❌ Tu ne peux pas utiliser ton propre code de parrainage.",
            )
            return
        await defer_single_ephemeral(interaction)
        await create_balance_recharge_ticket(interaction, referral)


class ReferralChoiceView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = int(user_id)
        apply_component_button_config(
            self.children[0],
            "balance_embed",
            "referral_yes",
            "Oui, j'ai un code",
            "✅",
            "success",
        )
        apply_component_button_config(
            self.children[1],
            "balance_embed",
            "referral_no",
            "Non",
            "❌",
            "secondary",
        )

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id == self.user_id:
            return True
        await send_single_ephemeral(interaction, "❌ Ce choix ne t'appartient pas.")
        return False

    @discord.ui.button(label="Oui, j'ai un code", emoji="✅", style=discord.ButtonStyle.success)
    async def yes_referral(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReferralCodeModal(self.user_id, interaction))

    @discord.ui.button(label="Non", emoji="❌", style=discord.ButtonStyle.secondary)
    async def no_referral(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await create_balance_recharge_ticket(interaction)


class BalanceView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        apply_component_button_config(
            self.children[0],
            "balance_embed",
            "view_balance",
            "Voir mes PinkCoins",
            "💰",
            "secondary",
        )
        apply_component_button_config(
            self.children[1],
            "balance_embed",
            "recharge_balance",
            "Recharger mon PinkWallet",
            "➕",
            "success",
        )

    @discord.ui.button(label="Voir mes PinkCoins", emoji="💰", style=discord.ButtonStyle.secondary, custom_id="pinkgift_view_balance")
    async def view_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        balance = get_balance(interaction.guild.id, interaction.user.id)
        await send_single_ephemeral(
            interaction,
            f"💰 Ton PinkWallet contient **{format_pinkcoins(balance)}**.",
        )

    @discord.ui.button(label="Recharger mon PinkWallet", emoji="➕", style=discord.ButtonStyle.success, custom_id="pinkgift_recharge_balance")
    async def recharge_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        existing = find_balance_ticket(interaction.guild, interaction.user.id)
        if existing:
            await send_single_ephemeral(
                interaction,
                f"ℹ️ Ton ticket de recharge existe déjà : {existing.mention}",
            )
            return
        await send_single_ephemeral(
            interaction,
            "🤝 As-tu un code de parrainage ?",
            view=ReferralChoiceView(interaction.user.id),
        )


class CloseTicketView(discord.ui.View):
    def __init__(self, client_id: int = 0):
        super().__init__(timeout=None)
        self.client_id = client_id
        apply_component_button_config(
            self.children[0],
            "close_ticket_embed",
            "close_ticket",
            "Close",
            "🔒",
            "danger",
        )

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="pinkgift_close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        channel = interaction.channel
        staff_role = guild.get_role(STAFF_ROLE_ID) if guild else None
        is_staff = staff_role in interaction.user.roles if hasattr(interaction.user, "roles") and staff_role else False
        if not is_staff:
            await send_single_ephemeral(interaction, "❌ Seul le staff peut fermer ce ticket.")
            return
        if guild is None or channel is None:
            await send_single_ephemeral(interaction, "❌ Ce bouton doit être utilisé dans un ticket serveur.")
            return
        if isinstance(channel, discord.Thread):
            await send_single_ephemeral(
                interaction,
                "ℹ️ Les fils de commande ne se ferment pas avec ce bouton.",
            )
            return

        # Discord attend une réponse en moins de trois secondes. On accuse
        # réception avant les changements de permissions et de catégorie.
        await interaction.response.defer(ephemeral=True, thinking=True)
        await clear_previous_ephemeral(interaction)
        ACTIVE_EPHEMERAL_RESPONSES[ephemeral_response_key(interaction)] = (time.time(), interaction)

        client_id = resolve_ticket_client_id(channel, self.client_id)
        client = guild.get_member(client_id) if client_id else None
        try:
            if client:
                await channel.set_permissions(
                    client,
                    view_channel=False,
                    send_messages=False,
                    read_message_history=False,
                    reason=f"Ticket fermé par {interaction.user}",
                )
            else:
                for target in list(channel.overwrites):
                    if not isinstance(target, discord.Member):
                        continue
                    has_staff_role = staff_role in target.roles if staff_role else False
                    if not target.bot and not has_staff_role:
                        await channel.set_permissions(
                            target,
                            view_channel=False,
                            send_messages=False,
                            read_message_history=False,
                            reason=f"Ticket fermé par {interaction.user}",
                        )

            if is_balance_ticket(channel):
                balance_user_id = get_balance_ticket_user_id(channel)
                credited = balance_ticket_marked_credited(channel)
                if not credited and balance_user_id:
                    try:
                        credited = balance_was_added_after(guild.id, balance_user_id, channel.created_at)
                    except Exception as error:
                        print(f"Erreur verification credit ticket solde {channel.id}: {error}")
                if not credited:
                    await finish_ephemeral_flow(
                        interaction,
                        "🗑️ Ticket fermé sans recharge du PinkWallet : suppression du salon.",
                    )
                    await channel.delete(reason=f"Ticket PinkWallet sans recharge fermé par {interaction.user}")
                    return

            closed_category = guild.get_channel(CLOSED_TICKET_CATEGORY_ID)
            new_name = channel.name if channel.name.startswith("closed-") else f"closed-{channel.name}"
            if closed_category:
                await channel.edit(name=new_name, category=closed_category, reason=f"Ticket ferme par {interaction.user}")
            else:
                await channel.edit(name=new_name, reason=f"Ticket ferme par {interaction.user}")
            await finish_ephemeral_flow(
                interaction,
                "🔒 Ticket fermé : le client n'a plus accès à ce salon.",
            )
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
            print(f"Erreur fermeture ticket {getattr(channel, 'id', '?')}: {error}")
            await finish_ephemeral_flow(
                interaction,
                "❌ Discord n'a pas pu fermer ce ticket. Vérifie les permissions du bot.",
            )


class PendingOrderActionsView(CloseTicketView):
    def __init__(self, client_id: int = 0):
        super().__init__(client_id)


class OpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        apply_component_button_config(
            self.children[0],
            "menu_ticket_embed",
            "open_ticket",
            "Ouvrir un ticket",
            "🎫",
            "success",
        )

    @discord.ui.button(label="Ouvrir un ticket", emoji="🎫", style=discord.ButtonStyle.success, custom_id="pinkgift_open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user
        if guild is None:
            await send_single_ephemeral(
                interaction,
                "❌ Cette action doit etre utilisee sur un serveur.",
            )
            return
        category = guild.get_channel(TICKET_CATEGORY_ID)
        if category is None:
            await send_single_ephemeral(interaction, "❌ Categorie ticket introuvable.")
            return
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: bot_ticket_permission_overwrite()
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
        opening_message = await ticket_channel.send(content=f"{user.mention} | <@&{STAFF_ROLE_ID}>", embed=embed_ticket, view=CloseTicketView(user.id))
        await pin_first_bot_ticket_message(ticket_channel, opening_message)
        await send_single_ephemeral(
            interaction,
            f"✅ Ton ticket a ete cree ici : {ticket_channel.mention}",
        )

class ProductView(OpenTicketView):
    pass


class ValoTicketButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        apply_component_button_config(
            self.children[0],
            "commande_vp_embed",
            "open_valo_ticket",
            "Ouvrir un ticket Valorant",
            "🎮",
            "success",
        )

    @discord.ui.button(label="Ouvrir un ticket Valorant", emoji="🎮", style=discord.ButtonStyle.success, custom_id="pinkgift_open_valo_ticket")
    async def open_valo_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user
        if guild is None:
            await send_single_ephemeral(
                interaction,
                "❌ Cette action doit etre utilisee sur un serveur.",
            )
            return
        category = guild.get_channel(VALO_TICKET_CATEGORY_ID)
        if category is None:
            await send_single_ephemeral(interaction, "❌ Categorie Valorant introuvable.")
            return
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: bot_ticket_permission_overwrite()
        }
        ticket_channel = await guild.create_text_channel(
            name=f"ticket-valorant-{user.name}",
            category=category,
            overwrites=overwrites,
            reason=f"Ouverture ticket Valorant par {user}"
        )
        embed_ticket = build_json_embed("valo_ticket_bienvenue_embed", {"user": user.mention})
        opening_message = await ticket_channel.send(content=f"{user.mention} | <@&{STAFF_ROLE_ID}>", embed=embed_ticket, view=CloseTicketView(user.id))
        await pin_first_bot_ticket_message(ticket_channel, opening_message)
        await send_single_ephemeral(
            interaction,
            f"✅ Ton ticket Valorant a ete cree ici : {ticket_channel.mention}",
        )


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


def weighted_giveaway_sample(candidates, count, participant_weights=None, random_source=None):
    pool = list(candidates)
    selected = []
    weights = participant_weights if isinstance(participant_weights, dict) else {}
    random_source = random_source or secrets.SystemRandom()
    count = min(max(0, int(count or 0)), len(pool))

    while pool and len(selected) < count:
        candidate_weights = []
        for user_id in pool:
            raw_weight = weights.get(user_id, weights.get(str(user_id), 1))
            try:
                weight = max(1.0, float(raw_weight or 1))
            except (TypeError, ValueError):
                weight = 1.0
            candidate_weights.append(weight)
        total_weight = sum(candidate_weights)
        target = random_source.random() * total_weight
        cumulative = 0.0
        selected_index = len(pool) - 1
        for index, weight in enumerate(candidate_weights):
            cumulative += weight
            if target < cumulative:
                selected_index = index
                break
        selected.append(pool.pop(selected_index))
    return selected


def select_giveaway_winners(
    participants,
    winner_count=1,
    winner_history=None,
    current_winners=None,
    participant_weights=None,
):
    participants = normalize_giveaway_participants(participants)
    if not participants:
        return []

    try:
        winner_count = max(1, int(winner_count or 1))
    except (TypeError, ValueError):
        winner_count = 1
    winner_count = min(winner_count, len(participants))

    history = normalize_giveaway_participants(winner_history)
    current = set(normalize_giveaway_participants(current_winners))
    history_set = set(history)
    selected = []
    random_source = secrets.SystemRandom()

    fresh_candidates = [
        user_id for user_id in participants
        if user_id not in history_set and user_id not in current
    ]
    if fresh_candidates:
        selected.extend(weighted_giveaway_sample(
            fresh_candidates,
            min(winner_count, len(fresh_candidates)),
            participant_weights,
            random_source,
        ))

    if len(selected) < winner_count:
        previous_candidates = [
            user_id for user_id in participants
            if user_id not in current and user_id not in selected
        ]
        if previous_candidates:
            missing = winner_count - len(selected)
            selected.extend(weighted_giveaway_sample(
                previous_candidates,
                min(missing, len(previous_candidates)),
                participant_weights,
                random_source,
            ))

    if len(selected) < winner_count:
        remaining = [user_id for user_id in participants if user_id not in selected]
        if remaining:
            missing = winner_count - len(selected)
            selected.extend(weighted_giveaway_sample(
                remaining,
                min(missing, len(remaining)),
                participant_weights,
                random_source,
            ))
    return selected


def select_giveaway_winner(participants, winner_history=None):
    winners = select_giveaway_winners(participants, 1, winner_history)
    return winners[0] if winners else None


def member_has_server_tag(member, guild_id):
    primary_guild = getattr(member, "primary_guild", None)
    if primary_guild is None or getattr(primary_guild, "identity_enabled", False) is not True:
        return False
    try:
        return int(getattr(primary_guild, "id", 0) or 0) == int(guild_id)
    except (TypeError, ValueError):
        return False


def giveaway_new_active_invites(guild_id, inviter_id, data):
    try:
        started_ts = float(data.get("invite_requirement_started_ts", 0) or 0)
    except (TypeError, ValueError):
        started_ts = 0
    if started_ts <= 0:
        try:
            started_at = datetime.datetime.fromisoformat(str(data.get("created_at") or "").replace("Z", "+00:00"))
            started_ts = started_at.timestamp()
        except (TypeError, ValueError):
            started_ts = 0
    active_new_invites = 0
    members = get_invite_tracking_data(guild_id)["members"]
    min_account_age_days = max(1, int(data.get("min_invite_account_age_days", MIN_INVITE_ACCOUNT_AGE_DAYS) or MIN_INVITE_ACCOUNT_AGE_DAYS))
    for invited_member_id, member_data in members.items():
        if (
            not isinstance(member_data, dict)
            or not member_data.get("active")
            or not member_data.get("counted", True)
            or not tracked_invite_is_eligible(invited_member_id, member_data, min_account_age_days)
        ):
            continue
        try:
            if int(member_data.get("inviter_id") or 0) != int(inviter_id):
                continue
            joined_ts = float(member_data.get("joined_ts", 0) or 0)
        except (TypeError, ValueError):
            continue
        if joined_ts <= 0:
            try:
                joined_at = datetime.datetime.fromisoformat(str(member_data.get("joined_at") or "").replace("Z", "+00:00"))
                joined_ts = joined_at.timestamp()
            except (TypeError, ValueError):
                continue
        if joined_ts >= started_ts:
            active_new_invites += 1
    return active_new_invites


def giveaway_requirement_failures(guild, member, data):
    failures = []
    min_invites = max(0, int(data.get("min_invites", 0) or 0))
    if min_invites:
        new_active_invites = giveaway_new_active_invites(guild.id, member.id, data)
        if new_active_invites < min_invites:
            failures.append(
                f"**{min_invites} nouvelle(s) invitation(s) active(s) et valide(s)** requise(s) depuis le début du giveaway, "
                f"tu en as **{new_active_invites}**"
            )
    if data.get("require_server_tag") and not member_has_server_tag(member, guild.id):
        failures.append("le **tag de ce serveur** doit être affiché sur ton profil Discord")
    return failures


async def eligible_giveaway_participants(guild, data):
    eligible = []
    rejected = []
    participant_weights = {}
    weighted_by_invites = bool(data.get("weighted_by_invites"))
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
            participant_weights[user_id] = (
                1 + giveaway_new_active_invites(guild.id, user_id, data)
                if weighted_by_invites
                else 1
            )
    return eligible, rejected, participant_weights


def giveaway_conditions_text(min_invites=0, require_server_tag=False, weighted_by_invites=False):
    conditions = []
    min_invites = max(0, int(min_invites or 0))
    if min_invites:
        conditions.append(
            f"• Obtenir au moins **{min_invites} nouvelle(s) invitation(s) active(s)** pendant ce giveaway\n"
            f"• Les comptes invités doivent avoir au moins **{MIN_INVITE_ACCOUNT_AGE_DAYS} jours** et ne sont comptés qu'une fois"
        )
    if require_server_tag:
        conditions.append("• Afficher le **tag de ce serveur** sur son profil Discord")
    if weighted_by_invites:
        conditions.append(
            "• **Chances bonus activées :** 1 chance de base + 1 chance par nouvelle invitation active et valide"
        )
    if conditions:
        conditions.append("• Les conditions sont vérifiées uniquement au moment du tirage")
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
    winner_count=1,
    weighted_by_invites=False,
):
    key = "giveaway_ended_embed" if ended else "giveaway_embed"
    data = load_embed_texts().get(key, DEFAULT_EMBED_DATA[key])
    winner_count = max(1, int(winner_count or 1))
    variables = {
        "name": name,
        "end_ts": end_ts,
        "count": participants_count,
        "winner": winner,
        "winner_count": winner_count,
    }
    rgb = data.get("color_rgb", [255, 192, 203])
    embed = discord.Embed(
        title=format_embed_text(data.get("title", "🎉 Giveaway"), variables),
        description=format_embed_description(data.get("description", []), variables),
        color=discord.Color.from_rgb(*rgb)
    )
    footer = data.get("footer")
    if footer:
        embed.set_footer(text=format_embed_text(footer, variables))
    conditions = giveaway_conditions_text(min_invites, require_server_tag, weighted_by_invites)
    if not ended:
        embed.add_field(name="Nombre de gagnants", value=f"**{winner_count}**", inline=True)
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
        winner_count=data.get("winner_count", 1),
        weighted_by_invites=bool(data.get("weighted_by_invites")),
    )


class GiveawayJoinView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        apply_component_button_config(
            self.children[0],
            "giveaway_embed",
            "join_giveaway",
            "Je participe",
            GIVEAWAY_JOIN_EMOJI,
            "success",
        )

    @discord.ui.button(label="Je participe", style=discord.ButtonStyle.success, emoji=GIVEAWAY_JOIN_EMOJI, custom_id="pinkgift_giveaway_join")
    async def join_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        message = interaction.message
        if message is None:
            await send_single_ephemeral(interaction, "❌ Giveaway introuvable.")
            return
        data = load_giveaway(message.id)
        if not data:
            await send_single_ephemeral(interaction, "❌ Ce giveaway n'est plus actif.")
            return
        if data.get("ended"):
            await send_single_ephemeral(interaction, "❌ Ce giveaway est déjà terminé.")
            return
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            await send_single_ephemeral(
                interaction,
                "❌ Cette participation doit être faite sur le serveur.",
            )
            return
        participants = normalize_giveaway_participants(data.get("participants", []))
        if interaction.user.id in participants:
            await send_single_ephemeral(
                interaction,
                "✅ Tu participes déjà à ce giveaway.",
            )
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
        await send_single_ephemeral(
            interaction,
            "✅ Participation enregistrée. Les conditions seront vérifiées au moment du tirage.",
        )


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
        eligible_participants, rejected, participant_weights = await eligible_giveaway_participants(guild, data)
        winner_text = "Aucun participant éligible" if participants else "Aucun participant"
        winner_count = max(1, int(data.get("winner_count", 1) or 1))
        winner_ids = select_giveaway_winners(
            eligible_participants,
            winner_count,
            participant_weights=participant_weights,
        )
        if winner_ids:
            winner_text = ", ".join(f"<@{winner_id}>" for winner_id in winner_ids)
            data["winner_id"] = winner_ids[0]
            data["winner_ids"] = winner_ids
            data["winner_history"] = list(winner_ids)
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
            f"Gagnant(s) : {winner_text}{excluded_text}"
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


def adjust_verified_reviews_count(guild_id, delta):
    data = get_server_counter_data(guild_id)
    if "verified_reviews_count" not in data:
        return False
    current = max(0, int(data.get("verified_reviews_count", 0) or 0))
    data["verified_reviews_count"] = max(0, current + int(delta))
    save_server_counter_data(guild_id, data)
    return True


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
    global SERVER_COUNTER_BACKOFF_UNTIL
    if guild is None or not guild_is_authorized(guild.id):
        return
    if time.monotonic() < SERVER_COUNTER_BACKOFF_UNTIL:
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
    global SERVER_COUNTER_BACKOFF_UNTIL
    await asyncio.sleep(5)
    refresh_reviews = bool(SERVER_COUNTER_UPDATE_FLAGS.pop(guild.id, False))
    try:
        await refresh_server_counters(guild, refresh_reviews=refresh_reviews)
    except (discord.Forbidden, discord.HTTPException) as error:
        if getattr(error, "status", None) == 429:
            SERVER_COUNTER_BACKOFF_UNTIL = max(
                SERVER_COUNTER_BACKOFF_UNTIL,
                time.monotonic() + SERVER_COUNTER_RATE_LIMIT_BACKOFF_SECONDS,
            )
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
    global SERVER_COUNTER_BACKOFF_UNTIL
    await asyncio.sleep(SERVER_COUNTER_INITIAL_DELAY_SECONDS)
    while not bot.is_closed():
        for guild in bot.guilds:
            if guild_is_authorized(guild.id):
                try:
                    await refresh_server_counters(guild, refresh_reviews=False)
                except (discord.Forbidden, discord.HTTPException) as error:
                    if getattr(error, "status", None) == 429:
                        SERVER_COUNTER_BACKOFF_UNTIL = max(
                            SERVER_COUNTER_BACKOFF_UNTIL,
                            time.monotonic() + SERVER_COUNTER_RATE_LIMIT_BACKOFF_SECONDS,
                        )
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
    global BOT_LOOP, COMMAND_SYNC_DONE, PUBLIC_VIEWS_REPAIRED, DECORATION_ACCESS_REPAIRED, SERVER_COUNTER_REFRESH_TASK, CUSTOMER_ROLES_SYNCED
    BOT_LOOP = asyncio.get_running_loop()
    if bot.user:
        try:
            set_panel_setting("discord_bot_user_id", bot.user.id)
        except Exception as error:
            print(f"Erreur mémorisation ID du bot : {error}")
    if not COMMAND_SYNC_DONE:
        await sync_commands_to_guilds()
        COMMAND_SYNC_DONE = True

    # Les vues sont déjà enregistrées dans setup_hook. Les réenregistrer à
    # chaque on_ready peut créer des doublons après une reconnexion.
    if not PUBLIC_VIEWS_REPAIRED:
        try:
            balance_repaired = await repair_balance_ticket_opening_embeds()
            print(f"✅ {balance_repaired} embed(s) d'ouverture PinkWallet restauré(s).")
            repaired = await repair_public_launcher_views()
            print(f"✅ {repaired} panneau(x) public(s) réparé(s).")
        except Exception as error:
            print(f"Erreur réparation automatique des boutons publics : {error}")
        PUBLIC_VIEWS_REPAIRED = True

    if not DECORATION_ACCESS_REPAIRED:
        try:
            repaired = await repair_discord_decoration_ticket_access()
            print(f"✅ Accès synchronisé sur {repaired} ticket(s) Décorations Discord/Nitro.")
        except Exception as error:
            print(f"Erreur réparation accès tickets Décorations Discord/Nitro : {error}")
        DECORATION_ACCESS_REPAIRED = True

    await schedule_active_giveaways()
    await initialize_invite_tracking()
    if not CUSTOMER_ROLES_SYNCED:
        for guild in bot.guilds:
            try:
                await sync_customer_roles(guild)
            except Exception as error:
                print(f"Erreur synchronisation initiale rôles clients pour {guild.id}: {error}")
        CUSTOMER_ROLES_SYNCED = True
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


def ghost_ping_setting_key(guild_id):
    return f"ghost_ping_channel:{int(guild_id)}"


def get_ghost_ping_channel_id(guild_id):
    data = get_panel_setting(ghost_ping_setting_key(guild_id), {})
    try:
        channel_id = int((data or {}).get("channel_id") or 0)
    except (TypeError, ValueError, AttributeError):
        return 0
    return channel_id if channel_id > 0 else 0


async def send_member_join_ghost_ping(member):
    channel_id = get_ghost_ping_channel_id(member.guild.id)
    if not channel_id:
        return
    channel = member.guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        await channel.send(
            member.mention,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
                replied_user=False,
            ),
            delete_after=1,
        )
    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
        print(f"Erreur ghost ping arrivée de {member} dans {channel_id}: {error}")


def anti_raid_setting_key(guild_id):
    return f"anti_raid:{int(guild_id)}"


def normalize_anti_raid_config(data=None):
    source = data if isinstance(data, dict) else {}
    try:
        threshold = max(3, min(50, int(source.get("threshold", 6) or 6)))
    except (TypeError, ValueError):
        threshold = 6
    try:
        window_seconds = max(3, min(60, int(source.get("window_seconds", 10) or 10)))
    except (TypeError, ValueError):
        window_seconds = 10
    try:
        raid_duration_minutes = max(1, min(120, int(source.get("raid_duration_minutes", 10) or 10)))
    except (TypeError, ValueError):
        raid_duration_minutes = 10
    try:
        log_channel_id = int(source.get("log_channel_id") or MEMBER_ACTIVITY_CHANNEL_ID)
    except (TypeError, ValueError):
        log_channel_id = MEMBER_ACTIVITY_CHANNEL_ID
    try:
        active_until = max(0.0, float(source.get("active_until", 0) or 0))
    except (TypeError, ValueError):
        active_until = 0.0
    try:
        blocked_count = max(0, int(source.get("blocked_count", 0) or 0))
    except (TypeError, ValueError):
        blocked_count = 0
    return {
        "enabled": bool(source.get("enabled", True)),
        "threshold": threshold,
        "window_seconds": window_seconds,
        "raid_duration_minutes": raid_duration_minutes,
        "log_channel_id": log_channel_id,
        "active_until": active_until,
        "blocked_count": blocked_count,
        "last_triggered_at": str(source.get("last_triggered_at") or ""),
        "updated_by": int(source.get("updated_by") or 0),
    }


def get_anti_raid_config(guild_id):
    guild_id = int(guild_id)
    if guild_id not in ANTI_RAID_CONFIG_CACHE:
        stored = get_panel_setting(anti_raid_setting_key(guild_id), {})
        ANTI_RAID_CONFIG_CACHE[guild_id] = normalize_anti_raid_config(stored)
    return dict(ANTI_RAID_CONFIG_CACHE[guild_id])


def save_anti_raid_config(guild_id, data):
    guild_id = int(guild_id)
    normalized = normalize_anti_raid_config(data)
    ANTI_RAID_CONFIG_CACHE[guild_id] = normalized
    set_panel_setting(anti_raid_setting_key(guild_id), normalized)
    return dict(normalized)


async def send_anti_raid_alert(guild, config, title, description, color):
    channel_id = int(config.get("log_channel_id") or MEMBER_ACTIVITY_CHANNEL_ID)
    channel = guild.get_channel(channel_id) or bot.get_channel(channel_id)
    if channel is None and channel_id != MEMBER_ACTIVITY_CHANNEL_ID:
        channel = guild.get_channel(MEMBER_ACTIVITY_CHANNEL_ID) or bot.get_channel(MEMBER_ACTIVITY_CHANNEL_ID)
    try:
        if channel is None:
            channel = await bot.fetch_channel(channel_id)
        embed = discord.Embed(title=title, description=description, color=color, timestamp=utc_now())
        embed.add_field(
            name="Configuration",
            value=(
                f"**{config['threshold']}** arrivées en **{config['window_seconds']} s**\n"
                f"Protection renforcée pendant **{config['raid_duration_minutes']} min**"
            ),
            inline=False,
        )
        embed.set_footer(text="PinkGift — Protection anti-raid")
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.NotFound, discord.HTTPException, AttributeError) as error:
        print(f"Erreur journal anti-raid sur {guild.id}: {error}")


async def kick_anti_raid_member(member, reason):
    if member.bot or member.id == member.guild.owner_id or member.guild_permissions.administrator:
        return False
    try:
        await member.kick(reason=reason)
        return True
    except (discord.Forbidden, discord.NotFound, discord.HTTPException) as error:
        print(f"Erreur expulsion anti-raid de {member} ({member.id}): {error}")
        return False


async def handle_anti_raid_join(member):
    if member.bot or member.id == member.guild.owner_id or member.guild_permissions.administrator:
        return False
    guild = member.guild
    lock = ANTI_RAID_LOCKS.setdefault(guild.id, asyncio.Lock())
    members_to_kick = []
    triggered = False
    config = None
    now = time.time()
    async with lock:
        config = get_anti_raid_config(guild.id)
        if not config["enabled"]:
            return False
        if config["active_until"] > now:
            members_to_kick = [member]
        else:
            if config["active_until"]:
                config["active_until"] = 0
                save_anti_raid_config(guild.id, config)
            cutoff = now - config["window_seconds"]
            recent = [
                (joined_at, member_id)
                for joined_at, member_id in ANTI_RAID_RECENT_JOINS.get(guild.id, [])
                if joined_at >= cutoff
            ]
            recent.append((now, member.id))
            ANTI_RAID_RECENT_JOINS[guild.id] = recent
            if len(recent) < config["threshold"]:
                return False
            triggered = True
            config["active_until"] = now + config["raid_duration_minutes"] * 60
            config["last_triggered_at"] = utc_now().isoformat()
            save_anti_raid_config(guild.id, config)
            member_ids = {member_id for _, member_id in recent}
            members_to_kick = [
                recent_member
                for member_id in member_ids
                if (recent_member := guild.get_member(member_id)) is not None
            ]
            ANTI_RAID_RECENT_JOINS[guild.id] = []

    results = await asyncio.gather(*(
        kick_anti_raid_member(
            recent_member,
            "Protection anti-raid PinkGift : arrivées massives détectées",
        )
        for recent_member in members_to_kick
    ))
    blocked = sum(1 for result in results if result)
    if blocked:
        config["blocked_count"] += blocked
        ANTI_RAID_CONFIG_CACHE[guild.id] = normalize_anti_raid_config(config)
        if triggered or config["blocked_count"] % 10 == 0:
            save_anti_raid_config(guild.id, config)
    if triggered:
        end_timestamp = int(config["active_until"])
        await send_anti_raid_alert(
            guild,
            config,
            "🚨 Raid détecté — protection activée",
            (
                f"Une vague de **{len(members_to_kick)} arrivées** a été détectée. "
                f"**{blocked} compte(s)** ont été expulsés.\n"
                f"Les nouvelles arrivées seront bloquées jusqu’à <t:{end_timestamp}:R>."
            ),
            discord.Color.red(),
        )
    return True


@bot.event
async def on_member_join(member):
    if await handle_anti_raid_join(member):
        schedule_server_counter_refresh(member.guild)
        return
    invite_data = await register_invited_member(member)
    await send_member_activity_log(member, joined=True, invite_data=invite_data)
    await send_member_join_ghost_ping(member)
    schedule_server_counter_refresh(member.guild)
    role = member.guild.get_role(NEW_MEMBER_ROLE_ID)
    if role:
        try:
            await member.add_roles(role, reason="Attribution automatique nouveau membre")
        except Exception as e:
            print(f"Erreur attribution role : {e}")


@bot.event
async def on_member_remove(member):
    invite_data = await register_departed_member(member)
    await send_member_activity_log(member, joined=False, invite_data=invite_data)
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
        if not adjust_verified_reviews_count(guild.id, 1):
            schedule_server_counter_refresh(guild, refresh_reviews=True)
        else:
            schedule_server_counter_refresh(guild)
    await bot.process_commands(message)


@bot.event
async def on_raw_message_delete(payload):
    guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
    if guild is not None and payload.channel_id in verified_reviews_channel_ids(guild.id):
        cached_message = getattr(payload, "cached_message", None)
        if cached_message is None or not cached_message.author.bot:
            if not adjust_verified_reviews_count(guild.id, -1):
                schedule_server_counter_refresh(guild, refresh_reviews=True)
            else:
                schedule_server_counter_refresh(guild)


@bot.event
async def on_raw_bulk_message_delete(payload):
    guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
    if guild is not None and payload.channel_id in verified_reviews_channel_ids(guild.id):
        cached_messages = getattr(payload, "cached_messages", ()) or ()
        cached_by_id = {message.id: message for message in cached_messages}
        deleted_count = sum(
            1
            for message_id in payload.message_ids
            if message_id not in cached_by_id or not cached_by_id[message_id].author.bot
        )
        if deleted_count:
            if not adjust_verified_reviews_count(guild.id, -deleted_count):
                schedule_server_counter_refresh(guild, refresh_reviews=True)
            else:
                schedule_server_counter_refresh(guild)


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
    embed = build_json_embed("tarifs_embed", data_override=texts)
    embed.description = description or None
    if not bool(texts.get("show_dynamic_fields", False)):
        return embed
    prices = get_pricing_config()
    gift_template = texts.get("gift_card_line_template", "**{amount} € reçus** → **{price} PC**")
    uber_template = texts.get("uber_eats_line_template", "**{drop} € estimés** → **{price} PC**")
    nitro_template = texts.get("nitro_value_template", "**{price} PC**")
    gift_lines = [
        format_embed_text(gift_template, {
            "amount": amount,
            "price": pinkcoin_number(prices["gift_cards"][str(amount)]),
        })
        for amount in GIFT_CARD_AMOUNTS
    ]
    uber_lines = [
        format_embed_text(uber_template, {
            "pack_key": pack_key,
            "drop": pack["drop"],
            "price": pinkcoin_number(prices["uber_eats"][pack_key]),
        })
        for pack_key, pack in UBEREATS_PACKS.items()
    ]
    dynamic_inline = bool(texts.get("dynamic_fields_inline", False))
    embed.add_field(
        name=texts.get("gift_cards_field_name", "💳 Cartes cadeaux — toutes les marques"),
        value="\n".join(gift_lines),
        inline=dynamic_inline,
    )
    embed.add_field(
        name=texts.get("uber_eats_field_name", "🍔 Uber Eats"),
        value="\n".join(uber_lines),
        inline=dynamic_inline,
    )
    embed.add_field(
        name=texts.get("nitro_field_name", "💎 Discord Nitro"),
        value=format_embed_text(nitro_template, {"price": pinkcoin_number(prices["discord_nitro"])}),
        inline=dynamic_inline,
    )
    return embed

def build_valo_embed():
    texts = load_embed_texts().get("valo_embed", DEFAULT_EMBED_DATA["valo_embed"])
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
    description = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip()
    embed = build_json_embed("valo_embed", data_override=texts)
    embed.description = description or None
    pricing = get_pricing_config()
    prices = pricing["valorant"]
    field_name_template = texts.get("region_field_name_template", "{emoji} {region}")
    pack_line_template = texts.get(
        "pack_line_template",
        "<:vp:1519915966476320901> **{pack}** — **{price} PC** · origine ≈ ~~{official} €~~",
    )
    region_emojis = texts.get("region_emojis", {}) if isinstance(texts.get("region_emojis"), dict) else {}
    dynamic_inline = bool(texts.get("dynamic_fields_inline", False))
    for region_key, region in VALO_REGIONS.items():
        lines = [
            format_embed_text(pack_line_template, {
                "region_key": region_key,
                "region": region["label"],
                "emoji": region_emojis.get(region_key, region["emoji"]),
                "pack_key": pack_key,
                "pack": pack["label"],
                "price": pinkcoin_number(prices[region_key][pack_key]),
                "official": format_price(pricing["valorant_original"][region_key][pack_key]),
            })
            for pack_key, pack in region["packs"].items()
        ]
        embed.add_field(
            name=format_embed_text(field_name_template, {
                "region_key": region_key,
                "region": region["label"],
                "emoji": region_emojis.get(region_key, region["emoji"]),
            }),
            value="\n".join(lines),
            inline=dynamic_inline,
        )
    return embed


def build_cp_embed():
    texts = load_embed_texts().get("cp_embed", DEFAULT_EMBED_DATA["cp_embed"])
    embed = build_json_embed("cp_embed", data_override=texts)
    prices = get_pricing_config()["cp"]
    line_template = texts.get(
        "pack_line_template",
        "<:cp:1528128623117205624> **{points} CP** — **{price} €** · officiel ≈ ~~{official} €~~",
    )
    lines = []
    for pack_key, pack in CP_PACKS.items():
        points = f"{pack['points']:,}".replace(",", " ")
        official = f"{pack['official_price']:.2f}".replace(".", ",")
        lines.append(format_embed_text(line_template, {
            "pack_key": pack_key,
            "points": points,
            "price": format_price(prices[pack_key]),
            "official": official,
        }))
    embed.add_field(
        name=texts.get("packs_field_name", "<:cp:1528128623117205624> Packs disponibles"),
        value="\n".join(lines),
        inline=bool(texts.get("dynamic_fields_inline", False)),
    )
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
        (["CALL OF DUTY POINTS", "COD POINTS"], build_cp_embed, CPOrderLauncherView()),
        (["AUTRES SERVICES", "ABONNEMENTS"], lambda: build_json_embed("autres_embed"), OtherServicesView()),
        (["PinkWallet", "PinkCoins", "Solde PinkGift", "Solde & paiements"], lambda: build_json_embed("balance_embed"), BalanceView()),
        (["PARRAINAGES PINKGIFT", "Programme de parrainage"], lambda: build_json_embed("parrainages_embed"), ReferralApplicationView()),
        (["RECRUTEMENT PINKGIFT", "Recrutement"], lambda: build_json_embed("recrutement_embed"), RecruitmentApplicationView()),
        (["PRIVILÈGES PINKGIFT", "PRIVILEGES PINKGIFT"], lambda: build_json_embed("privileges_embed"), PrivilegesLauncherView()),
        (["ÉQUIPE PINKGIFT", "EQUIPE PINKGIFT"], lambda: build_json_embed("team_embed"), None),
        (["Règlement", "REGLEMENT", "RÈGLEMENT"], lambda: build_json_embed("rules_embed"), None),
        (["FAQ PinkGift", "FAQ"], lambda: build_json_embed("faq_embed"), None),
        (["Classement", "CLASSEMENT"], build_leaderboard_embed, None),
    ]


async def repair_balance_ticket_opening_embeds():
    """Restaure l'embed et le bouton Close des tickets PinkWallet actifs."""
    repaired = 0
    for guild in bot.guilds:
        me = guild.me or (guild.get_member(bot.user.id) if bot.user else None)
        if me is None:
            continue
        for channel in guild.text_channels:
            if not is_balance_ticket(channel) or channel.name.startswith("closed-"):
                continue
            permissions = channel.permissions_for(me)
            if not permissions.view_channel or not permissions.read_message_history:
                continue

            user_id = get_balance_ticket_user_id(channel)
            if not user_id:
                continue
            opening_message = None
            fallback_message = None
            try:
                async for message in channel.history(limit=100, oldest_first=True):
                    if message.author.id != bot.user.id or not message.embeds:
                        continue
                    if fallback_message is None:
                        fallback_message = message
                    component_ids = {
                        getattr(component, "custom_id", None)
                        for row in message.components
                        for component in getattr(row, "children", [])
                    }
                    if message.pinned or component_ids.intersection({
                        "pinkgift_close_ticket",
                        "pinkgift_view_balance",
                        "pinkgift_recharge_balance",
                    }):
                        opening_message = message
                        break
                opening_message = opening_message or fallback_message
                if opening_message is None:
                    continue

                embed = build_json_embed("balance_ticket_embed", {
                    "user": f"<@{user_id}>",
                    "balance": pinkcoin_number(get_balance(guild.id, user_id)),
                })
                await opening_message.edit(embed=embed, view=CloseTicketView(user_id))
                await pin_first_bot_ticket_message(channel, opening_message)
                repaired += 1
            except (discord.Forbidden, discord.NotFound):
                continue
            except discord.HTTPException as error:
                print(f"Erreur restauration embed PinkWallet dans {channel}: {error}")
            except Exception as error:
                print(f"Erreur inattendue restauration PinkWallet dans {channel}: {error}")
    return repaired


async def repair_public_launcher_views():
    """Réattache les boutons actuels aux anciens panneaux publics du bot."""
    repaired = 0
    launcher_rules = (
        (("commandes pinkgift", "carte cadeaux"), build_tarifs_embed, OrderLauncherView),
        (("valorant", "valorant points"), build_valo_embed, ValoOrderLauncherView),
        (("call of duty points", "cod points"), build_cp_embed, CPOrderLauncherView),
        (("autres services", "abonnements"), lambda: build_json_embed("autres_embed"), OtherServicesView),
        (("solde & paiements", "solde pinkgift", "pinkwallet", "pinkcoins"), lambda: build_json_embed("balance_embed"), BalanceView),
        (("parrainages pinkgift", "programme de parrainage"), lambda: build_json_embed("parrainages_embed"), ReferralApplicationView),
        (("recrutement pinkgift",), lambda: build_json_embed("recrutement_embed"), RecruitmentApplicationView),
        (("privilèges pinkgift", "privileges pinkgift"), lambda: build_json_embed("privileges_embed"), PrivilegesLauncherView),
    )

    for guild in bot.guilds:
        me = guild.me or (guild.get_member(bot.user.id) if bot.user else None)
        if me is None:
            continue
        for channel in guild.text_channels:
            # Un ticket de recharge peut contenir « PinkWallet » dans son titre.
            # Il ne doit jamais être confondu avec le panneau public /pinkcoins.
            if is_managed_private_ticket(channel):
                continue
            permissions = channel.permissions_for(me)
            if not permissions.view_channel or not permissions.read_message_history:
                continue
            try:
                async for message in channel.history(limit=500):
                    if message.author.id != bot.user.id or not message.embeds:
                        continue
                    title = (message.embeds[0].title or "").lower()
                    for keywords, embed_builder, view_factory in launcher_rules:
                        if any(keyword in title for keyword in keywords):
                            await message.edit(embed=embed_builder(), view=view_factory())
                            repaired += 1
                            break
            except (discord.Forbidden, discord.NotFound):
                continue
            except discord.HTTPException as error:
                print(f"Erreur réparation boutons dans {channel}: {error}")
    return repaired


async def update_public_embeds_in_current_channel(ctx):
    builders = public_embed_builders()
    updated_count = 0
    channel = ctx.channel
    if is_managed_private_ticket(channel):
        return 0
    permissions = channel.permissions_for(ctx.guild.me or ctx.guild.default_role)
    if not permissions.read_message_history or not permissions.view_channel:
        return 0
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
        return 0
    except discord.HTTPException as error:
        print(f"Erreur mise à jour embeds dans {channel}: {error}")
    return updated_count


async def refresh_price_embeds_from_panel():
    """Actualise les panneaux /tarifs, /valo et /cp déjà publiés, sans envoyer de message."""
    rules = (
        (("commandes pinkgift", "carte cadeaux"), build_tarifs_embed, OrderLauncherView),
        (("valorant", "valorant points"), build_valo_embed, ValoOrderLauncherView),
        (("call of duty points", "cod points"), build_cp_embed, CPOrderLauncherView),
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


@bot.hybrid_command(name="maj_embed", description="Mettre à jour l’embed public du salon actuel")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def update_all_embeds(ctx):
    if ctx.guild is None:
        await ctx.send("❌ Cette commande doit être utilisée dans un serveur.", delete_after=6)
        return
    status = await ctx.send("🔄 Mise à jour de l’embed de ce salon en cours...")
    updated_count = await update_public_embeds_in_current_channel(ctx)
    if updated_count:
        await status.edit(content=f"✅ {updated_count} embed(s) mis à jour dans ce salon, sans ping.")
    else:
        await status.edit(content="❌ Aucun embed public reconnu n’a été trouvé dans ce salon.")
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
@commands.guild_only()
@commands.has_role(STAFF_ROLE_ID)
async def cmd_close_button(ctx):
    if isinstance(ctx.channel, discord.Thread):
        await ctx.send("ℹ️ Les fils de commande ne se ferment pas avec ce bouton.", ephemeral=True)
        return
    embed = build_json_embed("close_ticket_embed")
    await ctx.send(
        embed=embed,
        view=CloseTicketView(resolve_ticket_client_id(ctx.channel)),
    )

@bot.hybrid_command(name="tarifs", description="Publier le PinkShop et ses commandes")
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


@bot.hybrid_command(name="cp", description="Publier le panneau des Call of Duty Points")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_cp(ctx):
    embed = build_cp_embed()
    await ctx.send(content="||@everyone||", embed=embed, view=CPOrderLauncherView())


@bot.hybrid_command(name="autres", description="Publier le panneau des autres services")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_autres(ctx):
    await ctx.send(
        content="||@everyone||",
        embed=build_json_embed("autres_embed"),
        view=OtherServicesView(),
    )


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
    is_slash_command = ctx.interaction is not None
    if is_slash_command:
        await ctx.defer(ephemeral=True)
    if amount <= 0:
        await ctx.send(
            "❌ Indique un nombre de messages superieur a 0.",
            ephemeral=is_slash_command,
            delete_after=None if is_slash_command else 3,
        )
        return
    if not is_slash_command:
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
    deleted = await ctx.channel.purge(limit=amount)
    if is_slash_command:
        await ctx.send(f"🗑️ {len(deleted)} messages effaces.", ephemeral=True)
    else:
        await ctx.send(f"🗑️ {len(deleted)} messages effaces.", delete_after=4)


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


@bot.hybrid_command(name="reset_invitations", description="Réinitialiser les compteurs d'invitations")
@discord.app_commands.default_permissions(manage_guild=True)
@discord.app_commands.describe(
    member="Membre à réinitialiser, laisse vide pour tout le serveur",
    confirmation="Confirmer définitivement la remise à zéro",
)
@commands.guild_only()
@commands.has_role(STAFF_ROLE_ID)
async def cmd_reset_invitations(ctx, member: discord.Member = None, confirmation: bool = False):
    target_text = member.mention if member else "**tout le serveur**"
    if not confirmation:
        await ctx.send(
            f"⚠️ La remise à zéro de {target_text} est définitive. "
            "Relance la commande avec `confirmation:Oui` pour confirmer.",
            ephemeral=True,
        )
        return

    lock = INVITE_TRACKING_LOCKS.setdefault(ctx.guild.id, asyncio.Lock())
    async with lock:
        result = reset_invite_tracking_data(ctx.guild.id, member.id if member else None)
        await refresh_invite_cache(ctx.guild)

    await ctx.send(
        f"✅ Invitations réinitialisées pour {target_text}. "
        f"**{result['previous_total']}** invitation(s) totale(s) et "
        f"**{result['previous_active']}** active(s) ont été retirées.\n"
        f"Les **{result['affected_members']}** comptes déjà enregistrés ne pourront pas être recomptés en quittant puis revenant.",
        ephemeral=True,
    )


async def publish_pinkwallet_panel(ctx):
    await ctx.send(embed=build_json_embed("balance_embed"), view=BalanceView())


@bot.hybrid_command(name="pinkcoins", description="Publier le panneau PinkWallet et PinkCoins")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_pinkcoins(ctx):
    await publish_pinkwallet_panel(ctx)


@bot.hybrid_command(name="solde", description="Ancien alias du panneau PinkWallet")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_solde(ctx):
    await publish_pinkwallet_panel(ctx)


async def add_pinkcoins_from_euros(ctx, member, montant_euros):
    if montant_euros <= 0:
        await ctx.send("❌ Le montant doit être positif.", delete_after=5)
        return
    wallet = change_balance(ctx.guild.id, member.id, montant_euros, ctx.author.id)
    referral_lot = None
    try:
        referral_lot = track_referral_balance_credit(ctx.guild, member.id, montant_euros, ctx.author.id)
    except Exception as error:
        print(f"Erreur tracking PinkCoins parrainés pour {member}: {error}")
    await mark_balance_ticket_credited(ctx.guild, member.id)
    role_summary = None
    try:
        role_summary = await sync_customer_roles(ctx.guild, member.id)
    except Exception as error:
        print(f"Erreur attribution rôles client après recharge pour {member}: {error}")
    if referral_lot:
        try:
            await send_referral_tracking_notification(ctx.guild, member, ctx.author, referral_lot, wallet)
        except Exception as error:
            print(f"Erreur notification recharge parrainée pour {member}: {error}")
    tier_text = ""
    if role_summary:
        tier_text = (
            f" Dépôts nets : **{role_summary['total_added']:.2f} €** · "
            f"palier **{role_summary['tier']['label']}**"
            + (" · **meilleur client du serveur**" if role_summary["is_top"] else "")
            + "."
        )
    await ctx.send(
        f"✅ **{montant_euros:.2f} €** convertis en **{format_pinkcoins(montant_euros)}** pour {member.mention}. "
        f"PinkWallet : **{format_pinkcoins(wallet)}**.{tier_text}"
    )


async def remove_pinkcoins(ctx, member, montant_pinkcoins):
    try:
        montant_pinkcoins = parse_pinkcoin_amount(montant_pinkcoins)
    except ValueError:
        await ctx.send(
            "❌ Montant invalide. Exemples acceptés : `1250`, `1 250`, `2.500` ou `1,25k` PinkCoins.",
            delete_after=8,
        )
        return
    euros = pinkcoins_to_euros(montant_pinkcoins)
    try:
        wallet = change_balance(ctx.guild.id, member.id, -euros, ctx.author.id)
    except ValueError:
        await ctx.send("❌ PinkCoins insuffisants.", delete_after=5)
        return
    try:
        reconcile_referral_balance(ctx.guild.id, member.id, wallet)
    except Exception as error:
        print(f"Erreur réconciliation PinkCoins parrainés de {member}: {error}")
    role_summary = None
    try:
        role_summary = await sync_customer_roles(ctx.guild, member.id)
    except Exception as error:
        print(f"Erreur recalcul rôles client après retrait pour {member}: {error}")
    amount_text = f"{int(montant_pinkcoins):,}".replace(",", " ")
    tier_text = ""
    if role_summary:
        tier_text = (
            f" Dépôts nets : **{role_summary['total_added']:.2f} €** · "
            f"palier **{role_summary['tier']['label']}**."
        )
    await ctx.send(
        f"✅ **{amount_text} PinkCoins** retirés à {member.mention}. "
        f"PinkWallet : **{format_pinkcoins(wallet)}**.{tier_text}"
    )


@bot.hybrid_command(name="ajouter_pinkcoins", description="Convertir un dépôt en euros et créditer le PinkWallet")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.describe(member="Client concerné", montant_euros="Dépôt reçu en euros (1 € = 100 PinkCoins)")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_ajouter_pinkcoins(ctx, member: discord.Member, montant_euros: float):
    await add_pinkcoins_from_euros(ctx, member, montant_euros)


@bot.hybrid_command(name="retirer_pinkcoins", description="Retirer des PinkCoins du PinkWallet d'un client")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.describe(member="Client concerné", montant_pinkcoins="Exemple : 1250, 1 250 ou 1,25k PC")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_retirer_pinkcoins(ctx, member: discord.Member, montant_pinkcoins: str):
    await remove_pinkcoins(ctx, member, montant_pinkcoins)


@bot.hybrid_command(name="ajouter_solde", description="Ancien alias : convertir un dépôt en PinkCoins")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.describe(member="Client concerné", montant="Montant à ajouter en euros")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_ajouter_solde(ctx, member: discord.Member, montant: float):
    await add_pinkcoins_from_euros(ctx, member, montant)


@bot.hybrid_command(name="retirer_solde", description="Ancien alias : retirer des PinkCoins du PinkWallet")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.describe(member="Client concerné", montant="Montant à retirer en PinkCoins")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_retirer_solde(ctx, member: discord.Member, montant: str):
    await remove_pinkcoins(ctx, member, montant)


@bot.tree.command(name="corriger_depots", description="Retirer un montant des dépôts nets sans toucher au PinkWallet")
@discord.app_commands.guild_only()
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.checks.has_role(STAFF_ROLE_ID)
@discord.app_commands.describe(
    user="Client concerné",
    montant_euros="Montant historique à retirer des dépôts nets",
)
async def cmd_corriger_depots(
    interaction: discord.Interaction,
    user: discord.Member,
    montant_euros: float,
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        amount = Decimal(str(montant_euros)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        await interaction.followup.send("❌ Montant invalide.", ephemeral=True)
        return
    if not amount.is_finite() or amount <= 0 or amount > Decimal("100000"):
        await interaction.followup.send(
            "❌ Le montant à retirer doit être compris entre 0,01 € et 100 000 €.",
            ephemeral=True,
        )
        return

    try:
        remaining = remove_customer_net_deposit(
            interaction.guild_id,
            user.id,
            float(amount),
            interaction.user.id,
        )
    except ValueError as error:
        await interaction.followup.send(f"❌ {error}.", ephemeral=True)
        return
    except Exception as error:
        print(f"Erreur correction dépôts nets de {user} par {interaction.user}: {error}")
        await interaction.followup.send(
            "❌ La correction des dépôts nets a échoué.",
            ephemeral=True,
        )
        return

    try:
        await sync_customer_roles(interaction.guild, user.id)
    except Exception as error:
        print(f"Erreur rôles après correction dépôts nets de {user}: {error}")
    await interaction.followup.send(
        f"✅ **{float(amount):.2f} €** retirés des dépôts nets de {user.mention}.\n"
        f"Dépôts nets restants : **{remaining:.2f} €**.\n"
        "Le PinkWallet n’a pas été modifié.",
        ephemeral=True,
    )


@bot.tree.command(name="vente", description="Enregistrer une vente manuelle dans le panel")
@discord.app_commands.guild_only()
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.checks.has_role(STAFF_ROLE_ID)
@discord.app_commands.describe(
    user="Client concerné",
    produit="Nom du produit ou du service vendu",
    prix="Prix payé par le client en euros",
    cout_achat="Coût d'achat réel en euros",
)
async def cmd_vente(
    interaction: discord.Interaction,
    user: discord.Member,
    produit: str,
    prix: float,
    cout_achat: float,
):
    await interaction.response.defer(ephemeral=True, thinking=True)
    produit = re.sub(r"\s+", " ", str(produit or "")).strip()
    try:
        prix_decimal = Decimal(str(prix)).quantize(Decimal("0.01"))
        cout_decimal = Decimal(str(cout_achat)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        await interaction.followup.send("❌ Prix ou coût d'achat invalide.", ephemeral=True)
        return
    if not 1 <= len(produit) <= 100:
        await interaction.followup.send("❌ Le nom du produit doit contenir entre 1 et 100 caractères.", ephemeral=True)
        return
    if (
        not prix_decimal.is_finite()
        or not cout_decimal.is_finite()
        or prix_decimal <= 0
        or cout_decimal < 0
        or prix_decimal > Decimal("100000")
        or cout_decimal > Decimal("100000")
    ):
        await interaction.followup.send(
            "❌ Le prix doit être positif et le coût d'achat ne peut pas être négatif.",
            ephemeral=True,
        )
        return

    guild = interaction.guild
    if guild is None:
        await interaction.followup.send("❌ Cette commande doit être utilisée sur le serveur.", ephemeral=True)
        return
    if user.bot:
        await interaction.followup.send("❌ Une vente ne peut pas être attribuée à un bot.", ephemeral=True)
        return
    prix_value = float(prix_decimal)
    cout_value = float(cout_decimal)
    staff_id = interaction.user.id
    message_id = -time.time_ns()
    order_id = None
    deposit_applied = False
    try:
        wallet = apply_manual_sale_deposit(guild.id, user.id, prix_value, staff_id)
        deposit_applied = True
        order_id = save_order(
            guild.id,
            interaction.channel_id or 0,
            message_id,
            user.id,
            produit,
            prix_value,
            prix_value,
            user.name,
            "Vente manuelle",
        )
        save_order_purchase_cost(message_id, cout_value)
        mark_order_delivered(order_id, f"{MANUAL_SALE_CODE_PREFIX}{staff_id}")
    except Exception as error:
        if order_id is not None:
            try:
                delete_order_record(order_id)
                delete_panel_setting(f"order_cost:{message_id}")
            except Exception as cleanup_error:
                print(f"Erreur nettoyage vente manuelle #{order_id}: {cleanup_error}")
        if deposit_applied:
            try:
                reverse_manual_sale_deposit({
                    "guild_id": guild.id,
                    "user_id": user.id,
                    "paid": prix_value,
                    "code": f"{MANUAL_SALE_CODE_PREFIX}{staff_id}",
                })
            except Exception as rollback_error:
                print(f"ERREUR rollback complet vente manuelle de {user}: {rollback_error}")
        try:
            await sync_customer_roles(guild, user.id, target_member=user)
        except Exception as role_rollback_error:
            print(f"Erreur resynchronisation rôles après rollback vente de {user}: {role_rollback_error}")
        print(f"Erreur création vente manuelle par {interaction.user}: {error}")
        await interaction.followup.send(
            "❌ La vente n'a pas pu être enregistrée. Le PinkWallet du client n'a pas été modifié.",
            ephemeral=True,
        )
        return

    try:
        role_summary = await sync_customer_roles(guild, user.id, target_member=user)
    except Exception as error:
        print(f"Erreur rôles après vente manuelle pour {user}: {error}")
        try:
            total_added = get_customer_deposit_totals(guild.id).get(user.id, 0)
            total_spent = get_customer_spending_totals(guild.id).get(user.id, 0)
        except Exception as totals_error:
            print(f"Erreur totaux après vente manuelle pour {user}: {totals_error}")
            total_added = total_spent = 0
        role_summary = {
            "total_added": total_added,
            "total_spent": total_spent,
            "tier": customer_highest_tier(0),
            "is_top": False,
            "errors": [str(error)],
        }
    profit = round(prix_value - cout_value, 2)
    role_errors = role_summary.get("errors", [])
    role_status = (
        "\n⚠️ **Vente enregistrée, mais rôles Discord non synchronisés :** "
        + " ; ".join(str(error) for error in role_errors)
        if role_errors
        else "\n✅ Les rôles Discord du client ont été synchronisés."
    )
    await interaction.followup.send(
        f"✅ Vente **#{order_id}** enregistrée pour {user.mention}.\n"
        f"**Produit :** {discord.utils.escape_markdown(produit)}\n"
        f"**Prix :** {prix_value:.2f} € · **Coût :** {cout_value:.2f} € · "
        f"**Bénéfice :** {profit:.2f} €\n"
        f"**Total dépensé :** {role_summary['total_spent']:.2f} € · "
        f"**Dépôts nets :** {role_summary['total_added']:.2f} €\n"
        f"Le PinkWallet reste à **{format_pinkcoins(wallet)}**."
        f"{role_status}",
        ephemeral=True,
    )



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


PANEL_IDLE_TIMEOUT_SECONDS = 30 * 60


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
    if not request.path.startswith("/panel") or request.path == "/panel/heartbeat":
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
        now = time.time()
        try:
            last_activity = float(session.get("panel_last_activity_at", session.get("panel_login_at", 0)))
        except (TypeError, ValueError):
            last_activity = 0
        valid_token = PANEL_PASSWORD and secrets.compare_digest(session.get("panel_auth", ""), panel_auth_token())
        if not valid_token or now - last_activity >= PANEL_IDLE_TIMEOUT_SECONDS:
            session.clear()
            return redirect(url_for("panel_login"))
        session["panel_last_activity_at"] = now
        if not session.get("csrf"):
            session["csrf"] = secrets.token_urlsafe(24)
        return view(*args, **kwargs)
    return wrapped


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
    delivered = status in ("done", "livre", "livré", "delivered")
    order_id = panel_order_id(order)
    return (1 if delivered else 0, -order_id if delivered else order_id)


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


PANEL_TEMPLATE = """
<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Panel</title>
<style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}h1{margin:0;color:#ff8fc8;font-size:23px}main{padding:22px 5%}nav{display:flex;gap:8px;margin-bottom:18px}.tab{color:#e8dce3;text-decoration:none;padding:10px 14px;border:1px solid #4c3543}.tab.active{background:#e8509a;color:white;border-color:#e8509a}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}table{width:100%;border-collapse:collapse;background:#171419}th,td{text-align:left;padding:11px;border-bottom:1px solid #332630}th{color:#ff9dce}input,select{background:#0e0d11;color:white;border:1px solid #5a3a4d;padding:9px;min-width:160px}select{cursor:pointer}.filters{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 16px 0}.filters label{color:#ff9dce;font-weight:bold}button{background:#e8509a;color:white;border:0;padding:10px 13px;cursor:pointer}.delete{background:#9d294b;margin-left:5px}.done{color:#74d99f}.pending{color:#ffd27b}.muted{color:#aa98a4;font-size:12px}@media(max-width:800px){table,thead,tbody,tr,td{display:block}thead{display:none}tr{padding:12px;border-bottom:1px solid #332630}td{border:0;padding:6px}}</style></head><body>
<header><h1>PinkGift — Panel staff</h1><a href="{{ url_for('panel_logout') }}" style="color:#ff9dce">Déconnexion</a></header><main>
<nav><a class="tab {{ 'active' if tab == 'orders' else '' }}" href="{{ url_for('panel_orders', tab='orders') }}">Commandes</a><a class="tab {{ 'active' if tab == 'valorant' else '' }}" href="{{ url_for('panel_orders', tab='valorant') }}">Valorant</a><a class="tab" href="{{ url_for('panel_cp') }}">CP</a><a class="tab {{ 'active' if tab == 'clients' else '' }}" href="{{ url_for('panel_orders', tab='clients') }}">Clients</a><a class="tab" href="{{ url_for('panel_finances') }}">Statistiques</a><a class="tab" href="{{ url_for('panel_referrals') }}">Parrainage</a><a class="tab" href="{{ url_for('panel_prices') }}">Prix</a><a class="tab" href="{{ url_for('panel_stock') }}">Stock</a><a class="tab" href="{{ url_for('panel_embeds') }}">Embeds</a></nav>
{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}
{% if tab == 'clients' %}<table><thead><tr><th>Client</th><th>ID Discord</th><th>Commandes</th><th>Total dépensé</th><th>Dépôts nets</th><th>Palier Discord</th><th>Statut</th></tr></thead><tbody>{% for client in clients %}<tr><td><a href="https://discord.com/users/{{ client.user_id }}" target="_blank" style="color:#ff9dce;text-decoration:none"><strong>@{{ client.user_name }}</strong></a></td><td class="muted">{{ client.user_id }}</td><td>{{ client.order_count }}</td><td><strong>{{ '%.2f'|format(client.total_spent) }} €</strong></td><td><strong>{{ '%.2f'|format(client.total_added) }} €</strong></td><td><strong>{{ client.tier_label }}</strong>{% if client.tier_role_id %}<div class="muted">{{ client.tier_role_name }} · {{ client.tier_role_id }}</div>{% endif %}</td><td>{% if client.is_top %}<strong class="done">🏆 Meilleur client</strong>{% elif client.total_added > 0 %}<span class="done">✓ Client</span>{% else %}<span class="muted">Aucun dépôt</span>{% endif %}</td></tr>{% else %}<tr><td colspan="7">Aucun client enregistré.</td></tr>{% endfor %}</tbody></table>
{% else %}{% if tab == 'orders' %}<form class="filters" method="get" action="{{ url_for('panel_orders') }}"><input type="hidden" name="tab" value="orders"><label for="service-filter">Service</label><select id="service-filter" name="service" onchange="this.form.submit()"><option value="">Tous les services</option>{% for service in service_options %}<option value="{{ service }}" {% if service == service_filter %}selected{% endif %}>{{ service }}</option>{% endfor %}</select><label for="amount-filter">Montant</label><select id="amount-filter" name="amount" onchange="this.form.submit()"><option value="">Tous les montants</option>{% for amount in amount_options %}<option value="{{ amount }}" {% if amount == amount_filter %}selected{% endif %}>{{ amount }}</option>{% endfor %}</select></form>{% elif tab == 'valorant' %}<form class="filters" method="get" action="{{ url_for('panel_orders') }}"><input type="hidden" name="tab" value="valorant"><label for="region-filter">Région</label><select id="region-filter" name="region" onchange="this.form.submit()"><option value="">Toutes les régions</option>{% for region in region_options %}<option value="{{ region }}" {% if region == region_filter %}selected{% endif %}>{{ region }}</option>{% endfor %}</select><label for="pack-filter">Pack VP</label><select id="pack-filter" name="pack" onchange="this.form.submit()"><option value="">Tous les packs</option>{% for pack in pack_options %}<option value="{{ pack }}" {% if pack == pack_filter %}selected{% endif %}>{{ pack }}</option>{% endfor %}</select></form>{% endif %}<table><thead><tr><th>ID</th><th>Client</th><th>Service</th><th>Reçu</th><th>Payé</th><th>État</th><th>Actions</th></tr></thead><tbody>{% for order in orders %}<tr><td>#{{ loop.index }}</td><td><a href="https://discord.com/users/{{ order.user_id }}" target="_blank" style="color:#ff9dce;text-decoration:none">@{{ order.user_name or order.user_id }}</a></td><td>{{ order.service }}</td><td>{{ order.received_label or ((order.amount|string) + " €") }}</td><td>{{ order.paid }} €</td><td class="{{ order.status }}">{{ order.status }}</td><td><form method="post" action="{{ url_for('panel_set_code', order_id=order.id) }}" style="display:inline"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="return_tab" value="{{ tab }}"><input type="hidden" name="return_service" value="{{ service_filter }}"><input type="hidden" name="return_amount" value="{{ amount_filter }}"><input type="hidden" name="return_region" value="{{ region_filter }}"><input type="hidden" name="return_pack" value="{{ pack_filter }}"><input name="code" required placeholder="Code cadeau" value="{{ order.code or '' }}"><button type="submit">Livrer</button></form><form method="post" action="{{ url_for('panel_delete_order', order_id=order.id) }}" style="display:inline" onsubmit="return confirm('Supprimer cette commande du panel ?')"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="return_tab" value="{{ tab }}"><input type="hidden" name="return_service" value="{{ service_filter }}"><input type="hidden" name="return_amount" value="{{ amount_filter }}"><input type="hidden" name="return_region" value="{{ region_filter }}"><input type="hidden" name="return_pack" value="{{ pack_filter }}"><button class="delete" type="submit" title="Supprimer">Supprimer</button></form></td></tr>{% else %}<tr><td colspan="7">Aucune commande enregistrée.</td></tr>{% endfor %}</tbody></table>{% endif %}
</main></body></html>"""


PANEL_STOCK_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Stock</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}main{padding:22px 5%}h1{color:#ff8fc8}table{width:100%;border-collapse:collapse;background:#171419;margin-bottom:28px}th,td{text-align:left;padding:11px;border-bottom:1px solid #332630}th{color:#ff9dce}select,button{background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:9px}button{background:#e8509a;border:0;cursor:pointer}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}a{color:#ff9dce}</style></head><body><header><h1>PinkGift — Stock</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main>{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}<h2>Cartes cadeaux / produits</h2><table><thead><tr><th>Service</th><th>État</th><th>Action</th></tr></thead><tbody>{% for item in products %}<tr><td>{{ item.display }}</td><td>{{ ok_emoji if item.available else ko_emoji }} {{ 'Disponible' if item.available else 'Rupture' }}</td><td><form method="post"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="kind" value="product"><input type="hidden" name="key" value="{{ item.key }}"><select name="available"><option value="1" {% if item.available %}selected{% endif %}>Disponible</option><option value="0" {% if not item.available %}selected{% endif %}>Rupture</option></select><button>Enregistrer</button></form></td></tr>{% endfor %}</tbody></table><h2>Valorant Points</h2><table><thead><tr><th>Région</th><th>Pack</th><th>État</th><th>Action</th></tr></thead><tbody>{% for item in valorant %}<tr><td>{{ item.region }}</td><td>{{ item.pack }} — {{ item.price }} €</td><td>{{ ok_emoji if item.available else ko_emoji }} {{ 'Disponible' if item.available else 'Rupture' }}</td><td><form method="post"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="kind" value="valorant"><input type="hidden" name="region" value="{{ item.region_key }}"><input type="hidden" name="key" value="{{ item.pack_key }}"><select name="available"><option value="1" {% if item.available %}selected{% endif %}>Disponible</option><option value="0" {% if not item.available %}selected{% endif %}>Rupture</option></select><button>Enregistrer</button></form></td></tr>{% endfor %}</tbody></table></main></body></html>"""

PANEL_PRICES_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Prix</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}main{padding:22px 5%;max-width:1000px}h1{color:#ff8fc8}.card{background:#171419;border:1px solid #332630;padding:16px;margin-bottom:18px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:13px}.field{display:flex;flex-direction:column;gap:6px}.field span{color:#ff9dce;font-weight:bold}.field small,.muted{color:#aa98a4}input{background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:11px;font-size:16px}button{background:#e8509a;color:#fff;border:0;padding:13px 18px;cursor:pointer;font-weight:bold}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}a{color:#ff9dce}</style></head><body><header><h1>PinkGift — Prix</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main>{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}<p class="muted">Les nouveaux prix sont utilisés immédiatement dans les menus, les embeds et le débit du solde. Aucun redémarrage du bot n'est nécessaire.</p><form method="post"><input type="hidden" name="csrf" value="{{ session.csrf }}"><section class="card"><h2>Cartes cadeaux — toutes les marques</h2><div class="grid">{% for item in gift_cards %}<label class="field"><span>{{ item.amount }} € reçus</span><input type="number" name="gift_{{ item.amount }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01" required><small>Montant débité en euros</small></label>{% endfor %}</div></section><section class="card"><h2>Uber Eats</h2><div class="grid">{% for item in uber_eats %}<label class="field"><span>{{ item.drop }} € estimés</span><input type="number" name="uber_{{ item.key }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01" required><small>Montant débité en euros</small></label>{% endfor %}</div></section><section class="card"><h2>Discord Nitro</h2><div class="grid"><label class="field"><span>Discord Nitro</span><input type="number" name="discord_nitro" value="{{ discord_nitro }}" min="0.01" max="100000" step="0.01" required><small>Montant débité en euros</small></label></div></section><section class="card"><h2>Valorant Points</h2><div class="grid">{% for item in valorant %}<label class="field"><span>{{ item.region }} — {{ item.pack }}</span><input type="number" name="valo_{{ item.region_key }}_{{ item.pack_key }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01" required><small>Montant débité en euros</small></label>{% endfor %}</div></section><button type="submit">Enregistrer tous les prix</button></form></main></body></html>"""

PANEL_FINANCES_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Statistiques</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}main{padding:22px 5%;max-width:1100px}h1{color:#ff8fc8}.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin-bottom:20px}.toolbar label,.cost-form label{display:flex;flex-direction:column;gap:6px;color:#ff9dce;font-weight:bold}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-bottom:22px}.card{background:#171419;border:1px solid #332630;padding:18px}.card span{display:block;color:#aa98a4;font-size:13px}.card strong{display:block;margin-top:8px;color:#fff;font-size:30px}.card.profit strong.positive{color:#74d99f}.card.profit strong.negative{color:#ff718f}input,button{background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:10px;font-size:15px}button{background:#e8509a;border:0;cursor:pointer;font-weight:bold}table{width:100%;border-collapse:collapse;background:#171419;margin-top:18px}th,td{text-align:left;padding:11px;border-bottom:1px solid #332630}th{color:#ff9dce}.cost-form{display:flex;flex-wrap:wrap;gap:10px;align-items:end;background:#171419;border:1px solid #332630;padding:16px}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}.muted{color:#aa98a4;font-size:13px}a{color:#ff9dce}</style></head><body><header><h1>PinkGift — Statistiques</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main>{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}<form class="toolbar" method="get"><label>Mois<input type="month" name="month" value="{{ stats.month }}" required></label><button type="submit">Afficher</button></form><h2>{{ month_label }}</h2><div class="cards"><article class="card"><span>Chiffre d'affaires</span><strong>{{ '%.2f'|format(stats.revenue) }} €</strong></article><article class="card"><span>Coûts renseignés</span><strong>{{ '%.2f'|format(stats.costs) }} €</strong></article><article class="card profit"><span>Bénéfice</span><strong class="{{ 'positive' if stats.profit >= 0 else 'negative' }}">{{ '%.2f'|format(stats.profit) }} €</strong></article><article class="card"><span>Achats comptabilisés</span><strong>{{ stats.orders }}</strong></article><article class="card"><span>Panier moyen</span><strong>{{ '%.2f'|format(stats.average_order) }} €</strong></article></div><form class="cost-form" method="post"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="month" value="{{ stats.month }}"><label>Coûts d'achat et dépenses du mois<input type="number" name="costs" value="{{ stats.costs }}" min="0" max="100000" step="0.01" required></label><button type="submit">Recalculer le bénéfice</button><span class="muted">Bénéfice = chiffre d'affaires comptabilisé dès l'achat − coûts renseignés.</span></form><h2>Détail par produit</h2><table><thead><tr><th>Produit</th><th>Achats</th><th>Chiffre d'affaires</th></tr></thead><tbody>{% for item in stats.breakdown %}<tr><td>{{ item.service }}</td><td>{{ item.orders }}</td><td>{{ '%.2f'|format(item.revenue) }} €</td></tr>{% else %}<tr><td colspan="3">Aucun achat comptabilisé pendant ce mois.</td></tr>{% endfor %}</tbody></table></main></body></html>"""

PANEL_PRICES_COSTS_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Prix et coûts</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}main{padding:22px 5%;max-width:1100px}h1{color:#ff8fc8}.card,details{background:#171419;border:1px solid #332630;padding:16px;margin-bottom:16px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:13px}.field{display:flex;flex-direction:column;gap:6px}.field span,summary{color:#ff9dce;font-weight:bold}.field small,.muted{color:#aa98a4}summary{cursor:pointer}details .grid{margin-top:15px}input{background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:10px;font-size:15px}button{background:#e8509a;color:#fff;border:0;padding:13px 18px;cursor:pointer;font-weight:bold}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}a{color:#ff9dce}</style></head><body><header><h1>PinkGift — Prix et coûts d'achat</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main>{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}<p class="muted">Le prix de vente détermine le débit client. Le coût d'achat est enregistré avec chaque nouvelle commande pour calculer le bénéfice sans modifier l'historique.</p><form method="post"><input type="hidden" name="csrf" value="{{ session.csrf }}"><section class="card"><h2>Prix de vente des cartes cadeaux</h2><div class="grid">{% for item in gift_cards %}<label class="field"><span>{{ item.amount }} € reçus</span><input type="number" name="gift_{{ item.amount }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01" required><small>Débit client</small></label>{% endfor %}</div></section><h2>Coûts d'achat des cartes par marque</h2>{% for product in gift_cost_products %}<details><summary>{{ product.display }}</summary><div class="grid">{% for item in product.amounts %}<label class="field"><span>Carte {{ item.amount }} €</span><input type="number" name="cost_gift_{{ product.key }}_{{ item.amount }}" value="{{ item.cost }}" min="0" max="100000" step="0.01" required><small>Coût d'achat</small></label>{% endfor %}</div></details>{% endfor %}<section class="card"><h2>Uber Eats</h2><div class="grid">{% for item in uber_eats %}<label class="field"><span>{{ item.drop }} € estimés — prix de vente</span><input type="number" name="uber_{{ item.key }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01" required></label><label class="field"><span>{{ item.drop }} € estimés — coût d'achat</span><input type="number" name="cost_uber_{{ item.key }}" value="{{ item.cost }}" min="0" max="100000" step="0.01" required></label>{% endfor %}</div></section><section class="card"><h2>Discord Nitro</h2><div class="grid"><label class="field"><span>Prix de vente</span><input type="number" name="discord_nitro" value="{{ discord_nitro }}" min="0.01" max="100000" step="0.01" required></label><label class="field"><span>Coût d'achat</span><input type="number" name="cost_discord_nitro" value="{{ discord_nitro_cost }}" min="0" max="100000" step="0.01" required></label></div></section><section class="card"><h2>Valorant Points</h2><div class="grid">{% for item in valorant %}<label class="field"><span>{{ item.region }} — {{ item.pack }} — prix de vente</span><input type="number" name="valo_{{ item.region_key }}_{{ item.pack_key }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01" required></label><label class="field"><span>{{ item.region }} — {{ item.pack }} — coût d'achat</span><input type="number" name="cost_valo_{{ item.region_key }}_{{ item.pack_key }}" value="{{ item.cost }}" min="0" max="100000" step="0.01" required></label>{% endfor %}</div></section><button type="submit">Enregistrer les prix et les coûts</button></form></main></body></html>"""

PANEL_FINANCES_PRODUCT_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Statistiques</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}main{padding:22px 5%;max-width:1100px}h1{color:#ff8fc8}.toolbar{display:flex;gap:10px;align-items:end;margin-bottom:20px}.toolbar label{display:flex;flex-direction:column;gap:6px;color:#ff9dce;font-weight:bold}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-bottom:22px}.card{background:#171419;border:1px solid #332630;padding:18px}.card span{display:block;color:#aa98a4;font-size:13px}.card strong{display:block;margin-top:8px;font-size:30px}.positive{color:#74d99f}.negative{color:#ff718f}input,button{background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:10px}button{background:#e8509a;border:0;cursor:pointer}table{width:100%;border-collapse:collapse;background:#171419}th,td{text-align:left;padding:11px;border-bottom:1px solid #332630}th{color:#ff9dce}.muted{color:#aa98a4;font-size:13px}a{color:#ff9dce}</style></head><body><header><h1>PinkGift — Statistiques</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main><form class="toolbar" method="get"><label>Mois<input type="month" name="month" value="{{ stats.month }}" required></label><button>Afficher</button></form><h2>{{ month_label }}</h2><div class="cards"><article class="card"><span>Chiffre d'affaires</span><strong>{{ '%.2f'|format(stats.revenue) }} €</strong></article><article class="card"><span>Coûts d'achat</span><strong>{{ '%.2f'|format(stats.costs) }} €</strong></article><article class="card"><span>Bénéfice</span><strong class="{{ 'positive' if stats.profit >= 0 else 'negative' }}">{{ '%.2f'|format(stats.profit) }} €</strong></article><article class="card"><span>Achats comptabilisés</span><strong>{{ stats.orders }}</strong></article><article class="card"><span>Panier moyen</span><strong>{{ '%.2f'|format(stats.average_order) }} €</strong></article></div><p class="muted">Le bénéfice utilise le coût d'achat enregistré dès la création de la commande. Une commande remboursée ou supprimée est retirée des statistiques. <a href="{{ url_for('panel_prices') }}">Modifier les coûts d'achat</a>.</p><h2>Détail par produit</h2><table><thead><tr><th>Produit</th><th>Ventes</th><th>CA</th><th>Coûts</th><th>Bénéfice</th></tr></thead><tbody>{% for item in stats.breakdown %}<tr><td>{{ item.service }}</td><td>{{ item.orders }}</td><td>{{ '%.2f'|format(item.revenue) }} €</td><td>{{ '%.2f'|format(item.costs) }} €</td><td class="{{ 'positive' if item.profit >= 0 else 'negative' }}">{{ '%.2f'|format(item.profit) }} €</td></tr>{% else %}<tr><td colspan="5">Aucun achat comptabilisé pendant ce mois.</td></tr>{% endfor %}</tbody></table></main></body></html>"""

NITRO_FINANCE_BLOCK = """<h2>Discord Nitro — ventes du tiers</h2><div class="cards"><article class="card"><span>Nitro achetés</span><strong>{{ stats.nitro.orders }}</strong></article><article class="card"><span>Chiffre d'affaires Nitro</span><strong>{{ '%.2f'|format(stats.nitro.revenue) }} €</strong></article><article class="card"><span>Coûts d'achat Nitro</span><strong>{{ '%.2f'|format(stats.nitro.costs) }} €</strong></article><article class="card"><span>Bénéfice Nitro généré</span><strong class="{{ 'positive' if stats.nitro.profit >= 0 else 'negative' }}">{{ '%.2f'|format(stats.nitro.profit) }} €</strong></article></div>"""
PANEL_FINANCES_NITRO_TEMPLATE = PANEL_FINANCES_PRODUCT_TEMPLATE.replace(
    "</div><p class=\"muted\">",
    f"</div>{NITRO_FINANCE_BLOCK}<p class=\"muted\">",
    1,
)

PANEL_REFERRALS_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Parrainage</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}main{padding:22px 5%;max-width:1200px}h1{color:#ff8fc8}.card{background:#171419;border:1px solid #332630;padding:16px;margin-bottom:18px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:11px}.field{display:flex;flex-direction:column;gap:5px}.field span{color:#ff9dce;font-weight:bold}.field small,.muted{color:#aa98a4}input,button{background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:10px}button{background:#e8509a;border:0;cursor:pointer;font-weight:bold}table{width:100%;border-collapse:collapse;background:#171419;margin:18px 0}th,td{text-align:left;padding:10px;border-bottom:1px solid #332630;vertical-align:top}th{color:#ff9dce}.inline-form{display:flex;flex-wrap:wrap;gap:7px;align-items:center}.inline-form input{min-width:90px}.positive{color:#74d99f;font-weight:bold}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}a{color:#ff9dce}</style></head><body><header><h1>PinkGift — Parrainage</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main>{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}<section class="card"><h2>Créer un code</h2><form method="post"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="action" value="save"><div class="grid"><label class="field"><span>Code</span><input name="code" minlength="3" maxlength="32" placeholder="PINKY10" required></label><label class="field"><span>Nom du parrain</span><input name="sponsor_name" maxlength="80" required></label><label class="field"><span>ID Discord du parrain</span><input name="sponsor_id" inputmode="numeric" placeholder="Optionnel"></label><label class="field"><span>Commission (%)</span><input type="number" name="percentage" min="0" max="100" step="0.01" required></label><label class="field"><span>Déjà versé (€)</span><input type="number" name="paid" value="0" min="0" step="0.01" required></label></div><p><label><input type="checkbox" name="active" value="1" checked> Code actif</label></p><button>Créer le code</button></form></section><h2>Suivi des parrains</h2><table><thead><tr><th>Code / Parrain</th><th>Utilisations</th><th>Solde ajouté</th><th>Commission générée</th><th>Déjà versé</th><th>Reste à verser</th><th>Configuration</th></tr></thead><tbody>{% for item in summaries %}<tr><td><strong>{{ item.code }}</strong><br>{{ item.sponsor_name }}{% if item.sponsor_id %}<br><a href="https://discord.com/users/{{ item.sponsor_id }}" target="_blank">{{ item.sponsor_id }}</a>{% endif %}<br>{{ 'Actif' if item.active else 'Désactivé' }}</td><td>{{ item.uses }}</td><td>{{ '%.2f'|format(item.amount) }} €</td><td>{{ '%.2f'|format(item.commission) }} €</td><td>{{ '%.2f'|format(item.paid) }} €</td><td class="positive">{{ '%.2f'|format(item.due) }} €</td><td><form class="inline-form" method="post"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="action" value="save"><input type="hidden" name="code" value="{{ item.code }}"><input name="sponsor_name" value="{{ item.sponsor_name }}" title="Nom" required><input name="sponsor_id" value="{{ item.sponsor_id }}" title="ID Discord"><input type="number" name="percentage" value="{{ item.percentage }}" min="0" max="100" step="0.01" title="Pourcentage" required><input type="number" name="paid" value="{{ item.paid }}" min="0" step="0.01" title="Déjà versé" required><label><input type="checkbox" name="active" value="1" {% if item.active %}checked{% endif %}> actif</label><button>Enregistrer</button></form></td></tr>{% else %}<tr><td colspan="7">Aucun code créé.</td></tr>{% endfor %}</tbody></table><h2>Historique récent</h2><table><thead><tr><th>Date</th><th>Code</th><th>Client</th><th>Solde ajouté</th><th>Taux</th><th>Commission</th></tr></thead><tbody>{% for event in events %}<tr><td>{{ event.created_at }}</td><td>{{ event.code }}</td><td><a href="https://discord.com/users/{{ event.user_id }}" target="_blank">{{ event.user_id }}</a></td><td>{{ '%.2f'|format(event.amount) }} €</td><td>{{ event.percentage }} %</td><td>{{ '%.2f'|format(event.commission) }} €</td></tr>{% else %}<tr><td colspan="6">Aucune commission enregistrée.</td></tr>{% endfor %}</tbody></table></main></body></html>"""

PANEL_REFERRALS_PROFIT_TEMPLATE = (
    PANEL_REFERRALS_TEMPLATE
    .replace(
        "button{background:#e8509a;border:0;cursor:pointer;font-weight:bold}table",
        "button{background:#e8509a;border:0;cursor:pointer;font-weight:bold}.delete{background:#9d294b}table",
        1,
    )
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
        "<br>{{ 'Actif' if item.active else 'Désactivé' }}",
        "<br>{% if item.configured %}{{ 'Actif' if item.active else 'Désactivé' }}{% else %}Historique à purger{% endif %}",
    )
    .replace(
        "<td><form class=\"inline-form\" method=\"post\"><input type=\"hidden\" name=\"csrf\" value=\"{{ session.csrf }}\"><input type=\"hidden\" name=\"action\" value=\"save\">",
        "<td>{% if item.configured %}<form class=\"inline-form\" method=\"post\"><input type=\"hidden\" name=\"csrf\" value=\"{{ session.csrf }}\"><input type=\"hidden\" name=\"action\" value=\"save\">",
    )
    .replace(
        "<button>Enregistrer</button></form></td></tr>{% else %}",
        "<button>Enregistrer</button></form><form class=\"inline-form\" method=\"post\" onsubmit=\"return confirm('Supprimer définitivement ce code et tout son historique de commissions ? Cette action est irréversible.')\"><input type=\"hidden\" name=\"csrf\" value=\"{{ session.csrf }}\"><input type=\"hidden\" name=\"action\" value=\"delete\"><input type=\"hidden\" name=\"code\" value=\"{{ item.code }}\"><button class=\"delete\" type=\"submit\">Supprimer définitivement</button></form>{% else %}<form class=\"inline-form\" method=\"post\" onsubmit=\"return confirm('Purger définitivement cet historique de commissions ? Cette action est irréversible.')\"><input type=\"hidden\" name=\"csrf\" value=\"{{ session.csrf }}\"><input type=\"hidden\" name=\"action\" value=\"delete\"><input type=\"hidden\" name=\"code\" value=\"{{ item.code }}\"><button class=\"delete\" type=\"submit\">Purger l'historique</button></form>{% endif %}</td></tr>{% else %}",
        1,
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

PANEL_REFERRALS_PROFIT_TEMPLATE = (
    PANEL_REFERRALS_PROFIT_TEMPLATE
    .replace(
        '<table><thead><tr><th>Code / Parrain</th>',
        '<table class="referral-summary"><thead><tr><th>Code / Parrain</th>',
        1,
    )
    .replace(
        '<table><thead><tr><th>Date</th>',
        '<table class="referral-history"><thead><tr><th>Date</th>',
        1,
    )
)

PANEL_REFERRALS_LAYOUT_CSS = r"""
body { overflow-x: clip; }
body main { width: min(1680px, calc(100% - 28px)); max-width: 1680px !important; }
.referral-summary, .referral-history { table-layout: fixed; }
.referral-summary th, .referral-summary td,
.referral-history th, .referral-history td {
  min-width: 0 !important;
  padding: 11px 9px !important;
  white-space: normal !important;
  overflow-wrap: anywhere;
}
.referral-summary th { font-size: 10px; letter-spacing: .035em; }
.referral-summary th:nth-child(1) { width: 13%; }
.referral-summary th:nth-child(n+2):nth-child(-n+9) { width: 6.75%; }
.referral-summary th:nth-child(10) { width: 33%; }
.referral-summary .inline-form {
  display: grid !important;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  width: 100%;
  margin: 0 0 8px;
}
.referral-summary .inline-form input,
.referral-summary .inline-form button { width: 100%; min-width: 0 !important; }
.referral-summary .inline-form label { grid-column: 1 / -1; }
.referral-summary .inline-form button { min-height: 36px; padding: 7px 9px !important; }
.referral-history th:nth-child(1) { width: 16%; }
.referral-history th:nth-child(3) { width: 17%; }
.referral-history th:nth-child(4) { width: 19%; }

@media (max-width: 1250px) {
  .referral-summary, .referral-history {
    display: block !important;
    overflow: visible !important;
    border: 0 !important;
    border-radius: 0;
    background: transparent !important;
    box-shadow: none;
  }
  .referral-summary thead, .referral-history thead { display: none !important; }
  .referral-summary tbody, .referral-history tbody { display: grid !important; gap: 14px; }
  .referral-summary tr, .referral-history tr {
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    padding: 6px 14px !important;
    overflow: hidden;
    border: 1px solid var(--border);
    border-radius: 16px;
    background: rgba(16, 17, 24, .88);
    box-shadow: 0 14px 40px rgba(0, 0, 0, .18);
  }
  .referral-summary td, .referral-history td {
    display: grid !important;
    grid-template-columns: minmax(115px, .85fr) minmax(0, 1.15fr);
    align-items: center;
    gap: 10px;
    min-width: 0 !important;
    padding: 10px 4px !important;
    border-bottom: 1px solid rgba(255,255,255,.055) !important;
  }
  .referral-summary td:nth-child(odd), .referral-history td:nth-child(odd) { padding-right: 14px !important; }
  .referral-summary td:nth-child(even), .referral-history td:nth-child(even) { padding-left: 14px !important; }
  .referral-summary td::before, .referral-history td::before {
    color: var(--muted);
    font-size: 10px;
    font-weight: 750;
    letter-spacing: .045em;
    text-transform: uppercase;
  }
  .referral-summary td:nth-child(1)::before { content: "Code / Parrain"; }
  .referral-summary td:nth-child(2)::before { content: "Achats"; }
  .referral-summary td:nth-child(3)::before { content: "Solde credite"; }
  .referral-summary td:nth-child(4)::before { content: "Solde restant"; }
  .referral-summary td:nth-child(5)::before { content: "Solde utilise"; }
  .referral-summary td:nth-child(6)::before { content: "Benefice genere"; }
  .referral-summary td:nth-child(7)::before { content: "Commission"; }
  .referral-summary td:nth-child(8)::before { content: "Deja verse"; }
  .referral-summary td:nth-child(9)::before { content: "A verser"; }
  .referral-summary td:nth-child(10)::before { content: "Configuration"; }
  .referral-history td:nth-child(1)::before { content: "Date"; }
  .referral-history td:nth-child(2)::before { content: "Code"; }
  .referral-history td:nth-child(3)::before { content: "Client"; }
  .referral-history td:nth-child(4)::before { content: "Produit"; }
  .referral-history td:nth-child(5)::before { content: "Solde utilise"; }
  .referral-history td:nth-child(6)::before { content: "Benefice attribue"; }
  .referral-history td:nth-child(7)::before { content: "Taux"; }
  .referral-history td:nth-child(8)::before { content: "Commission"; }
  .referral-summary td:nth-child(10) { grid-column: 1 / -1; }
  .referral-summary td:nth-child(10),
  .referral-summary tr > td:only-child,
  .referral-history tr > td:only-child { padding-left: 4px !important; padding-right: 4px !important; }
}

@media (max-width: 720px) {
  body main { width: min(100% - 20px, 1680px); }
  .referral-summary tr, .referral-history tr { grid-template-columns: minmax(0, 1fr); padding: 5px 12px !important; }
  .referral-summary td, .referral-history td {
    grid-template-columns: minmax(105px, .8fr) minmax(0, 1.2fr);
    padding: 9px 2px !important;
  }
  .referral-summary td:nth-child(n), .referral-history td:nth-child(n) { padding-left: 2px !important; padding-right: 2px !important; }
  .referral-summary td:nth-child(10) { grid-column: auto; }
}
"""

PANEL_EMBEDS_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Embeds</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}main{padding:22px 5%}h1{color:#ff8fc8}details{background:#171419;border:1px solid #332630;margin-bottom:14px;padding:12px}summary{cursor:pointer;color:#ff9dce;font-weight:bold}textarea{box-sizing:border-box;width:100%;min-height:260px;background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:10px;font-family:Consolas,monospace}input,select,button{background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:9px;margin-top:8px}select{cursor:pointer}button{background:#e8509a;border:0;cursor:pointer}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}.muted{color:#aa98a4;font-size:13px}a{color:#ff9dce}</style></head><body><header><h1>PinkGift — Embeds</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main>{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}<p class="muted">Tous les embeds encore utilisés sont modifiables ici. Seuls les anciens messages d'ouverture manuelle d'une commande ont été retirés. L'aperçu Discord se met à jour pendant tes modifications.</p>{% for item in embeds %}<details><summary>{{ item.key }}</summary><form method="post" enctype="multipart/form-data"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="embed_key" value="{{ item.key }}"><textarea name="embed_json">{{ item.json }}</textarea><br><input type="file" name="image_file" accept="image/*"><button>Enregistrer</button></form></details>{% endfor %}</main></body></html>"""

PANEL_EMBEDS_TEMPLATE = (
    PANEL_EMBEDS_TEMPLATE
    .replace(
        '<summary>{{ item.key }}</summary>',
        '<summary>{{ item.key }}</summary>{% if item.help %}<p class="muted">{{ item.help }}</p>{% endif %}',
        1,
    )
    .replace(
        '<form method="post" enctype="multipart/form-data">',
        '<form class="embed-editor" method="post" enctype="multipart/form-data">',
        1,
    )
    .replace(
        '<input type="hidden" name="embed_key" value="{{ item.key }}">',
        '<input type="hidden" name="embed_key" value="{{ item.key }}"><textarea class="embed-preview-context" hidden>{{ item.preview_context }}</textarea>',
        1,
    )
    .replace(
        '<textarea name="embed_json">{{ item.json }}</textarea><br><input type="file" name="image_file" accept="image/*"><button>Enregistrer</button>',
        '<div class="embed-editor-grid"><div class="embed-controls"><textarea name="embed_json">{{ item.json }}</textarea><div class="embed-actions"><input type="file" name="image_file" accept="image/*"><button>Enregistrer</button></div></div><aside class="discord-preview" aria-label="Aperçu Discord" aria-live="polite"></aside></div>',
        1,
    )
    .replace(
        '<div class="embed-editor-grid">',
        '''{% if item.menu_enabled %}<details class="privilege-menu-editor" data-menu-kind="{{ item.menu_kind }}"><summary><span>Menus sous l’embed {{ item.menu_title }}</span><span class="menu-editor-chevron" aria-hidden="true">›</span></summary><div class="menu-editor-body"><div class="privilege-menu-settings"><label>Texte du bouton<input name="menu_button_label" maxlength="80" value="{{ item.menu_button_label }}"></label><label>Emoji du bouton<input name="menu_button_emoji" value="{{ item.menu_button_emoji }}"></label><label>Couleur Discord<select name="menu_button_style"><option value="primary"{% if item.menu_button_style == "primary" %} selected{% endif %}>Bleu Discord (#5865F2)</option><option value="secondary"{% if item.menu_button_style == "secondary" %} selected{% endif %}>Gris Discord (#4E5058)</option><option value="success"{% if item.menu_button_style == "success" %} selected{% endif %}>Vert Discord (#248046)</option><option value="danger"{% if item.menu_button_style == "danger" %} selected{% endif %}>Rouge Discord (#DA373C)</option></select></label><label>Texte du premier menu<input name="menu_placeholder" maxlength="150" value="{{ item.menu_placeholder }}"></label></div><div class="privilege-menu-list"></div><button class="privilege-add-category" type="button">＋ Ajouter une catégorie</button><textarea class="privilege-menu-config" name="menu_config_json" hidden>{{ item.menu_config_json }}</textarea><p class="muted">{% if item.menu_kind == "autres" %}Chaque catégorie et chaque service ouvre un ticket privé. Les services déjà en place conservent leur traitement particulier.{% else %}Chaque catégorie et chaque option peut être ajoutée, modifiée ou supprimée ici. Le message d’une option est envoyé en privé après sa sélection.{% endif %} Seules les quatre couleurs officielles des boutons Discord sont proposées.</p></div></details>{% endif %}<div class="embed-editor-grid">''',
        1,
    )
    .replace(
        '<div class="embed-editor-grid">',
        '''{% if item.launcher_only %}<details class="privilege-menu-editor"><summary><span>Menu sous l’embed {{ item.menu_title }}</span><span class="menu-editor-chevron" aria-hidden="true">›</span></summary><div class="menu-editor-body"><div class="privilege-menu-settings launcher-only-settings"><label>Texte du bouton<input name="menu_button_label" maxlength="80" value="{{ item.menu_button_label }}"></label><label>Emoji du bouton<input name="menu_button_emoji" value="{{ item.menu_button_emoji }}"></label><label>Couleur Discord<select name="menu_button_style"><option value="primary"{% if item.menu_button_style == "primary" %} selected{% endif %}>Bleu Discord (#5865F2)</option><option value="secondary"{% if item.menu_button_style == "secondary" %} selected{% endif %}>Gris Discord (#4E5058)</option><option value="success"{% if item.menu_button_style == "success" %} selected{% endif %}>Vert Discord (#248046)</option><option value="danger"{% if item.menu_button_style == "danger" %} selected{% endif %}>Rouge Discord (#DA373C)</option></select></label></div><p class="muted">Les options d’achat restent synchronisées avec les onglets Prix et Stock. La couleur choisie correspond exactement à un style officiel Discord.</p></div></details>{% endif %}<div class="embed-editor-grid">''',
        1,
    )
    .replace(
        '<div class="embed-editor-grid">',
        '''{% if item.component_buttons %}<details class="privilege-menu-editor component-buttons-editor"><summary><span>Tous les boutons sous cet embed</span><span class="menu-editor-chevron" aria-hidden="true">›</span></summary><div class="menu-editor-body"><div class="component-button-editor-list">{% for button in item.component_buttons %}<section class="component-button-card" data-button-key="{{ button.key }}"><strong>{{ button.name }}</strong><div class="privilege-menu-settings launcher-only-settings"><label>Texte du bouton<input name="component_label__{{ button.key }}" maxlength="80" value="{{ button.label }}"></label><label>Emoji du bouton<input name="component_emoji__{{ button.key }}" value="{{ button.emoji }}"></label><label>Couleur Discord<select name="component_style__{{ button.key }}"><option value="primary"{% if button.style == "primary" %} selected{% endif %}>Bleu Discord (#5865F2)</option><option value="secondary"{% if button.style == "secondary" %} selected{% endif %}>Gris Discord (#4E5058)</option><option value="success"{% if button.style == "success" %} selected{% endif %}>Vert Discord (#248046)</option><option value="danger"{% if button.style == "danger" %} selected{% endif %}>Rouge Discord (#DA373C)</option></select></label></div></section>{% endfor %}</div><p class="muted">Tous les boutons utilisent directement l’un des quatre styles officiels Discord : bleu, gris, vert ou rouge.</p></div></details>{% endif %}<div class="embed-editor-grid">''',
        1,
    )
)

PANEL_EMBEDS_PREVIEW_CSS = r"""
.embed-editor-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(330px, .85fr);
  gap: 20px;
  align-items: start;
}
.privilege-menu-editor {
  margin: 0 0 18px;
  padding: 0;
  border: 1px solid rgba(255,143,200,.24);
  border-radius: 12px;
  background: rgba(255,143,200,.05);
  overflow: hidden;
}
.privilege-menu-editor > summary {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 15px 16px;
  list-style: none;
  color: #ff9dce;
  font-size: 16px;
  font-weight: 800;
  user-select: none;
}
.privilege-menu-editor > summary::-webkit-details-marker { display: none; }
.menu-editor-chevron {
  display: inline-grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  color: #ffd3e9;
  background: rgba(255,143,200,.11);
  font-size: 26px;
  line-height: 1;
  transition: transform .18s ease;
}
.privilege-menu-editor[open] .menu-editor-chevron { transform: rotate(90deg); }
.menu-editor-body { padding: 0 16px 16px; }
.privilege-menu-settings {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.launcher-only-settings { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.component-button-editor-list { display: grid; gap: 12px; }
.component-button-card {
  padding: 13px;
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 10px;
  background: rgba(10,10,14,.42);
}
.component-button-card > strong { display: block; margin-bottom: 10px; color: #ffb6da; }
.privilege-menu-settings label, .privilege-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #f7edf3;
  font-size: 13px;
  font-weight: 700;
}
.privilege-menu-settings input, .privilege-menu-settings select { box-sizing: border-box; width: 100%; margin: 0; }
.privilege-menu-list { display: grid; gap: 14px; margin-top: 16px; }
.privilege-category-card {
  padding: 14px;
  border: 1px solid rgba(255,255,255,.09);
  border-radius: 11px;
  background: rgba(10,10,14,.44);
}
.privilege-category-head, .privilege-option-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.privilege-category-head strong { color: #ffb6da; }
.privilege-option-head strong { color: #e4d6de; font-size: 12px; }
.privilege-category-grid, .privilege-option-grid {
  display: grid;
  grid-template-columns: minmax(160px, 1fr) minmax(85px, .35fr) minmax(180px, 1.25fr);
  gap: 10px;
}
.privilege-option-grid { grid-template-columns: minmax(150px, 1fr) minmax(80px, .3fr) minmax(180px, 1.2fr); }
.privilege-field input, .privilege-field textarea, .privilege-field select {
  box-sizing: border-box;
  width: 100%;
  margin: 0;
  min-height: 40px;
}
.privilege-field textarea { min-height: 72px !important; resize: vertical; }
.privilege-options { display: grid; gap: 10px; margin-top: 12px; }
.privilege-option-card {
  padding: 12px;
  border: 1px solid rgba(255,255,255,.07);
  border-radius: 9px;
  background: rgba(255,255,255,.025);
}
.privilege-remove, .privilege-add-option, .privilege-add-category {
  margin: 0 !important;
  border-radius: 8px;
  font-weight: 750;
}
.privilege-remove { padding: 7px 10px; background: rgba(255,88,120,.16); color: #ff9fb2; border: 1px solid rgba(255,88,120,.3); }
.privilege-remove:disabled { opacity: .4; cursor: not-allowed; }
.privilege-add-option { margin-top: 10px !important; background: rgba(88,101,242,.18); color: #c9ceff; border: 1px solid rgba(88,101,242,.32); }
.privilege-add-category { margin-top: 14px !important; background: linear-gradient(135deg,#e8509a,#9e4dff); }
.privilege-menu-empty { padding: 18px; border: 1px dashed rgba(255,255,255,.14); border-radius: 10px; color: #aa98a4; text-align: center; }
.embed-controls { min-width: 0; }
.embed-controls textarea { width: 100%; min-height: 440px !important; resize: vertical; }
.embed-actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 10px; }
.embed-actions input { flex: 1 1 280px; margin: 0 !important; }
.embed-actions button { flex: 0 0 auto; margin: 0 !important; }
.discord-preview {
  position: sticky;
  top: 92px;
  min-width: 0;
  padding: 18px;
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 14px;
  background: #313338;
  box-shadow: 0 18px 45px rgba(0,0,0,.28);
}
.discord-preview::before {
  content: "Aperçu Discord en direct · " attr(data-status);
  display: block;
  margin: 0 0 14px;
  color: #b5bac1;
  font-size: 11px;
  font-weight: 750;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.discord-preview[data-state="valid"]::before { color: #5ed6a0; }
.discord-preview[data-state="invalid"]::before { color: #ffc96b; }
.preview-live-warning {
  margin: 0 0 12px 52px;
  padding: 8px 10px;
  border: 1px solid rgba(255,201,107,.3);
  border-radius: 6px;
  color: #ffc96b;
  background: rgba(255,201,107,.07);
  font-size: 11px;
}
.discord-preview.preview-updated .discord-embed-card { animation: preview-pulse .24s ease-out; }
@keyframes preview-pulse {
  from { box-shadow: 0 0 0 2px rgba(247,103,174,.36); }
  to { box-shadow: 0 0 0 0 rgba(247,103,174,0); }
}
.discord-message { display: grid; grid-template-columns: 40px minmax(0, 1fr); gap: 12px; }
.discord-avatar {
  display: block;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  background: #09080d;
  box-shadow: 0 0 18px rgba(247,103,174,.28);
}
.discord-message-content { min-width: 0; }
.discord-author { margin-bottom: 5px; color: #f2f3f5; font-size: 15px; font-weight: 650; }
.discord-bot-tag { margin-left: 6px; padding: 1px 4px; border-radius: 3px; color: white; font-size: 9px; background: #5865f2; vertical-align: 2px; }
.discord-embed-card {
  width: min(520px, 100%);
  max-width: 520px;
  overflow: hidden;
  border-left: 4px solid var(--pink);
  border-radius: 4px;
  color: #dbdee1;
  background: #2b2d31;
}
.preview-components { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.preview-component-button {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 2px 14px;
  border-radius: 3px;
  color: #fff;
  font-size: 14px;
  font-weight: 650;
}
.preview-button-primary { background: #5865f2; }
.preview-button-secondary { background: #4e5058; }
.preview-button-success { background: #248046; }
.preview-button-danger { background: #da373c; }
.preview-component-button .preview-custom-emoji { width: 18px; height: 18px; }
.discord-embed-inner { display: flow-root; padding: 13px 16px 14px; }
.preview-author { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; color: #f2f3f5; font-size: 13px; font-weight: 650; }
.preview-author-icon { width: 24px; height: 24px; border-radius: 50%; object-fit: cover; }
.preview-title { margin-bottom: 8px; color: #f2f3f5; font-size: 16px; font-weight: 700; overflow-wrap: anywhere; }
.preview-title[href] { color: #00a8fc; text-decoration: none; }
.preview-title[href]:hover { text-decoration: underline; }
.preview-description { color: #dbdee1; font-size: 14px; line-height: 1.35; white-space: pre-wrap; overflow-wrap: anywhere; }
.preview-fields { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 12px 16px; margin-top: 14px; }
.preview-field { min-width: 0; }
.preview-field.wide { grid-column: span 12; }
.preview-field-name { color: #f2f3f5; font-size: 13px; font-weight: 700; overflow-wrap: anywhere; }
.preview-field-value { margin-top: 2px; color: #dbdee1; font-size: 13px; white-space: pre-wrap; overflow-wrap: anywhere; }
.preview-thumbnail { float: right; width: 80px; max-height: 80px; margin: 0 0 10px 14px; border-radius: 4px; object-fit: cover; }
.preview-image { display: block; width: 100%; max-height: 320px; margin-top: 14px; border-radius: 4px; object-fit: contain; background: rgba(0,0,0,.12); }
.preview-footer { display: flex; align-items: center; gap: 7px; margin-top: 13px; color: #b5bac1; font-size: 11px; overflow-wrap: anywhere; }
.preview-footer-icon { width: 20px; height: 20px; border-radius: 50%; object-fit: cover; }
.preview-custom-emoji { width: 1.35em; height: 1.35em; vertical-align: -.28em; object-fit: contain; }
.preview-inline-code { padding: 1px 4px; border-radius: 3px; background: #1e1f22; font-family: Consolas, monospace; }
.preview-link { color: #00a8fc; text-decoration: none; }
.preview-link:hover { text-decoration: underline; }
.preview-media-error { clear: both; margin-top: 12px; padding: 9px 11px; border: 1px dashed rgba(255,100,129,.35); border-radius: 5px; color: #ff9aaa; font-size: 11px; }
.preview-image-key { display: inline-flex; align-items: center; margin: 0 0 10px; padding: 3px 7px; border-radius: 999px; color: #b5bac1; background: #1e1f22; font: 11px Consolas, monospace; }
.preview-empty, .preview-error { padding: 18px; border: 1px dashed rgba(255,255,255,.12); border-radius: 10px; color: #b5bac1; text-align: center; }
.preview-error { color: #ff9aaa; border-color: rgba(255,100,129,.28); background: rgba(255,100,129,.06); }
@media (max-width: 950px) {
  .embed-editor-grid { grid-template-columns: minmax(0, 1fr); }
  .privilege-menu-settings { grid-template-columns: minmax(0, 1fr); }
  .privilege-category-grid, .privilege-option-grid { grid-template-columns: minmax(0, 1fr); }
  .discord-preview { position: static; }
  .embed-controls textarea { min-height: 340px !important; }
}
@media (max-width: 560px) {
  .discord-preview { padding: 13px; }
  .discord-message { grid-template-columns: 32px minmax(0, 1fr); gap: 9px; }
  .discord-avatar { width: 32px; height: 32px; font-size: 12px; }
  .preview-fields { grid-template-columns: minmax(0, 1fr); }
  .preview-field, .preview-field.wide { grid-column: 1 / -1 !important; }
  .preview-live-warning { margin-left: 41px; }
}
"""

PANEL_EMBEDS_PREVIEW_SCRIPT = r"""
<script>
(() => {
  const allForms = [...document.querySelectorAll(".embed-editor")];
  const localImagePreviews = new WeakMap();
  const make = (tag, className, value) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null && value !== "") node.textContent = String(value);
    return node;
  };
  const imageUrl = value => {
    if (typeof value === "string") return value;
    if (value && typeof value.url === "string") return value.url;
    return "";
  };
  const textValue = value => {
    if (Array.isArray(value)) return value.map(textValue).filter(Boolean).join("\n");
    if (typeof value === "string" || typeof value === "number") return String(value);
    return value && (value.text || value.name) ? String(value.text || value.name) : "";
  };
  const parsePreviewContext = form => {
    try {
      return JSON.parse(form.querySelector(".embed-preview-context")?.value || "{}");
    } catch (error) {
      return {};
    }
  };
  const fillTokens = (template, values) => textValue(template).replace(/\{([A-Za-z0-9_]+)\}/g, (match, key) => (
    Object.prototype.hasOwnProperty.call(values, key) ? String(values[key]) : match
  ));
  const dynamicPreviewFields = (data, form) => {
    const fields = Array.isArray(data.fields) ? data.fields.map(field => ({...field})) : [];
    const key = form.querySelector('input[name="embed_key"]')?.value || "";
    const context = parsePreviewContext(form);
    const inline = data.dynamic_fields_inline === true;
    if (key === "cp_embed" && Array.isArray(context.packs)) {
      const template = data.pack_line_template || "<:cp:1528128623117205624> **{points} CP** — **{price} €** · officiel ≈ ~~{official} €~~";
      fields.push({
        name: data.packs_field_name || "<:cp:1528128623117205624> Packs disponibles",
        value: context.packs.map(pack => fillTokens(template, pack)).join("\n"),
        inline,
      });
    } else if (key === "tarifs_embed" && data.show_dynamic_fields === true) {
      const giftTemplate = data.gift_card_line_template || "**{amount} € reçus** → **{price} PC**";
      const uberTemplate = data.uber_eats_line_template || "**{drop} € estimés** → **{price} PC**";
      const nitroTemplate = data.nitro_value_template || "**{price} PC**";
      if (Array.isArray(context.gift_cards)) fields.push({
        name: data.gift_cards_field_name || "<:carte:1528346097276420271> Cartes cadeaux — toutes les marques",
        value: context.gift_cards.map(item => fillTokens(giftTemplate, item)).join("\n"), inline,
      });
      if (Array.isArray(context.uber_eats)) fields.push({
        name: data.uber_eats_field_name || "<:ubereats:1528671351668211722> Uber Eats",
        value: context.uber_eats.map(item => fillTokens(uberTemplate, item)).join("\n"), inline,
      });
      if (context.nitro) fields.push({
        name: data.nitro_field_name || "<:nitro:1528358484972671096> Discord Nitro",
        value: fillTokens(nitroTemplate, context.nitro), inline,
      });
    } else if (key === "valo_embed" && Array.isArray(context.regions)) {
      const nameTemplate = data.region_field_name_template || "{emoji} {region}";
      const packTemplate = data.pack_line_template || "<:vp:1519915966476320901> **{pack}** — **{price} PC** · origine ≈ ~~{official} €~~";
      const regionEmojis = data.region_emojis && typeof data.region_emojis === "object" ? data.region_emojis : {};
      context.regions.forEach(region => {
        const regionValues = {...region, emoji: regionEmojis[region.region_key] || region.emoji};
        fields.push({
        name: fillTokens(nameTemplate, regionValues),
        value: (region.packs || []).map(pack => fillTokens(packTemplate, {...regionValues, ...pack})).join("\n"),
        inline,
      });
      });
    }
    return fields;
  };
  const appendRichText = (parent, value) => {
    const raw = textValue(value);
    const tokenPattern = /(<a?:[A-Za-z0-9_]+:\d+>|\*\*[^*\n]+?\*\*|~~[^~\n]+?~~|__[^_\n]+?__|`[^`\n]+?`|\[[^\]\n]+\]\(https?:\/\/[^)\s]+\)|https?:\/\/[^\s<]+)/g;
    let cursor = 0;
    for (const match of raw.matchAll(tokenPattern)) {
      if (match.index > cursor) parent.appendChild(document.createTextNode(raw.slice(cursor, match.index)));
      const token = match[0];
      const emoji = token.match(/^<(a?):([A-Za-z0-9_]+):(\d+)>$/);
      const markdownLink = token.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/);
      if (emoji) {
        const image = make("img", "preview-custom-emoji");
        image.src = `https://cdn.discordapp.com/emojis/${emoji[3]}.${emoji[1] ? "gif" : "webp"}?size=32&quality=lossless`;
        image.alt = `:${emoji[2]}:`;
        image.title = image.alt;
        image.addEventListener("error", () => image.replaceWith(document.createTextNode(image.alt)));
        parent.appendChild(image);
      } else if (token.startsWith("**")) {
        const strong = make("strong");
        appendRichText(strong, token.slice(2, -2));
        parent.appendChild(strong);
      } else if (token.startsWith("~~")) {
        const strike = make("s");
        appendRichText(strike, token.slice(2, -2));
        parent.appendChild(strike);
      } else if (token.startsWith("__")) {
        const underline = make("u");
        appendRichText(underline, token.slice(2, -2));
        parent.appendChild(underline);
      } else if (token.startsWith("`")) {
        parent.appendChild(make("code", "preview-inline-code", token.slice(1, -1)));
      } else if (markdownLink) {
        const link = make("a", "preview-link", markdownLink[1]);
        link.href = markdownLink[2];
        link.target = "_blank";
        link.rel = "noreferrer noopener";
        parent.appendChild(link);
      } else {
        const link = make("a", "preview-link", token);
        link.href = token;
        link.target = "_blank";
        link.rel = "noreferrer noopener";
        parent.appendChild(link);
      }
      cursor = match.index + token.length;
    }
    if (cursor < raw.length) parent.appendChild(document.createTextNode(raw.slice(cursor)));
  };
  const makeRich = (tag, className, value) => {
    const node = make(tag, className);
    appendRichText(node, value);
    return node;
  };
  const safeColor = value => {
    if (Array.isArray(value) && value.length >= 3) {
      const [red, green, blue] = value.map(part => Math.max(0, Math.min(255, Number(part) || 0)));
      return `rgb(${red}, ${green}, ${blue})`;
    }
    if (Number.isFinite(value)) return `#${Math.max(0, Math.min(0xffffff, value)).toString(16).padStart(6, "0")}`;
    if (typeof value === "string" && /^#?[0-9a-f]{6}$/i.test(value)) return value.startsWith("#") ? value : `#${value}`;
    return "#f767ae";
  };
  const appendImage = (parent, className, url, alt) => {
    if (!url) return false;
    if (!/^(https?:\/\/|blob:)/i.test(url)) {
      parent.appendChild(make("div", "preview-media-error", `${alt} : l'URL n'est pas valide.`));
      return false;
    }
    const img = make("img", className);
    img.src = url;
    img.alt = alt;
    img.loading = "lazy";
    img.addEventListener("error", () => {
      const error = make("div", "preview-media-error", `${alt} indisponible ou lien expiré.`);
      img.replaceWith(error);
    });
    parent.appendChild(img);
    return true;
  };
  const parseFormJson = form => {
    try {
      return JSON.parse(form.querySelector('textarea[name="embed_json"]')?.value || "{}");
    } catch (error) {
      return null;
    }
  };
  const sharedImages = () => {
    const form = allForms.find(item => item.querySelector('input[name="embed_key"]')?.value === "images");
    const data = form && parseFormJson(form);
    return data && typeof data === "object" && !Array.isArray(data) ? data : {};
  };
  const resolvedMainImage = (data, form) => {
    const localPreview = localImagePreviews.get(form);
    if (localPreview) return localPreview;
    const fallback = imageUrl(data.image_url || data.image);
    const key = typeof data.image_key === "string" ? data.image_key.trim() : "";
    return key ? imageUrl(sharedImages()[key]) || fallback : fallback;
  };
  const renderFields = (inner, rawFields, hasThumbnail) => {
    if (!Array.isArray(rawFields) || !rawFields.length) return;
    const fields = make("div", "preview-fields");
    const appendField = (field, span) => {
      const fieldNode = make("div", `preview-field${span === 12 ? " wide" : ""}`);
      fieldNode.style.gridColumn = `span ${span}`;
      fieldNode.appendChild(makeRich("div", "preview-field-name", textValue(field?.name) || "Champ"));
      fieldNode.appendChild(makeRich("div", "preview-field-value", textValue(field?.value) || "—"));
      fields.appendChild(fieldNode);
    };
    const inlineLimit = hasThumbnail ? 2 : 3;
    let index = 0;
    while (index < rawFields.length) {
      const field = rawFields[index] || {};
      if (field.inline !== true) {
        appendField(field, 12);
        index += 1;
        continue;
      }
      const run = [];
      while (index < rawFields.length && rawFields[index]?.inline === true && run.length < inlineLimit) {
        run.push(rawFields[index]);
        index += 1;
      }
      const span = 12 / run.length;
      run.forEach(item => appendField(item, span));
    }
    inner.appendChild(fields);
  };
  const render = form => {
    const textarea = form.querySelector('textarea[name="embed_json"]');
    const preview = form.querySelector(".discord-preview");
    if (!textarea || !preview) return;
    const data = parseFormJson(form);
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      preview.dataset.state = "invalid";
      preview.dataset.status = "JSON en cours";
      if (preview.querySelector(".discord-message")) {
        let warning = preview.querySelector(".preview-live-warning");
        if (!warning) {
          warning = make("div", "preview-live-warning");
          preview.prepend(warning);
        }
        warning.textContent = "Le JSON est temporairement incomplet. Le dernier aperçu valide reste affiché.";
      } else {
        preview.replaceChildren(make("div", "preview-error", "JSON invalide : corrige la syntaxe pour retrouver l'aperçu."));
      }
      return;
    }
    const message = make("div", "discord-message");
    const avatar = make("img", "discord-avatar");
    avatar.src = "/static/discord_icon.gif";
    avatar.alt = "Logo PinkGift";
    message.appendChild(avatar);
    const content = make("div", "discord-message-content");
    const authorLine = make("div", "discord-author", "PinkGift");
    authorLine.appendChild(make("span", "discord-bot-tag", "BOT"));
    content.appendChild(authorLine);
    const card = make("article", "discord-embed-card");
    card.style.borderLeftColor = safeColor(data.color ?? data.color_rgb);
    const inner = make("div", "discord-embed-inner");
    const thumbnail = imageUrl(data.thumbnail_url || data.thumbnail);
    appendImage(inner, "preview-thumbnail", thumbnail, "Miniature de l'embed");
    const author = textValue(data.author?.name ?? data.author);
    const authorIcon = imageUrl(data.author?.icon_url || data.author_icon_url);
    const title = textValue(data.title);
    const description = textValue(data.description);
    if (author) {
      const authorNode = make("div", "preview-author");
      appendImage(authorNode, "preview-author-icon", authorIcon, "Icône de l'auteur");
      const authorText = makeRich(data.author?.url ? "a" : "span", data.author?.url ? "preview-link" : "", author);
      if (data.author?.url) {
        authorText.href = data.author.url;
        authorText.target = "_blank";
        authorText.rel = "noreferrer noopener";
      }
      authorNode.appendChild(authorText);
      inner.appendChild(authorNode);
    }
    if (title) {
      const titleNode = makeRich(data.url ? "a" : "div", "preview-title", title);
      if (data.url) {
        titleNode.href = data.url;
        titleNode.target = "_blank";
        titleNode.rel = "noreferrer noopener";
      }
      inner.appendChild(titleNode);
    }
    if (description) inner.appendChild(makeRich("div", "preview-description", description));
    renderFields(inner, dynamicPreviewFields(data, form), Boolean(thumbnail));
    const mainImage = resolvedMainImage(data, form);
    appendImage(inner, "preview-image", mainImage, "Image de l'embed");
    const footer = textValue(data.footer?.text ?? data.footer);
    const footerIcon = imageUrl(data.footer?.icon_url || data.footer_icon_url);
    let timestamp = "";
    if (data.timestamp) {
      const parsed = new Date(data.timestamp);
      if (!Number.isNaN(parsed.getTime())) timestamp = parsed.toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
    }
    if (footer || timestamp) {
      const footerNode = make("div", "preview-footer");
      appendImage(footerNode, "preview-footer-icon", footerIcon, "Icône du pied de page");
      footerNode.appendChild(make("span", "", [footer, timestamp].filter(Boolean).join(" • ")));
      inner.appendChild(footerNode);
    }
    if (!author && !title && !description && !(Array.isArray(data.fields) && data.fields.length) && !thumbnail && !mainImage && !footer && !timestamp) {
      inner.appendChild(make("div", "preview-empty", "Cet embed ne contient encore aucun élément visible."));
    }
    card.appendChild(inner);
    content.appendChild(card);
    const components = make("div", "preview-components");
    const discordButtonColors = {
      primary: "#5865F2",
      secondary: "#4E5058",
      success: "#248046",
      danger: "#DA373C",
    };
    const appendButtonPreview = (label, emoji, style) => {
      if (!label) return;
      const button = makeRich(
        "div",
        "preview-component-button",
        [emoji, label].filter(Boolean).join(" "),
      );
      button.style.backgroundColor = discordButtonColors[style] || discordButtonColors.secondary;
      components.appendChild(button);
    };
    const menuButtonLabel = form.querySelector('[name="menu_button_label"]')?.value?.trim();
    if (menuButtonLabel) {
      const buttonEmoji = form.querySelector('[name="menu_button_emoji"]')?.value?.trim() || "";
      const buttonStyle = form.querySelector('[name="menu_button_style"]')?.value || "primary";
      appendButtonPreview(menuButtonLabel, buttonEmoji, buttonStyle);
    }
    form.querySelectorAll(".component-button-card").forEach(cardNode => {
      const key = cardNode.dataset.buttonKey || "";
      appendButtonPreview(
        cardNode.querySelector(`[name="component_label__${key}"]`)?.value?.trim(),
        cardNode.querySelector(`[name="component_emoji__${key}"]`)?.value?.trim(),
        cardNode.querySelector(`[name="component_style__${key}"]`)?.value,
      );
    });
    if (components.children.length) content.appendChild(components);
    message.appendChild(content);
    preview.replaceChildren(message);
    preview.dataset.state = "valid";
    preview.dataset.status = localImagePreviews.has(form) ? "image locale" : "à jour";
    preview.classList.remove("preview-updated");
    requestAnimationFrame(() => preview.classList.add("preview-updated"));
  };
  allForms.forEach(form => {
    const textarea = form.querySelector('textarea[name="embed_json"]');
    const imageInput = form.querySelector('input[type="file"][name="image_file"]');
    render(form);
    if (textarea) textarea.addEventListener("input", () => {
      const key = form.querySelector('input[name="embed_key"]')?.value;
      if (key === "images") allForms.forEach(render);
      else render(form);
    });
    if (imageInput) imageInput.addEventListener("change", () => {
      const previous = localImagePreviews.get(form);
      if (previous) URL.revokeObjectURL(previous);
      const file = imageInput.files?.[0];
      if (file && file.type.startsWith("image/")) localImagePreviews.set(form, URL.createObjectURL(file));
      else localImagePreviews.delete(form);
      render(form);
    });
    form.querySelectorAll(
      '[name="menu_button_label"], [name="menu_button_emoji"], [name="menu_button_style"], '
      + '[name^="component_label__"], [name^="component_emoji__"], [name^="component_style__"]'
    ).forEach(control => {
      control.addEventListener(control.tagName === "SELECT" ? "change" : "input", () => render(form));
    });
  });
})();
</script>
"""

PANEL_PRIVILEGE_MENU_EDITOR_SCRIPT = r"""
<script>
(() => {
  const editors = [...document.querySelectorAll(".privilege-menu-editor[data-menu-kind]")];
  const create = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const field = (label, value, onInput, multiline = false, maxLength = 0) => {
    const wrapper = create("label", "privilege-field");
    wrapper.appendChild(create("span", "", label));
    const input = create(multiline ? "textarea" : "input");
    input.value = value || "";
    if (maxLength) input.maxLength = maxLength;
    input.addEventListener("input", () => onInput(input.value));
    wrapper.appendChild(input);
    return wrapper;
  };
  const selectField = (label, value, choices, onChange) => {
    const wrapper = create("label", "privilege-field");
    wrapper.appendChild(create("span", "", label));
    const select = create("select");
    choices.forEach(choice => {
      const option = create("option", "", choice.label);
      option.value = choice.value;
      option.selected = choice.value === value;
      select.appendChild(option);
    });
    select.addEventListener("change", () => onChange(select.value));
    wrapper.appendChild(select);
    return wrapper;
  };

  editors.forEach(editor => {
    const menuKind = editor.dataset.menuKind || "privileges";
    const list = editor.querySelector(".privilege-menu-list");
    const storage = editor.querySelector(".privilege-menu-config");
    const addCategoryButton = editor.querySelector(".privilege-add-category");
    const newOption = () => ({
      label: menuKind === "autres" ? "Nouveau service" : "Nouvelle option",
      emoji: "✨",
      description: "",
      response: "",
      ...(menuKind === "autres" ? {service_key: ""} : {}),
    });
    const newCategory = () => ({
      label: "Nouvelle catégorie",
      emoji: "📁",
      description: "",
      placeholder: "Choisis une option",
      ...(menuKind === "autres" ? {catalog_key: "autres"} : {}),
      options: [newOption()],
    });
    let categories = [];
    try {
      const parsed = JSON.parse(storage.value || "[]");
      categories = Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      categories = [];
    }

    const sync = () => {
      storage.value = JSON.stringify(categories);
    };

    const render = () => {
      list.replaceChildren();
      if (!categories.length) {
        list.appendChild(create("div", "privilege-menu-empty", "Aucune catégorie. Clique sur « Ajouter une catégorie »."));
      }
      categories.forEach((category, categoryIndex) => {
        if (!Array.isArray(category.options)) category.options = [];
        if (!category.options.length) category.options.push(newOption());
        const card = create("section", "privilege-category-card");
        const head = create("div", "privilege-category-head");
        head.appendChild(create("strong", "", `Catégorie ${categoryIndex + 1}`));
        const removeCategory = create("button", "privilege-remove", "Supprimer la catégorie");
        removeCategory.type = "button";
        removeCategory.disabled = categories.length <= 1;
        removeCategory.addEventListener("click", () => {
          categories.splice(categoryIndex, 1);
          sync();
          render();
        });
        head.appendChild(removeCategory);
        card.appendChild(head);

        const categoryGrid = create("div", "privilege-category-grid");
        categoryGrid.appendChild(field("Nom", category.label, value => { category.label = value; sync(); }, false, 100));
        categoryGrid.appendChild(field("Emoji", category.emoji, value => { category.emoji = value; sync(); }));
        categoryGrid.appendChild(field("Description du menu", category.description, value => { category.description = value; sync(); }, false, 100));
        categoryGrid.appendChild(field("Texte du second menu", category.placeholder, value => { category.placeholder = value; sync(); }, false, 150));
        if (menuKind === "autres") {
          categoryGrid.appendChild(selectField(
            "Type de ticket",
            category.catalog_key || "autres",
            [
              {value: "autres", label: "Autre service"},
              {value: "abonnements", label: "Abonnement"},
            ],
            value => { category.catalog_key = value; sync(); },
          ));
        }
        card.appendChild(categoryGrid);

        const options = create("div", "privilege-options");
        category.options.forEach((option, optionIndex) => {
          const optionCard = create("section", "privilege-option-card");
          const optionHead = create("div", "privilege-option-head");
          optionHead.appendChild(create("strong", "", `Option ${optionIndex + 1}`));
          const removeOption = create("button", "privilege-remove", "Supprimer");
          removeOption.type = "button";
          removeOption.disabled = category.options.length <= 1;
          removeOption.addEventListener("click", () => {
            category.options.splice(optionIndex, 1);
            sync();
            render();
          });
          optionHead.appendChild(removeOption);
          optionCard.appendChild(optionHead);

          const optionGrid = create("div", "privilege-option-grid");
          optionGrid.appendChild(field("Nom", option.label, value => { option.label = value; sync(); }, false, 100));
          optionGrid.appendChild(field("Emoji", option.emoji, value => { option.emoji = value; sync(); }));
          optionGrid.appendChild(field("Description dans le menu", option.description, value => { option.description = value; sync(); }, false, 100));
          if (menuKind === "privileges") {
            optionGrid.appendChild(field("Message envoyé après sélection", option.response, value => { option.response = value; sync(); }, true));
          }
          optionCard.appendChild(optionGrid);
          options.appendChild(optionCard);
        });
        card.appendChild(options);

        const addOption = create("button", "privilege-add-option", "＋ Ajouter une option");
        addOption.type = "button";
        addOption.disabled = category.options.length >= 25;
        addOption.addEventListener("click", () => {
          if (category.options.length >= 25) return;
          category.options.push(newOption());
          sync();
          render();
        });
        card.appendChild(addOption);
        list.appendChild(card);
      });
      addCategoryButton.disabled = categories.length >= 25;
      sync();
    };

    addCategoryButton.addEventListener("click", () => {
      if (categories.length >= 25) return;
      categories.push(newCategory());
      render();
    });
    editor.closest("form")?.addEventListener("submit", sync);
    render();
  });
})();
</script>
"""

LOGIN_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift</title><style>body{background:#0e0d11;color:#fff;font-family:Arial;display:grid;place-items:center;height:100vh;margin:0}form{background:#19151b;padding:28px;border:1px solid #4a3040;width:min(340px,80vw)}h1{color:#ff8fc8}input,button{box-sizing:border-box;width:100%;padding:12px;margin-top:10px}input{background:#0e0d11;color:#fff;border:1px solid #5a3a4d}button{background:#e8509a;color:#fff;border:0}</style></head><body><form method="post"><h1>PinkGift Staff</h1><input type="password" name="password" placeholder="Mot de passe" required><button>Connexion</button></form></body></html>"""

PANEL_ACCESS_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — Accès panel</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}h1{margin:0;color:#ff8fc8;font-size:23px}main{padding:22px 5%}table{width:100%;border-collapse:collapse;background:#171419}th,td{text-align:left;padding:11px;border-bottom:1px solid #332630;vertical-align:top}th{color:#ff9dce}.muted{color:#aa98a4;font-size:12px}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}input{background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:11px;min-width:260px}button{background:#e8509a;color:#fff;border:0;padding:12px 14px;cursor:pointer}a{color:#ff9dce}.ua{max-width:520px;word-break:break-word}</style></head><body><header><h1>PinkGift — Accès panel</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main>{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}{% if locked %}<form method="get"><h2>Accès protégé</h2><p class="muted">Entre la clé privée configurée dans PANEL_AUDIT_KEY.</p><input type="password" name="key" placeholder="Clé privée" required><button type="submit">Ouvrir</button></form>{% else %}<table><thead><tr><th>Heure</th><th>IP</th><th>Mode</th><th>Page</th><th>Méthode</th><th>User-agent</th></tr></thead><tbody>{% for log in logs %}<tr><td>{{ log.created_at }}</td><td>{{ log.ip }}</td><td>{{ log.device }}</td><td>{{ log.path }}</td><td>{{ log.method }}</td><td class="ua muted">{{ log.user_agent }}</td></tr>{% else %}<tr><td colspan="6">Aucun accès enregistré.</td></tr>{% endfor %}</tbody></table>{% endif %}</main></body></html>"""


PANEL_CP_TEMPLATE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PinkGift — COD Points</title><style>body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}main{padding:22px 5%;max-width:1400px}h1{color:#ff8fc8}.card{background:#171419;border:1px solid #332630;padding:16px;margin-bottom:18px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:13px}.field{display:flex;flex-direction:column;gap:6px}.field span,th{color:#ff9dce;font-weight:bold}.field small,.muted{color:#aa98a4}input,select,textarea,button{box-sizing:border-box;background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:10px}textarea{width:100%;min-height:150px;font-family:Consolas,monospace}button{background:#e8509a;border:0;cursor:pointer;font-weight:bold}.danger{background:#9d294b}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}table{width:100%;border-collapse:collapse;background:#171419;margin:14px 0 24px}th,td{text-align:left;padding:10px;border-bottom:1px solid #332630;vertical-align:top}code{overflow-wrap:anywhere;color:#ffd2e8}.positive{color:#74d99f;font-weight:bold}a{color:#ff9dce}</style></head><body><header><h1>PinkGift — COD Points</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header><main>{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}<p class="muted">Les prix et coûts sont appliqués immédiatement. Une commande est acceptée uniquement lorsqu'un code du pack est en stock ; le solde est alors débité et le code livré automatiquement dans le ticket client.</p><form method="post" class="card"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="action" value="save_settings"><h2>Prix et coûts des packs</h2><div class="grid">{% for item in packs %}<section class="card"><h3>{{ item.points_label }} CP</h3><label class="field"><span>Prix de vente</span><input type="number" name="cp_price_{{ item.key }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01" required><small>Débit du solde client</small></label><label class="field"><span>Coût d'achat</span><input type="number" name="cp_cost_{{ item.key }}" value="{{ item.cost }}" min="0" max="100000" step="0.01" required><small>Utilisé pour le bénéfice</small></label><p class="muted">Officiel ≈ {{ item.official }} € · Stock : <strong>{{ item.stock }}</strong></p></section>{% endfor %}</div><button type="submit">Enregistrer les prix et coûts</button></form><section class="card"><h2>Ajouter des codes au stock</h2><form method="post"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="action" value="add_codes"><div class="grid"><label class="field"><span>Pack</span><select name="pack_key" required>{% for item in packs %}<option value="{{ item.key }}">{{ item.points_label }} CP — {{ item.stock }} en stock</option>{% endfor %}</select></label><label class="field"><span>Codes à ajouter</span><textarea name="codes" placeholder="Un code par ligne" required></textarea><small>Les doublons sont ignorés.</small></label></div><button type="submit">Ajouter au stock</button></form></section><h2>Inventaire actuel</h2>{% for item in packs %}<details class="card"><summary><strong>{{ item.points_label }} CP</strong> — {{ item.stock }} code(s)</summary>{% if item.codes %}<table><thead><tr><th>Code</th><th>Action</th></tr></thead><tbody>{% for code in item.codes %}<tr><td><code>{{ code }}</code></td><td><form method="post" onsubmit="return confirm('Supprimer ce code du stock ?')"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="action" value="delete_code"><input type="hidden" name="pack_key" value="{{ item.key }}"><input type="hidden" name="code" value="{{ code }}"><button class="danger" type="submit">Supprimer</button></form></td></tr>{% endfor %}</tbody></table><form method="post" onsubmit="return confirm('Vider tout le stock de ce pack ?')"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="action" value="clear_pack"><input type="hidden" name="pack_key" value="{{ item.key }}"><button class="danger" type="submit">Vider ce pack</button></form>{% else %}<p class="muted">Aucun code disponible.</p>{% endif %}</details>{% endfor %}<h2>Dernières commandes CP</h2><table><thead><tr><th>Client</th><th>Pack</th><th>Payé</th><th>État</th><th>Date</th></tr></thead><tbody>{% for order in orders %}<tr><td><a href="https://discord.com/users/{{ order.user_id }}" target="_blank">@{{ order.user_name or order.user_id }}</a></td><td>{{ order.received_label }}</td><td>{{ order.paid }} €</td><td class="{{ 'positive' if order.status == 'done' else '' }}">{{ order.status }}</td><td>{{ order.updated_at or order.created_at }}</td></tr>{% else %}<tr><td colspan="5">Aucune commande CP.</td></tr>{% endfor %}</tbody></table></main></body></html>"""


# Thème commun du panel. Les templates historiques gardent leur structure et
# leurs formulaires, puis ces règles unifient toute l'interface en un seul
# design responsive. Cela évite aussi de dupliquer les futures retouches CSS.
PANEL_THEME_CSS = r"""
:root {
  color-scheme: dark;
  --bg: #08090d;
  --surface: rgba(18, 19, 27, .86);
  --surface-strong: #151620;
  --surface-soft: rgba(255, 255, 255, .035);
  --border: rgba(255, 255, 255, .09);
  --border-focus: rgba(247, 103, 174, .58);
  --text: #f7f7fb;
  --muted: #999aaa;
  --pink: #f767ae;
  --pink-strong: #e94698;
  --purple: #8b6cff;
  --green: #5ed6a0;
  --amber: #ffc96b;
  --danger: #ff6481;
  --shadow: 0 24px 70px rgba(0, 0, 0, .32);
}
* { box-sizing: border-box; }
html { min-height: 100%; background: var(--bg); }
body {
  min-height: 100vh;
  margin: 0;
  color: var(--text);
  font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.55;
  background:
    radial-gradient(900px 460px at 8% -8%, rgba(247, 103, 174, .16), transparent 62%),
    radial-gradient(760px 420px at 100% 4%, rgba(139, 108, 255, .13), transparent 58%),
    linear-gradient(180deg, #0b0c12 0%, var(--bg) 70%);
  background-attachment: fixed;
}
body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  opacity: .16;
  background-image: linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
  background-size: 38px 38px;
  mask-image: linear-gradient(to bottom, black, transparent 70%);
}
header {
  position: sticky;
  top: 0;
  z-index: 20;
  min-height: 72px;
  padding: 14px clamp(18px, 4vw, 64px);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  border-bottom: 1px solid var(--border);
  background: rgba(8, 9, 13, .78);
  backdrop-filter: blur(18px) saturate(140%);
  -webkit-backdrop-filter: blur(18px) saturate(140%);
}
header h1 {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0;
  color: var(--text);
  font-size: clamp(18px, 2.1vw, 23px);
  font-weight: 760;
  letter-spacing: -.035em;
}
header h1::before {
  content: "";
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  border-radius: 12px;
  background: #09080d url("/static/discord_icon.gif") center / cover no-repeat;
  box-shadow: 0 10px 30px rgba(233, 70, 152, .3), inset 0 1px rgba(255,255,255,.24);
}
header > a {
  display: inline-flex;
  align-items: center;
  min-height: 38px;
  padding: 8px 13px;
  border: 1px solid var(--border);
  border-radius: 11px;
  color: #e7e7ef !important;
  text-decoration: none;
  background: var(--surface-soft);
  transition: .18s ease;
}
header > a:hover { border-color: rgba(247,103,174,.38); background: rgba(247,103,174,.1); color: white !important; }
main {
  position: relative;
  z-index: 1;
  width: min(1440px, calc(100% - 40px));
  max-width: 1440px !important;
  margin: 0 auto;
  padding: 30px 0 64px !important;
}
nav {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin: 0 0 24px !important;
  padding: 7px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: rgba(18, 19, 27, .74);
  box-shadow: 0 16px 50px rgba(0,0,0,.18);
}
.tab {
  padding: 9px 13px !important;
  border: 0 !important;
  border-radius: 10px;
  color: #b9bac8 !important;
  font-size: 13px;
  font-weight: 650;
  text-decoration: none;
  transition: .18s ease;
}
.tab:hover { color: white !important; background: rgba(255,255,255,.055); }
.tab.active {
  color: white !important;
  background: linear-gradient(135deg, var(--pink-strong), #c64ee7) !important;
  box-shadow: 0 8px 24px rgba(233, 70, 152, .24);
}
h2 {
  margin: 30px 0 14px;
  color: #f0f0f6;
  font-size: 18px;
  line-height: 1.3;
  letter-spacing: -.025em;
}
p { color: #c2c2cd; }
a { color: #ff8bc2; text-underline-offset: 3px; }
.muted { color: var(--muted) !important; font-size: 13px !important; }
.notice {
  margin: 0 0 20px !important;
  padding: 13px 15px !important;
  border: 1px solid rgba(247, 103, 174, .2) !important;
  border-left: 3px solid var(--pink) !important;
  border-radius: 12px;
  color: #f5dbe8;
  background: rgba(247, 103, 174, .08) !important;
  box-shadow: 0 12px 35px rgba(0,0,0,.12);
}
.card, details, .cost-form {
  border: 1px solid var(--border) !important;
  border-radius: 16px;
  background: linear-gradient(145deg, rgba(24,25,35,.95), rgba(15,16,23,.95)) !important;
  box-shadow: 0 16px 50px rgba(0,0,0,.18);
}
.card { padding: 20px !important; }
.cards { gap: 14px !important; }
.cards .card { position: relative; overflow: hidden; }
.cards .card::after {
  content: "";
  position: absolute;
  width: 90px;
  height: 90px;
  right: -42px;
  bottom: -50px;
  border-radius: 50%;
  background: rgba(247,103,174,.09);
  filter: blur(2px);
}
.card span { color: var(--muted) !important; font-size: 12px !important; font-weight: 650; text-transform: uppercase; letter-spacing: .055em; }
.card strong { color: white; letter-spacing: -.04em; }
details { padding: 0 !important; overflow: hidden; }
summary {
  padding: 16px 18px;
  color: #efc2d9 !important;
  cursor: pointer;
  list-style-position: inside;
  user-select: none;
}
details[open] summary { border-bottom: 1px solid var(--border); background: rgba(247,103,174,.045); }
details .grid, details form { padding: 18px; margin-top: 0 !important; }
.grid { gap: 14px !important; }
.field { gap: 7px !important; }
.field span, .toolbar label, .cost-form label { color: #d6d6df !important; font-size: 13px; font-weight: 650 !important; }
input, select, textarea {
  min-height: 42px;
  padding: 10px 12px !important;
  border: 1px solid var(--border) !important;
  border-radius: 10px;
  outline: none;
  color: var(--text) !important;
  background: rgba(4, 5, 9, .58) !important;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.025);
  transition: border-color .18s ease, box-shadow .18s ease, background .18s ease;
}
input::placeholder, textarea::placeholder { color: #6f7080; }
input:hover, select:hover, textarea:hover { border-color: rgba(255,255,255,.16) !important; }
input:focus, select:focus, textarea:focus {
  border-color: var(--border-focus) !important;
  background: rgba(8, 9, 14, .9) !important;
  box-shadow: 0 0 0 4px rgba(247,103,174,.09);
}
input[type="checkbox"] { min-width: 16px !important; min-height: 16px; width: 16px; height: 16px; padding: 0 !important; accent-color: var(--pink); }
input[type="file"] { padding: 8px !important; }
textarea { min-height: 300px !important; font-family: "SFMono-Regular", Consolas, monospace !important; line-height: 1.55; }
button {
  min-height: 40px;
  padding: 9px 14px !important;
  border: 0 !important;
  border-radius: 10px;
  color: white !important;
  font-family: inherit;
  font-size: 13px;
  font-weight: 720 !important;
  cursor: pointer;
  background: linear-gradient(135deg, var(--pink-strong), #c64ee7) !important;
  box-shadow: 0 8px 22px rgba(233,70,152,.18);
  transition: transform .16s ease, filter .16s ease, box-shadow .16s ease;
}
button:hover { transform: translateY(-1px); filter: brightness(1.08); box-shadow: 0 11px 28px rgba(233,70,152,.26); }
button:active { transform: translateY(0); }
button.delete, .delete { background: linear-gradient(135deg, #ce3d5e, #a8294d) !important; box-shadow: 0 8px 22px rgba(206,61,94,.16); }
.filters, .toolbar {
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 14px;
  background: rgba(18,19,27,.72);
}
.filters label { color: #bfc0cb !important; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
table {
  width: 100%;
  overflow: hidden;
  border: 1px solid var(--border) !important;
  border-collapse: separate !important;
  border-spacing: 0;
  border-radius: 16px;
  background: rgba(16,17,24,.84) !important;
  box-shadow: 0 18px 55px rgba(0,0,0,.2);
}
thead { background: rgba(255,255,255,.035); }
th {
  padding: 13px 14px !important;
  border-bottom: 1px solid var(--border) !important;
  color: #b5b6c3 !important;
  font-size: 11px;
  font-weight: 750;
  letter-spacing: .065em;
  text-transform: uppercase;
  white-space: nowrap;
}
td {
  padding: 13px 14px !important;
  border-bottom: 1px solid rgba(255,255,255,.055) !important;
  color: #dddde6;
  vertical-align: middle !important;
}
tbody tr { transition: background .15s ease; }
tbody tr:hover { background: rgba(255,255,255,.025); }
tbody tr:last-child td { border-bottom: 0 !important; }
td.done, .positive { color: var(--green) !important; font-weight: 700; }
td.pending { color: var(--amber) !important; font-weight: 700; }
.negative { color: var(--danger) !important; }
.inline-form { gap: 8px !important; }
.cost-form { padding: 18px !important; }
main > p.muted {
  margin: 0 0 22px;
  padding: 14px 16px;
  border-left: 3px solid rgba(139,108,255,.7);
  border-radius: 0 12px 12px 0;
  background: rgba(139,108,255,.065);
}
body > form {
  position: relative;
  width: min(410px, calc(100vw - 32px)) !important;
  padding: 34px !important;
  overflow: hidden;
  border: 1px solid var(--border) !important;
  border-radius: 22px;
  background: linear-gradient(150deg, rgba(24,25,35,.96), rgba(12,13,19,.97)) !important;
  box-shadow: var(--shadow);
}
body > form::before {
  content: "";
  display: grid;
  place-items: center;
  width: 54px;
  height: 54px;
  margin-bottom: 18px;
  border-radius: 16px;
  background: #09080d url("/static/discord_icon.gif") center / cover no-repeat;
  box-shadow: 0 14px 38px rgba(233,70,152,.3);
}
body > form h1 { margin: 0 0 20px; color: white !important; font-size: 28px; letter-spacing: -.045em; }
body > form input, body > form button { width: 100%; margin-top: 11px; }
body > form button { min-height: 45px; margin-top: 14px; }
@media (max-width: 800px) {
  header { position: relative; min-height: 64px; padding: 12px 16px; }
  header h1::before { width: 34px; height: 34px; flex-basis: 34px; border-radius: 10px; }
  header > a { min-height: 34px; padding: 7px 10px; font-size: 12px; }
  main { width: min(100% - 24px, 1440px); padding-top: 18px !important; }
  nav { flex-wrap: nowrap; overflow-x: auto; padding: 6px; scrollbar-width: none; }
  nav::-webkit-scrollbar { display: none; }
  .tab { flex: 0 0 auto; }
  .filters, .toolbar, .cost-form { align-items: stretch !important; }
  .filters label { width: 100%; }
  input, select { min-width: 0 !important; width: 100%; }
  table { display: block !important; overflow-x: auto; border-radius: 13px; }
  thead { display: table-header-group !important; }
  tbody { display: table-row-group !important; }
  tr { display: table-row !important; padding: 0 !important; }
  th, td { display: table-cell !important; min-width: 118px; white-space: nowrap; }
  td form { white-space: normal; }
  .grid { grid-template-columns: 1fr !important; }
  .card { padding: 17px !important; }
  body > form { padding: 28px 24px !important; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; }
}
"""

PANEL_FAVICON = '<link rel="icon" type="image/gif" href="/static/discord_icon.gif">'


PANEL_CP_TEMPLATE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PinkGift — COD Points</title>
<style>
body{margin:0;background:#0e0d11;color:#f7edf3;font-family:Arial,sans-serif}header{padding:18px 5%;border-bottom:1px solid #352632;display:flex;justify-content:space-between;align-items:center}main{padding:22px 5%;max-width:1400px}h1{color:#ff8fc8}.card{background:#171419;border:1px solid #332630;padding:16px;margin-bottom:18px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:13px}.field{display:flex;flex-direction:column;gap:6px}.field span,th{color:#ff9dce;font-weight:bold}.field small,.muted{color:#aa98a4}input,button{box-sizing:border-box;background:#0e0d11;color:#fff;border:1px solid #5a3a4d;padding:10px}button{background:#e8509a;border:0;cursor:pointer;font-weight:bold}.danger{background:#9d294b}.notice{padding:12px;background:#241821;border-left:3px solid #ff78bb;margin-bottom:18px}table{width:100%;border-collapse:collapse;background:#171419;margin:14px 0 24px}th,td{text-align:left;padding:10px;border-bottom:1px solid #332630;vertical-align:top}.positive{color:#74d99f;font-weight:bold}.pending{color:#ffbd66;font-weight:bold}.cancelled{color:#ff6c8f;font-weight:bold}.actions{display:flex;gap:6px;flex-wrap:wrap}.actions form{display:flex;gap:6px}.actions input{min-width:210px}a{color:#ff9dce}@media(max-width:850px){table{display:block;overflow-x:auto}.actions input{min-width:150px}}
</style></head><body>
<header><h1>PinkGift — COD Points</h1><a href="{{ url_for('panel_orders') }}">Retour panel</a></header>
<main>
{% with messages=get_flashed_messages() %}{% for message in messages %}<div class="notice">{{ message }}</div>{% endfor %}{% endwith %}
<section class="card"><h2>Fonctionnement actuel</h2><p>Les nouvelles demandes CP ouvrent un ticket manuel dans Discord. Le client y précise le nombre de CP souhaité et combien il propose de payer.</p><p class="muted">Le solde PinkGift n'est ni consulté ni débité. Le tableau ci-dessous conserve uniquement les anciennes commandes automatiques pour permettre leur livraison ou leur remboursement.</p></section>
<form method="post" class="card"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="action" value="save_settings">
<h2>Prix affichés dans l'embed /cp</h2><div class="grid">{% for item in packs %}<section class="card"><h3>{{ item.points_label }} CP</h3>
<label class="field"><span>Prix affiché</span><input type="number" name="cp_price_{{ item.key }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01" required><small>Information visible dans /cp, sans débit automatique</small></label>
<label class="field"><span>Coût d'achat</span><input type="number" name="cp_cost_{{ item.key }}" value="{{ item.cost }}" min="0" max="100000" step="0.01" required><small>Conservé comme donnée interne</small></label>
<p class="muted">Prix officiel ≈ {{ item.official }} €</p></section>{% endfor %}</div><button type="submit">Mettre à jour l'embed /cp</button></form>
<h2>Anciennes commandes CP automatiques</h2><table><thead><tr><th>Client</th><th>Pack</th><th>Payé</th><th>État</th><th>Date</th><th>Actions</th></tr></thead><tbody>
{% for order in orders %}<tr><td><a href="https://discord.com/users/{{ order.user_id }}" target="_blank">@{{ order.user_name or order.user_id }}</a></td><td>{{ order.received_label }}</td><td>{{ order.paid }} €</td><td class="{{ order.status }}">{{ order.status }}</td><td>{{ order.updated_at or order.created_at }}</td><td><div class="actions">
{% if order.status == 'pending' %}<form method="post"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="action" value="deliver_order"><input type="hidden" name="order_id" value="{{ order.id }}"><input name="code" required placeholder="Code reçu du fournisseur"><button type="submit">Livrer</button></form>
<form method="post" onsubmit="return confirm('Annuler cette commande et rembourser le client ?')"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="action" value="refund_order"><input type="hidden" name="order_id" value="{{ order.id }}"><button class="danger" type="submit">Annuler + rembourser</button></form>{% elif order.status == 'done' %}<span class="positive">Livrée</span>{% else %}<span>—</span>{% endif %}
</div></td></tr>{% else %}<tr><td colspan="6">Aucune commande CP.</td></tr>{% endfor %}</tbody></table>
</main></body></html>"""


PANEL_PRICES_COSTS_TEMPLATE = PANEL_PRICES_COSTS_TEMPLATE.replace(
    '<input type="number" name="valo_{{ item.region_key }}_{{ item.pack_key }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01" required></label><label class="field"><span>{{ item.region }} — {{ item.pack }} — coût d\'achat</span>',
    '<input type="number" name="valo_{{ item.region_key }}_{{ item.pack_key }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01" required></label><label class="field"><span>{{ item.region }} — {{ item.pack }} — prix d\'origine</span><input type="number" name="valo_original_{{ item.region_key }}_{{ item.pack_key }}" value="{{ item.official }}" min="0.01" max="100000" step="0.01" required><small>Affiché barré dans l\'embed</small></label><label class="field"><span>{{ item.region }} — {{ item.pack }} — coût d\'achat</span>',
    1,
)

PANEL_PRICES_COSTS_TEMPLATE = (
    PANEL_PRICES_COSTS_TEMPLATE
    .replace("Prix et coûts d'achat", "PinkShop — Prix et coûts d'achat")
    .replace("Le prix de vente détermine le débit client.", "Le prix de vente en PinkCoins détermine le débit du PinkWallet.")
    .replace("— prix de vente", "— prix PinkCoins")
    .replace("<span>Prix de vente</span>", "<span>Prix en PinkCoins</span>")
    .replace("<small>Débit client</small>", "<small>Débit du PinkWallet en PinkCoins</small>")
    .replace('min="0.01" max="100000" step="0.01" required><small>Débit du PinkWallet', 'min="1" max="10000000" step="1" required><small>Débit du PinkWallet')
    .replace('name="uber_{{ item.key }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01"', 'name="uber_{{ item.key }}" value="{{ item.price }}" min="1" max="10000000" step="1"')
    .replace('name="discord_nitro" value="{{ discord_nitro }}" min="0.01" max="100000" step="0.01"', 'name="discord_nitro" value="{{ discord_nitro }}" min="1" max="10000000" step="1"')
    .replace('name="valo_{{ item.region_key }}_{{ item.pack_key }}" value="{{ item.price }}" min="0.01" max="100000" step="0.01"', 'name="valo_{{ item.region_key }}_{{ item.pack_key }}" value="{{ item.price }}" min="1" max="10000000" step="1"')
)


PANEL_SESSION_SCRIPT = r"""
<script>
(() => {
  const idleLimit = 30 * 60 * 1000;
  const heartbeatDelay = 60 * 1000;
  const heartbeatUrl = "{{ url_for('panel_heartbeat') }}";
  const logoutUrl = "{{ url_for('panel_logout') }}";
  let idleTimer;
  let lastHeartbeat = Date.now();

  const logout = () => { window.location.assign(logoutUrl); };
  const heartbeat = async () => {
    try {
      const response = await fetch(heartbeatUrl, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "X-Panel-Heartbeat": "1" }
      });
      if (response.redirected || response.status === 401) logout();
    } catch (_) {
      // Une coupure réseau temporaire ne doit pas effacer la session locale.
    }
  };
  const noteActivity = () => {
    const now = Date.now();
    window.clearTimeout(idleTimer);
    idleTimer = window.setTimeout(logout, idleLimit);
    if (now - lastHeartbeat >= heartbeatDelay) {
      lastHeartbeat = now;
      heartbeat();
    }
  };

  ["pointerdown", "keydown", "input", "change", "scroll", "touchstart"].forEach((eventName) => {
    window.addEventListener(eventName, noteActivity, { passive: true });
  });
  window.addEventListener("focus", noteActivity);
  noteActivity();
})();
</script>
"""


def apply_panel_theme(template, include_session_timeout=True):
    themed = template.replace("</style>", PANEL_THEME_CSS + "</style>", 1)
    themed = themed.replace("</head>", PANEL_FAVICON + "</head>", 1)
    if include_session_timeout:
        themed = themed.replace("</body>", PANEL_SESSION_SCRIPT + "</body>", 1)
    return themed


def migrate_panel_pinkcoin_copy(template):
    """Nettoie les anciennes mentions visibles sans toucher aux clés techniques."""
    replacements = {
        "Solde ajouté": "Dépôts suivis",
        "Solde parrainé crédité": "Valeur parrainée créditée",
        "Solde parrainé restant": "Valeur parrainée restante",
        "Solde utilisé": "Valeur utilisée",
        "solde utilisé": "valeur utilisée",
        "Le solde obtenu avec un code": "Les PinkCoins obtenus avec un code",
        "part de solde parrainée": "part de PinkCoins parrainée",
        "Aucun solde n'est crédité": "Aucun PinkCoin n'est crédité",
        "rembourser le client en solde": "recréditer les PinkCoins du client",
    }
    for old, new in replacements.items():
        template = template.replace(old, new)
    template = template.replace(">Prix</a>", ">PinkShop</a>")
    return re.sub(r"\bsoldes?\b", "PinkWallet", template, flags=re.IGNORECASE)


PANEL_TEMPLATE = migrate_panel_pinkcoin_copy(PANEL_TEMPLATE)
PANEL_STOCK_TEMPLATE = migrate_panel_pinkcoin_copy(PANEL_STOCK_TEMPLATE)
PANEL_STOCK_TEMPLATE = PANEL_STOCK_TEMPLATE.replace("{{ item.price }} €", "{{ item.price }} PC")
PANEL_CP_TEMPLATE = migrate_panel_pinkcoin_copy(PANEL_CP_TEMPLATE)
PANEL_PRICES_TEMPLATE = migrate_panel_pinkcoin_copy(PANEL_PRICES_TEMPLATE)
PANEL_FINANCES_TEMPLATE = migrate_panel_pinkcoin_copy(PANEL_FINANCES_TEMPLATE)
PANEL_PRICES_COSTS_TEMPLATE = migrate_panel_pinkcoin_copy(PANEL_PRICES_COSTS_TEMPLATE)
PANEL_FINANCES_PRODUCT_TEMPLATE = migrate_panel_pinkcoin_copy(PANEL_FINANCES_PRODUCT_TEMPLATE)
PANEL_FINANCES_NITRO_TEMPLATE = migrate_panel_pinkcoin_copy(PANEL_FINANCES_NITRO_TEMPLATE)
PANEL_REFERRALS_TEMPLATE = migrate_panel_pinkcoin_copy(PANEL_REFERRALS_TEMPLATE)
PANEL_REFERRALS_PROFIT_TEMPLATE = migrate_panel_pinkcoin_copy(PANEL_REFERRALS_PROFIT_TEMPLATE)
PANEL_EMBEDS_TEMPLATE = migrate_panel_pinkcoin_copy(PANEL_EMBEDS_TEMPLATE)


PANEL_TEMPLATE = apply_panel_theme(PANEL_TEMPLATE).replace(
    '<form method="post" action="{{ url_for(\'panel_delete_order\', order_id=order.id) }}" style="display:inline"',
    '''{% if order.status == 'pending' %}<form method="post" action="{{ url_for('panel_refund_order', order_id=order.id) }}" style="display:inline" onsubmit="return confirm('Annuler cette commande et recréditer les PinkCoins du client ?')"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="hidden" name="return_tab" value="{{ tab }}"><input type="hidden" name="return_service" value="{{ service_filter }}"><input type="hidden" name="return_amount" value="{{ amount_filter }}"><input type="hidden" name="return_region" value="{{ region_filter }}"><input type="hidden" name="return_pack" value="{{ pack_filter }}"><button class="delete" type="submit">Rembourser</button></form>{% endif %}<form method="post" action="{{ url_for('panel_delete_order', order_id=order.id) }}" style="display:inline"'''
)
PANEL_TEMPLATE = PANEL_TEMPLATE.replace(
    '<form method="post" action="{{ url_for(\'panel_set_code\', order_id=order.id) }}" style="display:inline">',
    '''{% if order.status == 'pending' %}<form method="post" action="{{ url_for('panel_set_code', order_id=order.id) }}" style="display:inline">'''
).replace(
    "<button type=\"submit\">Livrer</button></form>{% if order.status == 'pending' %}",
    "<button type=\"submit\">Livrer</button></form>{% endif %}{% if order.status == 'pending' %}",
)
PANEL_TEMPLATE = PANEL_TEMPLATE.replace(
    "<th>Statut</th></tr></thead><tbody>",
    "<th>Statut</th><th>Correction</th></tr></thead><tbody>",
).replace(
    '''</span>{% endif %}</td></tr>{% else %}<tr><td colspan="7">Aucun client enregistré.</td></tr>{% endfor %}</tbody></table>''',
    '''</span>{% endif %}</td><td>{% if client.total_added > 0 %}<form method="post" action="{{ url_for('panel_remove_client_deposit', guild_id=client.guild_id, user_id=client.user_id) }}" style="display:flex;gap:6px;align-items:center" onsubmit="return confirm('Retirer ce montant des dépôts nets ? Le PinkWallet restera inchangé.')"><input type="hidden" name="csrf" value="{{ session.csrf }}"><input type="number" name="amount" min="0.01" max="{{ '%.2f'|format(client.total_added) }}" step="0.01" required placeholder="Montant €" style="min-width:105px;width:105px"><button class="delete" type="submit">Retirer</button></form>{% else %}<span class="muted">—</span>{% endif %}</td></tr>{% else %}<tr><td colspan="8">Aucun client enregistré.</td></tr>{% endfor %}</tbody></table>''',
)
PANEL_TEMPLATE = PANEL_TEMPLATE.replace(
    "<td>{{ order.service }}</td>",
    '<td>{{ order.service }}{% if order.supplier %}<div class="muted">Fournisseur : {{ order.supplier }}</div>{% endif %}</td>',
).replace(
    '<input name="code" required placeholder="Code cadeau" value="{{ order.code or \'\' }}">',
    '''{% if order.is_nitro %}<input name="supplier" required maxlength="100" placeholder="Fournisseur Nitro" value="{{ order.supplier or '' }}">{% endif %}<input name="code" required placeholder="{{ 'Lien Nitro' if order.is_nitro else 'Code cadeau' }}" value="{{ order.code or '' }}">''',
)

PANEL_ORDER_ACTIONS_CSS = r"""
.order-actions-cell {
  min-width: 700px;
  vertical-align: middle;
}
.order-actions {
  display: grid;
  grid-template-columns: minmax(430px, 1fr) auto auto;
  gap: 10px;
  align-items: center;
}
.order-actions form {
  margin: 0;
}
.order-delivery-form {
  display: grid;
  grid-template-columns: minmax(145px, .8fr) minmax(190px, 1.2fr) auto;
  gap: 8px;
  align-items: center;
  min-width: 0;
}
.order-delivery-form input {
  width: 100%;
  min-width: 0;
}
.order-actions button {
  min-height: 46px;
  margin: 0;
  white-space: nowrap;
}
.order-refund-form,
.order-delete-form {
  display: flex;
}
@media (max-width: 1500px) {
  .order-actions-cell {
    min-width: 500px;
  }
  .order-actions {
    grid-template-columns: 1fr auto auto;
  }
  .order-delivery-form {
    grid-column: 1 / -1;
  }
  .order-refund-form {
    grid-column: 2;
  }
  .order-delete-form {
    grid-column: 3;
  }
}
@media (max-width: 800px) {
  .order-actions-cell {
    min-width: 0;
  }
  .order-actions {
    grid-template-columns: 1fr;
  }
  .order-delivery-form {
    grid-column: auto;
    grid-template-columns: 1fr;
  }
  .order-delivery-form button,
  .order-refund-form button,
  .order-delete-form button {
    width: 100%;
  }
  .order-refund-form,
  .order-delete-form {
    grid-column: auto;
  }
}
"""

PANEL_TEMPLATE = PANEL_TEMPLATE.replace(
    '''<td>{% if order.status == 'pending' %}<form method="post" action="{{ url_for('panel_set_code', order_id=order.id) }}" style="display:inline">''',
    '''<td class="order-actions-cell"><div class="order-actions">{% if order.status == 'pending' %}<form class="order-delivery-form" method="post" action="{{ url_for('panel_set_code', order_id=order.id) }}">''',
).replace(
    '''{% if order.status == 'pending' %}<form method="post" action="{{ url_for('panel_refund_order', order_id=order.id) }}" style="display:inline"''',
    '''{% if order.status == 'pending' %}<form class="order-refund-form" method="post" action="{{ url_for('panel_refund_order', order_id=order.id) }}"''',
).replace(
    '''<form method="post" action="{{ url_for('panel_delete_order', order_id=order.id) }}" style="display:inline"''',
    '''<form class="order-delete-form" method="post" action="{{ url_for('panel_delete_order', order_id=order.id) }}"''',
).replace(
    '''<button class="delete" type="submit" title="Supprimer">Supprimer</button></form></td></tr>{% else %}<tr><td colspan="7">''',
    '''<button class="delete" type="submit" title="Supprimer">Supprimer</button></form></div></td></tr>{% else %}<tr><td colspan="7">''',
).replace(
    "</style>",
    PANEL_ORDER_ACTIONS_CSS + "</style>",
    1,
)
PANEL_STOCK_TEMPLATE = apply_panel_theme(PANEL_STOCK_TEMPLATE)
PANEL_CP_TEMPLATE = apply_panel_theme(PANEL_CP_TEMPLATE)
PANEL_PRICES_TEMPLATE = apply_panel_theme(PANEL_PRICES_TEMPLATE)
PANEL_FINANCES_TEMPLATE = apply_panel_theme(PANEL_FINANCES_TEMPLATE)
PANEL_PRICES_COSTS_TEMPLATE = apply_panel_theme(PANEL_PRICES_COSTS_TEMPLATE)
PANEL_FINANCES_PRODUCT_TEMPLATE = apply_panel_theme(PANEL_FINANCES_PRODUCT_TEMPLATE)
PANEL_FINANCES_NITRO_TEMPLATE = apply_panel_theme(PANEL_FINANCES_NITRO_TEMPLATE)
PANEL_REFERRALS_TEMPLATE = apply_panel_theme(PANEL_REFERRALS_TEMPLATE)
PANEL_REFERRALS_PROFIT_TEMPLATE = apply_panel_theme(PANEL_REFERRALS_PROFIT_TEMPLATE).replace(
    "</style>", PANEL_REFERRALS_LAYOUT_CSS + "</style>", 1
)
PANEL_EMBEDS_TEMPLATE = (
    apply_panel_theme(PANEL_EMBEDS_TEMPLATE)
    .replace("</style>", PANEL_EMBEDS_PREVIEW_CSS + "</style>", 1)
    .replace(
        "</body>",
        PANEL_EMBEDS_PREVIEW_SCRIPT + PANEL_PRIVILEGE_MENU_EDITOR_SCRIPT + "</body>",
        1,
    )
)
LOGIN_TEMPLATE = apply_panel_theme(LOGIN_TEMPLATE, include_session_timeout=False)
PANEL_ACCESS_TEMPLATE = apply_panel_theme(PANEL_ACCESS_TEMPLATE)


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
        session["panel_last_activity_at"] = session["panel_login_at"]
        session["csrf"] = secrets.token_urlsafe(24)
        return redirect(url_for("panel_orders"))
    return render_template_string(LOGIN_TEMPLATE)


@app.route("/panel/logout")
def panel_logout():
    session.clear()
    return redirect(url_for("panel_login"))


@app.route("/panel/heartbeat")
@panel_required
def panel_heartbeat():
    return "", 204


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
    try:
        order_suppliers = load_order_suppliers()
    except Exception as error:
        print(f"Erreur chargement fournisseurs Nitro : {error}")
        order_suppliers = {}
    for order in all_orders:
        order["is_nitro"] = is_nitro_order(order)
        order["supplier"] = order_suppliers.get(int(order.get("message_id") or 0), "")
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
    guild_ids = {
        int(order.get("guild_id") or 0)
        for order in all_orders
        if int(order.get("guild_id") or 0) > 0
    }
    guild_ids.update(guild.id for guild in bot.guilds)
    deposit_totals_by_guild = {}
    for guild_id in guild_ids:
        try:
            deposit_totals_by_guild[guild_id] = get_customer_deposit_totals(guild_id)
        except Exception as error:
            print(f"Erreur chargement dépôts clients pour {guild_id}: {error}")
            deposit_totals_by_guild[guild_id] = {}

    clients_by_id = {}
    for order in all_orders:
        user_id = int(order.get("user_id") or 0)
        guild_id = int(order.get("guild_id") or 0)
        if user_id <= 0:
            continue
        client_key = (guild_id, user_id)
        client = clients_by_id.setdefault(client_key, {
            "guild_id": guild_id,
            "user_id": user_id,
            "user_name": order.get("user_name") or str(user_id),
            "order_count": 0,
            "total_spent": 0.0,
            "total_added": 0.0,
        })
        if order.get("user_name"):
            client["user_name"] = order["user_name"]
        if order_counts_as_purchase(order):
            client["order_count"] += 1
            client["total_spent"] += float(order.get("paid") or 0)
    for guild_id, deposit_totals in deposit_totals_by_guild.items():
        guild = bot.get_guild(guild_id)
        for user_id, total_added in deposit_totals.items():
            client_key = (guild_id, int(user_id))
            member = guild.get_member(int(user_id)) if guild else None
            client = clients_by_id.setdefault(client_key, {
                "guild_id": guild_id,
                "user_id": int(user_id),
                "user_name": member.name if member else str(user_id),
                "order_count": 0,
                "total_spent": 0.0,
                "total_added": 0.0,
            })
            if member:
                client["user_name"] = member.name
            client["total_added"] = float(total_added or 0)

    spending_totals_by_guild = {
        guild_id: get_customer_spending_totals(guild_id, all_orders)
        for guild_id in guild_ids
    }
    leaders_by_guild = {}
    for guild_id, spending_totals in spending_totals_by_guild.items():
        guild = bot.get_guild(guild_id)
        if guild:
            leaders_by_guild[guild_id] = customer_top_user_id(guild, spending_totals)
        elif spending_totals:
            highest = max(float(value or 0) for value in spending_totals.values())
            leaders_by_guild[guild_id] = min(
                int(user_id) for user_id, value in spending_totals.items() if float(value or 0) == highest
            )
    for client in clients_by_id.values():
        tier = customer_highest_tier(client.get("total_added", 0))
        client["tier_label"] = tier["label"]
        client["tier_role_id"] = tier["role_id"]
        guild = bot.get_guild(client["guild_id"])
        tier_role = guild.get_role(tier["role_id"]) if guild and tier["role_id"] else None
        client["tier_role_name"] = tier_role.name if tier_role else "Rôle client"
        client["is_top"] = client["user_id"] == leaders_by_guild.get(client["guild_id"])
    clients = sorted(
        clients_by_id.values(),
        key=lambda item: (item["total_spent"], item["total_added"], item["order_count"]),
        reverse=True,
    )
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


def panel_pinkcoin_value(field_name):
    raw = request.form.get(field_name, "").strip().replace(" ", "").replace(",", ".")
    try:
        parsed = float(raw)
        if not parsed.is_integer():
            raise ValueError
        pinkcoins = int(parsed)
    except ValueError as error:
        raise ValueError(f"Nombre de PinkCoins invalide pour {field_name}") from error
    if not 1 <= pinkcoins <= 10000000:
        raise ValueError(f"Le prix {field_name} doit être compris entre 1 et 10 000 000 PinkCoins")
    return pinkcoins_to_euros(pinkcoins)


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
            action = request.form.get("action", "save")
            code = normalize_referral_code(request.form.get("code"))
            if len(code) < 3:
                raise ValueError("Le code doit contenir au moins 3 caractères")
            codes = get_referral_codes()
            if action == "delete":
                was_configured = code in codes
                purge = purge_referral_code_data(code)
                notification_messages = purge.pop("notification_messages", [])
                if was_configured:
                    del codes[code]
                    save_referral_codes(codes)
                if notification_messages:
                    if BOT_LOOP is None:
                        print("Notifications de parrainage non supprimées : le bot Discord n'est pas encore prêt.")
                    else:
                        future = asyncio.run_coroutine_threadsafe(
                            delete_referral_tracking_notifications(notification_messages),
                            BOT_LOOP,
                        )
                        future.add_done_callback(log_referral_notification_deletion)
                if not was_configured and not any(purge[key] for key in ("ledgers", "lots", "events", "tickets")):
                    raise ValueError("Ce code est déjà totalement supprimé ou introuvable")
                flash(
                    f"Code {code} supprimé définitivement : {purge['events']} commission(s) "
                    f"pour {purge['commission']:.2f} €, {purge['lots']} recharge(s) suivie(s) "
                    f"{purge['tickets']} association(s) de ticket et {purge['notifications']} "
                    f"notification(s) Discord effacées."
                )
                return redirect(url_for("panel_referrals"))
            if action != "save":
                raise ValueError("Action inconnue")
            sponsor_name = request.form.get("sponsor_name", "").strip()[:80]
            if not sponsor_name:
                raise ValueError("Le nom du parrain est obligatoire")
            sponsor_id = request.form.get("sponsor_id", "").strip()
            if sponsor_id and not re.fullmatch(r"\d{15,25}", sponsor_id):
                raise ValueError("L'ID Discord du parrain est invalide")
            percentage = panel_percentage_value("percentage")
            paid = panel_cost_value("paid")
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
            flash(f"Impossible de modifier le code : {error}")
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


@app.route("/panel/cp", methods=["GET", "POST"])
@panel_required
def panel_cp():
    if request.method == "POST":
        if not valid_panel_csrf():
            flash("Session invalide. Recharge la page.")
            return redirect(url_for("panel_cp"))
        try:
            action = request.form.get("action", "")
            if action == "save_settings":
                pricing = get_pricing_config()
                purchase_costs = get_purchase_cost_config()
                for pack_key in CP_PACKS:
                    pricing["cp"][pack_key] = panel_price_value(f"cp_price_{pack_key}")
                    purchase_costs["cp"][pack_key] = panel_cost_value(f"cp_cost_{pack_key}")
                set_panel_setting("pricing", pricing)
                set_panel_setting("purchase_costs", purchase_costs)
                if BOT_LOOP is not None:
                    future = asyncio.run_coroutine_threadsafe(refresh_price_embeds_from_panel(), BOT_LOOP)
                    future.add_done_callback(log_price_embed_refresh)
                flash("Prix et coûts CP enregistrés. L'embed /cp est synchronisé sans redémarrage ; aucun débit automatique n'est effectué.")
            elif action == "deliver_order":
                order = get_cp_order(order_id=int(request.form.get("order_id", 0)))
                code = normalize_cp_code(request.form.get("code"))
                if not order or str(order.get("status") or "pending").lower() != "pending" or not code:
                    raise ValueError("Commande CP ou code invalide")
                if BOT_LOOP is None:
                    raise RuntimeError("Le bot Discord n'est pas encore prêt")
                mark_order_status(order["id"], "delivering")
                try:
                    asyncio.run_coroutine_threadsafe(deliver_cp_order_to_discord(order, code), BOT_LOOP).result(timeout=25)
                except Exception:
                    mark_order_status(order["id"], "pending")
                    raise
                flash(f"Commande CP #{order['id']} livrée au client.")
            elif action == "refund_order":
                order = get_cp_order(order_id=int(request.form.get("order_id", 0)))
                if not order or str(order.get("status") or "pending").lower() != "pending":
                    raise ValueError("Cette commande CP n'est plus en attente")
                new_balance = refund_pending_order(order, bot.user.id if bot.user else 0)
                if BOT_LOOP is not None:
                    try:
                        asyncio.run_coroutine_threadsafe(show_order_refund_on_discord(order, new_balance), BOT_LOOP).result(timeout=25)
                    except Exception as discord_error:
                        print(f"Erreur mise à jour ticket après remboursement CP #{order['id']}: {discord_error}")
                flash(f"Commande CP #{order['id']} annulée et client remboursé.")
            else:
                raise ValueError("Action CP inconnue")
        except Exception as error:
            print(f"Erreur panel CP : {error}")
            flash(f"Modification CP impossible : {error}")
        return redirect(url_for("panel_cp"))

    pricing = get_pricing_config()["cp"]
    purchase_costs = get_purchase_cost_config()["cp"]
    packs = []
    for pack_key, pack in CP_PACKS.items():
        packs.append({
            "key": pack_key,
            "points_label": f"{pack['points']:,}".replace(",", " "),
            "price": format_price(pricing[pack_key]),
            "cost": format_price(purchase_costs[pack_key]),
            "official": f"{pack['official_price']:.2f}".replace(".", ","),
        })
    try:
        orders = [
            order for order in load_orders_for_stats(limit=1000)
            if str(order.get("service") or "").upper().startswith("COD POINTS")
        ][:200]
    except Exception as error:
        print(f"Erreur historique CP panel : {error}")
        orders = []
    return render_template_string(PANEL_CP_TEMPLATE, packs=packs, orders=orders)


@app.route("/panel/prix", methods=["GET", "POST"])
@panel_required
def panel_prices():
    if request.method == "POST":
        if not valid_panel_csrf():
            flash("Session invalide. Recharge la page.")
            return redirect(url_for("panel_prices"))
        try:
            pricing = {
                "gift_cards": {str(amount): panel_pinkcoin_value(f"gift_{amount}") for amount in GIFT_CARD_AMOUNTS},
                "uber_eats": {pack_key: panel_pinkcoin_value(f"uber_{pack_key}") for pack_key in UBEREATS_PACKS},
                "discord_nitro": panel_pinkcoin_value("discord_nitro"),
                "cp": get_pricing_config()["cp"],
                "valorant": {
                    region_key: {
                        pack_key: panel_pinkcoin_value(f"valo_{region_key}_{pack_key}")
                        for pack_key in region["packs"]
                    }
                    for region_key, region in VALO_REGIONS.items()
                },
                "valorant_original": {
                    region_key: {
                        pack_key: panel_price_value(f"valo_original_{region_key}_{pack_key}")
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
                "cp": get_purchase_cost_config()["cp"],
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
                flash("Prix PinkCoins et coûts d'achat enregistrés. Le PinkShop et les panneaux Discord sont actualisés sans redémarrage.")
            else:
                flash("Prix et coûts d'achat enregistrés. Ils seront utilisés dès que le bot Discord sera connecté.")
        except Exception as error:
            print(f"Erreur mise à jour prix : {error}")
            flash(f"Impossible d'enregistrer les prix : {error}")
        return redirect(url_for("panel_prices"))

    pricing = get_pricing_config()
    purchase_costs = get_purchase_cost_config()
    gift_cards = [
        {"amount": amount, "price": pinkcoin_input_value(pricing["gift_cards"][str(amount)])}
        for amount in GIFT_CARD_AMOUNTS
    ]
    uber_eats = [
        {"key": pack_key, "drop": pack["drop"], "price": pinkcoin_input_value(pricing["uber_eats"][pack_key]), "cost": format_price(purchase_costs["uber_eats"][pack_key])}
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
                "price": pinkcoin_input_value(pricing["valorant"][region_key][pack_key]),
                "official": format_price(pricing["valorant_original"][region_key][pack_key]),
                "cost": format_price(purchase_costs["valorant"][region_key][pack_key]),
            })
    return render_template_string(
        PANEL_PRICES_COSTS_TEMPLATE,
        gift_cards=gift_cards,
        gift_cost_products=gift_cost_products,
        uber_eats=uber_eats,
        discord_nitro=pinkcoin_input_value(pricing["discord_nitro"]),
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
            valorant.append({"region_key": region_key, "region": region["label"], "pack_key": pack_key, "price": pinkcoin_number(pricing["valorant"][region_key][pack_key]), "pack": pack["label"], "available": stock["valorant"].get(region_key, {}).get(pack_key, True)})
    return render_template_string(PANEL_STOCK_TEMPLATE, products=products, valorant=valorant, ok_emoji=STOCK_OK_EMOJI, ko_emoji=STOCK_KO_EMOJI)


PANEL_HIDDEN_EMBED_KEYS = {
    "ticket_bienvenue",
    "valo_ticket_bienvenue_embed",
}


EMBED_COMPONENT_BUTTON_DEFINITIONS = {
    "tarifs_embed": [
        {"key": "confirm_nitro", "label": "Commander Discord Nitro", "emoji": "💎", "style": "success"},
    ],
    "cp_embed": [
        {"key": "start_cp_order", "label": "Commander des COD Points", "emoji": "<:cp:1528128623117205624>", "style": "success"},
    ],
    "cp_order_pending_embed": [
        {"key": "deliver_pending", "label": "Livrer le code", "emoji": "📩", "style": "success"},
    ],
    "autres_embed": [
        {"key": "back_categories", "label": "Retour aux catégories", "emoji": "↩️", "style": "secondary"},
    ],
    "privileges_embed": [
        {"key": "back_categories", "label": "Retour aux catégories", "emoji": "↩️", "style": "secondary"},
    ],
    "balance_embed": [
        {"key": "view_balance", "label": "Voir mes PinkCoins", "emoji": "💰", "style": "secondary"},
        {"key": "recharge_balance", "label": "Recharger mon PinkWallet", "emoji": "➕", "style": "success"},
        {"key": "referral_yes", "label": "Oui, j'ai un code", "emoji": "✅", "style": "success"},
        {"key": "referral_no", "label": "Non", "emoji": "❌", "style": "secondary"},
    ],
    "parrainages_embed": [
        {"key": "open_referral_ticket", "label": "Devenir parrain", "emoji": "🤝", "style": "success"},
    ],
    "recrutement_embed": [
        {"key": "open_recruitment_ticket", "label": "Postuler", "emoji": "📩", "style": "primary"},
    ],
    "close_ticket_embed": [
        {"key": "close_ticket", "label": "Close", "emoji": "🔒", "style": "danger"},
    ],
    "menu_ticket_embed": [
        {"key": "open_ticket", "label": "Ouvrir un ticket", "emoji": "🎫", "style": "success"},
    ],
    "commande_vp_embed": [
        {"key": "open_valo_ticket", "label": "Ouvrir un ticket Valorant", "emoji": "🎮", "style": "success"},
    ],
    "giveaway_embed": [
        {"key": "join_giveaway", "label": "Je participe", "emoji": GIVEAWAY_JOIN_EMOJI, "style": "success"},
    ],
}


def privilege_component_value(label, fallback):
    normalized = unicodedata.normalize("NFD", str(label or "").lower())
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return (normalized or fallback)[:100]


def parse_privilege_menu_config(raw_text):
    try:
        raw_categories = json.loads(str(raw_text or "[]"))
    except json.JSONDecodeError as error:
        raise ValueError("La configuration visuelle des menus est invalide") from error
    if not isinstance(raw_categories, list):
        raise ValueError("La configuration des menus doit contenir une liste de catégories")
    if not raw_categories:
        raise ValueError("Ajoute au moins une catégorie au menu Privilèges")
    if len(raw_categories) > 25:
        raise ValueError("Le menu Privilèges accepte au maximum 25 catégories")

    categories = []
    used_category_values = set()
    for category_index, raw_category in enumerate(raw_categories, start=1):
        if not isinstance(raw_category, dict):
            raise ValueError(f"La catégorie {category_index} est invalide")
        label = str(raw_category.get("label") or "").strip()[:100]
        if not label:
            raise ValueError(f"La catégorie {category_index} doit avoir un nom")
        emoji = str(raw_category.get("emoji") or "📁").strip()
        description = str(raw_category.get("description") or f"Ouvrir {label}").strip()[:100]
        placeholder = str(
            raw_category.get("placeholder") or f"Choisis une option — {label}"
        ).strip()[:150]
        category_value = privilege_component_value(label, f"categorie-{category_index}")
        if category_value in used_category_values:
            category_value = f"{category_value[:90]}-{category_index}"
        used_category_values.add(category_value)

        raw_options = raw_category.get("options", [])
        if not isinstance(raw_options, list) or not raw_options:
            raise ValueError(f"Ajoute au moins une option à la catégorie {label}")
        if len(raw_options) > 25:
            raise ValueError(f"La catégorie {label} accepte au maximum 25 options")
        options = []
        used_option_values = set()
        for option_index, raw_option in enumerate(raw_options, start=1):
            if not isinstance(raw_option, dict):
                raise ValueError(f"L’option {option_index} de {label} est invalide")
            option_label = str(raw_option.get("label") or "").strip()[:100]
            if not option_label:
                raise ValueError(f"L’option {option_index} de {label} doit avoir un nom")
            option_emoji = str(raw_option.get("emoji") or "✨").strip()
            option_value = privilege_component_value(option_label, f"option-{option_index}")
            if option_value in used_option_values:
                option_value = f"{option_value[:90]}-{option_index}"
            used_option_values.add(option_value)
            options.append({
                "label": option_label,
                "value": option_value,
                "emoji": option_emoji,
                "description": str(raw_option.get("description") or "").strip()[:100],
                "response": str(raw_option.get("response") or "").strip(),
            })
        categories.append({
            "label": label,
            "value": category_value,
            "emoji": emoji,
            "description": description,
            "placeholder": placeholder,
            "options": options,
        })
    return categories


def parse_other_services_menu_config(raw_text):
    try:
        raw_categories = json.loads(str(raw_text or "[]"))
    except json.JSONDecodeError as error:
        raise ValueError("La configuration visuelle du menu Autres est invalide") from error
    if not isinstance(raw_categories, list):
        raise ValueError("La configuration du menu Autres doit contenir une liste de catégories")
    if not raw_categories:
        raise ValueError("Ajoute au moins une catégorie au menu Autres")
    if len(raw_categories) > 25:
        raise ValueError("Le menu Autres accepte au maximum 25 catégories")

    categories = []
    used_category_values = set()
    for category_index, raw_category in enumerate(raw_categories, start=1):
        if not isinstance(raw_category, dict):
            raise ValueError(f"La catégorie {category_index} est invalide")
        label = str(raw_category.get("label") or "").strip()[:100]
        if not label:
            raise ValueError(f"La catégorie {category_index} doit avoir un nom")
        category_value = privilege_component_value(label, f"categorie-{category_index}")
        if category_value in used_category_values:
            category_value = f"{category_value[:90]}-{category_index}"
        used_category_values.add(category_value)
        catalog_key = str(raw_category.get("catalog_key") or "autres").strip().lower()
        if catalog_key not in {"autres", "abonnements"}:
            raise ValueError(f"Le type de ticket de la catégorie {label} est invalide")

        raw_options = raw_category.get("options", [])
        if not isinstance(raw_options, list) or not raw_options:
            raise ValueError(f"Ajoute au moins un service à la catégorie {label}")
        if len(raw_options) > 25:
            raise ValueError(f"La catégorie {label} accepte au maximum 25 services")
        options = []
        used_option_values = set()
        for option_index, raw_option in enumerate(raw_options, start=1):
            if not isinstance(raw_option, dict):
                raise ValueError(f"Le service {option_index} de {label} est invalide")
            option_label = str(raw_option.get("label") or "").strip()[:100]
            if not option_label:
                raise ValueError(f"Le service {option_index} de {label} doit avoir un nom")
            option_value = privilege_component_value(option_label, f"service-{option_index}")
            if option_value in used_option_values:
                option_value = f"{option_value[:90]}-{option_index}"
            used_option_values.add(option_value)
            service_key = str(raw_option.get("service_key") or "").strip().upper()
            if not service_key:
                service_key = f"CUSTOM_{option_value.upper().replace('-', '_')}"
            options.append({
                "label": option_label,
                "value": option_value,
                "emoji": str(raw_option.get("emoji") or "✨").strip(),
                "description": str(raw_option.get("description") or "").strip()[:100],
                "service_key": service_key[:100],
            })
        categories.append({
            "label": label,
            "value": category_value,
            "emoji": str(raw_category.get("emoji") or "📁").strip(),
            "description": str(raw_category.get("description") or f"Ouvrir {label}").strip()[:100],
            "placeholder": str(
                raw_category.get("placeholder") or f"Choisis un service — {label}"
            ).strip()[:150],
            "catalog_key": catalog_key,
            "options": options,
        })
    return categories


@app.route("/panel/embeds", methods=["GET", "POST"])
@panel_required
def panel_embeds():
    if request.method == "POST":
        if not valid_panel_csrf():
            flash("Session invalide. Recharge la page.")
            return redirect(url_for("panel_embeds"))
        embed_key = request.form.get("embed_key", "").strip()
        try:
            current_data = load_embed_texts()
            if embed_key in PANEL_HIDDEN_EMBED_KEYS or not isinstance(current_data.get(embed_key), dict):
                raise ValueError("Cet ancien embed de commande manuelle n'est plus modifiable")
            embed_data = json.loads(request.form.get("embed_json", "{}"))
            if not isinstance(embed_data, dict):
                raise ValueError("Le contenu doit être un objet JSON")
            menu_launcher_defaults = {
                "privileges_embed": "Découvrir les privilèges",
                "autres_embed": "Voir les services",
                "tarifs_embed": "Commander",
                "valo_embed": "Commander des VP",
            }
            if embed_key in menu_launcher_defaults:
                default_button_label = menu_launcher_defaults[embed_key]
                embed_data["menu_button_label"] = (
                    request.form.get("menu_button_label", "").strip()
                    or default_button_label
                )[:80]
                embed_data["menu_button_emoji"] = (
                    request.form.get("menu_button_emoji", "").strip()
                    or "✨"
                )
                fallback_style = (
                    "success" if embed_key in {"tarifs_embed", "valo_embed"} else "primary"
                )
                raw_button_style = request.form.get("menu_button_style", "").strip()
                if raw_button_style not in DISCORD_BUTTON_COLORS:
                    raise ValueError("Choisis une couleur de bouton officielle Discord")
                embed_data["menu_button_style"] = normalize_button_style(
                    raw_button_style,
                    fallback_style,
                )
                embed_data.pop("menu_button_color", None)
            if embed_key in {"privileges_embed", "autres_embed"}:
                embed_data["menu_placeholder"] = (
                    request.form.get("menu_placeholder", "").strip()
                    or "Choisis une catégorie"
                )[:150]
                menu_parser = (
                    parse_privilege_menu_config
                    if embed_key == "privileges_embed"
                    else parse_other_services_menu_config
                )
                embed_data["menu_categories"] = menu_parser(
                    request.form.get("menu_config_json", "[]")
                )
            component_definitions = EMBED_COMPONENT_BUTTON_DEFINITIONS.get(embed_key, [])
            if component_definitions:
                component_buttons = {}
                for definition in component_definitions:
                    button_key = definition["key"]
                    raw_style = request.form.get(f"component_style__{button_key}", "").strip()
                    if raw_style not in DISCORD_BUTTON_COLORS:
                        raise ValueError(
                            f"Choisis une couleur Discord valide pour le bouton « {definition['label']} »"
                        )
                    component_buttons[button_key] = {
                        "label": (
                            request.form.get(f"component_label__{button_key}", "").strip()
                            or definition["label"]
                        )[:80],
                        "emoji": (
                            request.form.get(f"component_emoji__{button_key}", "").strip()
                            or definition["emoji"]
                        ),
                        "style": normalize_button_style(
                            raw_style,
                            definition["style"],
                        ),
                    }
                embed_data["component_buttons"] = component_buttons
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
            flash(
                f"Embed {embed_key} enregistré. Exécute /maj_embed dans le salon de l’embed à actualiser."
            )
        except Exception as error:
            print(f"Erreur sauvegarde embed {embed_key}: {error}")
            flash(f"Sauvegarde impossible : {error}")
        return redirect(url_for("panel_embeds"))
    data = load_embed_texts()
    preview_contexts = {}
    try:
        pricing = get_pricing_config()
        preview_contexts["tarifs_embed"] = {
            "gift_cards": [
                {"amount": amount, "price": pinkcoin_number(pricing["gift_cards"][str(amount)])}
                for amount in GIFT_CARD_AMOUNTS
            ],
            "uber_eats": [
                {
                    "pack_key": pack_key,
                    "drop": pack["drop"],
                    "price": pinkcoin_number(pricing["uber_eats"][pack_key]),
                }
                for pack_key, pack in UBEREATS_PACKS.items()
            ],
            "nitro": {"price": pinkcoin_number(pricing["discord_nitro"])},
        }
        preview_contexts["valo_embed"] = {
            "regions": [
                {
                    "region_key": region_key,
                    "region": region["label"],
                    "emoji": region["emoji"],
                    "packs": [
                        {
                            "pack_key": pack_key,
                            "pack": pack["label"],
                            "price": pinkcoin_number(pricing["valorant"][region_key][pack_key]),
                            "official": format_price(pricing["valorant_original"][region_key][pack_key]),
                        }
                        for pack_key, pack in region["packs"].items()
                    ],
                }
                for region_key, region in VALO_REGIONS.items()
            ]
        }
        preview_contexts["cp_embed"] = {
            "packs": [
                {
                    "pack_key": pack_key,
                    "points": f"{pack['points']:,}".replace(",", " "),
                    "price": format_price(pricing["cp"][pack_key]),
                    "official": f"{pack['official_price']:.2f}".replace(".", ","),
                }
                for pack_key, pack in CP_PACKS.items()
            ]
        }
    except Exception as error:
        print(f"Erreur préparation aperçus dynamiques du panel : {error}")
    embed_help = {
        "emojis": "Catalogue central des emojis custom. Toute modification est reprise par les menus et les embeds concernés sans redémarrage.",
        "tarifs_embed": "La liste des marques est modifiable ici. Le texte, l’emoji et la couleur du bouton sont configurables ; les prix restent synchronisés avec l'onglet Prix et le parcours de commande.",
        "valo_embed": "Le bouton est personnalisable. Les régions, emojis et packs sont générés avec les prix en direct. Variables : {emoji}, {region}, {region_key}, {pack}, {pack_key}, {price} et {official}.",
        "cp_embed": "Les packs et prix restent affichés dans l'embed. Le bouton ouvre toutefois un ticket manuel sans lecture ni débit de PinkCoins.",
        "autres_embed": "Publié avec /autres. Le bouton, sa couleur, les catégories et tous les services se configurent ici sans redémarrer le bot.",
        "privileges_embed": "Publié avec /privilèges. L’embed, le bouton, les catégories et les sous-options se configurent ici sans redémarrer le bot.",
        "parrainages_embed": "Publié avec /parrainages. Le bouton ouvre une candidature privée dans la catégorie Parrainage/Recrutement.",
        "recrutement_embed": "Publié avec /recrutement. Le bouton ouvre une candidature privée dans la catégorie Parrainage/Recrutement.",
        "team_embed": "Publié avec /teams. Ajoute les membres du staff dans les champs correspondant à leurs grades.",
    }
    embeds = []
    for key in sorted(
        key for key, value in data.items()
        if isinstance(value, dict) and key not in PANEL_HIDDEN_EMBED_KEYS
    ):
        menu_enabled = key in {"privileges_embed", "autres_embed"}
        launcher_only = key in {"tarifs_embed", "valo_embed"}
        launcher_enabled = menu_enabled or launcher_only
        menu_titles = {
            "autres_embed": "/autres",
            "privileges_embed": "Privilèges",
            "tarifs_embed": "/tarifs",
            "valo_embed": "/valo",
        }
        configured_component_buttons = (
            data[key].get("component_buttons", {})
            if isinstance(data[key].get("component_buttons"), dict)
            else {}
        )
        component_buttons = []
        for definition in EMBED_COMPONENT_BUTTON_DEFINITIONS.get(key, []):
            configured = configured_component_buttons.get(definition["key"], {})
            if not isinstance(configured, dict):
                configured = {}
            component_buttons.append({
                "key": definition["key"],
                "name": definition["label"],
                "label": str(configured.get("label") or definition["label"])[:80],
                "emoji": str(configured.get("emoji") or definition["emoji"]),
                "style": normalize_button_style(
                    configured.get("style") or configured.get("color"),
                    definition["style"],
                ),
            })
        embeds.append({
            "key": key,
            "json": json.dumps(data[key], ensure_ascii=False, indent=2),
            "preview_context": json.dumps(preview_contexts.get(key, {}), ensure_ascii=False),
            "help": embed_help.get(key, ""),
            "menu_enabled": menu_enabled,
            "launcher_only": launcher_only,
            "menu_kind": "autres" if key == "autres_embed" else "privileges",
            "menu_title": menu_titles.get(key, key),
            "menu_button_label": data[key].get("menu_button_label", "") if launcher_enabled else "",
            "menu_button_emoji": data[key].get("menu_button_emoji", "") if launcher_enabled else "",
            "menu_button_style": normalize_button_style(
                data[key].get("menu_button_style") or data[key].get("menu_button_color"),
                "success" if key in {"tarifs_embed", "valo_embed"} else "primary",
            ) if launcher_enabled else "primary",
            "menu_placeholder": data[key].get("menu_placeholder", "") if menu_enabled else "",
            "component_buttons": component_buttons,
            "menu_config_json": json.dumps(
                data[key].get("menu_categories", []),
                ensure_ascii=False,
            ) if menu_enabled else "[]",
        })
    return render_template_string(PANEL_EMBEDS_TEMPLATE, embeds=embeds)


async def deliver_order_from_panel(order, code):
    channel = bot.get_channel(order["channel_id"])
    if channel is None:
        channel = await bot.fetch_channel(order["channel_id"])
    message = await channel.fetch_message(order["message_id"])
    if not message.embeds:
        raise RuntimeError("Embed Discord introuvable")
    old = message.embeds[0]
    nitro_order = is_nitro_order(order)
    finish_data = load_embed_texts().get("commande_finalisee", DEFAULT_EMBED_DATA["commande_finalisee"])
    rgb = finish_data.get("color_rgb", [46, 204, 113])
    finish_description_raw = finish_data.get("description", [])
    finish_description = "\n".join(finish_description_raw) if isinstance(finish_description_raw, list) else str(finish_description_raw or "")
    if nitro_order:
        finish_description = (
            "Ta commande Discord Nitro a été livrée automatiquement.\n"
            "Ton lien Nitro est envoyé dans un message séparé ci-dessous.\n\n"
            "⚠️ **Un avis est obligatoire après la livraison dans <#1517525842111234088>.**\n"
            "Sans avis, tu seras **banni des commandes** et ta commande sera **révoquée**."
        )
    updated = discord.Embed(
        title=finish_data.get("title", old.title),
        description=finish_description or old.description,
        color=discord.Color.from_rgb(*rgb),
    )
    code_found = False
    for field in old.fields:
        if "code" in field.name.lower():
            if not nitro_order:
                updated.add_field(name=finish_data.get("code_field_name", field.name), value=(chr(96) * 3) + "\n" + code + "\n" + (chr(96) * 3), inline=False)
            code_found = True
        else:
            updated.add_field(name=field.name, value=field.value, inline=field.inline)
    if not code_found and not nitro_order:
        updated.add_field(name=finish_data.get("code_field_name", "Code"), value=(chr(96) * 3) + "\n" + code + "\n" + (chr(96) * 3), inline=False)
    updated.set_footer(text=finish_data.get("footer", "PinkGift — Commande finalisée"))
    await message.edit(embed=updated, view=None)
    if nitro_order:
        await channel.send(
            f"<@{int(order['user_id'])}> voici ton lien Discord Nitro :\n{str(code).strip()}",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )
    await send_order_delivery_ghost_ping(channel, order["user_id"])


def valid_panel_csrf():
    expected = session.get("csrf", "")
    received = request.form.get("csrf", "")
    return bool(expected and secrets.compare_digest(expected, received))


@app.post("/panel/clients/<int:guild_id>/<int:user_id>/deposits/remove")
@panel_required
def panel_remove_client_deposit(guild_id, user_id):
    if not valid_panel_csrf():
        flash("Session invalide. Recharge la page.")
        return redirect(url_for("panel_orders", tab="clients"))
    try:
        amount = Decimal(request.form.get("amount", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        flash("Montant de correction invalide.")
        return redirect(url_for("panel_orders", tab="clients"))
    if not amount.is_finite() or amount <= 0 or amount > Decimal("100000"):
        flash("Le montant doit être compris entre 0,01 € et 100 000 €.")
        return redirect(url_for("panel_orders", tab="clients"))

    try:
        remaining = remove_customer_net_deposit(
            guild_id,
            user_id,
            float(amount),
            0,
        )
    except ValueError as error:
        flash(f"Correction impossible : {error}.")
        return redirect(url_for("panel_orders", tab="clients"))
    except Exception as error:
        print(f"Erreur correction dépôts nets panel pour {user_id}: {error}")
        flash("La correction des dépôts nets a échoué.")
        return redirect(url_for("panel_orders", tab="clients"))
    try:
        sync_customer_roles_from_panel(guild_id, user_id)
        sync_message = " Rôles Discord synchronisés."
    except Exception as error:
        print(f"Erreur synchronisation rôles après correction panel pour {user_id}: {error}")
        sync_message = f" Attention : rôles Discord non synchronisés ({error})."
    flash(
        f"{float(amount):.2f} € retirés des dépôts nets du client {user_id}. "
        f"Reste : {remaining:.2f} €. Le PinkWallet n'a pas été modifié.{sync_message}"
    )
    return redirect(url_for("panel_orders", tab="clients"))


@app.post("/panel/orders/<int:order_id>/refund")
@panel_required
def panel_refund_order(order_id):
    if not valid_panel_csrf():
        flash("Session invalide. Recharge la page.")
        return panel_filter_redirect()
    try:
        order = get_order_record(order_id=order_id)
        if not order or str(order.get("status") or "pending").lower() != "pending":
            raise ValueError("Seule une commande en attente peut être remboursée")
        new_balance = refund_pending_order(order, bot.user.id if bot.user else 0)
        if BOT_LOOP is not None:
            try:
                asyncio.run_coroutine_threadsafe(show_order_refund_on_discord(order, new_balance), BOT_LOOP).result(timeout=25)
            except Exception as discord_error:
                print(f"Erreur mise à jour ticket après remboursement commande #{order_id}: {discord_error}")
        try:
            sync_customer_roles_from_panel(order["guild_id"], order["user_id"])
            sync_message = " Rôles Discord synchronisés."
        except Exception as role_error:
            print(f"Erreur synchronisation rôles après remboursement #{order_id}: {role_error}")
            sync_message = f" Attention : rôles Discord non synchronisés ({role_error})."
        flash(
            f"Commande #{order_id} annulée : {format_price(order.get('paid') or 0)} € "
            f"recrédités au client. La commission de parrainage a été retirée.{sync_message}"
        )
    except Exception as error:
        print(f"Erreur remboursement commande {order_id}: {error}")
        flash(f"Remboursement impossible : {error}")
    return panel_filter_redirect()


@app.post("/panel/orders/<int:order_id>/delete")
@panel_required
def panel_delete_order(order_id):
    if not valid_panel_csrf():
        flash("Session invalide. Recharge la page.")
        return panel_filter_redirect()
    existing_order = get_order_record(order_id=order_id)
    if existing_order and str(existing_order.get("status") or "pending").lower() == "pending":
        flash("Commande en attente : utilise « Rembourser » pour recréditer le client avant de la supprimer.")
        return panel_filter_redirect()
    order = existing_order
    manual_deposit_reversed = False
    try:
        if order is None:
            raise RuntimeError("Commande introuvable")
        manual_deposit_reversed = reverse_manual_sale_deposit(order)
        delete_order_record(order_id)
    except Exception as error:
        if manual_deposit_reversed:
            try:
                apply_manual_sale_deposit(
                    order["guild_id"],
                    order["user_id"],
                    order["paid"],
                    manual_sale_staff_id(order),
                )
            except Exception as rollback_error:
                print(f"ERREUR restauration vente manuelle #{order_id}: {rollback_error}")
        print(f"Erreur suppression commande {order_id}: {error}")
        flash("La suppression a échoué.")
        return panel_filter_redirect()
    try:
        delete_panel_setting(f"order_cost:{int(order['message_id'])}")
    except Exception as error:
        print(f"Erreur nettoyage coût commande {order_id}: {error}")
    try:
        delete_panel_setting(f"order_supplier:{int(order['message_id'])}")
    except Exception as error:
        print(f"Erreur nettoyage fournisseur Nitro {order_id}: {error}")
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
    try:
        sync_customer_roles_from_panel(order["guild_id"], order["user_id"])
        flash("Les rôles Discord du client ont été synchronisés.")
    except Exception as error:
        print(f"Erreur synchronisation rôles après suppression commande #{order_id}: {error}")
        flash(f"Commande supprimée, mais rôles Discord non synchronisés : {error}")
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
            row = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            order = dict(row) if row else None
    if not order or not code or str(order.get("status") or "pending").lower() != "pending":
        flash("Commande ou code invalide.")
        return panel_filter_redirect()
    supplier = normalize_order_supplier(request.form.get("supplier", ""))
    if is_nitro_order(order) and not supplier:
        flash("Le nom du fournisseur est obligatoire pour livrer un Nitro.")
        return panel_filter_redirect()
    if BOT_LOOP is None:
        flash("Le bot Discord n'est pas encore prêt.")
        return panel_filter_redirect()
    try:
        if is_nitro_order(order):
            save_order_supplier(order["message_id"], supplier)
        asyncio.run_coroutine_threadsafe(deliver_order_from_panel(order, code), BOT_LOOP).result(timeout=25)
        if USE_SUPABASE:
            supabase_request("PATCH", f"orders?id=eq.{order_id}", {"code": code, "status": "done", "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
        else:
            with db_connect() as db:
                db.execute("UPDATE orders SET code=?, status='done', updated_at=CURRENT_TIMESTAMP WHERE id=?", (code, order_id))
        supplier_note = f" Fournisseur interne : {supplier}." if is_nitro_order(order) else ""
        flash(f"Commande #{order_id} livrée et embed Discord mis à jour.{supplier_note}")
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


@bot.hybrid_command(name="ghostping", description="Configurer le ghost ping des nouveaux membres")
@discord.app_commands.default_permissions(administrator=True)
@discord.app_commands.describe(
    salon="Salon dans lequel mentionner les nouveaux membres",
    activer="Active ou désactive le ghost ping",
)
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def cmd_ghostping(ctx, salon: discord.TextChannel = None, activer: bool = True):
    setting_key = ghost_ping_setting_key(ctx.guild.id)
    if not activer:
        delete_panel_setting(setting_key)
        await ctx.send("✅ Le ghost ping des nouveaux membres est désactivé.", ephemeral=True)
        return
    if salon is None:
        await ctx.send(
            "❌ Choisis un salon avec `/ghostping salon:#ton-salon activer:Oui`.",
            ephemeral=True,
        )
        return
    bot_member = ctx.guild.me
    permissions = salon.permissions_for(bot_member) if bot_member else None
    if permissions is None or not permissions.view_channel or not permissions.send_messages:
        await ctx.send(
            "❌ Le bot doit pouvoir voir ce salon et y envoyer des messages.",
            ephemeral=True,
        )
        return
    set_panel_setting(setting_key, {
        "channel_id": salon.id,
        "updated_by": ctx.author.id,
        "updated_at": utc_now().isoformat(),
    })
    await ctx.send(
        f"✅ Chaque nouveau membre sera ghost ping dans {salon.mention}. "
        "La mention sera supprimée automatiquement après une seconde.",
        ephemeral=True,
    )


@bot.hybrid_command(name="antiraid", description="Configurer la protection contre les raids")
@discord.app_commands.default_permissions(administrator=True)
@discord.app_commands.describe(
    activer="Active ou désactive la protection anti-raid",
    seuil="Nombre d'arrivées déclenchant la protection (3 à 50)",
    fenetre="Durée de détection en secondes (3 à 60)",
    duree="Durée du mode raid en minutes (1 à 120)",
    salon_logs="Salon recevant les alertes anti-raid",
)
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def cmd_antiraid(
    ctx,
    activer: bool = True,
    seuil: int = 6,
    fenetre: int = 10,
    duree: int = 10,
    salon_logs: discord.TextChannel = None,
):
    config = get_anti_raid_config(ctx.guild.id)
    if not activer:
        config["enabled"] = False
        config["active_until"] = 0
        config["updated_by"] = ctx.author.id
        save_anti_raid_config(ctx.guild.id, config)
        ANTI_RAID_RECENT_JOINS.pop(ctx.guild.id, None)
        await ctx.send("✅ La protection anti-raid est désactivée.", ephemeral=True)
        return
    if not 3 <= seuil <= 50:
        await ctx.send("❌ Le seuil doit être compris entre 3 et 50 arrivées.", ephemeral=True)
        return
    if not 3 <= fenetre <= 60:
        await ctx.send("❌ La fenêtre doit être comprise entre 3 et 60 secondes.", ephemeral=True)
        return
    if not 1 <= duree <= 120:
        await ctx.send("❌ La durée doit être comprise entre 1 et 120 minutes.", ephemeral=True)
        return
    bot_member = ctx.guild.me
    if bot_member is None or not bot_member.guild_permissions.kick_members:
        await ctx.send(
            "❌ Le bot doit avoir la permission **Expulser des membres** pour activer l’anti-raid.",
            ephemeral=True,
        )
        return
    log_channel = salon_logs or ctx.guild.get_channel(int(config.get("log_channel_id") or 0)) or ctx.channel
    log_permissions = log_channel.permissions_for(bot_member) if isinstance(log_channel, discord.TextChannel) else None
    if log_permissions is None or not log_permissions.view_channel or not log_permissions.send_messages:
        await ctx.send(
            "❌ Le bot doit pouvoir voir le salon de logs et y envoyer des messages.",
            ephemeral=True,
        )
        return
    config.update({
        "enabled": True,
        "threshold": seuil,
        "window_seconds": fenetre,
        "raid_duration_minutes": duree,
        "log_channel_id": log_channel.id,
        "updated_by": ctx.author.id,
    })
    save_anti_raid_config(ctx.guild.id, config)
    ANTI_RAID_RECENT_JOINS.pop(ctx.guild.id, None)
    await ctx.send(
        f"✅ Anti-raid activé : **{seuil} arrivées en {fenetre} secondes** déclencheront "
        f"une protection de **{duree} minutes**. Alertes dans {log_channel.mention}.\n"
        "Les comptes de la vague et les nouvelles arrivées seront expulsés, jamais bannis.",
        ephemeral=True,
    )


@bot.hybrid_command(name="antiraid_statut", description="Afficher l'état de la protection anti-raid")
@discord.app_commands.default_permissions(administrator=True)
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def cmd_antiraid_statut(ctx):
    config = get_anti_raid_config(ctx.guild.id)
    now = time.time()
    if not config["enabled"]:
        state = "⛔ Désactivée"
    elif config["active_until"] > now:
        state = f"🚨 Mode raid actif jusqu’à <t:{int(config['active_until'])}:R>"
    else:
        state = "✅ Active — surveillance en cours"
    embed = discord.Embed(
        title="🛡️ Protection anti-raid",
        description=state,
        color=discord.Color.red() if config["active_until"] > now else discord.Color.green(),
        timestamp=utc_now(),
    )
    embed.add_field(
        name="Déclenchement",
        value=f"**{config['threshold']}** arrivées en **{config['window_seconds']} secondes**",
        inline=False,
    )
    embed.add_field(name="Durée du mode raid", value=f"**{config['raid_duration_minutes']} minutes**", inline=True)
    embed.add_field(name="Comptes bloqués", value=f"**{config['blocked_count']}**", inline=True)
    embed.add_field(name="Salon d’alertes", value=f"<#{config['log_channel_id']}>", inline=False)
    await ctx.send(embed=embed, ephemeral=True)


@bot.hybrid_command(name="antiraid_stop", description="Arrêter immédiatement le mode raid automatique")
@discord.app_commands.default_permissions(administrator=True)
@commands.guild_only()
@commands.has_permissions(administrator=True)
async def cmd_antiraid_stop(ctx):
    config = get_anti_raid_config(ctx.guild.id)
    config["active_until"] = 0
    config["updated_by"] = ctx.author.id
    save_anti_raid_config(ctx.guild.id, config)
    ANTI_RAID_RECENT_JOINS.pop(ctx.guild.id, None)
    await ctx.send(
        "✅ Le mode raid est arrêté. La détection automatique reste active.",
        ephemeral=True,
    )


@bot.hybrid_command(name="giveaway", aliases=["gw"], description="Créer un giveaway avec bouton de participation")
@discord.app_commands.default_permissions(manage_messages=True)
@discord.app_commands.describe(
    duration="Durée, par exemple 30m, 2h ou 1d",
    nom="Nom du giveaway",
    invitations="Nouvelles invitations actives à obtenir pendant le giveaway",
    chances_invitations="Donner une chance supplémentaire par invitation valide",
    tag_serveur="Exiger que le membre affiche le tag de ce serveur",
    nombre_gagnants="Nombre de gagnants à tirer",
    image_url="Lien direct d'une image optionnelle",
)
@commands.guild_only()
@commands.has_role(STAFF_ROLE_ID)
async def cmd_giveaway(
    ctx,
    duration: str,
    nom: str,
    invitations: int = 0,
    chances_invitations: bool = False,
    tag_serveur: bool = False,
    nombre_gagnants: int = 1,
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
    if nombre_gagnants < 1 or nombre_gagnants > 25:
        await ctx.send("❌ Le nombre de gagnants doit être compris entre 1 et 25.", ephemeral=True)
        return
    if tag_serveur and not hasattr(discord.Member, "primary_guild"):
        await ctx.send("❌ La vérification du tag serveur nécessite discord.py 2.6 ou plus récent.", ephemeral=True)
        return
    image_url = (image_url or "").strip()
    if not image_url and getattr(ctx, "message", None) and ctx.message.attachments:
        image_url = ctx.message.attachments[0].url
    end_ts = int(time.time()) + seconds
    giveaway_started_at = utc_now()
    embed = build_giveaway_embed(
        nom,
        end_ts,
        0,
        image_url,
        min_invites=invitations,
        require_server_tag=tag_serveur,
        winner_count=nombre_gagnants,
        weighted_by_invites=chances_invitations,
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
        "min_invite_account_age_days": MIN_INVITE_ACCOUNT_AGE_DAYS,
        "require_server_tag": tag_serveur,
        "weighted_by_invites": chances_invitations,
        "winner_count": nombre_gagnants,
        "participants": [],
        "ended": False,
        "created_at": giveaway_started_at.isoformat(),
        "invite_requirement_started_ts": giveaway_started_at.timestamp(),
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
    eligible_participants, rejected, participant_weights = await eligible_giveaway_participants(ctx.guild, data)
    if not eligible_participants:
        await ctx.send(
            "❌ Impossible de reroll : aucun participant ne remplit encore toutes les conditions.",
            ephemeral=True,
        )
        return

    winner_history = normalize_giveaway_participants(data.get("winner_history", []))
    current_winner_ids = normalize_giveaway_participants(data.get("winner_ids", []))
    current_winner_id = data.get("winner_id")
    if current_winner_id is not None:
        try:
            current_winner_id = int(current_winner_id)
        except (TypeError, ValueError):
            current_winner_id = None
    if current_winner_id and current_winner_id not in winner_history:
        winner_history.append(current_winner_id)
    if current_winner_id and current_winner_id not in current_winner_ids:
        current_winner_ids.append(current_winner_id)

    winner_count = max(1, int(data.get("winner_count", 1) or 1))
    winner_ids = select_giveaway_winners(
        eligible_participants,
        winner_count,
        winner_history,
        current_winner_ids,
        participant_weights,
    )
    winner_text = ", ".join(f"<@{winner_id}>" for winner_id in winner_ids)
    data["winner_id"] = winner_ids[0]
    data["winner_ids"] = winner_ids
    data["winner_history"] = normalize_giveaway_participants([*winner_history, *winner_ids])
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
            f"Nouveau(x) gagnant(s) : {winner_text}{excluded_text}"
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


@bot.hybrid_command(name="parrainages", description="Publier la présentation du programme de parrainage")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_parrainages(ctx):
    await ctx.send(
        embed=build_json_embed("parrainages_embed"),
        view=ReferralApplicationView(),
    )


@bot.hybrid_command(name="recrutement", description="Publier le panneau de recrutement PinkGift")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_recrutement(ctx):
    await ctx.send(
        embed=build_json_embed("recrutement_embed"),
        view=RecruitmentApplicationView(),
    )


@bot.hybrid_command(name="privilèges", aliases=["privileges"], description="Publier les privilèges PinkGift")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_privileges(ctx):
    await ctx.send(embed=build_json_embed("privileges_embed"), view=PrivilegesLauncherView())


@bot.hybrid_command(name="teams", description="Publier la présentation de l’équipe PinkGift")
@discord.app_commands.default_permissions(manage_messages=True)
@commands.has_role(STAFF_ROLE_ID)
async def cmd_teams(ctx):
    await ctx.send(embed=build_json_embed("team_embed"))


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
                bot.clear()
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


# Gunicorn importe `bot:app` sans exécuter le bloc __main__. Le thread Discord
# doit donc démarrer dès l'import du module, sans attendre une visite du site.
start_discord_background()


if __name__ == "__main__":
    run_web()
