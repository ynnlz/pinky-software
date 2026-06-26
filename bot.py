import discord
from discord.ext import commands
from flask import Flask
from threading import Thread
import os
import json
import asyncio
import datetime
import re

app = Flask('')

@app.route('/')
def home():
    return "67 j aime le TastyCrousty"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

Thread(target=run_web).start()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

PAYPAL_EMOJI = "<:paypal:1517582845315649751>"
STAFF_ROLE_ID = 1517487833886228550
PURGE_ROLE_ID = 1517495087825817691
NEW_MEMBER_ROLE_ID = 1517580901356277921
TICKET_CATEGORY_ID = 1519898899047776336
TICKET_IMAGE_URL = "https://media.discordapp.net/attachments/1517516946390908949/1517517071217332424/Ticket_cree.png?ex=6a369167&is=6a353fe7&hm=ce29c76d8a92020dd78c32b4ef8c7a7a41338df78ecf9455f930b9c0dcb1bd08&=&format=webp&quality=lossless"
TARIFS_THUMBNAIL_URL = "https://media.discordapp.net/attachments/1517516946390908949/1517517070894502108/Produits.png?ex=6a369167&is=6a353fe7&hm=06c63f7fb8cca01a4b847fd53b228c2442a158c7fe04c5f61c858a015c517c24&=&format=webp&quality=lossless"
TARIFS_IMAGE_URL = "https://media.discordapp.net/attachments/1517516946390908949/1517517070554890385/Photo_accueil.png?ex=6a369167&is=6a353fe7&hm=07fe98ebafb4108c5c5288ea0d18e1ce113aeebd25d71c4b433033e914d21e44&=&format=webp&quality=lossless"
ORDER_PENDING_IMAGE_URL = "https://media.discordapp.net/attachments/1517516946390908949/1517517069657309204/Commande_recu.png?ex=6a369167&is=6a353fe7&hm=5a401706a47f8c7571510f5112ea122b3061eca7382f31d077c7bdbe7c690d9a&=&format=webp&quality=lossless"
ORDER_FINISHED_IMAGE_URL = "https://media.discordapp.net/attachments/1517516946390908949/1517517069061456102/commande_fini.png?ex=6a369167&is=6a353fe7&hm=e736d0cec28bfc2192e4f360738654e7b4e446adb36b81d33273845a462ce4b8&=&format=webp&quality=lossless"

PRODUCT_CONFIG = {
    "AMAZON": {"display": "AMAZON", "emoji": "<:amazon:1519907450403160104>", "emoji_ch": "<:amazon:1519907450403160104>"},
    "CARREFOUR": {"display": "CARREFOUR", "emoji": "<:carrefour:1519906825494073414>", "emoji_ch": "<:carrefour:1519906825494073414>"},
    "INTERMARCHE": {"display": "INTERMARCHE", "emoji": "<:intermarche:1519907100057276546>", "emoji_ch": "<:intermarche:1519907100057276546>"},
    "ZARA": {"display": "ZARA", "emoji": "<:zara:1519907265681948773>", "emoji_ch": "<:zara:1519907265681948773>"},
    "SEPHORA": {"display": "SEPHORA", "emoji": "<:sephora:1519907492862103742>", "emoji_ch": "<:sephora:1519907492862103742>"},
    "UBEREATS": {"display": "UBER EATS", "emoji": "<:ubereats:1519907186636099604>", "emoji_ch": "<:ubereats:1519907186636099604>"},
    "APPLE": {"display": "APPLE", "emoji": "<:apple:1519906800411869204>", "emoji_ch": "<:apple:1519906800411869204>"},
    "GOOGLE_PLAY": {"display": "GOOGLE PLAY", "emoji": "<:googleplay:1519907060555186278>", "emoji_ch": "<:googleplay:1519907060555186278>"},
    "STEAM": {"display": "STEAM", "emoji": "<:steam:1519907154545610873>", "emoji_ch": "<:steam:1519907154545610873>"},
    "NETFLIX": {"display": "NETFLIX", "emoji": "<:netflix:1519907125160316928>", "emoji_ch": "<:netflix:1519907125160316928>"},
    "SMYTHS_TOYS": {"display": "SMYTHS TOYS", "emoji": "<:smythstoys:1519907368429944832>", "emoji_ch": "<:smythstoys:1519907368429944832>"},
    "ZALANDO": {"display": "ZALANDO", "emoji": "<:zalando:1519907231812816906>", "emoji_ch": "<:zalando:1519907231812816906>"},
    "KING_JOUET": {"display": "KING JOUET", "emoji": "<:kingjouet:1519907322783338557>", "emoji_ch": "<:kingjouet:1519907322783338557>"},
    "LEGO": {"display": "LEGO", "emoji": "<:lego:1519907470854852720>", "emoji_ch": "<:lego:1519907470854852720>"},
    "ADIDAS": {"display": "ADIDAS", "emoji": "<:adidas:1519906784515588116>", "emoji_ch": "<:adidas:1519906784515588116>"},
    "FOOT_LOCKER": {"display": "FOOT LOCKER", "emoji": "<:footlocker:1519907296342310952>", "emoji_ch": "<:footlocker:1519907296342310952>"},
    "DELIVEROO": {"display": "DELIVEROO", "emoji": "<:deliveroo:1519906860356993174>", "emoji_ch": "<:deliveroo:1519906860356993174>"},
    "CLAUDE": {"display": "CLAUDE", "emoji": "<:claude:1519906842006913065>", "emoji_ch": "<:claude:1519906842006913065>"},
    "AIRBNB": {"display": "AIRBNB", "emoji": "<:airbnb:1519906701900386344>", "emoji_ch": "<:airbnb:1519906701900386344>"},
    "XBOX": {"display": "XBOX", "emoji": "<:xbox:1519907418836828230>", "emoji_ch": "<:xbox:1519907418836828230>"},
    "PLAYSTATION": {"display": "PLAYSTATION", "emoji": "<:playstation:1519906767268741200>", "emoji_ch": "<:playstation:1519906767268741200>"},
    "PAYSAFECARD": {"display": "PAYSAFECARD", "emoji": "<:paysafecard:1519906750571085995>", "emoji_ch": "<:paysafecard:1519906750571085995>"},
    "FNAC": {"display": "FNAC", "emoji": "<:fnac:1519906718140727387>", "emoji_ch": "<:fnac:1519906718140727387>"},
    "NINTENDO": {"display": "NINTENDO", "emoji": "<:nintendo:1519907394157678632>", "emoji_ch": "<:nintendo:1519907394157678632>"},
    "NIKE": {"display": "NIKE", "emoji": "<:nike:1519906735589167164>", "emoji_ch": "<:nike:1519906735589167164>"},
    "VALORANT": {"display": "VALORANT", "emoji": "🎮", "emoji_ch": "🎮"},
}

DEFAULT_EMBED_DATA = {
    "tarifs_embed": {
        "title": "🎟️ COMMANDES PINKGIFT",
        "description": [
            "Choisis une option puis clique sur le bouton pour ouvrir un ticket avec le staff. Toutes les cartes cadeaux à -30%.",
            "",
            "📦 **Amazon**", "🛒 **Carrefour**", "🏬 **Intermarché**", "👕 **Zara**", "💄 **Sephora**",
            "🍔 **Uber Eats**", "🍎 **Apple**", "🎮 **Google Play**", "🎮 **Steam**", "🎬 **Netflix**",
            "🧸 **Smyths Toys**", "👟 **Zalando**", "🧸 **King Jouet**", "🧱 **LEGO**", "👟 **Adidas**",
            "👟 **Foot Locker**", "🍽️ **Deliveroo**", "✨ **Claude**", "🏠 **Airbnb**", "🎮 **Xbox**",
            "🎮 **PlayStation**", "💳 **Paysafecard**", "📚 **Fnac**", "🎮 **Nintendo**", "👟 **Nike**",
            "",
            "🎫 Clique sur le bouton ci-dessous pour creer un ticket prive."
        ],
        "color_rgb": [255, 192, 203]
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

def load_embed_texts():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    possible_paths = [os.path.join(base_dir, "config_embeds.json"), os.path.join(os.getcwd(), "config_embeds.json")]
    env_path = os.environ.get("EMBED_CONFIG_PATH")
    if env_path:
        possible_paths.insert(0, env_path)
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
                print(f"Erreur chargement config_embeds.json : {e}")
    return DEFAULT_EMBED_DATA

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
            await interaction.response.send_message("❌ Tu n as pas la permission de fermer ce ticket.", ephemeral=True)
            return
        if client:
            await channel.set_permissions(client, view_channel=False, send_messages=False, read_message_history=False)
        await interaction.response.send_message("🔒 Ticket ferme : le client n a plus acces a ce salon.")
        try:
            await channel.edit(name=f"closed-{channel.name}")
        except:
            pass

class OpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ouvrir un ticket", emoji="🎫", style=discord.ButtonStyle.success)
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
        embed_ticket.set_image(url=TICKET_IMAGE_URL)
        await ticket_channel.send(content=f"{user.mention} | <@&{STAFF_ROLE_ID}>", embed=embed_ticket, view=CloseTicketView(user.id))
        await interaction.response.send_message(f"✅ Ton ticket a ete cree ici : {ticket_channel.mention}", ephemeral=True)

class ProductView(OpenTicketView):
    pass

@bot.event
async def on_ready():
    print("Le bot PinkSoftware est en ligne et fonctionnel !")

@bot.event
async def on_member_join(member):
    role = member.guild.get_role(NEW_MEMBER_ROLE_ID)
    if role:
        try:
            await member.add_roles(role, reason="Attribution automatique nouveau membre")
        except Exception as e:
            print(f"Erreur attribution role : {e}")

@bot.command(name="tarifs")
@commands.has_role(PURGE_ROLE_ID)
async def send_tarifs(ctx):
    texts = load_embed_texts()["tarifs_embed"]
    rgb = texts.get("color_rgb", [255, 192, 203])
    desc_raw = texts.get("description", [])
    description = "\n".join(desc_raw) if isinstance(desc_raw, list) else str(desc_raw)
    embed = discord.Embed(title=texts.get("title", "🎟️ COMMANDES PINKGIFT"), description=description, color=discord.Color.from_rgb(rgb[0], rgb[1], rgb[2]))
    embed.set_thumbnail(url=TARIFS_THUMBNAIL_URL)
    embed.set_image(url=TARIFS_IMAGE_URL)
    await ctx.send(embed=embed, view=OpenTicketView())

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

@bot.command(name="paiements")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_paiements(ctx):
    try:
        await ctx.message.delete()
    except:
        pass
    embed = discord.Embed(
        title="💳 Moyens de paiement",
        description=(
            "Pour finaliser votre achat chez **PinkGift**, nous acceptons :\n\n"
            f"{PAYPAL_EMOJI} **PayPal**\n"
            "🏦 **Virements bancaires**\n"
            "₿ **Cryptomonnaies**\n\n"
            "Merci d'indiquer le moyen de paiement souhaite dans le ticket."
        ),
        color=discord.Color.from_rgb(255, 192, 203)
    )
    embed.set_footer(text="PinkGift — Paiements")
    await ctx.send(embed=embed)

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
    new_name = f"{emoji}-{display_name}-{amount_paid}€"
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
    embed = discord.Embed(title=f"{emoji} Commande prise en charge", description=f"Merci pour votre confiance {client_user.mention} !", color=discord.Color.from_rgb(46, 204, 113))
    embed.add_field(name="Article", value=f"**{display_name}**", inline=True)
    embed.add_field(name="Montant", value=f"{amount_paid}€", inline=True)
    embed.add_field(name="Payé", value=f"{paid_display}€", inline=True)
    embed.add_field(name="Code", value=f"```\n{card_code}\n```", inline=False)
    embed.set_image(url=ORDER_PENDING_IMAGE_URL)
    embed.set_footer(text="PinkSoftware — Ticket commande")
    await ctx.send(content=f"{client_user.mention} commande enregistree : **{display_name}-{amount_paid}€**", embed=embed)

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
async def cmd_vp(ctx, amount: int, *, code: str = "En attente..."): await process_order(ctx, "VALORANT", amount, code)

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
    new_embed = discord.Embed(title=old_embed.title, description=old_embed.description, color=discord.Color.from_rgb(46, 204, 113))
    code_updated = False
    for field in old_embed.fields:
        if "code" in field.name.lower():
            new_embed.add_field(name=field.name, value=f"```\n{code_carte}\n```", inline=False)
            code_updated = True
        else:
            new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
    if not code_updated:
        new_embed.add_field(name="Code", value=f"```\n{code_carte}\n```", inline=False)
    new_embed.set_image(url=ORDER_FINISHED_IMAGE_URL)
    new_embed.set_footer(text="PinkSoftware — Commande finalisee")
    await embed_message.edit(embed=new_embed)
    await ctx.send("✅ Commande finalisee avec succes.", delete_after=5)

@bot.command(name="commandes")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_directory(ctx):
    embed = discord.Embed(
        title="📜 COMMANDES STAFF — PinkSoftware",
        description="Liste des commandes actuellement actives sur le bot.",
        color=discord.Color.from_rgb(255, 192, 203)
    )
    embed.add_field(
        name="🎫 Tickets",
        value=(
            "!tarifs : envoie l'embed public avec le bouton Ouvrir un ticket.\n"
            "Bouton Ouvrir un ticket : cree un salon prive dans la categorie configuree.\n"
            "Bouton Close : ferme le ticket et retire l'acces au client."
        ),
        inline=False
    )
    embed.add_field(
        name="🛍️ Articles",
        value=(
            "Syntaxe : !article montant\n"
            "Exemple : !deliveroo 60 renomme le ticket en 🍽️-DELIVEROO-60€\n\n"
            "!amazon, !carrefour, !intermarche, !zara, !sephora, !ubereats\n"
            "!apple, !googleplay, !steam, !netflix, !smyths, !zalando\n"
            "!kingjouet, !lego, !adidas, !footlocker, !deliveroo, !claude\n"
            "!airbnb, !xbox, !playstation, !paysafecard, !fnac, !nintendo, !nike, !vp"
        ),
        inline=False
    )
    embed.add_field(
        name="✅ Finalisation",
        value="!finish <code> : remplace ou ajoute le code dans l'embed de commande.",
        inline=False
    )
    embed.add_field(
        name="🛡️ Moderation / Staff",
        value=(
            "!paiements : envoie l'embed des moyens de paiement.\n"
            "!clear <nombre> : supprime des messages.\n"
            "!purge_all : supprime les tickets.\n"
            "!ban, !tempban, !tempmute : moderation staff."
        ),
        inline=False
    )
    await ctx.send(embed=embed)

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

token_discord = os.environ.get("TOKEN")
bot.run(token_discord)
