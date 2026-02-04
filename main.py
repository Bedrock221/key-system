import discord
from discord.ext import commands
import pymongo
from pymongo import MongoClient
import datetime
import uuid
import os
import threading
from flask import Flask, request, render_template_string

# --- CONFIGURATION (Environment Variables) ---
TOKEN = os.environ.get("DISCORD_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 598460565387476992))
WORKINK_LINK = os.environ.get("WORKINK_LINK", "https://work.ink/YOUR_LINK")
MONGO_URL = os.environ.get("MONGO_URL")

# --- DATABASE SETUP ---
client = MongoClient(MONGO_URL)
db = client["KeySystem"]
keys_col = db["keys"]

# --- FLASK API & DISPENSER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Verification Server Online", 200

# NEW: The Page where users see their key after Work.ink
@app.route('/get-key')
def dispenser():
    # SECURITY: Check if user came from Work.ink to prevent direct link sharing
    referrer = request.headers.get("Referer", "")
    if "work.ink" not in referrer and "localhost" not in referrer:
         return "<h1>Access Denied</h1><p>Please complete the tasks on Work.ink first.</p>", 403

    # Find ONE unactivated key from MongoDB
    key_doc = keys_col.find_one({"status": "unactivated"})
    
    if not key_doc:
        return "<h1>Out of Keys!</h1><p>The owner needs to run !add_keys in Discord.</p>", 404
    
    # Professional HTML Display
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Key Dispenser</title>
        <style>
            body { background: #1a1a1a; color: white; font-family: sans-serif; text-align: center; padding-top: 100px; }
            .box { background: #2d2d2d; padding: 40px; border-radius: 15px; display: inline-block; border: 1px solid #444; }
            h1 { color: #5865F2; }
            .key { font-size: 32px; font-weight: bold; background: #111; padding: 20px; border: 2px dashed #5865F2; margin: 20px 0; color: #fff; }
            .btn { background: #5865F2; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; text-decoration: none; }
        </style>
    </head>
    <body>
        <div class="box">
            <h1>Your Script Key</h1>
            <p>Copy this key and use the Redeem button in Discord.</p>
            <div class="key" id="keyText">{{ key }}</div>
            <button class="btn" onclick="copyKey()">Copy Key</button>
        </div>
        <script>
            function copyKey() {
                var text = document.getElementById("keyText").innerText;
                navigator.clipboard.writeText(text);
                alert("Key Copied!");
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template, key=key_doc["key"])

@app.route('/check', methods=['GET'])
def verify():
    key = request.args.get('key')
    hwid = request.args.get('hwid')
    if not key or not hwid: return "invalid", 400
    found = keys_col.find_one({"key": key.strip()})
    if found and found["status"] == "active":
        expiry_dt = datetime.datetime.strptime(found["expires"], '%Y-%m-%d %H:%M:%S')
        if datetime.datetime.now() < expiry_dt and found["hwid"] == hwid:
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
            await interaction.response.send_message("❌ Key already used!", ephemeral=True)
        else:
            expiry = datetime.datetime.now() + datetime.timedelta(hours=24)
            keys_col.update_one({"key": key_val}, {"$set": {
                "hwid": hwid_val,
                "expires": expiry.strftime('%Y-%m-%d %H:%M:%S'),
                "status": "active",
                "owner_id": interaction.user.id
            }})
            await interaction.response.send_message(f"✅ Activated! Expires: {expiry.strftime('%Y-%m-%d %H:%M')}", ephemeral=True)

class ResetHWIDModal(discord.ui.Modal, title="Reset HWID"):
    key_input = discord.ui.TextInput(label="Enter Your Activated Key")
    async def on_submit(self, interaction: discord.Interaction):
        key_val = self.key_input.value.strip()
        found = keys_col.find_one({"key": key_val, "owner_id": interaction.user.id})
        if found:
            keys_col.update_one({"key": key_val}, {"$set": {"hwid": None, "status": "unactivated"}})
            await interaction.response.send_message("✅ HWID Reset!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Error resetting HWID.", ephemeral=True)

# --- INTERFACE ---
class MainMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Free Key", style=discord.ButtonStyle.link, url=WORKINK_LINK))

    @discord.ui.button(label="View Script", style=discord.ButtonStyle.blurple, emoji="📜")
    async def view_script(self, interaction: discord.Interaction):
        grabber = "```lua\nsetclipboard(game:GetService('RbxAnalyticsService'):GetClientId())\nprint('HWID Copied!')\n```"
        await interaction.response.send_message(f"Run this to get HWID:\n{grabber}", ephemeral=True)

    @discord.ui.button(label="Redeem Key", style=discord.ButtonStyle.green, emoji="🔑")
    async def redeem_key(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RedeemModal())

    @discord.ui.button(label="Reset HWID", style=discord.ButtonStyle.danger, emoji="⚙️")
    async def reset_hwid(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ResetHWIDModal())

# --- COMMANDS ---
@bot.command()
async def setup_panel(ctx):
    if ctx.author.id != ADMIN_ID: return
    embed = discord.Embed(title="AutoFarm Dhc", description="Manage your keys below\nPolSec | v5", color=0x5865F2)
    await ctx.send(embed=embed, view=MainMenuView())

@bot.command()
async def add_keys(ctx, amount: int):
    if ctx.author.id != ADMIN_ID: return
    for _ in range(amount):
        k = str(uuid.uuid4())[:8].upper()
        keys_col.insert_one({"key": k, "hwid": None, "expires": None, "status": "unactivated", "owner_id": None})
    await ctx.send(f"✅ {amount} keys added to MongoDB pool.")

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
