import discord
from discord.ext import commands
from flask import Flask
from threading import Thread
import os

# =========================================================
# 🌐 CONFIGURATION SERVEUR WEB (Pour l'hébergement gratuit)
# =========================================================
app = Flask('')

@app.route('/')
def home():
    return "PinkySoftware est en ligne !"

def run_web():
    # Render attribue un port dynamiquement via la variable d'environnement PORT
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# Lance le serveur Flask dans un thread séparé pour ne pas bloquer le bot Discord
Thread(target=run_web).start()


# =========================================================
# 🤖 CONFIGURATION DU BOT DISCORD (PinkySoftware)
# =========================================================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ✅ Ton identifiant de catégorie a été configuré ici :
CATEGORY_TICKET_ID = 1418873021615308850  

# Définition du menu déroulant interactif
class ProductSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="AMAZON", description="Gift Card", emoji="📦"),
            discord.SelectOption(label="CARREFOUR", description="Gift Card", emoji="🛒"),
            discord.SelectOption(label="INTERMARCHE", description="Gift Card", emoji="🏬"),
            discord.SelectOption(label="ZARA", description="Gift Card", emoji="👕"),
            discord.SelectOption(label="SEPHORA", description="Gift Card", emoji="💄"),
            discord.SelectOption(label="XB/PL", description="Gift Card", emoji="🎮"),
            discord.SelectOption(label="UBEREATS", description="Gift Card", emoji="🍔"),
        ]
        super().__init__(placeholder="Je veux me régaler avec PinkGift", min_values=1, max_values=1, options=options)

    # Action quand un client choisit un produit
    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        product_chosen = self.values[0]

        # Permissions : seul l'acheteur, le bot et les admins voient le ticket
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)
        }

        # Récupération de la catégorie configurée
        category = guild.get_channel(CATEGORY_TICKET_ID)

        if category is None:
            await interaction.response.send_message(
                "❌ Erreur : La catégorie des tickets est introuvable. Contacte un administrateur.", 
                ephemeral=True
            )
            return

        # Création du salon de ticket privé
        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{user.name}",
            category=category,
            overwrites=overwrites,
            reason=f"Ouverture ticket PinkGift pour {product_chosen}"
        )

        # Message de bienvenue à l'intérieur du ticket
        embed_ticket = discord.Embed(
            title=f"🎫 Ticket d'achat — {product_chosen}",
            description=(
                f"Bonjour {user.mention} !\n\n"
                f"Merci de l'intérêt que tu portes à **PinkGift**.\n"
                f"Tu as sélectionné le produit : **{product_chosen}**.\n\n"
                "Le staff de **PinkySoftware** a été prévenu et va te prendre en charge rapidement. "
                "En attendant, tu peux préciser le montant souhaité ainsi que ton moyen de paiement."
            ),
            color=discord.Color.from_rgb(255, 192, 203)
        )
        
        await ticket_channel.send(content=f"{user.mention} | @here", embed=embed_ticket)

        # Confirmation invisible pour le client
        await interaction.response.send_message(
            f"✅ Ton ticket pour **{product_chosen}** a été créé ici : {ticket_channel.mention}", 
            ephemeral=True
        )

class ProductView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProductSelect())

@bot.event
async def on_ready():
    print(f"Le bot PinkySoftware est en ligne et prêt à l'emploi !")

@bot.command(name="tarifs")
async def send_tarifs(ctx):
    embed = discord.Embed(
        title="[CARTE CADEAUX]",
        description=(
            "**📦 AMAZON** `-72h`\n"
            "*60€* -> **75~120€**\n"
            "*180€* -> **225~310€**\n"
            "*420€* -> **525~730€**\n"
            "*600€* -> **750~1200€**\n"
            "⁠—\n"
            "**🛒 CARREFOUR** `-72h`\n"
            "*120€* -> **150~200€**\n"
            "*300€* -> **375~500€**\n"
            "*600€* -> **750~1000€**\n"
            "*900€* -> **1125~1500€**\n"
            "⁠—\n"
            "**🏬 INTERMARCHE** `-72h`\n"
            "*60€* -> **75~100€**\n"
            "*180€* -> **225~300€**\n"
            "*360€* -> **450~600€**\n"
            "*600€* -> **750~1000€**\n"
            "⁠—\n"
            "**👕 ZARA** `-48h`\n"
            "*35€* -> **45~60€**\n"
            "*90€* -> **112~150€**\n"
            "*180€* -> **225~300€**\n"
            "*360€* -> **450~600€**\n"
            "⁠—\n"
            "**💄 SEPHORA** `-48h`\n"
            "*30€* -> **38~50€**\n"
            "*60€* -> **75~100€**\n"
            "*120€* -> **150~200€**\n"
            "*240€* -> **300~400€**\n"
            "⁠—\n"
            "**🎮 XB/PL** `-24h`\n"
            "*All* -> **-30%**\n"
            "⁠—\n"
            "**🍔 UBEREATS** `-2h`\n"
            "*20€* -> **28~42€**\n"
            "*65€* -> **85~115€**\n"
            "*130€* -> **165~225€**\n"
            "*400€* -> **501~680€**\n"
            "⁠—\n"
            "└  __**Livraison automatique.**__"
        ),
        color=discord.Color.from_rgb(255, 192, 203)
    )
    
    # Remplis ces liens plus tard si tu veux ajouter des images
    # embed.set_thumbnail(url="LIEN_DE_TON_LOGO")
    # embed.set_image(url="LIEN_DE_TON_GIF")
    
    # Envoi de l'embed combiné avec le menu déroulant
    await ctx.send(embed=embed, view=ProductView())

# Récupération sécurisée du token via les variables d'environnement de Render
token_discord = os.environ.get("TOKEN")
bot.run(token_discord)
