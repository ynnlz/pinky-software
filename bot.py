import discord
from discord.ext import commands
from flask import Flask
from threading import Thread
import os
import json
import asyncio
import datetime
import re

#app = Flask('')
@app.route('/')
def home():
    return "PinkSoftware est en ligne !"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

Thread(target=run_web).start()

#intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

PAYPAL_EMOJI = "<:paypal:1517582845315649751>" 
STAFF_ROLE_ID = 1517487833886228550
PURGE_ROLE_ID = 1517495087825817691
NEW_MEMBER_ROLE_ID = 1517580901356277921
VALO_CATEGORY_ID = 1517488399106183188

PRODUCT_CONFIG = {
    "AMAZON": {"cat": 1517488377744593057, "emoji": "📦", "emoji_ch": "📦", "rates": {60: "75~120€", 180: "225~310€", 420: "525~730€", 600: "750~1200€"}},
    "CARREFOUR": {"cat": 1517488444769833011, "emoji": "🛒", "emoji_ch": "🛒", "rates": {120: "150~200€", 300: "375~500€", 600: "750~1000€", 900: "1125~1500€"}},
    "INTERMARCHE": {"cat": 1517488466600919153, "emoji": "🏬", "emoji_ch": "🏬", "rates": {60: "75~100€", 180: "225~300€", 360: "450~600€", 600: "750~1000€"}},
    "ZARA": {"cat": 1517488486783910008, "emoji": "👕", "emoji_ch": "👕", "rates": {35: "45~60€", 90: "112~150€", 180: "225~300€", 360: "450~600€"}},
    "SEPHORA": {"cat": 1517488524180455484, "emoji": "💄", "emoji_ch": "💄", "rates": {30: "38~50€", 60: "75~100€", 120: "150~200€", 240: "300~400€"}},
    "XB/PL": {"cat": 1517488548964466819, "emoji": "🎮", "emoji_ch": "🎮", "rates": {}}, 
    "UBEREATS": {"cat": 1517488572083470386, "emoji": "🍔", "emoji_ch": "🍽️", "rates": {20: "28~42€", 65: "85~115€", 130: "165~225€", 400: "501~680€"}}
}

DEFAULT_EMBED_DATA = {
    "tarifs_embed": {"title": "[CARTE CADEAUX]", "description": ["📦 AMAZON -72h", "60€ -> 75~120€", "└ Livraison automatique."], "color_rgb": [255, 192, 203]},
    "ticket_bienvenue": {"title": "🎫 Ticket d'achat — {product}", "description": ["Bonjour {user} !", "", "Merci de l'intérêt que tu portes à PinkGift.", "Tu as sélectionné le produit : {product}.", "⚠️ Les seuls moyens de paiement acceptés sont PayPal."], "color_rgb": [255, 192, 203]}
}

#def load_embed_texts():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    filename = os.path.join(base_dir, "config_embeds.json")
    if not os.path.exists(filename): return DEFAULT_EMBED_DATA
    try:
        with open(filename, "r", encoding="utf-8") as f: return json.load(f)
    except: return DEFAULT_EMBED_DATA

def get_next_order_number():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    filename = os.path.join(base_dir, "order_count.json")
    count = 1
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f: count = json.load(f).get("count", 0) + 1
        except: count = 1
    with open(filename, "w") as f: json.dump({"count": count}, f)
    return count

def reset_order_counter():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    filename = os.path.join(base_dir, "order_count.json")
    with open(filename, "w") as f: json.dump({"count": 0}, f)

def parse_duration(duration_str: str):
    match = re.match(r"(\d+)([mhds])?", duration_str.lower())
    if not match: return None
    amount, unit = int(match.group(1)), match.group(2) or "m"
    multipliers = {"m": 60, "h": 3600, "d": 86400, "s": 1}
    return amount * multipliers.get(unit, 60)

#class CloseTicketView(discord.ui.View):
    def __init__(self, client_id: int):
        super().__init__(timeout=None)
        self.client_id = client_id

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="btn_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.edit(name=f"closed-{interaction.channel.name}")
        await interaction.response.send_message("🔒 Ticket fermé.", ephemeral=False)

class ProductSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=k, description="Gift Card", emoji=v["emoji"]) for k, v in PRODUCT_CONFIG.items()]
        super().__init__(placeholder="Choisis ton produit", options=options, custom_id="prod_select")
    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        category = guild.get_channel(PRODUCT_CONFIG[self.values[0]]["cat"])
        ticket = await guild.create_text_channel(name=f"ticket-{interaction.user.name}", category=category)
        await ticket.send(f"{interaction.user.mention} Bienvenue, un staff va arriver.", view=CloseTicketView(interaction.user.id))
        await interaction.response.send_message(f"Ticket ouvert : {ticket.mention}", ephemeral=True)

class ProductView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProductSelect())

class ValoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="🛒 Acheter mes VP", style=discord.ButtonStyle.success, custom_id="btn_buy_valo")
    async def buy_valo(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        category = guild.get_channel(VALO_CATEGORY_ID)
        ticket = await guild.create_text_channel(name=f"ticket-valo-{interaction.user.name}", category=category)
        await ticket.send(f"{interaction.user.mention} Bienvenue, un staff va arriver pour tes VP.", view=CloseTicketView(interaction.user.id))
        await interaction.response.send_message(f"Ticket créé : {ticket.mention}", ephemeral=True)

#@bot.event
async def on_ready():
    bot.add_view(ProductView())
    bot.add_view(ValoView())
    print("Bot en ligne et vues enregistrées !")

@bot.event
async def on_member_join(member):
    role = member.guild.get_role(NEW_MEMBER_ROLE_ID)
    if role: await member.add_roles(role)

#@bot.command(name="tarifs")
@commands.has_role(PURGE_ROLE_ID)
async def cmd_tarifs(ctx):
    await ctx.send("Voici nos tarifs :", view=ProductView())

@bot.command(name="valo")
@commands.has_role(PURGE_ROLE_ID)
async def cmd_valo(ctx):
    desc = (
        "🇪🇺 **Europe**\n"
        "♦️ **3650 VP** — `28€`\n"
        "♦️ **5350 VP** — `39€`\n"
        "♦️ **8700 VP** — `52€`\n\n"
        "🇹🇷 **Turquie**\n"
        "♦️ **2925 VP** — `14€`\n"
        "♦️ **4325 VP** — `22€`\n"
        "♦️ **8900 VP** — `39€`\n\n"
        "`[API] GET /v2/inventory`"
    )
    embed = discord.Embed(title="💸 [API_K4x] VALORANT POINTS 💸", description=desc, color=0xFFC0CB)
    await ctx.send(embed=embed, view=ValoView())

@bot.command(name="ban")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_ban(ctx, member: discord.Member, *, reason: str = "Aucune raison"):
    await member.ban(reason=reason)
    await ctx.send(f"🔨 {member.name} banni.")

@bot.command(name="clear")
@commands.has_role(PURGE_ROLE_ID)
async def cmd_clear(ctx, amount: int):
    await ctx.channel.purge(limit=amount + 1)

@bot.command(name="tempban")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_tempban(ctx, member: discord.Member, duration: str, *, reason: str = "Aucune raison"):
    seconds = parse_duration(duration)
    await member.ban(reason=reason)
    await ctx.send(f"⏳ Banni {duration}.")
    await asyncio.sleep(seconds)
    await ctx.guild.unban(member)

@bot.command(name="tempmute")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_tempmute(ctx, member: discord.Member, duration: str, *, reason: str = "Aucune raison"):
    seconds = parse_duration(duration)
    await member.timeout(datetime.timedelta(seconds=seconds), reason=reason)
    await ctx.send(f"🔇 Mute {duration}.")

@bot.command(name="paypal")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_paypal(ctx):
    await ctx.send("⚠️ Paiement exclusivement via PayPal.")

#async def process_order(ctx, product_name, amount_paid, card_code):
    cfg = PRODUCT_CONFIG.get(product_name)
    drop_val = cfg["rates"].get(amount_paid, "Sur-mesure")
    new_name = f"{cfg['emoji_ch']}-{product_name.lower()}-{drop_val}".replace("~", "-")
    await ctx.channel.edit(name=new_name)
    cc_num = get_next_order_number()
    embed = discord.Embed(title=f"{cfg['emoji']} Commande #CC-{cc_num}", description="Commande validée", color=0x2ECC71)
    embed.add_field(name="Code", value=f"```\n{card_code}\n```")
    await ctx.send(embed=embed)

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

@bot.command(name="finish")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_finish(ctx, *, code_carte: str):
    # Logique de finalisation
    await ctx.send(f"✅ Commande finalisée : `{code_carte}`")

#token = os.environ.get("TOKEN")
bot.run(token)
