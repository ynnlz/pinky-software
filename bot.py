import discord
from discord.ext import commands
from flask import Flask
from threading import Thread
import os
import json

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

bot = commands.Bot(command_prefix="!", intents=intents)

# ✅ ID du rôle Staff requis pour les commandes
STAFF_ROLE_ID = 1517487833886228550

PRODUCT_CONFIG = {
    "AMAZON": {"cat": 1517488377744593057, "emoji": "📦", "emoji_ch": "📦", "rates": {60: "75~120€", 180: "225~310€", 420: "525~730€", 600: "750~1200€"}},
    "CARREFOUR": {"cat": 1517488444769833011, "emoji": "🛒", "emoji_ch": "🛒", "rates": {120: "150~200€", 300: "375~500€", 600: "750~1000€", 900: "1125~1500€"}},
    "INTERMARCHE": {"cat": 1517488466600919153, "emoji": "🏬", "emoji_ch": "🏬", "rates": {60: "75~100€", 180: "225~300€", 360: "450~600€", 600: "750~1000€"}},
    "ZARA": {"cat": 1517488486783910008, "emoji": "👕", "emoji_ch": "👕", "rates": {35: "45~60€", 90: "112~150€", 180: "225~300€", 360: "450~600€"}},
    "SEPHORA": {"cat": 1517488524180455484, "emoji": "💄", "emoji_ch": "💄", "rates": {30: "38~50€", 60: "75~100€", 120: "150~200€", 240: "300~400€"}},
    "XB/PL": {"cat": 1517488548964466819, "emoji": "🎮", "emoji_ch": "🎮", "rates": {}}, 
    "UBEREATS": {"cat": 1517488572083470386, "emoji": "🍔", "emoji_ch": "🍽️", "rates": {20: "28~42€", 65: "85~115€", 130: "165~225€", 400: "501~680€"}}
}

# 🔢 Gestion du compteur de commandes persistant
def get_next_order_number():
    filename = "order_count.json"
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                data = json.load(f)
                count = data.get("count", 0) + 1
        except:
            count = 1
    else:
        count = 1
    
    with open(filename, "w") as f:
        json.dump({"count": count}, f)
    return count

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

        # ✅ Embed d'ouverture modifié avec l'instruction PayPal obligatoire
        embed_ticket = discord.Embed(
            title=f"🎫 Ticket d'achat — {product_chosen}",
            description=(
                f"Bonjour {user.mention} !\n\n"
                f"Merci de l'intérêt que tu portes à **PinkGift**.\n"
                f"Tu as sélectionné le produit : **{product_chosen}**.\n\n"
                f"Le <@&{STAFF_ROLE_ID}> a été prévenu et va te prendre en charge rapidement.\n"
                f"En attendant, tu peux préciser le montant souhaité.\n\n"
                f"⚠️ **Les seuls moyens de paiement acceptés sont PayPal.**"
            ),
            color=discord.Color.from_rgb(255, 192, 203)
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

@bot.command(name="tarifs")
async def send_tarifs(ctx):
    embed = discord.Embed(
        title="[CARTE CADEAUX]",
        description=(
            "**📦 AMAZON** `-72h`\n*60€* -> **75~120€**\n*180€* -> **225~310€**\n*420€* -> **525~730€**\n*600€* -> **750~1200€**\n⁠—\n"
            "**🛒 CARREFOUR** `-72h`\n*120€* -> **150~200€**\n*300€* -> **375~500€**\n*600€* -> **750~1000€**\n*900€* -> **1125~1500€**\n⁠—\n"
            "**🏬 INTERMARCHE** `-72h`\n*60€* -> **75~100€**\n*180€* -> **225~300€**\n*360€* -> **450~600€**\n*600€* -> **750~1000€**\n⁠—\n"
            "**👕 ZARA** `-48h`\n*35€* -> **45~60€**\n*90€* -> **112~150€**\n*180€* -> **225~300€**\n*360€* -> **450~600€**\n⁠—\n"
            "**💄 SEPHORA** `-48h`\n*30€* -> **38~50€**\n*60€* -> **75~100€**\n*120€* -> **150~200€**\n*240€* -> **300~400€**\n⁠—\n"
            "**🎮 XB/PL** `-24h`\n*All* -> **-30%**\n⁠—\n"
            "**🍔 UBEREATS** `-2h`\n*20€* -> **28~42€**\n*65€* -> **85~115€**\n*130€* -> **165~225€**\n*400€* -> **501~680€**\n⁠—\n"
            "└  __**Livraison automatique.**__"
        ),
        color=discord.Color.from_rgb(255, 192, 203)
    )
    await ctx.send(embed=embed, view=ProductView())

# =========================================================
# 🛠️ FONCTION DE TRAITEMENT UNIQUE
# =========================================================
async def process_order(ctx, product_name, amount_paid):
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

    cc_num = get_next_order_number()
    clean_name = product_name.replace('UBEREATS', 'Uber Eats')

    embed_desc = f"{client_user.mention}\n"
    embed_desc += f"💵 **Payé : {amount_paid}€**\n"
    embed_desc += f"🚨 **Drop : {drop_val}**"

    embed = discord.Embed(
        title=f"{cfg['emoji']} #CC-{cc_num} - {clean_name}",
        description=embed_desc,
        color=discord.Color.from_rgb(46, 204, 113)
    )
    
    await ctx.send(content=f"{client_user.mention} Votre carte cadeau **#CC-{cc_num}** est en cours de traitement.", embed=embed)

# =========================================================
# 📜 RÉPERTOIRE DES COMMANDES (STAFF UNIQUEMENT)
# =========================================================
@bot.command(name="commandes")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_directory(ctx):
    embed = discord.Embed(
        title="📜 Répertoire des Commandes de Traitement",
        description=(
            "Ces commandes permettent de valider les commandes et de renommer automatiquement les salons de tickets.\n\n"
            "**Syntaxe :** `!<nom_de_la_commande> <montant_payé>`\n\n"
            "📦 **`!amazon <montant>`** : Traite une commande Amazon\n"
            "🛒 **`!carrefour <montant>`** : Traite une commande Carrefour\n"
            "🏬 **`!intermarche <montant>`** : Traite une commande Intermarché\n"
            "👕 **`!zara <montant>`** : Traite une commande Zara\n"
            "💄 **`!sephora <montant>`** : Traite une commande Sephora\n"
            "🎮 **`!xbox <montant>`** : Traite une commande Xbox / PSN\n"
            "🍔 **`!ubereats <montant>`** : Traite une commande Uber Eats\n\n"
            "ℹ️ *Note : Le numéro #CC s'incrémente tout seul à chaque commande passée.*"
        ),
        color=discord.Color.from_rgb(52, 152, 219)
    )
    await ctx.send(embed=embed)

# =========================================================
# 🔒 COMMANDES DE TRAITEMENT PROTÉGÉES PAR RÔLE
# =========================================================
@bot.command(name="amazon")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_amazon(ctx, amount: int):
    await process_order(ctx, "AMAZON", amount)

@bot.command(name="carrefour")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_carrefour(ctx, amount: int):
    await process_order(ctx, "CARREFOUR", amount)

@bot.command(name="intermarche")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_intermarche(ctx, amount: int):
    await process_order(ctx, "INTERMARCHE", amount)

@bot.command(name="zara")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_zara(ctx, amount: int):
    await process_order(ctx, "ZARA", amount)

@bot.command(name="sephora")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_sephora(ctx, amount: int):
    await process_order(ctx, "SEPHORA", amount)

@bot.command(name="xbox")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_xbox(ctx, amount: int):
    await process_order(ctx, "XB/PL", amount)

@bot.command(name="ubereats")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_ubereats(ctx, amount: int):
    await process_order(ctx, "UBEREATS", amount)

# =========================================================
# ⚠️ GESTION DES ERREURS DE PERMISSION
# =========================================================
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        try:
            await ctx.message.delete()
        except:
            pass
        await ctx.send(f"❌ {ctx.author.mention}, tu n'as pas la permission d'utiliser cette commande (Rôle Staff requis).", delete_after=5)

token_discord = os.environ.get("TOKEN")
bot.run(token_discord)
