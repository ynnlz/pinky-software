import discord
from discord.ext import commands
from flask import Flask
from threading import Thread
import os
import json
import asyncio

# =========================================================
# 🌐 SERVEUR WEB
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
# 🤖 CONFIGURATION
# =========================================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

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

def load_embed_texts():
    filename = "config_embeds.json"
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"tarifs_embed": {"title": "Tarifs", "description": "Non configuré", "color_rgb": [255, 192, 203]}}

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

class ProductSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=k, description="Gift Card", emoji=v["emoji"]) for k, v in PRODUCT_CONFIG.items()]
        super().__init__(placeholder="Choisis ton magasin", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"Ticket en création pour {self.values[0]}...", ephemeral=True)

class ProductView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProductSelect())

# =========================================================
# 📜 COMMANDES
# =========================================================
@bot.command(name="tarifs")
@commands.has_role(PURGE_ROLE_ID)
async def send_tarifs(ctx):
    texts = load_embed_texts()["tarifs_embed"]
    rgb = texts.get("color_rgb", [255, 192, 203])
    embed = discord.Embed(
        title=texts["title"],
        description=texts["description"],
        color=discord.Color.from_rgb(rgb[0], rgb[1], rgb[2])
    )
    await ctx.send(embed=embed, view=ProductView())

@bot.command(name="commandes")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_directory(ctx):
    embed = discord.Embed(
        title="📜 RÉPERTOIRE GLOBAL DES COMMANDES — PinkySoftware", 
        description="Voici la liste exhaustive et l'utilité de chaque commande actuellement active sur le bot.",
        color=discord.Color.from_rgb(255, 192, 203)
    )
    embed.add_field(
        name="👑 Administration (Rôle Responsable requis)", 
        value="`!tarifs` : Génère l'embed des prix avec le menu déroulant d'ouverture de ticket.\n`!purge_all` : Supprime l'intégralité des salons tickets et remet le compteur à zéro.\n`!clear <nombre>` : Efface un nombre précis de messages dans le salon actuel (Ex: !clear 20).", 
        inline=False
    )
    embed.add_field(
        name="🛡️ Modération (Rôle Staff requis)", 
        value="`!ban <@membre> <raison>` : Bannit définitivement un utilisateur.\n`!tempban <@membre> <durée> <raison>` : Bannit temporairement (ex: 10m, 2h, 5d).\n`!tempmute <@membre> <durée> <raison>` : Mute temporairement un utilisateur via timeout Discord.\n`!commandes` : Affiche ce répertoire d'aide complet.", 
        inline=False
    )
    embed.add_field(
        name="📦 Traitement des Commandes (Rôle Staff requis)", 
        value="Syntaxe globale : `!<nom_commande> <montant_payé>`\nPermet de valider un achat, calcule le drop, renomme le salon et crée l'embed vert.\nCommandes : `!amazon`, `!carrefour`, `!intermarche`, `!zara`, `!sephora`, `!xbox`, `!ubereats`", 
        inline=False
    )
    await ctx.send(embed=embed)

# =========================================================
# 🛠️ TRAITEMENT
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

    client_user = ctx.author
    async for msg in ctx.channel.history(oldest_first=True, limit=5):
        if msg.author != bot.user and not msg.author.bot:
            client_user = msg.author
            break

    cc_num = get_next_order_number()
    formatted_code = "```\n" + str(card_code) + "\n```"
    is_pending = (card_code == "En attente...")
    status_text = "Votre commande est en cours de traitement." if is_pending else "Votre commande a été traitée avec succès."
    embed_color = discord.Color.from_rgb(255, 165, 0) if is_pending else discord.Color.from_rgb(46, 204, 113)

    embed = discord.Embed(title=f"{cfg['emoji']} Commande #CC-{cc_num}", description=status_text, color=embed_color)
    embed.add_field(name="Client", value=client_user.mention, inline=True)
    embed.add_field(name="Magasin", value=product_name, inline=True)
    embed.add_field(name="Montant Payé", value=f"`{amount_paid}€`", inline=True)
    embed.add_field(name="Drop Approximatif", value=f"**{drop_val}**", inline=True)
    embed.add_field(name="Code Carte Cadeau", value=formatted_code, inline=False)
    await ctx.send(content=f"{client_user.mention} Voici votre récapitulatif.", embed=embed)

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

bot.run(os.environ.get("TOKEN"))
