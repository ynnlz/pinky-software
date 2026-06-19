import discord
from discord.ext import commands
from flask import Flask
from threading import Thread
import os
import json
import asyncio

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

# =========================================================
# 🛠️ FONCTION DE TRAITEMENT (MISE À JOUR)
# =========================================================
async def process_order(ctx, product_name, amount_paid, card_code):
    try: await ctx.message.delete()
    except: pass

    cfg = PRODUCT_CONFIG.get(product_name)
    
    # Calcul du drop
    if product_name == "XB/PL":
        val_recue = round(amount_paid / 0.7)
        drop_val = f"{val_recue}€"
    else:
        drop_val = cfg["rates"].get(amount_paid, "Sur-mesure")
        if drop_val == "Sur-mesure":
            drop_val = f"{round(amount_paid * 1.3)}~{round(amount_paid * 1.7)}€"

    # Récupération du client
    client_user = ctx.author
    async for msg in ctx.channel.history(oldest_first=True, limit=5):
        if msg.author != bot.user and not msg.author.bot:
            client_user = msg.author
            break

    cc_num = get_next_order_number()
    formatted_code = "```\n" + str(card_code) + "\n```"

    # Définition des états
    is_pending = (card_code == "En attente...")
    status_text = "Votre commande est en cours de traitement." if is_pending else "Votre commande a été traitée avec succès."
    embed_color = discord.Color.from_rgb(255, 165, 0) if is_pending else discord.Color.from_rgb(46, 204, 113)

    embed = discord.Embed(
        title=f"{cfg['emoji']} Commande #CC-{cc_num}",
        description=status_text,
        color=embed_color
    )
    embed.add_field(name="Client", value=client_user.mention, inline=True)
    embed.add_field(name="Magasin", value=product_name, inline=True)
    embed.add_field(name="Montant Payé", value=f"`{amount_paid}€`", inline=True)
    embed.add_field(name="Drop Approximatif", value=f"**{drop_val}**", inline=True)
    embed.add_field(name="Code Carte Cadeau", value=formatted_code, inline=False)
    embed.set_footer(text="PinkySoftware")

    await ctx.send(content=f"{client_user.mention} Voici le récapitulatif de votre commande.", embed=embed)

# Commandes
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

token_discord = os.environ.get("TOKEN")
bot.run(token_discord)
