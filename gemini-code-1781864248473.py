import discord
from discord.ext import commands

# Configuration des intentions (Intents)
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Le bot est en ligne sous le nom de : {bot.user}")

@bot.command(name="tarifs")
async def send_tarifs(ctx):
    # Création de l'Embed principal
    embed = discord.Embed(
        title="[CARTE CADEAUX]",
        description=(
            "**<:amazon:1234567890> AMAZON** `-72h`\n"
            "*50€* -> **75~120€**\n"
            "*150€* -> **225~310€**\n"
            "*350€* -> **525~730€**\n"
            "*500€* -> **750~1200€**\n"
            "⁠—\n"
            "**<:carrefour:1234567890> CARREFOUR** `-72h`\n"
            "*100€* -> **150~200€**\n"
            "*250€* -> **375~500€**\n"
            "*500€* -> **750~1000€**\n"
            "*750€* -> **1125~1500€**\n"
            "⁠—\n"
            "**<:intermarche:1234567890> INTERMARCHE** `-72h`\n"
            "*50€* -> **75~100€**\n"
            "*150€* -> **225~300€**\n"
            "*300€* -> **450~600€**\n"
            "*500€* -> **750~1000€**\n"
            "⁠—\n"
            "**<:zara:1234567890> ZARA** `-48h`\n"
            "*30€* -> **45~60€**\n"
            "*75€* -> **112~150€**\n"
            "*150€* -> **225~300€**\n"
            "*300€* -> **450~600€**\n"
            "⁠—\n"
            "**<:sephora:1234567890> SEPHORA** `-48h`\n"
            "*25€* -> **38~50€**\n"
            "*50€* -> **75~100€**\n"
            "*100€* -> **150~200€**\n"
            "*200€* -> **300~400€**\n"
            "⁠—\n"
            "**<:xbox:1234567890> XB/PL** `-24h`\n"
            "*All* -> **-40%**\n"
            "⁠—\n"
            "**<:ubereats:1234567890> UBEREATS** `-2h`\n"
            "*15€* -> **28~42€**\n"
            "*50€* -> **85~115€**\n"
            "*100€* -> **165~225€**\n"
            "*250€* -> **501~680€**\n"
            "⁠—\n"
            "└  __**Livraison automatique.**__"
        ),
        color=discord.Color.from_rgb(255, 192, 203) # Rose "Kitty"
    )
    
    # Ajout de l'image de profil/logo en haut à droite (comme sur l'image image_49a149.png)
    embed.set_thumbnail(url="LIEN_DE_TON_LOGO_KITTY_TOP_UP")
    
    # Ajout de la grande image / GIF tout en bas
    embed.set_image(url="LIEN_DE_TON_GIF_ANIME_DU_BAS")
    
    # Envoi du message dans le salon où la commande a été tapée
    await ctx.send(embed=embed)

# Remplace par ton propre token disponible sur le Discord Developer Portal
import os
bot.run(os.environ.get('TOKEN'))