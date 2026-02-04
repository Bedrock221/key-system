import discord
from discord.ext import commands
import pymongo
from pymongo import MongoClient
import datetime
import uuid
import os
import threading
from flask import Flask, request

# --- CONFIGURATION (Environment Variables) ---
TOKEN = os.environ.get("DISCORD_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 598460565387476992))
WORKINK_LINK = os.environ.get("WORKINK_LINK", "https://work.ink/YOUR_LINK")
MONGO_URL = os.environ.get("MONGO_URL")

# --- DATABASE SETUP ---
client = MongoClient(MONGO_URL)
db = client["KeySystem"]
keys_col = db["keys"]

# --- FLASK API (Verification for Roblox) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Verification Server Online", 200

@app.route('/check', methods=['GET'])
def verify():
    key = request.args.get('key')
    hwid = request.args.get('hwid')
    
    if not key or not hwid:
        return "invalid", 400
        
    found = keys_col.find_one({"key": key.strip()})
    
    if found and found["status"] == "active":
        # Check Expiration
        expiry_dt = datetime.datetime.strptime(found["expires"], '%Y-%m-%d %H:%M:%S')
        if datetime.datetime.now() < expiry_dt:
            # Check HWID Match
            if found["hwid"] == hwid:
                return "valid", 200
    return "invalid", 403

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- DISCORD BOT ---
class KeyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

bot = KeyBot()

# --- MODALS ---

class RedeemModal(discord.ui.Modal, title="Redeem Your Key"):
    key_input = discord.ui.TextInput(label="Enter Key", placeholder="XXXX-XXXX", min_length=8)
    hwid_input = discord.ui.TextInput(label="Enter Your HWID", placeholder="Paste from clipboard...")

    async def on_submit(self, interaction: discord.Interaction):
        key_val = self.key_input.value.strip()
        hwid_val = self.hwid_input.value.strip()
        found = keys_col.find_one({"key": key_val})

        if not found:
            await interaction.response.send_message("❌ Invalid Key!", ephemeral=True)
        elif found["status"] != "unactivated":
            await interaction.response.send_message("❌ This key has already been used!", ephemeral=True)
        else:
            expiry = datetime.datetime.now() + datetime.timedelta(hours=24)
            keys_col.update_one({"key": key_val}, {"$set": {
                "hwid": hwid_val,
                "expires": expiry.strftime('%Y-%m-%d %H:%M:%S'),
                "status": "active",
                "owner_id": interaction.user.id
            }})
            await interaction.response.send_message(f"✅ Key Activated! Expires in 24 hours: {expiry.strftime('%Y-%m-%d %H:%M')}", ephemeral=True)

class ResetHWIDModal(discord.ui.Modal, title="Reset HWID"):
    key_input = discord.ui.TextInput(label="Enter Your Activated Key")

    async def on_submit(self, interaction: discord.Interaction):
        key_val = self.key_input.value.strip()
        found = keys_col.find_one({"key": key_val, "owner_id": interaction.user.id})
        
        if found:
            keys_col.update_one({"key": key_val}, {"$set": {"hwid": None, "status": "unactivated"}})
            await interaction.response.send_message("✅ HWID Reset! You can now redeem it again with your new HWID.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Key not found or you don't own it.", ephemeral=True)

# --- BUTTON INTERFACE ---

class MainMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="View Script", style=discord.ButtonStyle.blurple, emoji="📜")
    async def view_script(self, interaction: discord.Interaction):
        grabber = "```lua\nsetclipboard(game:GetService('RbxAnalyticsService'):GetClientId())\nprint('HWID Copied!')\n```"
        await interaction.response.send_message(f"Run this in your executor to copy your HWID:\n{grabber}", ephemeral=True)

    @discord.ui.button(label="Redeem Key", style=discord.ButtonStyle.green, emoji="🔑")
    async def redeem_key(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RedeemModal())

    @discord.ui.button(label="Free Key", style=discord.ButtonStyle.link, url=WORKINK_LINK)
    async def free_key(self, interaction: discord.Interaction):
        pass

    @discord.ui.button(label="Reset HWID", style=discord.ButtonStyle.danger, emoji="⚙️")
    async def reset_hwid(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ResetHWIDModal())

# --- COMMANDS ---

@bot.command()
async def setup_panel(ctx):
    if ctx.author.id != ADMIN_ID: return
    embed = discord.Embed(
        title="AutoFarm Dhc", 
        description="Use the buttons below to manage your key\nPolSec | v5", 
        color=0x5865F2
    )
    await ctx.send(embed=embed, view=MainMenuView())

@bot.command()
async def add_keys(ctx, amount: int):
    if ctx.author.id != ADMIN_ID: return
    new_keys = []
    for _ in range(amount):
        # Generates a clean 8-character key
        k = str(uuid.uuid4())[:8].upper()
        keys_col.insert_one({
            "key": k, 
            "hwid": None, 
            "expires": None, 
            "status": "unactivated", 
            "owner_id": None
        })
        new_keys.append(k)
    
    with open("keys_export.txt", "w") as f:
        f.write("\n".join(new_keys))
    
    try:
        await ctx.author.send(f"Generated {amount} keys:", file=discord.File("keys_export.txt"))
        await ctx.send(f"✅ {amount} keys saved to MongoDB and sent to your DMs.")
    except:
        await ctx.send(f"✅ {amount} keys saved, but I couldn't DM you the file.")

if __name__ == "__main__":
    # Run API and Bot simultaneously
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
