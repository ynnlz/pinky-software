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
    return {"ticket_bienvenue": {"title": "🎫 Ticket — {product}", "description": "Bonjour {user} !"}}

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
# 🎫 GESTION DES TICKETS
# =========================================================
class ProductSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=k, description="Gift Card", emoji=v["emoji"]) for k, v in PRODUCT_CONFIG.items()]
        super().__init__(placeholder="Choisis ton magasin", min_values=1, max_values=1, options=options)
    
    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        product = self.values[0]
        cfg = PRODUCT_CONFIG.get(product)
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }
        
        category = guild.get_channel(cfg["cat"])
        channel = await guild.create_text_channel(name=f"ticket-{user.name}", category=category, overwrites=overwrites)
        
        texts = load_embed_texts()["ticket_bienvenue"]
        embed = discord.Embed(title=texts["title"].format(product=product), description=texts["description"].format(user=user.mention), color=discord.Color.from_rgb(255, 192, 203))
        await channel.send(content=f"{user.mention} | <@&{STAFF_ROLE_ID}>", embed=embed)
        await interaction.response.send_message(f"✅ Ticket créé : {channel.mention}", ephemeral=True)

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
    embed = discord.Embed(title="[CARTE CADEAUX]", description="Utilise le menu ci-dessous.", color=discord.Color.from_rgb(255, 192, 203))
    await ctx.send(embed=embed, view=ProductView())

@bot.command(name="commandes")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_directory(ctx):
    embed = discord.Embed(title="📜 RÉPERTOIRE GLOBAL DES COMMANDES", color=discord.Color.from_rgb(255, 192, 203))
    embed.add_field(name="👑 Administration", value="`!tarifs`, `!purge_all`, `!clear <nombre>`", inline=False)
    embed.add_field(name="🛡️ Modération", value="`!ban`, `!tempban`, `!tempmute`, `!commandes`", inline=False)
    embed.add_field(name="📦 Traitement", value="Syntaxe : `!<magasin> <montant>`\nCommandes : `!amazon`, `!carrefour`, `!intermarche`, `!zara`, `!sephora`, `!xbox`, `!ubereats`", inline=False)
    await ctx.send(embed=embed)

# =========================================================
# 🛠️ TRAITEMENT
# =========================================================
async def process_order(ctx, product_name, amount_paid, card_code):
    try: await ctx.message.delete()
    except: pass
    cfg = PRODUCT_CONFIG.get(product_name)
    val_recue = round(amount_paid / 0.7) if product_name == "XB/PL" else cfg["rates"].get(amount_paid, "Sur-mesure")
    
    cc_num = get_next_order_number()
    is_pending = (card_code == "En attente...")
    status_text = "Votre commande est en cours de traitement." if is_pending else "Votre commande a été traitée avec succès."
    embed_color = discord.Color.from_rgb(255, 165, 0) if is_pending else discord.Color.from_rgb(46, 204, 113)

    embed = discord.Embed(title=f"{cfg['emoji']} Commande #CC-{cc_num}", description=status_text, color=embed_color)
    embed.add_field(name="Client", value=ctx.author.mention, inline=True)
    embed.add_field(name="Magasin", value=product_name, inline=True)
    embed.add_field(name="Montant Payé", value=f"`{amount_paid}€`", inline=True)
    embed.add_field(name="Code", value=f"```\n{card_code}\n```", inline=False)
    await ctx.send(content=f"{ctx.author.mention} Voici votre récapitulatif.", embed=embed)

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
