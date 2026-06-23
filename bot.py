import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import re
from flask import Flask
from threading import Thread

# ✅ CONFIGURATION FLASK (Keep-Alive pour l'hébergement continu)
app = Flask('')

@app.route('/')
def home():
    return "PinkSoftware est en ligne et opérationnel !"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ✅ INITIALISATION DU BOT ET INTENTS
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Indispensable pour l'événement on_member_join
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command('help')

# ✅ CONFIGURATION DES ÉMOJIS ET RÔLES
PAYPAL_EMOJI = "<:paypal:1517582845315649751>" 

STAFF_ROLE_ID = 1517487833886228550
PURGE_ROLE_ID = 1517495087825817691
NEW_MEMBER_ROLE_ID = 1517580901356277921

# Catégorie spécifique pour les Valorant Points
VALO_CATEGORY_ID = 1517488399106183188

PRODUCT_CONFIG = {
    "AMAZON": {"emoji": "📦", "emoji_ch": "📦", "rates": {60: "75~120€", 180: "225~310€", 420: "525~730€", 600: "750~1200€"}},
    "CARREFOUR": {"emoji": "🛒", "emoji_ch": "🛒", "rates": {120: "150~200€", 300: "375~500€", 600: "750~1000€", 900: "1125~1500€"}},
    "INTERMARCHE": {"emoji": "🏬", "emoji_ch": "🏬", "rates": {60: "75~100€", 180: "225~300€", 360: "450~600€", 600: "750~1000€"}},
    "ZARA": {"emoji": "👕", "emoji_ch": "👕", "rates": {35: "45~60€", 90: "112~150€", 180: "225~300€", 360: "450~600€"}},
    "SEPHORA": {"emoji": "💄", "emoji_ch": "💄", "rates": {30: "38~50€", 60: "75~100€", 120: "150~200€", 240: "300~400€"}},
    "XB/PL": {"emoji": "🎮", "emoji_ch": "🎮", "rates": {}},
    "UBEREATS": {"emoji": "🍔", "emoji_ch": "🍔", "rates": {20: "28~42€", 65: "85~115€", 130: "165~225€", 400: "501~680€"}}
}

def load_embed_texts():
    """Charge les textes de l'embed depuis un fichier JSON de manière ultra-sécurisée."""
    default_texts = {
        "tarifs_embed": {
            "title": "[CARTE CADEAUX]",
            "description": ["**⚠️ Tarifs non configurés dans le fichier config_embeds.json**"],
            "color_rgb": [255, 192, 203]
        },
        "ticket_bienvenue": {
            "title": "🎫 Ticket d'achat — {product}",
            "description": ["**⚠️ Message de bienvenue non configuré.**"],
            "color_rgb": [255, 192, 203]
        }
    }

    try:
        # Calcul du chemin d'accès absolu pour éviter les erreurs "File not found" des hébergeurs
        script_dir = os.path.dirname(os.path.abspath(__file__))
        json_path = os.path.join(script_dir, "config_embeds.json")
        print(f"[PinkSoftware] Lecture du fichier JSON à : {json_path}")

        with open(json_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Nettoyage automatique des petites erreurs de syntaxe (virgules en trop à la fin)
        content = re.sub(r',\s*}', '}', content)
        content = re.sub(r',\s*]', ']', content)

        data = json.loads(content)
        return data
    except FileNotFoundError:
        print("[PinkSoftware] ❌ ERREUR : Le fichier config_embeds.json est introuvable. Chargement des données par défaut.")
        return default_texts
    except json.JSONDecodeError as e:
        print(f"[PinkSoftware] ❌ ERREUR DE SYNTAXE JSON à la ligne {e.lineno}, colonne {e.colno} : {e.msg}")
        return default_texts
    except Exception as e:
        print(f"[PinkSoftware] ❌ ERREUR INCONNUE JSON : {e}")
        return default_texts

ORDER_FILE = "order_count.txt"

def get_next_order_number():
    """Génère le prochain numéro de commande CC-XXXX"""
    if not os.path.exists(ORDER_FILE):
        with open(ORDER_FILE, "w") as f:
            f.write("0")
    
    with open(ORDER_FILE, "r") as f:
        current = int(f.read().strip())
    
    next_num = current + 1
    
    with open(ORDER_FILE, "w") as f:
        f.write(str(next_num))
        
    return str(next_num).zfill(4)

class CloseTicketView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="Fermer le ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="btn_close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Autoriser uniquement le créateur ou le Staff
        if interaction.user.id != self.user_id and STAFF_ROLE_ID not in [role.id for role in interaction.user.roles]:
            await interaction.response.send_message("❌ Vous n'avez pas la permission de fermer ce ticket.", ephemeral=True)
            return
        
        await interaction.response.send_message("🔒 Fermeture du ticket dans 5 secondes...")
        import asyncio
        await asyncio.sleep(5)
        await interaction.channel.delete()

class ProductSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="AMAZON", emoji="📦", description="Cartes Amazon"),
            discord.SelectOption(label="CARREFOUR", emoji="🛒", description="Cartes Carrefour"),
            discord.SelectOption(label="INTERMARCHE", emoji="🏬", description="Cartes Intermarché"),
            discord.SelectOption(label="ZARA", emoji="👕", description="Cartes Zara"),
            discord.SelectOption(label="SEPHORA", emoji="💄", description="Cartes Sephora"),
            discord.SelectOption(label="XB/PL", emoji="🎮", description="Cartes Xbox/PlayStation"),
            discord.SelectOption(label="UBEREATS", emoji="🍔", description="Cartes UberEats"),
        ]
        super().__init__(placeholder="Choisissez votre produit PinkGift...", min_values=1, max_values=1, options=options, custom_id="select_product")

    async def callback(self, interaction: discord.Interaction):
        selected_product = self.values[0]
        guild = interaction.guild
        user = interaction.user

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }

        # Création du channel privé ticket
        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{user.name}",
            overwrites=overwrites,
            reason="Ouverture ticket PinkGift"
        )

        texts = load_embed_texts()["ticket_bienvenue"]
        title_formatted = texts["title"].format(product=selected_product)
        
        # Formatage dynamique de la description gérant tableaux ou chaînes
        desc_lines = texts.get("description", [])
        desc_string = "\n".join(desc_lines) if isinstance(desc_lines, list) else desc_lines
        desc_formatted = desc_string.format(user=user.mention, product=selected_product)
        
        color_config = texts.get("color_rgb", [255, 192, 203])

        embed_ticket = discord.Embed(
            title=title_formatted,
            description=desc_formatted,
            color=discord.Color.from_rgb(*color_config)
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

class ValoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Acheter mes VP", style=discord.ButtonStyle.success, emoji="🛒", custom_id="btn_buy_valo")
    async def buy_valo(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }

        category = guild.get_channel(VALO_CATEGORY_ID)
        if category is None:
            await interaction.response.send_message("❌ Erreur : Catégorie Valorant introuvable. Vérifiez l'ID.", ephemeral=True)
            return

        # Création du ticket valorant
        ticket_channel = await guild.create_text_channel(
            name=f"ticket-valo-{user.name}",
            category=category,
            overwrites=overwrites,
            reason="Ouverture ticket Valorant PinkGift"
        )

        texts = load_embed_texts()["ticket_bienvenue"]
        title_formatted = texts["title"].format(product="VALORANT POINTS")
        
        desc_lines = texts.get("description", [])
        desc_string = "\n".join(desc_lines) if isinstance(desc_lines, list) else desc_lines
        desc_formatted = desc_string.format(user=user.mention, product="VALORANT POINTS")

        embed_ticket = discord.Embed(
            title=title_formatted,
            description=desc_formatted,
            color=discord.Color.from_rgb(255, 192, 203)
        )
        embed_ticket.set_image(
            url="https://media.discordapp.net/attachments/1517516946390908949/1517517071217332424/Ticket_cree.png?ex=6a369167&is=6a353fe7&hm=ce29c76d8a92020dd78c32b4ef8c7a7a41338df78ecf9455f930b9c0dcb1bd08&=&format=webp&quality=lossless"
        )
        await ticket_channel.send(content=f"{user.mention} | <@&{STAFF_ROLE_ID}>", embed=embed_ticket, view=CloseTicketView(user.id))
        await interaction.response.send_message(f"✅ Ton ticket Valorant a été créé ici : {ticket_channel.mention}", ephemeral=True)

@bot.event
async def on_ready():
    print(f"[PinkSoftware] Connecté en tant que {bot.user} !")
    try:
        synced = await bot.tree.sync()
        print(f"[PinkSoftware] {len(synced)} commandes slash synchronisées.")
    except Exception as e:
        print(f"[PinkSoftware] Erreur de synchronisation des commandes : {e}")
    
    # Enregistrer les boutons interactifs persistants
    bot.add_view(ProductView())
    bot.add_view(ValoView())

@bot.event
async def on_member_join(member):
    print(f"[PinkSoftware] Nouveau membre arrivé sur le serveur : {member.name}")
    role = member.guild.get_role(NEW_MEMBER_ROLE_ID)
    
    if role:
        try:
            await member.add_roles(role)
            print(f"[PinkSoftware] Rôle auto {role.name} attribué avec succès à {member.name}.")
        except discord.Forbidden:
            print(f"[PinkSoftware] ❌ ERREUR : Le bot n'a pas les permissions pour donner le rôle à {member.name} (le rôle du bot doit être au-dessus du rôle à donner).")
        except Exception as e:
            print(f"[PinkSoftware] ❌ ERREUR lors de l'attribution du rôle à {member.name} : {e}")
    else:
        print(f"[PinkSoftware] ❌ ERREUR : Impossible de trouver le rôle ID {NEW_MEMBER_ROLE_ID} sur ce serveur.")

@bot.command(name="tarifs")
@commands.has_role(PURGE_ROLE_ID)
async def cmd_tarifs(ctx):
    try: await ctx.message.delete()
    except: pass

    texts = load_embed_texts()["tarifs_embed"]
    
    desc_lines = texts.get("description", [])
    desc_string = "\n".join(desc_lines) if isinstance(desc_lines, list) else desc_lines
    
    color_config = texts.get("color_rgb", [255, 192, 203])

    embed = discord.Embed(
        title=texts["title"],
        description=desc_string,
        color=discord.Color.from_rgb(*color_config)
    )
    embed.set_image(
        url="https://media.discordapp.net/attachments/1517516946390908949/1517517070554890385/Photo_accueil.png?ex=6a369167&is=6a353fe7&hm=07fe98ebafb4108c5c5288ea0d18e1ce113aeebd25d71c4b433033e914d21e44&=&format=webp&quality=lossless"
    )
    await ctx.send(embed=embed, view=ProductView())

@bot.command(name="valo")
@commands.has_role(PURGE_ROLE_ID)
async def cmd_valo(ctx):
    try: await ctx.message.delete()
    except: pass
    
    desc = (
        "| Choisis ton montant et clique sur le bouton pour commander. 💖✨\n\n"
        "🇪🇺 **Europe**\n"
        "♦️ **3650 VP** — `25€`\n"
        "♦️ **5350 VP** — `35€`\n"
        "♦️ **8700 VP** — `45€`\n\n"
        "🇹🇷 **Turquie**\n"
        "♦️ **2925 VP** — `12€`\n"
        "♦️ **4325 VP** — `19€`\n"
        "♦️ **8900 VP** — `35€`\n\n"
        "`[API] GET /v2/inventory`"
    )

    embed = discord.Embed(
        title="💸 [PINKGIFT] VALORANT POINTS 💸",
        description=desc,
        color=discord.Color.from_rgb(255, 192, 203)
    )
    embed.set_image(
        url="https://media.discordapp.net/attachments/1517516946390908949/1517517070554890385/Photo_accueil.png?ex=6a369167&is=6a353fe7&hm=07fe98ebafb4108c5c5288ea0d18e1ce113aeebd25d71c4b433033e914d21e44&=&format=webp&quality=lossless"
    )
    await ctx.send(embed=embed, view=ValoView())

@bot.command(name="purge_all")
@commands.has_role(PURGE_ROLE_ID)
async def cmd_purge_all(ctx):
    await ctx.send("🧹 Début de la suppression de tous les salons tickets et assimilés...")
    count = 0
    for channel in ctx.guild.text_channels:
        if channel.name.startswith("ticket-") or channel.name.startswith("📦-amazon") or channel.name.startswith("🛒-carrefour") or channel.name.startswith("🏬-intermarche") or channel.name.startswith("👕-zara") or channel.name.startswith("💄-sephora") or channel.name.startswith("🎮-xb") or channel.name.startswith("🍔-ubereats"):
            try:
                await channel.delete()
                count += 1
            except discord.Forbidden:
                pass
    
    # Remise à zéro du compteur CC
    if os.path.exists(ORDER_FILE):
        with open(ORDER_FILE, "w") as f:
            f.write("0")
    
    await ctx.author.send(f"✅ Purge PinkSoftware terminée ! {count} salons supprimés et le compteur des numéros de carte est remis à zéro.")

@bot.command(name="clear")
@commands.has_role(PURGE_ROLE_ID)
async def cmd_clear(ctx, amount: int):
    if amount < 1 or amount > 100:
        await ctx.send("❌ Veuillez spécifier un nombre entre 1 et 100.")
        return
    
    await ctx.channel.purge(limit=amount + 1)
    msg = await ctx.send(f"✅ {amount} messages supprimés par le staff PinkSoftware.")
    import asyncio
    await asyncio.sleep(3)
    await msg.delete()

@bot.command(name="commandes")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_directory(ctx):
    try: await ctx.message.delete()
    except: pass

    embed = discord.Embed(
        title="📜 RÉPERTOIRE GLOBAL DES COMMANDES — PinkSoftware",
        description="Voici la liste exhaustive et l'utilité de chaque commande actuellement active sur le bot.",
        color=discord.Color.from_rgb(255, 192, 203)
    )
    embed.add_field(
        name="👑 Administration (Rôle Responsable/Purge requis)",
        value=(
            "`!tarifs` : Génère l'embed des prix classique (avec menu déroulant).\n"
            "`!valo` : Génère l'embed spécial Valorant Points.\n"
            "`!purge_all` : Supprime l'intégralité des salons tickets et remet le compteur à zéro.\n"
            "`!clear <nombre>` : Efface un nombre précis de messages dans le salon actuel."
        ),
        inline=False
    )
    embed.add_field(
        name="🛍️ Gestion de Commandes (En Ticket - Rôle Staff requis)",
        value=(
            "`!amz <prix> <code_carte>` : Valide une commande Amazon.\n"
            "`!crf <prix> <code_carte>` : Valide une commande Carrefour.\n"
            "`!int <prix> <code_carte>` : Valide une commande Intermarché.\n"
            "`!zara <prix> <code_carte>` : Valide une commande Zara.\n"
            "`!seph <prix> <code_carte>` : Valide une commande Sephora.\n"
            "`!xb <prix> <code_carte>` : Valide une commande Xbox/PlayStation.\n"
            "`!uber <prix> <code_carte>` : Valide une commande UberEats."
        ),
        inline=False
    )
    embed.set_footer(text="PinkSoftware — Système Interne")
    await ctx.send(embed=embed)

async def process_order(ctx, product_name, amount_paid, card_code):
    try: await ctx.message.delete()
    except: pass

    cfg = PRODUCT_CONFIG.get(product_name)

    # Calcul spécifique pour XB/PL (prix payé = 70% de la valeur, donc valeur = prix / 0.7)
    if product_name == "XB/PL":
        val_recue = round(amount_paid / 0.7)
        drop_val = f"{val_recue}€"
    else:
        # Chercher le drop correspondant au montant exact
        drop_val = cfg["rates"].get(amount_paid, "Sur-mesure")
        if drop_val == "Sur-mesure":
            # Si le montant n'est pas standard, on l'estime
            drop_val = f"{round(amount_paid * 1.3)}~{round(amount_paid * 1.7)}€"

    # Renommer le channel : 📦-amazon-75-120€
    new_name = f"{cfg['emoji_ch']}-{product_name.lower()}-{drop_val}".replace("~", "-")
    await ctx.channel.edit(name=new_name)

    # Identifier le client (celui qui n'est ni le bot ni la commande de bot)
    client_user = ctx.author
    async for msg in ctx.channel.history(oldest_first=True, limit=5):
        if msg.author != bot.user and not msg.author.bot:
            client_user = msg.author
            break

    cc_num = get_next_order_number()

    # Nettoyage affichage
    clean_name = product_name.replace('UBEREATS', 'Uber Eats')
    
    # SOLUTION BUG F-STRING : Utiliser la concaténation de chaînes simples
    formatted_code = "```\n" + str(card_code) + "\n```"

    embed = discord.Embed(
        title=f"{cfg['emoji']} Commande validée — #CC-{cc_num}",
        description=f"Merci pour votre confiance {client_user.mention} ! Votre commande a été traitée avec succès.",
        color=discord.Color.from_rgb(46, 204, 113)
    )
    embed.add_field(name="🏪 Magasin", value=f"**{clean_name}**", inline=True)
    embed.add_field(name="💵 Prix payé", value=f"`{amount_paid}€`", inline=True)
    embed.add_field(name="🚨 Drop reçu", value=f"**{drop_val}**", inline=True)
    embed.add_field(name="🔑 Carte Cadeau / Code", value=formatted_code, inline=False)
    embed.set_footer(text="PinkSoftware — Livraison Instantanée")

    await ctx.send(content=f"{client_user.mention} Votre carte cadeau **#CC-{cc_num}** est disponible !", embed=embed)

@bot.command(name="amz")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_amz(ctx, amount_paid: int, *, card_code: str):
    await process_order(ctx, "AMAZON", amount_paid, card_code)

@bot.command(name="crf")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_crf(ctx, amount_paid: int, *, card_code: str):
    await process_order(ctx, "CARREFOUR", amount_paid, card_code)

@bot.command(name="int")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_int(ctx, amount_paid: int, *, card_code: str):
    await process_order(ctx, "INTERMARCHE", amount_paid, card_code)

@bot.command(name="zara")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_zara(ctx, amount_paid: int, *, card_code: str):
    await process_order(ctx, "ZARA", amount_paid, card_code)

@bot.command(name="seph")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_seph(ctx, amount_paid: int, *, card_code: str):
    await process_order(ctx, "SEPHORA", amount_paid, card_code)

@bot.command(name="xb")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_xb(ctx, amount_paid: int, *, card_code: str):
    await process_order(ctx, "XB/PL", amount_paid, card_code)

@bot.command(name="uber")
@commands.has_role(STAFF_ROLE_ID)
async def cmd_uber(ctx, amount_paid: int, *, card_code: str):
    await process_order(ctx, "UBEREATS", amount_paid, card_code)

if __name__ == "__main__":
    # Lancement du serveur Keep-Alive
    keep_alive()
    
    # Lancement du bot Discord
    # NOTE: Assure-toi que ton token est défini dans les variables d'environnement (Secret/Env Vars de ton hébergeur)
    token = os.getenv("DISCORD_TOKEN")
    
    if token:
        bot.run(token)
    else:
        print("[PinkSoftware] ❌ ERREUR CRITIQUE : Token introuvable. Mets ton token Discord directement ici ou configure la variable DISCORD_TOKEN.")
        # bot.run("TON_TOKEN_ICI") # Si tu veux coller ton token en clair (déconseillé sur les hébergeurs publics)
