import discord
from discord.ext import commands
from flask import Flask
from threading import Thread
import os
import json
import asyncio
import datetime
import re

# =========================================================
# 🌐 SERVEUR WEB (Pour éviter que Render coupe le bot)
# =========================================================
app = Flask('')

@app.route('/')
def home():
    return "PinkSoftware est en ligne !"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

Thread(target=run_web).start()


# =========================================================
# 🤖 CONFIGURATION DU BOT DISCORD
# =========================================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ✅ CONFIGURATION DES ÉMOJIS ET RÔLES
PAYPAL_EMOJI = "<:paypal:1517582845315649751>" 

STAFF_ROLE_ID = 1517487833886228550
PURGE_ROLE_ID = 1517495087825817691
NEW_MEMBER_ROLE_ID = 1517580901356277921

PRODUCT_CONFIG = {
    "AMAZON": {"cat": 1517488377744593057, "emoji": "📦", "emoji_ch": "📦", "rates": {60: "75~120€", 180: "225~310€", 420: "525~730€", 600: "750~1200€"}},
    "CARREFOUR": {"cat": 1517488444769833011, "emoji": "🛒", "emoji_ch": "🛒", "rates": {120: "150~200€", 300: "375~500€", 600: "750~1000€", 900: "1125~1500€"}},
    "INTERMARCHE": {"cat": 1517488466600919153, "emoji": "🏬", "emoji_ch": "🏬", "rates": {60: "75~100€", 180: "225~300€", 360: "450~600€", 600: "750~1000€"}},
    "ZARA": {"cat": 1517488486783910008, "emoji": "👕", "emoji_ch": "👕", "rates": {35: "45~60€", 90: "112~150€", 180: "225~300€", 360: "450~600€"}},
    "SEPHORA": {"cat": 1517488524180455484, "emoji": "💄", "emoji_ch": "💄", "rates": {30: "38~50€", 60: "75~100€", 120: "150~200€", 240: "300~400€"}},
    "XB/PL": {"cat": 1517488548964466819, "emoji": "🎮", "emoji_ch": "🎮", "rates": {}}, 
    "UBEREATS": {"cat": 1517488572083470386, "emoji": "🍔", "emoji_ch": "🍽️", "rates": {20: "28~42€", 65: "85~115€", 130: "165~225€", 400: "501~680€"}},
    "VALORANT": {"cat": 1517488399106183188, "emoji": "🎮", "emoji_ch": "🎮", "rates": {22: "3650 VP Europe", 32: "5350 VP Europe / 8900 VP Turquie", 42: "8700 VP Europe", 10: "2925 VP Turquie", 17: "4325 VP Turquie"}}
}

# 📁 Configuration par défaut des embeds
# Elle sert aussi de secours si config_embeds.json est absent sur Render.
DEFAULT_EMBED_DATA = {
    "tarifs_embed": {
        "title": "[CARTE CADEAUX]",
        "description": [
            "📦 AMAZON -72h",
            "60€ -> 75~120€",
            "180€ -> 225~310€",
            "420€ -> 525~730€",
            "600€ -> 750~1200€",
            "⁠—",
            "🛒 CARREFOUR -72h",
            "120€ -> 150~200€",
            "300€ -> 375~500€",
            "600€ -> 750~1000€",
            "900€ -> 1125~1500€",
            "⁠—",
            "🏬 INTERMARCHE -72h",
            "60€ -> 75~100€",
            "180€ -> 225~300€",
            "360€ -> 450~600€",
            "600€ -> 750~1000€",
            "⁠—",
            "👕 ZARA -48h",
            "35€ -> 45~60€",
            "90€ -> 112~150€",
            "180€ -> 225~300€",
            "360€ -> 450~600€",
            "⁠—",
            "💄 SEPHORA -48h",
            "30€ -> 38~50€",
            "60€ -> 75~100€",
            "120€ -> 150~200€",
            "240€ -> 300~400€",
            "⁠—",
            "🎮 XB/PL -24h",
            "All -> -30%",
            "⁠—",
            "🍔 UBEREATS -2h",
            "20€ -> 28~42€",
            "65€ -> 85~115€",
            "130€ -> 165~225€",
            "400€ -> 501~680€",
            "⁠—",
            "└  Livraison automatique."
        ],
        "color_rgb": [
            255,
            192,
            203
        ]
    },
    "valo_embed": {
            "title": "💘 VALORANT POINTS 💘",
            "description": [
                    "Choisis ton montant, paie avec ton solde. 💞",
                    "",
                    "🇪🇺 **Europe**",
                    "💎 **3650 VP** — `24€`",
                    "💎 **5350 VP** — `34€`",
                    "💎 **8700 VP** — `43€`",
                    "",
                    "🇹🇷 **Turquie**",
                    "💎 **2925 VP** — `11€`",
                    "💎 **4325 VP** — `18€`",
                    "💎 **8900 VP** — `33€`",
                    "",
                    "🛒 Clique sur le bouton vert ci-dessous pour ouvrir un ticket."
            ],
            "color_rgb": [
                    255,
                    192,
                    203
            ],
            "image_url": ""
    },
    "ticket_bienvenue": {
        "title": "🎫 Ticket d'achat — {product}",
        "description": [
            "Bonjour {user} !",
            "",
            "Merci de l'intérêt que tu portes à PinkGift.",
            "Tu as sélectionné le produit : {product}.",
            "",
            "Le <@&1517487833886228550> a été prévenu et va te prendre en charge rapidement.",
            "En attendant, tu peux préciser le montant souhaité.",
            "",
            "⚠️ Les seuls moyens de paiement acceptés sont PayPal. <:paypal:1517582845315649751> "
        ],
        "color_rgb": [
            255,
            192,
            203
        ]
    }
}

# 📁 Outil pour charger la configuration des textes à la volée de manière ultra robuste
def load_embed_texts():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # Le bot essaie plusieurs emplacements possibles.
    # Sur Render, le plus important est que config_embeds.json soit dans le même dossier que bot.py.
    possible_paths = []

    env_path = os.environ.get("EMBED_CONFIG_PATH")
    if env_path:
        possible_paths.append(env_path)

    possible_paths.extend([
        os.path.join(base_dir, "config_embeds.json"),
        os.path.join(os.getcwd(), "config_embeds.json"),
    ])

    filename = None
    for path in possible_paths:
        if path and os.path.exists(path):
            filename = path
            break

    # Si le fichier n'existe pas, on le crée automatiquement avec les vrais tarifs
    # au lieu d'afficher "Tarifs non configurés."
    if filename is None:
        filename = os.path.join(base_dir, "config_embeds.json")
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_EMBED_DATA, f, ensure_ascii=False, indent=4)
            print(f"✅ config_embeds.json créé automatiquement ici : {filename}")
        except Exception as e:
            print(f"⚠️ Impossible de créer config_embeds.json : {e}")
        return DEFAULT_EMBED_DATA

    try:
        with open(filename, "r", encoding="utf-8") as f:
            raw_content = f.read()

        # Supprime les virgules traînantes invalides en JSON
        cleaned_content = re.sub(r',\s*([\]}])', r'\1', raw_content)
        data = json.loads(cleaned_content)

        # Fusion robuste : si une clé manque, elle est récupérée depuis DEFAULT_EMBED_DATA
        for main_key, default_value in DEFAULT_EMBED_DATA.items():
            if main_key not in data or not isinstance(data[main_key], dict):
                data[main_key] = default_value
                continue

            for sub_key, sub_default in default_value.items():
                if sub_key not in data[main_key]:
                    data[main_key][sub_key] = sub_default

        print(f"✅ Configuration des embeds chargée depuis : {filename}")
        return data

    except json.JSONDecodeError as decode_err:
        print(f"❌ Erreur de syntaxe JSON dans {filename} : {decode_err}")
        lines = raw_content.splitlines()
        if decode_err.lineno <= len(lines):
            print(f"👉 Ligne contenant l'erreur ({decode_err.lineno}) : {lines[decode_err.lineno - 1]}")
        print("⚠️ Utilisation de la configuration par défaut intégrée au bot.")
        return DEFAULT_EMBED_DATA

    except Exception as e:
        print(f"⚠️ Erreur de chargement JSON : {e}. Utilisation de la configuration par défaut intégrée au bot.")
        return DEFAULT_EMBED_DATA


def parse_duration(duration_str: str):
    match = re.match(r"(\d+)([mhds])?", duration_str.lower())
    if not match: return None
    amount = int(match.group(1))
    unit = match.group(2) or "m"
    if unit == "m": return amount * 60
    if unit == "h": return amount * 3600
    if unit == "d": return amount * 86400
    if unit == "s": return amount
    return None

def get_next_order_number():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    filename = os.path.join(base_dir, "order_count.json")
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                data = json.load(f)
                count = data.get("count", 0) + 1
        except: count = 1
    else: count = 1
    with open(filename, "w") as f: json.dump({"count": count}, f)
    return count

def reset_order_counter():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    filename = os.path.join(base_dir, "order_count.json")
    with open(filename, "w") as f: json.dump({"count": 0}, f)


# =========================================================
# 🔒 SYSTÈME DE FERMETURE DES TICKETS
# =========================================================
class CloseTicketView(discord.ui.View):
    def __init__(self, client_id: int):
        super().__init__(timeout=None)
        self.client_id = client_id

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="🔒")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        channel = interaction.channel
        client = guild.get_member(self.client_id) if guild else None
        staff_role = guild.get_role(STAFF_ROLE_ID) if guild else None

        is_staff = staff_role in interaction.user.roles if hasattr(interaction.user, "roles") and staff_role else False
        is_client = interaction.user.id == self.client_id

        if not is_staff and not is_client:
            await interaction.response.send_message("❌ Tu n'as pas la permission de fermer ce ticket.", ephemeral=True)
            return

        if client:
            await channel.set_permissions(
                client,
                view_channel=False,
                send_messages=False,
                read_message_history=False,
                reason=f"Ticket fermé par {interaction.user}"
            )

        await interaction.response.send_message(
            "🔒 Ticket fermé : le client n'a plus accès à ce salon.",
            ephemeral=False
        )

        try:
            await channel.edit(name=f"closed-{channel.name}")
        except:
            pass


class ProductSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=k, description="Gift Card", emoji=v["emoji"]) for k, v in PRODUCT_CONFIG.items()]
        super().__init__(placeholder="Je veux me régaler avec PinkGift", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        product_chosen = self.values[0]

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }

        cfg = PRODUCT_CONFIG.get(product_chosen)
        category = guild.get_channel(cfg["cat"])
        if category is None:
            await interaction.response.send_message("❌ Erreur : Catégorie introuvable.", ephemeral=True)
            return

        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{user.name}",
            category=category,
            overwrites=overwrites,
            reason=f"Ouverture ticket PinkGift pour {product_chosen}"
        )

        texts = load_embed_texts()["ticket_bienvenue"]
        title_formatted = texts["title"].format(product=product_chosen)
        
        # Reconstitution de la description (liste -> string)
        desc_raw = texts["description"]
        if isinstance(desc_raw, list):
            description_str = "\n".join(desc_raw)
        else:
            description_str = str(desc_raw)
            
        desc_formatted = description_str.format(user=user.mention, product=product_chosen)
        rgb = texts.get("color_rgb", [255, 192, 203])

        embed_ticket = discord.Embed(
            title=title_formatted,
            description=desc_formatted,
            color=discord.Color.from_rgb(rgb[0], rgb[1], rgb[2])
        )
        embed_ticket.set_image(
            url="https://media.discordapp.net/attachments/1517516946390908949/1517517071217332424/Ticket_cree.png?ex=6a369167&is=6a353fe7&hm=ce29c76d8a92020dd78c32b4ef8c7a7a41338df78ecf9455f930b9c0dcb1bd08&=&format=webp&quality=lossless"
        )
        await ticket_channel.send(content=f"{user.mention} | <@&{STAFF_ROLE_ID}>", embed=embed_ticket, view=CloseTicketView(user.id))
        await interaction.response.send_message(f"✅ Ton ticket a été créé ici : {ticket_channel.mention}", ephemeral=True)

class ProductView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProductSelect())


class ValoTicketButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ouvrir un ticket", emoji="🛒", style=discord.ButtonStyle.success)
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user

        if guild is None:
            await interaction.response.send_message("❌ Cette commande doit être utilisée sur un serveur.", ephemeral=True)
            return

        category = guild.get_channel(1517488399106183188)
        if category is None:
            await interaction.response.send_message("❌ Erreur : catégorie Valorant introuvable.", ephemeral=True)
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
            reason=f"Ouverture ticket PinkGift pour Valorant Points par {user}"
        )

        embed_ticket = discord.Embed(
            title="🎫 Ticket d'achat — VALORANT POINTS",
            description=(
                f"Bonjour {user.mention} !\n\n"
                "Merci de l'intérêt que tu portes à PinkGift.\n"
                "Tu as sélectionné le produit : **VALORANT POINTS**.\n\n"
                f"Le <@&{STAFF_ROLE_ID}> a été prévenu et va te prendre en charge rapidement.\n"
                "En attendant, indique le pack VP souhaité.\n\n"
                "⚠️ Les seuls moyens de paiement acceptés sont PayPal."
            ),
            color=discord.Color.from_rgb(255, 192, 203)
        )
        embed_ticket.set_image(
            url="https://media.discordapp.net/attachments/1517516946390908949/1517517071217332424/Ticket_cree.png?ex=6a369167&is=6a353fe7&hm=ce29c76d8a92020dd78c32b4ef8c7a7a41338df78ecf9455f930b9c0dcb1bd08&=&format=webp&quality=lossless"
        )

        await ticket_channel.send(
            content=f"{user.mention} | <@&{STAFF_ROLE_ID}>",
            embed=embed_ticket,
            view=CloseTicketView(user.id)
        )
        await interaction.response.send_message(f"✅ Ton ticket a été créé ici : {ticket_channel.mention}", ephemeral=True)

@bot.event
async def on_ready():
    print("Le bot PinkSoftware est en ligne et fonctionnel !")

@bot.event
async def on_member_join(member):
    """Attribue automatiquement le rôle configuré lors de l'arrivée d'un nouveau membre."""
    guild = member.guild
    role = guild.get_role(NEW_MEMBER_ROLE_ID)
    if role:
        try:
            await member.add_roles(role, reason="Attribution automatique nouveau membre (PinkSoftware)")
            print(f"✅ Rôle attribué avec succès à {member.name}")
        except discord.Forbidden:
            print(f"❌ Erreur de permissions : impossible d'attribuer le rôle à {member.name}")
        except Exception as e:
            print(f"❌ Erreur lors de l'attribution du rôle à {member.name} : {e}")
    else:
        print(f"❌ Erreur : Le rôle ID {NEW_MEMBER_ROLE_ID} n'existe pas sur cette guilde.")


# =========================================================
# 🔒 COMMANDES ADMINISTRATEUR (RÔLE RESPONSIBLE/PURGE)
# =========================================================
@bot.command(name="tarifs")
@commands.has_role(PURGE_ROLE_ID)
async def send_tarifs(ctx):
    texts = load_embed_texts()["tarifs_embed"]
    rgb = texts["color_rgb"]

    # Reconstitution de la description (liste -> string)
    desc_raw = texts["description"]
    if isinstance(desc_raw, list):
        description_str = "\n".join(desc_raw)
    else:
        description_str = str(desc_raw)

    embed = discord.Embed(
        title=texts["title"],
        description=description_str,
        color=discord.Color.from_rgb(rgb[0], rgb[1], rgb[2])
    )
    embed.set_thumbnail(
        url="https://media.discordapp.net/attachments/1517516946390908949/1517517070894502108/Produits.png?ex=6a369167&is=6a353fe7&hm=06c63f7fb8cca01a4b847fd53b228c2442a158c7fe04c5f61c858a015c517c24&=&format=webp&quality=lossless"
    )
    embed.set_image(
        url="https://media.discordapp.net/attachments/1517516946390908949/1517517070554890385/Photo_accueil.png?ex=6a369167&is=6a353fe7&hm=07fe98ebafb4108c5c5288ea0d18e1ce113aeebd25d71c4b433033e914d21e44&=&format=webp&quality=lossless"
    )
    await ctx.send(embed=embed, view=ProductView())

@bot.command(name="purge_all")
@commands.has_role(PURGE_ROLE_ID)
async def cmd_purge_all(ctx):
    status_msg = await ctx.send("🔄 **PinkSoftware initialise la purge complète des tickets et commandes...**")
    order_prefixes = [v["emoji_ch"] for v in PRODUCT_CONFIG.values()]
    deleted_count = 0
    for channel in ctx.guild.text_channels:
        is_ticket = channel.name.startswith("ticket-")
        is_processed_order = any(channel.name.startswith(prefix.lower()) or channel.name.startswith(prefix) for prefix in order_prefixes)
        if is_ticket or is_processed_order:
            try:
                await channel.delete(reason="Purge complète demandée.")
                deleted_count += 1
                await asyncio.sleep(0.5)
            except: pass
    reset_order_counter()
    try: await status_msg.edit(content=f"✅ **Purge terminée avec succès !**\n🗑️ `{deleted_count}` salons supprimés.\n🔢 Compteur réinitialisé à `0`.")
    except: pass

@bot.command(name="clear", aliases=["purge"])
@commands.has_role(PURGE_ROLE_ID)
async def cmd_clear_messages(ctx, amount: int):
    if amount <= 0:
        await ctx.send("❌ Veuillez indiquer un nombre de messages supérieur à 0.", delete_after=3)
        return
    try: await ctx.message.delete()
    except: pass
    deleted = await ctx.channel.purge(limit=amount)
    msg = await ctx.send(f"🗑️ **{len(deleted)}** messages ont été effacés avec succès par l'administration.")
    await asyncio.sleep(4)
    try: await msg.delete()
    except: pass


# =========================================================
# 🛡️ COMMANDES DE MODÉRATION & INFORMATIONS (STAFF)
# =========================================================
@bot.command(name="ban")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_ban(ctx, member: discord.Member, *, reason: str = "Aucune raison fournie"):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 **{member.name}** a été banni définitivement du serveur. (Raison : {reason})")

@bot.command(name="tempban")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_tempban(ctx, member: discord.Member, duration: str, *, reason: str = "Aucune raison fournie"):
    seconds = parse_duration(duration)
    if not seconds:
        await ctx.send("❌ Format de temps invalide. Utilisez par exemple `10m`, `2h`, ou `3d`.")
        return
    await member.ban(reason=f"[Tempban {duration}] {reason}")
    await ctx.send(f"⏳ **{member.name}** a été banni temporairement pour **{duration}**. (Raison : {reason})")
    await asyncio.sleep(seconds)
    try: await ctx.guild.unban(member, reason="Fin du tempban.")
    except: pass

@bot.command(name="tempmute")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_tempmute(ctx, member: discord.Member, duration: str, *, reason: str = "Aucune raison fournie"):
    seconds = parse_duration(duration)
    if not seconds:
        await ctx.send("❌ Format de temps invalide. Utilisez par exemple `10m`, `2h`.")
        return
    td = datetime.timedelta(seconds=seconds)
    await member.timeout(td, reason=reason)
    await ctx.send(f"🔇 **{member.name}** a été réduit au silence pendant **{duration}**. (Raison : {reason})")

# 💳 COMMANDE PAYPAL (STAFF)
@bot.command(name="paypal")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_paypal(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    embed = discord.Embed(
        title="💳 Moyen de Paiement — PayPal",
        description=(
            f"Pour finaliser votre achat chez **PinkSoftware**, veuillez noter la règle suivante :\n\n"
            f"<:paypal:1517582845315649751> **Nous n'acceptons uniquement PayPal comme moyen de paiement.**\n\n"
            "Veuillez préparer votre compte ainsi que votre adresse e-mail de paiement, et la communiquer au staff dans ce ticket."
        ),
        color=discord.Color.from_rgb(255, 192, 203) 
    )
    embed.set_footer(text="PinkGift — Sécurité & Rapidité")
    await ctx.send(embed=embed)


# 🎮 COMMANDE VALORANT POINTS (STAFF)
@bot.command(name="valo")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_valo(ctx):
    try:
        await ctx.message.delete()
    except:
        pass

    texts = load_embed_texts().get("valo_embed", DEFAULT_EMBED_DATA["valo_embed"])
    rgb = texts.get("color_rgb", [255, 192, 203])

    desc_raw = texts.get("description", [])
    if isinstance(desc_raw, list):
        description_str = "\n".join(desc_raw)
    else:
        description_str = str(desc_raw)

    embed = discord.Embed(
        title=texts.get("title", "💘 VALORANT POINTS 💘"),
        description=description_str,
        color=discord.Color.from_rgb(rgb[0], rgb[1], rgb[2])
    )

    image_url = texts.get("image_url", "")
    if image_url:
        embed.set_image(url=image_url)

    embed.set_footer(text="PinkGift — Valorant Points")
    await ctx.send(embed=embed, view=ValoTicketButton())


# =========================================================
# 📜 REPERTOIRE GÉNÉRAL DES COMMANDES (MIS À JOUR)
# =========================================================
@bot.command(name="commandes")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_directory(ctx):
    embed = discord.Embed(
        title="📜 RÉPERTOIRE GLOBAL DES COMMANDES — PinkSoftware",
        description="Voici la liste exhaustive et l'utilité de chaque commande actuellement active sur le bot.",
        color=discord.Color.from_rgb(255, 192, 203)
    )
    embed.add_field(
        name="👑 Administration (Rôle Responsable/Purge requis)",
        value=(
            "`!tarifs` : Génère l'embed des prix (chargé depuis le JSON) avec le menu déroulant d'ouverture de ticket.\n"
            "`!valo` : Envoie l'embed des Valorant Points avec le bouton vert d'ouverture de ticket.\n"
            "`!purge_all` : Supprime l'intégralité des salons tickets et remet le compteur à zéro.\n"
            "`!clear <nombre>` : Efface un nombre précis de messages dans le salon actuel (Ex: `!clear 20`)."
        ),
        inline=False
    )
    embed.add_field(
        name="🛡️ Modération & Informations (Rôle Staff requis)",
        value=(
            f"`!paypal` : Envoie l'embed spécifiant que seul PayPal est accepté {PAYPAL_EMOJI}.\n"
            "`!ban <@membre> <raison>` : Bannit définitivement un utilisateur.\n"
            "`!tempban <@membre> <durée> <raison>` : Bannit temporairement (ex: `10m`, `2h`, `5d`).\n"
            "`!tempmute <@membre> <durée> <raison>` : Mute temporairement un utilisateur via timeout Discord.\n"
            "`!finish <code_carte>` : Finalise la commande en remplaçant `En attente...` par le code de carte et met à jour l'embed.\n"
            "`Bouton Close` : Ferme le ticket et retire l'accès au client.\n"
            "`!commandes` : Affiche ce répertoire d'aide complet."
        ),
        inline=False
    )
    embed.add_field(
        name="📦 Traitement des Cartes Cadeaux / VP (Rôle Staff requis)",
        value=(
            "**Syntaxe prise en charge :** `!<nom_du_magasin> <montant>` ou `!vp <montant>`\n"
            "Crée une commande en attente, renomme automatiquement le salon et affiche l'embed de commande reçue.\n"
            "**Finalisation :** `!finish <code_carte>`\n"
            "Remplace le code `En attente...` par le vrai code carte et finalise l'embed.\n"
            "⚠️ Ces commandes ne doivent être utilisées que dans les salons tickets.\n"
            "👉 `!amazon`, `!carrefour`, `!intermarche`, `!zara`, `!sephora`, `!xbox`, `!ubereats`, `!vp <montant>`"
        ),
        inline=False
    )
    await ctx.send(embed=embed)


# =========================================================
# 🛠️ FONCTION DE TRAITEMENT UNIQUE DES CARTES
# =========================================================
async def process_order(ctx, product_name, amount_paid, card_code):
    try:
        await ctx.message.delete()
    except:
        pass

    cfg = PRODUCT_CONFIG.get(product_name)
    if product_name == "XB/PL":
        val_recue = round(amount_paid / 0.7)
        drop_val = f"{val_recue}€"
    else:
        drop_val = cfg["rates"].get(amount_paid, "Sur-mesure")
        if drop_val == "Sur-mesure":
            drop_val = f"{round(amount_paid * 1.3)}~{round(amount_paid * 1.7)}€"

    new_name = f"{cfg['emoji_ch']}-{product_name.lower()}-{drop_val}".replace("~", "-")
    await ctx.channel.edit(name=new_name)

    client_user = ctx.author
    async for msg in ctx.channel.history(oldest_first=True, limit=5):
        if msg.author != bot.user and not msg.author.bot:
            client_user = msg.author
            break

    clean_name = product_name.replace('UBEREATS', 'Uber Eats')
    formatted_code = f"```\n{card_code}\n```"

    code_fourni = card_code and card_code.strip().lower() not in ["en attente...", "en attente", "attente", "none", "null"]

    embed = discord.Embed(
        title=f"{cfg['emoji']} Commande validée",
        description=f"Merci pour votre confiance {client_user.mention} ! Votre commande a été traitée avec succès.",
        color=discord.Color.from_rgb(46, 204, 113)
    )
    embed.add_field(name="🏪 Magasin", value=f"**{clean_name}**", inline=True)
    embed.add_field(name="💵 Prix payé", value=f"`{amount_paid}€`", inline=True)
    embed.add_field(name="🚨 Drop reçu", value=f"**{drop_val}**", inline=True)
    embed.add_field(name="🔑 Carte Cadeau / Code", value=formatted_code, inline=False)

    if code_fourni:
        embed.set_image(url="https://media.discordapp.net/attachments/1517516946390908949/1517517069061456102/commande_fini.png?ex=6a369167&is=6a353fe7&hm=e736d0cec28bfc2192e4f360738654e7b4e446adb36b81d33273845a462ce4b8&=&format=webp&quality=lossless")
        content = f"{client_user.mention} Votre carte cadeau est disponible !"
    else:
        embed.set_image(url="https://media.discordapp.net/attachments/1517516946390908949/1517517069657309204/Commande_recu.png?ex=6a369167&is=6a353fe7&hm=5a401706a47f8c7571510f5112ea122b3061eca7382f31d077c7bdbe7c690d9a&=&format=webp&quality=lossless")
        content = f"{client_user.mention} Votre commande a bien été prise en charge !"

    embed.set_footer(text="PinkSoftware — Livraison Instantanée")

    await ctx.send(content=content, embed=embed)


# =========================================================
# 🎮 TRAITEMENT VALORANT POINTS
# =========================================================
async def process_vp_order(ctx, amount_paid: int):
    try:
        await ctx.message.delete()
    except:
        pass

    vp_packs = {
        22: "3650 VP Europe",
        32: "5350 VP Europe / 8900 VP Turquie",
        42: "8700 VP Europe",
        10: "2925 VP Turquie",
        17: "4325 VP Turquie"
    }
    pack = vp_packs.get(amount_paid, "Pack personnalisé")

    try:
        await ctx.channel.edit(name=f"🎮-valorant-{amount_paid}e")
    except:
        pass

    client_user = ctx.author
    async for msg in ctx.channel.history(oldest_first=True, limit=8):
        if msg.author != bot.user and not msg.author.bot:
            client_user = msg.author
            break

    embed = discord.Embed(
        title="🎮 Commande validée",
        description=f"Merci pour votre confiance {client_user.mention} ! Votre commande a été traitée avec succès.",
        color=discord.Color.from_rgb(46, 204, 113)
    )
    embed.add_field(name="🎯 Produit", value="**Valorant Points**", inline=True)
    embed.add_field(name="💵 Prix payé", value=f"`{amount_paid}€`", inline=True)
    embed.add_field(name="🚨 Pack VP", value=f"**{pack}**", inline=True)
    embed.add_field(name="🔑 Carte Cadeau / Code", value="```\nEn attente...\n```", inline=False)
    embed.set_image(url="https://media.discordapp.net/attachments/1517516946390908949/1517517069657309204/Commande_recu.png?ex=6a369167&is=6a353fe7&hm=5a401706a47f8c7571510f5112ea122b3061eca7382f31d077c7bdbe7c690d9a&=&format=webp&quality=lossless")
    embed.set_footer(text="PinkSoftware — Livraison Instantanée")

    await ctx.send(content=f"{client_user.mention} Votre commande VP a bien été prise en charge !", embed=embed)


# =========================================================
# 🛍️ COMMANDES DE BOUTIQUE INDIVIDUELLES
# =========================================================
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

@bot.command(name="xbox")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_xbox(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "XB/PL", amount, code)

@bot.command(name="ubereats")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_ubereats(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "UBEREATS", amount, code)

@bot.command(name="vp")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_vp(ctx, amount: int):
    await process_vp_order(ctx, amount)


# =========================================================
# 🏁 COMMANDE DE FINALISATION
# =========================================================
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
            embed = msg.embeds[0]
            if embed.title and "Commande validée" in embed.title:
                embed_message = msg
                break

    if not embed_message:
        await ctx.send("❌ Aucun embed de commande trouvé dans ce salon.", delete_after=5)
        return

    old_embed = embed_message.embeds[0]

    new_description = old_embed.description or ""
    new_description = new_description.replace(
        "Votre commande a été traitée avec succès.",
        "Votre commande est finalisé n'oubliez pas de laissez un avis ! (Sinon vous serez ban des commandes)"
    )

    new_embed = discord.Embed(
        title=old_embed.title,
        description=new_description,
        color=discord.Color.from_rgb(46, 204, 113)
    )

    for field in old_embed.fields:
        if field.name == "🔑 Carte Cadeau / Code":
            new_embed.add_field(
                name="🔑 Carte Cadeau / Code",
                value=f"```\n{code_carte}\n```",
                inline=False
            )
        else:
            new_embed.add_field(
                name=field.name,
                value=field.value,
                inline=field.inline
            )

    new_embed.set_image(url="https://media.discordapp.net/attachments/1517516946390908949/1517517069061456102/commande_fini.png?ex=6a369167&is=6a353fe7&hm=e736d0cec28bfc2192e4f360738654e7b4e446adb36b81d33273845a462ce4b8&=&format=webp&quality=lossless")
    new_embed.set_footer(text="PinkSoftware — Livraison Instantanée")

    await embed_message.edit(embed=new_embed)
    await ctx.send("✅ Commande finalisée avec succès.", delete_after=5)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        try: await ctx.message.delete()
        except: pass
        await ctx.send(f"❌ {ctx.author.mention}, tu n'as pas la permission requise.", delete_after=5)
    else:
        print(f"⚠️ Erreur sur la commande [{ctx.command}] lancée par [{ctx.author}] : {error}")

token_discord = os.environ.get("TOKEN")
bot.run(token_discord)
