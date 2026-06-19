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
    return "PinkySoftware est en ligne !"

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

# ✅ ID des rôles
STAFF_ROLE_ID = 1517487833886228550
PURGE_ROLE_ID = 1517495087825817691

PRODUCT_CONFIG = {
    "AMAZON": {"cat": 1517488377744593057, "emoji": "📦", "emoji_ch": "📦", "rates": {60: "75~120€", 180: "225~310€", 420: "525~730€", 600: "750~1200€"}},
    "CARREFOUR": {"cat": 1517488444769833011, "emoji": "🛒", "emoji_ch": "🛒", "rates": {120: "150~200€", 300: "375~500€", 600: "750~1000€", 900: "1125~1500€"}},
    "INTERMARCHE": {"cat": 1517488466600919153, "emoji": "🏬", "emoji_ch": "🏬", "rates": {60: "75~100€", 180: "225~300€", 360: "450~600€", 600: "750~1000€"}},
    "ZARA": {"cat": 1517488486783910008, "emoji": "👕", "emoji_ch": "👕", "rates": {35: "45~60€", 90: "112~150€", 180: "225~300€", 360: "450~600€"}},
    "SEPHORA": {"cat": 1517488524180455484, "emoji": "💄", "emoji_ch": "💄", "rates": {30: "38~50€", 60: "75~100€", 120: "150~200€", 240: "300~400€"}},
    "XB/PL": {"cat": 1517488548964466819, "emoji": "🎮", "emoji_ch": "🎮", "rates": {}}, 
    "UBEREATS": {"cat": 1517488572083470386, "emoji": "🍔", "emoji_ch": "🍽️", "rates": {20: "28~42€", 65: "85~115€", 130: "165~225€", 400: "501~680€"}}
}

# 📁 Outil pour charger la configuration des textes à la volée
def load_embed_texts():
    filename = "config_embeds.json"
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "tarifs_embed": {"title": "[CARTE CADEAUX]", "description": "Tarifs non configurés.", "color_rgb": [255, 192, 203]},
        "ticket_bienvenue": {"title": "🎫 Ticket — {product}", "description": "Bonjour {user} !"}
    }

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
    filename = "order_count.json"
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
    filename = "order_count.json"
    with open(filename, "w") as f: json.dump({"count": 0}, f)

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
        desc_formatted = texts["description"].format(user=user.mention, product=product_chosen)

        embed_ticket = discord.Embed(
            title=title_formatted,
            description=desc_formatted,
            color=discord.Color.from_rgb(255, 192, 203)
        )
        embed_ticket.set_image(
            url="https://media.discordapp.net/attachments/1517516946390908949/1517517071217332424/Ticket_cree.png?ex=6a369167&is=6a353fe7&hm=ce29c76d8a92020dd78c32b4ef8c7a7a41338df78ecf9455f930b9c0dcb1bd08&=&format=webp&quality=lossless"
        )
        await ticket_channel.send(content=f"{user.mention} | <@&{STAFF_ROLE_ID}>", embed=embed_ticket)
        await interaction.response.send_message(f"✅ Ton ticket a été créé ici : {ticket_channel.mention}", ephemeral=True)

class ProductView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProductSelect())

@bot.event
async def on_ready():
    print("Le bot PinkySoftware est en ligne et fonctionnel !")

# =========================================================
# 🔒 COMMANDES ADMINISTRATEUR (RÔLE RESPONSIBLE/PURGE)
# =========================================================
@bot.command(name="tarifs")
@commands.has_role(PURGE_ROLE_ID)
async def send_tarifs(ctx):
    texts = load_embed_texts()["tarifs_embed"]
    rgb = texts["color_rgb"]

    embed = discord.Embed(
        title=texts["title"],
        description=texts["description"],
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
    status_msg = await ctx.send("🔄 **PinkySoftware initialise la purge complète des tickets et commandes...**")
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
# 🛡️ COMMANDES DE MODÉRATION (STAFF)
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

# =========================================================
# 📜 REPERTOIRE GÉNÉRAL DES COMMANDES (MIS À POUR)
# =========================================================
@bot.command(name="commandes")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_directory(ctx):
    embed = discord.Embed(
        title="📜 RÉPERTOIRE GLOBAL DES COMMANDES — PinkySoftware",
        description="Voici la liste exhaustive et l'utilité de chaque commande actuellement active sur le bot.",
        color=discord.Color.from_rgb(255, 192, 203)
    )
    embed.add_field(
        name="👑 Administration (Rôle Responsable/Purge requis)",
        value=(
            "`!tarifs` : Génère l'embed des prix (chargé depuis le JSON) avec le menu déroulant d'ouverture de ticket.\n"
            "`!purge_all` : Supprime l'intégralité des salons tickets et remet le compteur à zéro.\n"
            "`!clear <nombre>` : Efface un nombre précis de messages dans le salon actuel (Ex: `!clear 20`)."
        ),
        inline=False
    )
    embed.add_field(
        name="🛡️ Modération (Rôle Staff requis)",
        value=(
            "`!ban <@membre> <raison>` : Bannit définitivement un utilisateur.\n"
            "`!tempban <@membre> <durée> <raison>` : Bannit temporairement (ex: `10m`, `2h`, `5d`).\n"
            "`!tempmute <@membre> <durée> <raison>` : Mute temporairement un utilisateur via timeout Discord.\n"
            "`!commandes` : Affiche ce répertoire d'aide complet."
        ),
        inline=False
    )
    embed.add_field(
        name="📦 Traitement des Cartes Cadeaux (Rôle Staff requis)",
        value=(
            "**Syntaxe :** `!<nom_du_magasin> <montant> <code_carte_cadeau>`\n"
            "Valide l'achat, renomme automatiquement le salon avec le drop calculé, et envoie l'embed de livraison avec le code au client.\n"
            "👉 `!amazon`, `!carrefour`, `!intermarche`, `!zara`, `!sephora`, `!xbox`, `!ubereats`"
        ),
        inline=False
    )
    await ctx.send(embed=embed)

# =========================================================
# 🛠️ FONCTION DE TRAITEMENT UNIQUE DES CARTES
# =========================================================
async def process_order(ctx, product_name, amount_paid, card_code):
    try: await ctx.message.delete()
    except: pass

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

    cc_num = get_next_order_number()
    clean_name = product_name.replace('UBEREATS', 'Uber Eats')
    
    # Correction définitive : concaténation simple et propre, impossible à faire planter
    formatted_code = f"```\n{card_code}\n```"

    embed = discord.Embed(
        title=f"{cfg['emoji']} Commande validée — #CC-{cc_num}",
        description=f"Merci pour votre confiance {client_user.mention} ! Votre commande a été traitée avec succès.",
        color=discord.Color.from_rgb(46, 204, 113)
    )
    embed.add_field(name="🏪 Magasin", value=f"**{clean_name}**", inline=True)
    embed.add_field(name="💵 Prix payé", value=f"`{amount_paid}€`", inline=True)
    embed.add_field(name="🚨 Drop reçu", value=f"**{drop_val}**", inline=True)
    embed.add_field(name="🔑 Carte Cadeau / Code", value=formatted_code, inline=False)
    embed.set_footer(text="PinkySoftware — Livraison Instantanée")

    await ctx.send(content=f"{client_user.mention} Votre carte cadeau **#CC-{cc_num}** est disponible !", embed=embed)

# Commandes cadeaux
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

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        try: await ctx.message.delete()
        except: pass
        await ctx.send(f"❌ {ctx.author.mention}, tu n'as pas la permission requise.", delete_after=5)

token_discord = os.environ.get("TOKEN")
bot.run(token_discord)
