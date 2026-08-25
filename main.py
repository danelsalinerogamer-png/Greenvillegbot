import asyncio
import datetime
import json
import os
from threading import Thread
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask

# --- FLASK WEB SERVER FOR 24/7 UPTIME ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is online and running!"

def run_web():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# --- BOT SETUP ---
intents = discord.Intents.default()
intents.members = True  # Required for fetching/managing members
bot = commands.Bot(command_prefix="!", intents=intents)

# Track session vote message object to delete later
session_vote_msg = None

# --- DATABASE / STORAGE SETUP ---
DATA_FILE = "shift_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def format_seconds(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    parts = []
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0 or hours > 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    parts.append(f"{secs} second{'s' if secs != 1 else ''}")
    return ", ".join(parts)

# --- SHIFT PANEL BUTTON VIEW ---
class ShiftView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def get_user_stats(self, user_id):
        data = load_data()
        uid = str(user_id)
        if uid not in data:
            data[uid] = {
                "shift_count": 0,
                "total_seconds": 0,
                "active_start": None,
                "paused_seconds": 0,
                "status": "Ended",
                "last_shift_seconds": 0
            }
        return data, data[uid]

    def build_embed(self, user, stats):
        embed = discord.Embed(color=discord.Color.blue())
        embed.set_author(name=f"{user.display_name}", icon_url=user.display_avatar.url)

        count = stats["shift_count"]
        total_sec = stats["total_seconds"]
        avg_sec = total_sec / count if count > 0 else 0

        embed.add_field(
            name="📑 All Time Information",
            value=(
                f"**Shift Count:** {count}\n"
                f"**Total Duration:** {format_seconds(total_sec)}\n"
                f"**Average Duration:** {format_seconds(avg_sec)}"
            ),
            inline=False
        )

        status = stats["status"]
        status_text = f"🔘 {status}"
        if status == "Active":
            status_text = "🟢 Active"
        elif status == "Paused":
            status_text = "⏸️ Paused"

        time_display = format_seconds(stats["last_shift_seconds"])
        if status == "Active" and stats["active_start"]:
            time_display = f"<t:{int(stats['active_start'])}:R>"

        embed.add_field(
            name="🕒 Last Shift",
            value=(
                f"**Status:** {status_text}\n"
                f"**Total Time:** {time_display}\n"
                f"**Shift Type:** Patrol Staff"
            ),
            inline=False
        )
        return embed

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success, emoji="⏱️", custom_id="shift_start")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data, stats = self.get_user_stats(interaction.user.id)
        if stats["status"] == "Active":
            await interaction.response.send_message("You are already on an active shift!", ephemeral=True)
            return

        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        stats["status"] = "Active"
        stats["active_start"] = now
        save_data(data)

        embed = self.build_embed(interaction.user, stats)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.primary, emoji="⏸️", custom_id="shift_pause")
    async def pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data, stats = self.get_user_stats(interaction.user.id)
        if stats["status"] != "Active":
            await interaction.response.send_message("You do not have an active shift to pause!", ephemeral=True)
            return

        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        elapsed = now - stats["active_start"]
        stats["paused_seconds"] += elapsed
        stats["last_shift_seconds"] = stats["paused_seconds"]
        stats["status"] = "Paused"
        stats["active_start"] = None
        save_data(data)

        embed = self.build_embed(interaction.user, stats)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="End", style=discord.ButtonStyle.danger, emoji="⏰", custom_id="shift_end")
    async def end_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data, stats = self.get_user_stats(interaction.user.id)
        if stats["status"] not in ["Active", "Paused"]:
            await interaction.response.send_message("You do not have a shift to end!", ephemeral=True)
            return

        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        if stats["status"] == "Active":
            elapsed = now - stats["active_start"]
            stats["paused_seconds"] += elapsed

        shift_duration = stats["paused_seconds"]
        stats["total_seconds"] += shift_duration
        stats["last_shift_seconds"] = shift_duration
        stats["shift_count"] += 1
        stats["status"] = "Ended"
        stats["active_start"] = None
        stats["paused_seconds"] = 0
        save_data(data)

        embed = self.build_embed(interaction.user, stats)
        await interaction.response.edit_message(embed=embed, view=self)

# --- VERIFICATION PANEL BUTTON VIEW ---
class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify", style=discord.ButtonStyle.success, emoji="✅", custom_id="persistent_verify:verify_btn")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        VERIFIED_ROLE_ID = 1537473046158246021

        role = interaction.guild.get_role(VERIFIED_ROLE_ID)
        if not role:
            await interaction.response.send_message("Verification role not found! Please contact an administrator.", ephemeral=True)
            return

        if role in interaction.user.roles:
            await interaction.response.send_message("You are already verified!", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message("🎉 You have been successfully verified!", ephemeral=True)

# --- SLASH COMMAND GROUPS ---
session_group = app_commands.Group(name="session", description="Manage roleplay sessions")
shift_group = app_commands.Group(name="shift", description="Manage staff shifts")
staff_group = app_commands.Group(name="staff", description="Staff management commands")
application_group = app_commands.Group(name="application", description="Application management commands")

# --- SESSION COMMANDS ---
@session_group.command(name="vote", description="Start a session attendance vote")
@app_commands.describe(
    min_reacts="Minimum reactions required for session to start",
    description="Optional description or details for the vote"
)
async def session_vote(interaction: discord.Interaction, min_reacts: int = None, description: str = None):
    await interaction.response.defer()
    global session_vote_msg
    
    desc = description if description else "React with ✅ if you plan on attending the upcoming session!"
    if min_reacts:
        desc += f"\n\n📌 **Minimum Reacts Needed:** {min_reacts}"

    embed = discord.Embed(
        title="🚗 Session Attendance Vote",
        description=desc,
        color=discord.Color.green()
    )
    embed.set_image(url="https://cdn.discordapp.com/attachments/1539991169231228938/1540780344620490752/image0.jpg")
    await interaction.followup.send(embed=embed)
    session_vote_msg = await interaction.original_response()
    await session_vote_msg.add_reaction("✅")
    await session_vote_msg.add_reaction("❌")

@session_group.command(name="start", description="Announce the start of a session")
@app_commands.describe(
    link="Optional server link to join directly",
    frp_limit="Optional FRP speed limit or rule setup",
    description="Optional extra details for the session start"
)
async def session_start(interaction: discord.Interaction, link: str = None, frp_limit: str = None, description: str = None):
    await interaction.response.defer()
    global session_vote_msg
    if session_vote_msg:
        try:
            await session_vote_msg.delete()
        except Exception:
            pass
        session_vote_msg = None

    desc = description if description else "The roleplay session is now **ACTIVE**! Jump in-game."
    if frp_limit:
        desc += f"\n\n⚡ **FRP Limit:** {frp_limit}"
    if link:
        desc += f"\n\n🔗 **Join Link:** {link}"

    embed = discord.Embed(
        title="🟢 Session Started",
        description=desc,
        color=discord.Color.green()
    )
    embed.set_image(url="https://cdn.discordapp.com/attachments/1539991169231228938/1540781020377391125/image0.jpg")
    await interaction.followup.send(embed=embed)

@session_group.command(name="end", description="Announce session termination")
async def session_end(interaction: discord.Interaction):
    await interaction.response.defer()
    embed = discord.Embed(
        title="🔴 Session Ended",
        description="The roleplay session has officially concluded. Thank you for participating!",
        color=discord.Color.red()
    )
    embed.set_image(url="https://cdn.discordapp.com/attachments/1539991169231228938/1540781434107732018/image0.jpg")
    end_msg = await interaction.followup.send(embed=embed, wait=True)

    await asyncio.sleep(3600)
    try:
        await end_msg.delete()
    except discord.NotFound:
        pass

# --- SHIFT COMMANDS ---
@shift_group.command(name="manage", description="Open your shift management panel")
async def shift_manage(interaction: discord.Interaction):
    await interaction.response.defer()
    view = ShiftView()
    data, stats = view.get_user_stats(interaction.user.id)
    embed = view.build_embed(interaction.user, stats)
    await interaction.followup.send(embed=embed, view=view)

@shift_group.command(name="leaderboard", description="View the staff shift duration leaderboard")
async def shift_leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    data = load_data()
    if not data:
        await interaction.followup.send("No shift data recorded yet!", ephemeral=True)
        return

    sorted_users = sorted(data.items(), key=lambda x: x[1].get("total_seconds", 0), reverse=True)

    embed = discord.Embed(title="🏆 Staff Shift Leaderboard", color=discord.Color.gold())
    description = ""

    for rank, (uid, stats) in enumerate(sorted_users[:10], start=1):
        user = interaction.guild.get_member(int(uid))
        if user is None:
            try:
                user = await interaction.guild.fetch_member(int(uid))
            except (discord.NotFound, discord.HTTPException):
                try:
                    user = await bot.fetch_user(int(uid))
                except (discord.NotFound, discord.HTTPException):
                    user = None

        if isinstance(user, discord.Member):
            name = user.display_name
        elif user is not None:
            name = user.name
        else:
            name = f"User ID: {uid}"
        time_str = format_seconds(stats.get("total_seconds", 0))
        description += f"**#{rank} {name}** — {time_str} ({stats.get('shift_count', 0)} shifts)\n"

    embed.description = description or "No data available."
    await interaction.followup.send(embed=embed)

# --- STAFF COMMANDS ---
@staff_group.command(name="app-closed", description="Post closed/under review applications embed")
async def app_closed(interaction: discord.Interaction):
    await interaction.response.defer()
    embed = discord.Embed(
        title="🔒 Staff Applications — Closed",
        description=(
            "Staff applications for **Greenville Roleplay Globe** are currently **CLOSED**.\n\n"
            "If you have already applied and haven't received a response yet, your application is currently **under review**. "
            "Results will be published in a couple of days in the staff announcements channel.\n\n"
            "Thank you for your patience!"
        ),
        color=discord.Color.red()
    )
    await interaction.followup.send(embed=embed)

@staff_group.command(name="app-open", description="Post open applications embed with form link")
async def app_open(interaction: discord.Interaction):
    await interaction.response.defer()
    embed = discord.Embed(
        title="🟢 Staff Applications — NOW OPEN!",
        description=(
            "Staff applications for **Greenville Roleplay Globe** are officially **OPEN**!\n\n"
            "We are looking for active and dedicated members to join our staff team. Please read all questions carefully and fill out the form honestly and thoroughly.\n\n"
            "👉 [Click Here to Apply](https://docs.google.com/forms/d/e/1FAIpQLSdCvSvHve1pLQLv4pjkmONYNbbhuWwOi_9h-Dn1Jnnrvg0Jg/viewform?usp=dialog)"
        ),
        color=discord.Color.green()
    )
    await interaction.followup.send(embed=embed)

@staff_group.command(name="verify-setup", description="Post the persistent verification panel")
@app_commands.describe(channel="The channel to send the verification embed in")
async def verify_setup(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(
        title="🔒 Server Verification",
        description="Click the **Verify** button below to unlock access to **Greenville Roleplay Globe**!",
        color=discord.Color.green()
    )
    embed.set_footer(text="Greenville Roleplay Globe • Security")

    view = VerifyView()
    await channel.send(embed=embed, view=view)
    await interaction.followup.send(
        f"Verification panel successfully sent to {channel.mention}!",
        ephemeral=True,
    )

# --- APPLICATION COMMANDS ---
@application_group.command(name="passed", description="Announce an accepted application")
@app_commands.describe(user="The user who passed the application")
async def app_passed(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer()
    embed = discord.Embed(
        title="🎉 Staff Application Passed!",
        description=(
            f"Congratulations {user.mention}! Your application for the **Greenville Roleplay Globe** "
            "staff team has been **ACCEPTED**.\n\n"
            "Please check your direct messages or wait for High Management to ping you regarding onboarding."
        ),
        color=discord.Color.green()
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="Greenville Roleplay Globe • Staff Team")
    await interaction.followup.send(embed=embed)

@application_group.command(name="denied", description="Announce a denied application")
@app_commands.describe(user="The user whose application was denied")
async def app_denied(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer()
    embed = discord.Embed(
        title="❌ Staff Application Denied",
        description=(
            f"Thank you for your interest in joining our staff team, {user.mention}.\n\n"
            "Unfortunately, your staff application has been **DENIED** at this time. "
            "You are welcome to re-apply during our next open application cycle."
        ),
        color=discord.Color.red()
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="Greenville Roleplay Globe • Staff Team")
    await interaction.followup.send(embed=embed)

# --- STANDALONE COMMANDS ---
@bot.tree.command(name="promote", description="Announce a staff or member promotion")
@app_commands.describe(user="The user being promoted", old_rank="Their current rank", new_rank="Their new rank", reason="Reason for promotion")
async def promote(interaction: discord.Interaction, user: discord.Member, old_rank: str, new_rank: str, reason: str = "Hard work and dedication"):
    await interaction.response.defer()
    embed = discord.Embed(title="🎉 Staff Promotion!", description=f"Congratulations to {user.mention} on their promotion!", color=discord.Color.green())
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="👤 User", value=f"{user.mention}", inline=True)
    embed.add_field(name="📉 Previous Rank", value=old_rank, inline=True)
    embed.add_field(name="📈 New Rank", value=f"**{new_rank}**", inline=True)
    embed.add_field(name="📝 Reason", value=reason, inline=False)
    embed.set_footer(text="Greenville Roleplay Globe • Management")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="demote", description="Announce a staff or member demotion")
@app_commands.describe(user="The user being demoted", old_rank="Their current rank", new_rank="Their new rank", reason="Reason for demotion")
async def demote(interaction: discord.Interaction, user: discord.Member, old_rank: str, new_rank: str, reason: str = "No reason provided"):
    await interaction.response.defer()
    embed = discord.Embed(title="📉 Staff Demotion", description=f"A rank update has been issued for {user.mention}.", color=discord.Color.red())
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="👤 User", value=f"{user.mention}", inline=True)
    embed.add_field(name="📈 Previous Rank", value=old_rank, inline=True)
    embed.add_field(name="📉 New Rank", value=f"**{new_rank}**", inline=True)
    embed.add_field(name="📝 Reason", value=reason, inline=False)
    embed.set_footer(text="Greenville Roleplay Globe • Management")
    await interaction.followup.send(embed=embed)

# --- REGISTER COMMAND GROUPS TO BOT.TREE ---
bot.tree.add_command(session_group)
bot.tree.add_command(shift_group)
bot.tree.add_command(staff_group)
bot.tree.add_command(application_group)

@bot.event
async def on_ready():
    bot.add_view(ShiftView())
    bot.add_view(VerifyView())
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

# Start the web server and run the bot
keep_alive()
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
