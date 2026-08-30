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
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

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

def get_next_ticket_number():
    data = load_data()
    current_count = data.get("ticket_counter", 0) + 1
    data["ticket_counter"] = current_count
    save_data(data)
    return current_count

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
        CIVILIAN_ROLE_ID = 1537473046158246021

        civilian_role = interaction.guild.get_role(CIVILIAN_ROLE_ID)
        unverified_role = discord.utils.get(interaction.guild.roles, name="Unverified")

        if not civilian_role:
            await interaction.response.send_message("Civilian role not found! Please check the Role ID in code.", ephemeral=True)
            return

        try:
            if civilian_role not in interaction.user.roles:
                await interaction.user.add_roles(civilian_role)
            
            if unverified_role and unverified_role in interaction.user.roles:
                await interaction.user.remove_roles(unverified_role)
                
            await interaction.response.send_message("🎉 You have been successfully verified!", ephemeral=True)
        except Exception:
            await interaction.response.send_message("Failed to update roles. Make sure bot role is high enough!", ephemeral=True)

# --- TICKET CLOSE REASON MODAL ---
class CloseReasonModal(discord.ui.Modal, title="Close Ticket with Reason"):
    reason = discord.ui.TextInput(
        label="Reason for closing",
        style=discord.TextStyle.paragraph,
        placeholder="Type why this ticket is being closed...",
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"🔒 Ticket closing with reason: **{self.reason.value}**", ephemeral=False)
        await asyncio.sleep(4)
        try:
            await interaction.channel.delete()
        except Exception:
            pass

# --- TICKET CLOSE VIEW WITH STAFF PERMISSION CHECK ---
class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def is_staff(self, member: discord.Member) -> bool:
        if member.guild_permissions.administrator:
            return True
        return any(role.name in ["Staff", "Moderator", "Administrator"] for role in member.roles)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_ticket_btn")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_staff(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to close this ticket.", ephemeral=True)
            return

        await interaction.response.send_message("Closing ticket in 5 seconds...", ephemeral=True)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
        except Exception:
            pass

    @discord.ui.button(label="Close With Reason", style=discord.ButtonStyle.danger, emoji="📝", custom_id="close_reason_ticket_btn")
    async def close_reason_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_staff(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to close this ticket.", ephemeral=True)
            return

        await interaction.response.send_modal(CloseReasonModal())

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, emoji="🙋‍♂️", custom_id="claim_ticket_btn")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_staff(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to claim this ticket.", ephemeral=True)
            return

        embed = interaction.message.embeds[0]
        desc_lines = embed.description.split("\n")
        new_desc_lines = []
        for line in desc_lines:
            if line.startswith("**Status:**"):
                new_desc_lines.append(f"**Status:** Claimed by {interaction.user.mention}")
            else:
                new_desc_lines.append(line)
        
        if not any(line.startswith("**Status:**") for line in desc_lines):
            new_desc_lines.insert(2, f"**Status:** Claimed by {interaction.user.mention}")

        embed.description = "\n".join(new_desc_lines)
        
        button.disabled = True
        button.label = f"Claimed by {interaction.user.display_name}"
        
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(f"🔒 This ticket has been claimed by {interaction.user.mention}.", ephemeral=False)

# --- TICKET DROPDOWN & MODAL ---
class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="General Support", description="For any random questions, enquiries, or perk requests", emoji="❓", value="general"),
            discord.SelectOption(label="Staff Report", description="Feel like a staff member has treated you unfairly?", emoji="⚠️", value="staff_report"),
            discord.SelectOption(label="Affiliation Request", description="Request a partnership with GVRG", emoji="🤝", value="affiliation"),
        ]
        super().__init__(placeholder="Select a ticket category...", min_values=1, max_values=1, options=options, custom_id="ticket_select_menu")

    async def callback(self, interaction: discord.Interaction):
        category_name = self.values[0]
        titles = {
            "general": "General Support",
            "staff_report": "Staff Report",
            "affiliation": "Affiliation Request"
        }
        await interaction.response.send_modal(TicketModal(title=titles[category_name], category=category_name))

class TicketModal(discord.ui.Modal):
    def __init__(self, title: str, category: str):
        super().__init__(title=title)
        self.category = category

        if category == "general":
            self.field1 = discord.ui.TextInput(label="Ping yourself", style=discord.TextStyle.short, placeholder="@YourName", required=True)
            self.field2 = discord.ui.TextInput(label="Enquiry", style=discord.TextStyle.paragraph, placeholder="Type your enquiry here...", required=True)
            self.field3 = discord.ui.TextInput(label="Additional Info", style=discord.TextStyle.paragraph, placeholder="Any extra information...", required=False)
        elif category == "staff_report":
            self.field1 = discord.ui.TextInput(label="Ping yourself", style=discord.TextStyle.short, placeholder="@YourName", required=True)
            self.field2 = discord.ui.TextInput(label="Ping staff", style=discord.TextStyle.short, placeholder="@StaffMember", required=True)
            self.field3 = discord.ui.TextInput(label="Details", style=discord.TextStyle.paragraph, placeholder="Describe the situation...", required=True)
        else: # affiliation
            self.field1 = discord.ui.TextInput(label="Server Name", style=discord.TextStyle.short, placeholder="Your server name", required=True)
            self.field2 = discord.ui.TextInput(label="Member Count", style=discord.TextStyle.short, placeholder="e.g. 500 members", required=True)
            self.field3 = discord.ui.TextInput(label="Do you agree to stay in the server?", style=discord.TextStyle.short, placeholder="Yes/No", required=True)

        self.add_item(self.field1)
        self.add_item(self.field2)
        self.add_item(self.field3)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True, read_message_history=True)
        }

        try:
            ticket_num = get_next_ticket_number()
            channel_name = f"ticket-{ticket_num}"
            ticket_channel = await guild.create_text_channel(name=channel_name, overwrites=overwrites)

            if self.category == "general":
                desc = (
                    f"Thank you for opening a general support ticket. Please follow the format below:\n\n"
                    f"**Ping yourself:** {self.field1.value}\n\n"
                    f"**Enquiry:** {self.field2.value}\n\n"
                    f"**Additional Info:** {self.field3.value or 'None'}"
                )
            elif self.category == "staff_report":
                desc = (
                    f"Thank you for opening a staff report ticket. Please follow the format below:\n\n"
                    f"**Ping yourself:** {self.field1.value}\n\n"
                    f"**Ping staff:** {self.field2.value}\n\n"
                    f"**Details:** {self.field3.value}"
                )
            else:
                desc = (
                    f"Thank you for requesting an affiliation, please follow the format below:\n\n"
                    f"**Server Name:** {self.field1.value}\n\n"
                    f"**Member Count:** {self.field2.value}\n\n"
                    f"**Do you agree to stay in the server?:** {self.field3.value}"
                )

            embed = discord.Embed(
                title=self.title,
                description=desc,
                color=discord.Color.from_rgb(46, 204, 113)
            )
            embed.set_footer(text="Powered by GVRG Support")

            close_view = TicketCloseView()
            await ticket_channel.send(content=f"{interaction.user.mention}", embed=embed, view=close_view)
            await interaction.followup.send(f"Your ticket has been created! Head over to {ticket_channel.mention}.", ephemeral=True)
        except Exception as e:
            print(f"CRITICAL TICKET ERROR: {e}")
            await interaction.followup.send(f"An error occurred while creating your ticket: {e}", ephemeral=True)

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())

# --- SLASH COMMAND GROUPS ---
session_group = app_commands.Group(name="session", description="Manage roleplay sessions")
shift_group = app_commands.Group(name="shift", description="Manage staff shifts")
staff_group = app_commands.Group(name="staff", description="Staff management commands")
verify_group = app_commands.Group(name="verify", description="Verification commands")
application_group = app_commands.Group(name="application", description="Application management commands")
ticket_group = app_commands.Group(name="ticket", description="Ticket system management commands")

# --- SESSION COMMANDS ---
@session_group.command(name="vote", description="Start a session attendance vote")
@app_commands.describe(min_reacts="Minimum reactions required", description="Optional description")
async def session_vote(interaction: discord.Interaction, min_reacts: int = None, description: str = None):
    await interaction.response.defer()
    global session_vote_msg
    
    desc = description if description else "React with ✅ if you plan on attending the upcoming session!"
    if min_reacts:
        desc += f"\n\n📌 **Minimum Reacts Needed:** {min_reacts}"

    embed = discord.Embed(title="🚗 GVRG Session Attendance Vote", description=desc, color=discord.Color.green())
    embed.set_image(url="https://cdn.discordapp.com/attachments/1539991169231228938/1540780344620490752/image0.jpg")
    await interaction.followup.send(embed=embed)
    session_vote_msg = await interaction.original_response()
    await session_vote_msg.add_reaction("✅")
    await session_vote_msg.add_reaction("❌")

@session_group.command(name="start", description="Announce the start of a session")
@app_commands.describe(link="Server link", frp_limit="FRP speed limit", description="Extra details")
async def session_start(interaction: discord.Interaction, link: str = None, frp_limit: str = None, description: str = None):
    await interaction.response.defer()
    global session_vote_msg
    if session_vote_msg:
        try:
            await session_vote_msg.delete()
        except Exception:
            pass
        session_vote_msg = None

    desc = description if description else "The GVRG roleplay session is now **ACTIVE**! Jump in-game."
    if frp_limit:
        desc += f"\n\n⚡ **FRP Limit:** {frp_limit}"
    if link:
        desc += f"\n\n🔗 **Join Link:** {link}"

    embed = discord.Embed(title="🟢 GVRG Session Started", description=desc, color=discord.Color.green())
    embed.set_image(url="https://cdn.discordapp.com/attachments/1539991169231228938/1540781020377391125/image0.jpg")
    await interaction.followup.send(embed=embed)

@session_group.command(name="end", description="Announce session termination")
async def session_end(interaction: discord.Interaction):
    await interaction.response.defer()
    embed = discord.Embed(title="🔴 GVRG Session Ended", description="The GVRG roleplay session has concluded.", color=discord.Color.red())
    embed.set_image(url="https://cdn.discordapp.com/attachments/1539991169231228938/1540781434107732018/image0.jpg")
    end_msg = await interaction.followup.send(embed=embed, wait=True)
    await asyncio.sleep(3600)
    try:
        await end_msg.delete()
    except discord.NotFound:
        pass

# --- SHIFT COMMANDS ---
@shift_group.command(name="manage", description="Open your shift panel")
async def shift_manage(interaction: discord.Interaction):
    await interaction.response.defer()
    view = ShiftView()
    data, stats = view.get_user_stats(interaction.user.id)
    embed = view.build_embed(interaction.user, stats)
    await interaction.followup.send(embed=embed, view=view)

@shift_group.command(name="leaderboard", description="View shift leaderboard")
async def shift_leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    data = load_data()
    if not data:
        await interaction.followup.send("No shift data recorded yet!", ephemeral=True)
        return

    sorted_users = sorted([item for item in data.items() if item[0] != "ticket_counter"], key=lambda x: x[1].get("total_seconds", 0), reverse=True)
    embed = discord.Embed(title="🏆 GVRG Staff Shift Leaderboard", color=discord.Color.gold())
    description = ""

    for rank, (uid, stats) in enumerate(sorted_users[:10], start=1):
        user = interaction.guild.get_member(int(uid)) or await bot.fetch_user(int(uid))
        name = user.display_name if isinstance(user, discord.Member) else (user.name if user else f"User ID: {uid}")
        description += f"**#{rank} {name}** — {format_seconds(stats.get('total_seconds', 0))} ({stats.get('shift_count', 0)} shifts)\n"

    embed.description = description or "No data available."
    await interaction.followup.send(embed=embed)

# --- VERIFY COMMANDS ---
@verify_group.command(name="startup", description="Post verification panel")
async def verify_startup(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(title="🔒 GVRG Server Verification", description="Click **Verify** below!", color=discord.Color.green())
    await channel.send(embed=embed, view=VerifyView())
    await interaction.followup.send("Sent!", ephemeral=True)

# --- STAFF COMMANDS ---
@staff_group.command(name="app-closed", description="Post closed applications")
async def app_closed(interaction: discord.Interaction):
    await interaction.response.defer()
    embed = discord.Embed(title="🔒 GVRG Staff Applications — Closed", description="Applications are closed.", color=discord.Color.red())
    await interaction.followup.send(embed=embed)

@staff_group.command(name="app-open", description="Post open applications")
async def app_open(interaction: discord.Interaction):
    await interaction.response.defer()
    embed = discord.Embed(title="🟢 GVRG Staff Applications — OPEN!", description="[Apply Here](https://docs.google.com/forms/)", color=discord.Color.green())
    await interaction.followup.send(embed=embed)

@staff_group.command(name="report-setup", description="Post ticket panel")
async def staff_report_setup(interaction: discord.Interaction, channel: discord.TextChannel, image_url: str = None):
    await interaction.response.defer(ephemeral=True)
    
    panel_desc = (
        "**Welcome to the GVRG Support Center.** To receive assistance, please open a formal support ticket within this channel; our staff team aims to address all inquiries efficiently.\n\n"
        "🔸 **General Support**\n"
        "For any random questions, enquiries, or perk requests.\n\n"
        "🔸 **Staff Report**\n"
        "Feel like a staff member has treated you unfairly? Open one of these and submit your evidence.\n\n"
        "🔸 **Affiliation Request**\n"
        "Request a partnership with GVRG."
    )
    
    embed = discord.Embed(title="GVRG Support", description=panel_desc, color=discord.Color.from_rgb(46, 204, 113))
    if image_url: embed.set_image(url=image_url)
    await channel.send(embed=embed, view=TicketView())
    await interaction.followup.send("Sent!", ephemeral=True)

# --- TICKET COMMANDS ---
@ticket_group.command(name="setup", description="Post support ticket panel")
async def ticket_setup(interaction: discord.Interaction, channel: discord.TextChannel, image_url: str = None):
    await interaction.response.defer(ephemeral=True)
    
    panel_desc = (
        "**Welcome to the GVRG Support Center.** To receive assistance, please open a formal support ticket within this channel; our staff team aims to address all inquiries efficiently.\n\n"
        "🔸 **General Support**\n"
        "For any random questions, enquiries, or perk requests.\n\n"
        "🔸 **Staff Report**\n"
        "Feel like a staff member has treated you unfairly? Open one of these and submit your evidence.\n\n"
        "🔸 **Affiliation Request**\n"
        "Request a partnership with GVRG."
    )

    embed = discord.Embed(title="GVRG Support", description=panel_desc, color=discord.Color.from_rgb(46, 204, 113))
    if image_url: embed.set_image(url=image_url)
    await channel.send(embed=embed, view=TicketView())
    await interaction.followup.send("Sent!", ephemeral=True)

# --- APPLICATION COMMANDS ---
@application_group.command(name="passed", description="Accept application")
async def app_passed(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer()
    embed = discord.Embed(title="🎉 Accepted!", description=f"Congrats {user.mention}!", color=discord.Color.green())
    await interaction.followup.send(embed=embed)

@application_group.command(name="denied", description="Deny application")
async def app_denied(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer()
    embed = discord.Embed(title="❌ Denied", description=f"Sorry {user.mention}.", color=discord.Color.red())
    await interaction.followup.send(embed=embed)

# --- REGISTER GROUPS ---
bot.tree.add_command(session_group)
bot.tree.add_command(shift_group)
bot.tree.add_command(verify_group)
bot.tree.add_command(staff_group)
bot.tree.add_command(application_group)
bot.tree.add_command(ticket_group)

@bot.event
async def on_ready():
    bot.add_view(ShiftView())
    bot.add_view(VerifyView())
    bot.add_view(TicketView())
    bot.add_view(TicketCloseView())
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

keep_alive()
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
