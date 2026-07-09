import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import random
import asyncio
import aiohttp
from datetime import datetime
from typing import Optional

# ---------- Environment ----------
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set.")

GUILD_IDS = os.getenv("GUILD_IDS")
guild_ids = [int(g.strip()) for g in GUILD_IDS.split(",")] if GUILD_IDS else None

# ---------- Data Manager ----------
class DataManager:
    def __init__(self, filename="data.json"):
        self.filename = filename
        self.data = {}
        self.load()

    def load(self):
        try:
            with open(self.filename, "r") as f:
                self.data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}

    def save(self):
        with open(self.filename, "w") as f:
            json.dump(self.data, f, indent=4)

    def get_guild(self, guild_id):
        guild_id = str(guild_id)
        if guild_id not in self.data:
            self.data[guild_id] = {
                "prefix": "!",
                "welcome_channel": None,
                "welcome_message": "Welcome {user} to {server}!",
                "verify_role": None,
                "mute_role": None,
                "log_channel": None
            }
            self.save()
        return self.data[guild_id]

    def set_prefix(self, guild_id, prefix):
        g = self.get_guild(guild_id)
        g["prefix"] = prefix
        self.save()

    def get_prefix(self, guild_id):
        return self.get_guild(guild_id)["prefix"]

# ---------- Bot Instance ----------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
data_manager = DataManager()

async def get_prefix(bot, message):
    if not message.guild:
        return "!"
    return data_manager.get_prefix(message.guild.id)

bot.command_prefix = get_prefix

# ---------- Helper ----------
async def get_mute_role(guild):
    data = data_manager.get_guild(guild.id)
    role_id = data.get("mute_role")
    if role_id:
        role = guild.get_role(role_id)
        if role:
            return role
    role = await guild.create_role(name="Muted", permissions=discord.Permissions(0), reason="Mute role")
    for channel in guild.channels:
        await channel.set_permissions(role, send_messages=False, speak=False)
    data["mute_role"] = role.id
    data_manager.save()
    return role

# ---------- Cogs ----------

# ----- Moderation -----
class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    mod = app_commands.Group(name="mod", description="Moderation commands")

    @mod.command(name="kick")
    @app_commands.describe(member="Member to kick", reason="Reason")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
        await member.kick(reason=reason)
        embed = discord.Embed(title="Kicked", color=0xff0000)
        embed.add_field(name="Member", value=member.mention)
        embed.add_field(name="Reason", value=reason)
        await interaction.response.send_message(embed=embed)

    @mod.command(name="ban")
    @app_commands.describe(member="Member to ban", reason="Reason")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
        await member.ban(reason=reason)
        embed = discord.Embed(title="Banned", color=0xff0000)
        embed.add_field(name="Member", value=member.mention)
        embed.add_field(name="Reason", value=reason)
        await interaction.response.send_message(embed=embed)

    @mod.command(name="unban")
    @app_commands.describe(user_id="ID of user to unban", reason="Reason")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason"):
        try:
            user = await self.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user, reason=reason)
            embed = discord.Embed(title="Unbanned", color=0x00ff00)
            embed.add_field(name="User", value=user.mention)
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

    @mod.command(name="mute")
    @app_commands.describe(member="Member to mute", duration="e.g., 10m, 1h, 2d", reason="Reason")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def mute(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "No reason"):
        mute_role = await get_mute_role(interaction.guild)
        if mute_role in member.roles:
            await interaction.response.send_message(f"⚠️ {member.mention} is already muted.", ephemeral=True)
            return
        units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        try:
            num = int(duration[:-1])
            unit = duration[-1].lower()
            seconds = num * units[unit]
        except:
            await interaction.response.send_message("❌ Invalid duration. Use e.g., 10m, 1h, 2d.", ephemeral=True)
            return
        await member.add_roles(mute_role, reason=reason)
        embed = discord.Embed(title="Muted", color=0xffaa00)
        embed.add_field(name="Member", value=member.mention)
        embed.add_field(name="Duration", value=duration)
        embed.add_field(name="Reason", value=reason)
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(seconds)
        if mute_role in member.roles:
            await member.remove_roles(mute_role, reason="Mute expired")

    @mod.command(name="unmute")
    @app_commands.describe(member="Member to unmute", reason="Reason")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def unmute(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
        mute_role = await get_mute_role(interaction.guild)
        if mute_role not in member.roles:
            await interaction.response.send_message(f"⚠️ {member.mention} is not muted.", ephemeral=True)
            return
        await member.remove_roles(mute_role, reason=reason)
        embed = discord.Embed(title="Unmuted", color=0x00ff00)
        embed.add_field(name="Member", value=member.mention)
        await interaction.response.send_message(embed=embed)

    @mod.command(name="clear")
    @app_commands.describe(amount="Number of messages (1-100)")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: int):
        if amount < 1 or amount > 100:
            await interaction.response.send_message("❌ Must be between 1 and 100.", ephemeral=True)
            return
        deleted = await interaction.channel.purge(limit=amount+1)
        await interaction.response.send_message(f"✅ Deleted {len(deleted)-1} messages.", ephemeral=True)

    @mod.command(name="slowmode")
    @app_commands.describe(seconds="Slowmode delay in seconds (0 to disable)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, seconds: int):
        await interaction.channel.edit(slowmode_delay=seconds)
        await interaction.response.send_message(f"✅ Slowmode set to {seconds} seconds.")

    @mod.command(name="lock")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction):
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
        await interaction.response.send_message("🔒 Channel locked.")

    @mod.command(name="unlock")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction):
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
        await interaction.response.send_message("🔓 Channel unlocked.")

    @mod.command(name="warn")
    @app_commands.describe(member="Member to warn", reason="Reason")
    @app_commands.checks.has_permissions(kick_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason"):
        try:
            await member.send(f"⚠️ You were warned in {interaction.guild.name} for: {reason}")
        except:
            pass
        embed = discord.Embed(title="Warning", color=0xffaa00)
        embed.add_field(name="Member", value=member.mention)
        embed.add_field(name="Reason", value=reason)
        await interaction.response.send_message(embed=embed)

# ----- Fun -----
class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession()

    def cog_unload(self):
        asyncio.create_task(self.session.close())

    fun = app_commands.Group(name="fun", description="Fun commands")

    @fun.command(name="8ball")
    @app_commands.describe(question="Your question")
    async def eightball(self, interaction: discord.Interaction, question: str):
        responses = [
            "It is certain.", "It is decidedly so.", "Without a doubt.",
            "Yes, definitely.", "You may rely on it.", "As I see it, yes.",
            "Most likely.", "Outlook good.", "Yes.",
            "Signs point to yes.", "Reply hazy, try again.", "Ask again later.",
            "Better not tell you now.", "Cannot predict now.", "Concentrate and ask again.",
            "Don't count on it.", "My reply is no.", "My sources say no.",
            "Outlook not so good.", "Very doubtful."
        ]
        embed = discord.Embed(title="🎱 8Ball", color=0x9b59b6)
        embed.add_field(name="Question", value=question)
        embed.add_field(name="Answer", value=random.choice(responses))
        await interaction.response.send_message(embed=embed)

    @fun.command(name="coinflip")
    async def coinflip(self, interaction: discord.Interaction):
        result = random.choice(["Heads", "Tails"])
        embed = discord.Embed(title="🪙 Coin Flip", description=f"Result: **{result}**", color=0xf1c40f)
        await interaction.response.send_message(embed=embed)

    @fun.command(name="dice")
    @app_commands.describe(sides="Number of sides (default 6)")
    async def dice(self, interaction: discord.Interaction, sides: int = 6):
        result = random.randint(1, sides)
        embed = discord.Embed(title=f"🎲 {sides}-sided die", description=f"Result: **{result}**", color=0x3498db)
        await interaction.response.send_message(embed=embed)

    @fun.command(name="rps")
    @app_commands.describe(choice="rock, paper, or scissors")
    async def rps(self, interaction: discord.Interaction, choice: str):
        choices = ["rock", "paper", "scissors"]
        if choice.lower() not in choices:
            await interaction.response.send_message("❌ Choose rock, paper, or scissors.", ephemeral=True)
            return
        bot_choice = random.choice(choices)
        result = ""
        if choice.lower() == bot_choice:
            result = "It's a tie!"
        elif (choice.lower() == "rock" and bot_choice == "scissors") or \
             (choice.lower() == "paper" and bot_choice == "rock") or \
             (choice.lower() == "scissors" and bot_choice == "paper"):
            result = "You win! 🎉"
        else:
            result = "I win! 😈"
        embed = discord.Embed(title="Rock Paper Scissors", color=0x2ecc71)
        embed.add_field(name="You", value=choice.capitalize(), inline=True)
        embed.add_field(name="Bot", value=bot_choice.capitalize(), inline=True)
        embed.add_field(name="Result", value=result, inline=False)
        await interaction.response.send_message(embed=embed)

    @fun.command(name="meme")
    async def meme(self, interaction: discord.Interaction):
        async with self.session.get("https://meme-api.com/gimme") as resp:
            if resp.status == 200:
                data = await resp.json()
                embed = discord.Embed(title=data.get("title", "Meme"), color=0xe67e22)
                embed.set_image(url=data.get("url"))
                embed.set_footer(text=f"👍 {data.get('ups', 0)}")
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("❌ Failed to fetch meme.")

    @fun.command(name="joke")
    async def joke(self, interaction: discord.Interaction):
        async with self.session.get("https://v2.jokeapi.dev/joke/Any?type=single") as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("type") == "single":
                    joke = data.get("joke", "No joke found.")
                else:
                    joke = f"{data.get('setup', '')}\n{data.get('delivery', '')}"
                embed = discord.Embed(title="😂 Joke", description=joke, color=0xf39c12)
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("❌ Failed to fetch joke.")

    @fun.command(name="dog")
    async def dog(self, interaction: discord.Interaction):
        async with self.session.get("https://dog.ceo/api/breeds/image/random") as resp:
            if resp.status == 200:
                data = await resp.json()
                embed = discord.Embed(title="🐶 Dog", color=0x8e44ad)
                embed.set_image(url=data.get("message"))
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message("❌ Failed to fetch dog.")

    @fun.command(name="cat")
    async def cat(self, interaction: discord.Interaction):
        async with self.session.get("https://api.thecatapi.com/v1/images/search") as resp:
            if resp.status == 200:
                data = await resp.json()
                if data:
                    embed = discord.Embed(title="🐱 Cat", color=0x8e44ad)
                    embed.set_image(url=data[0].get("url"))
                    await interaction.response.send_message(embed=embed)
                else:
                    await interaction.response.send_message("❌ No cat found.")
            else:
                await interaction.response.send_message("❌ Failed to fetch cat.")

    @fun.command(name="fact")
    async def fact(self, interaction: discord.Interaction):
        facts = [
            "A group of flamingos is called a 'flamboyance'.",
            "Bananas are berries, but strawberries aren't.",
            "Octopuses have three hearts.",
            "The shortest war in history lasted 38 minutes.",
            "A jiffy is an actual unit of time (1/100th of a second).",
            "Honey never spoils.",
            "The Eiffel Tower can grow 15 cm in summer due to heat.",
            "A crocodile cannot stick its tongue out.",
            "Elephants are the only mammals that cannot jump.",
            "A cat's nose is unique, like a fingerprint."
        ]
        embed = discord.Embed(title="💡 Fact", description=random.choice(facts), color=0x1abc9c)
        await interaction.response.send_message(embed=embed)

    @fun.command(name="quote")
    async def quote(self, interaction: discord.Interaction):
        quotes = [
            ("The only way to do great work is to love what you do.", "Steve Jobs"),
            ("In the middle of difficulty lies opportunity.", "Albert Einstein"),
            ("Life is what happens when you're busy making other plans.", "John Lennon"),
            ("Be yourself; everyone else is already taken.", "Oscar Wilde"),
            ("To be or not to be, that is the question.", "Shakespeare")
        ]
        q, author = random.choice(quotes)
        embed = discord.Embed(title="📜 Quote", description=f"“{q}”", color=0x34495e)
        embed.set_footer(text=f"— {author}")
        await interaction.response.send_message(embed=embed)

    # Extra fun commands
    @fun.command(name="hug")
    @app_commands.describe(member="Who to hug")
    async def hug(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.send_message(f"🤗 {interaction.user.mention} hugs {member.mention}!")

    @fun.command(name="pat")
    @app_commands.describe(member="Who to pat")
    async def pat(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.send_message(f"🖐️ {interaction.user.mention} pats {member.mention}!")

    @fun.command(name="slap")
    @app_commands.describe(member="Who to slap")
    async def slap(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.send_message(f"👋 {interaction.user.mention} slaps {member.mention}!")

    @fun.command(name="roll")
    @app_commands.describe(dice="e.g., 2d6")
    async def roll(self, interaction: discord.Interaction, dice: str):
        try:
            num, sides = map(int, dice.lower().split('d'))
            if num > 100 or sides > 1000:
                await interaction.response.send_message("❌ Too many dice or sides.", ephemeral=True)
                return
            results = [random.randint(1, sides) for _ in range(num)]
            total = sum(results)
            embed = discord.Embed(title="🎲 Dice Roll", description=f"Rolling {dice}: **{total}**", color=0x3498db)
            embed.add_field(name="Results", value=", ".join(map(str, results)))
            await interaction.response.send_message(embed=embed)
        except:
            await interaction.response.send_message("❌ Invalid format. Use e.g., `2d6`.", ephemeral=True)

    @fun.command(name="reverse")
    @app_commands.describe(text="Text to reverse")
    async def reverse(self, interaction: discord.Interaction, text: str):
        await interaction.response.send_message(f"🔄 {text[::-1]}")

    @fun.command(name="say")
    @app_commands.describe(message="Message to repeat")
    async def say(self, interaction: discord.Interaction, message: str):
        await interaction.response.send_message(message)

    @fun.command(name="poll")
    @app_commands.describe(question="Poll question", option1="First option", option2="Second option")
    async def poll(self, interaction: discord.Interaction, question: str, option1: str, option2: str):
        embed = discord.Embed(title="📊 Poll", description=question, color=0x2ecc71)
        embed.add_field(name="1️⃣", value=option1, inline=True)
        embed.add_field(name="2️⃣", value=option2, inline=True)
        embed.set_footer(text="React with 1️⃣ or 2️⃣ to vote!")
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        await msg.add_reaction("1️⃣")
        await msg.add_reaction("2️⃣")

    @fun.command(name="love")
    @app_commands.describe(person1="First person", person2="Second person")
    async def love(self, interaction: discord.Interaction, person1: str, person2: str):
        percent = random.randint(0, 100)
        embed = discord.Embed(title="💕 Love Meter", description=f"{person1} ❤️ {person2} = {percent}%", color=0xff69b4)
        await interaction.response.send_message(embed=embed)

    @fun.command(name="rate")
    @app_commands.describe(thing="What to rate")
    async def rate(self, interaction: discord.Interaction, thing: str):
        rating = random.randint(0, 10)
        embed = discord.Embed(title="⭐ Rating", description=f"I rate **{thing}** a {rating}/10!", color=0xf1c40f)
        await interaction.response.send_message(embed=embed)

    @fun.command(name="choose")
    @app_commands.d
