import discord
from discord.ext import commands
import pymongo
from pymongo import MongoClient
import datetime
import uuid
import os
import threading
from flask import Flask, request, render_template_string

# --- CONFIGURATION ---
TOKEN = os.environ.get("DISCORD_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 598460565387476992))
WORKINK_LINK = os.environ.get("WORKINK_LINK", "https://work.ink/1W4t/this-time")
MONGO_URL = os.environ.get("MONGO_URL")
# Replace the URL below with your Raw GitHub/Gist link where the obfuscated script is hosted
SCRIPT_URL = "https://raw.githubusercontent.com/Bedrock221/vault/refs/heads/main/vault"

# --- DATABASE SETUP ---
client = MongoClient(MONGO_URL)
db = client["KeySystem"]
keys_col = db["keys"]

# --- FLASK API ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Verification Server Online", 200

@app.route('/get-key')
def dispenser():
    referrer = request.headers.get("Referer", "")
    if "work.ink" not in referrer and "localhost" not in referrer:
         return "<h1>Access Denied</h1><p>Please complete the tasks on Work.ink first.</p>", 403

    key_doc = keys_col.find_one({"status": "unactivated"})
    if not key_doc:
        return "<h1>Out of Keys!</h1><p>The owner needs to run !add_keys in Discord.</p>", 404
    
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
    hwid_input = discord.ui.TextInput(label="Enter Your HWID", placeholder="Paste from script output...")

    async def on_submit(self, interaction: discord.Interaction):
        key_val = self.key_input.value.strip()
        hwid_val = self.hwid_input.value.strip()
        found = keys_col.find_one({"key": key_val})

        if not found:
            await interaction.response.send_message("❌ Invalid Key!", ephemeral=True)
        elif found["status"] == "active":
            await interaction.response.send_message("❌ Key already used!", ephemeral=True)
        else:
            expiry = datetime.datetime.now() + datetime.timedelta(hours=24)
            keys_col.update_one({"key": key_val}, {"$set": {
                "hwid": hwid_val,
                "expires": expiry.strftime('%Y-%m-%d %H:%M:%S'),
                "status": "active",
                "owner_id": interaction.user.id
            }})
            
            # THE RESPONSE CONTAINING THE SCRIPT
            script_payload = f"```lua\ngetgenv().key = \"{key_val}\"\nloadstring(game:HttpGet(\"{SCRIPT_URL}\"))()\n```"
            
            embed = discord.Embed(
                title="✅ Activation Successful",
                description=f"Your key is now linked to your HWID.\n**Expires:** {expiry.strftime('%Y-%m-%d %H:%M')}\n\n**Copy and paste this into your executor:**",
                color=0x2ecc71
            )
            await interaction.response.send_message(embed=embed, content=script_payload, ephemeral=True)

# --- INTERFACE ---
class MainMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Free Key", style=discord.ButtonStyle.link, url=WORKINK_LINK))

    @discord.ui.button(label="Redeem Key", style=discord.ButtonStyle.green, emoji="🔑")
    async def redeem_key(self, interaction: discord.Interaction, button: discord.ui.Button):
        grabber = "```lua\nsetclipboard(game:GetService('RbxAnalyticsService'):GetClientId())\nprint('HWID Copied!')\n```"
        embed = discord.Embed(
            title="Step 2: Get HWID",
            description=f"To link your key, you need your HWID.\n\n1. Run this in your executor:\n{grabber}\n2. Once copied, click the button below.",
            color=0x5865F2
        )
        
        view = discord.ui.View()
        async def open_modal(inter):
            await inter.response.send_modal(RedeemModal())
            
        btn = discord.ui.Button(label="Submit Details", style=discord.ButtonStyle.blurple)
        btn.callback = open_modal
        view.add_item(btn)
        
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Reset HWID", style=discord.ButtonStyle.danger, emoji="⚙️")
    async def reset_hwid(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Look for the active key owned by this specific Discord user
        found = keys_col.find_one({"owner_id": interaction.user.id, "status": "active"})
        
        if found:
            # We reset the key so it's 'unactivated' again, 
            # allowing the same user (or someone else) to redeem it with a new HWID.
            keys_col.update_one(
                {"_id": found["_id"]}, 
                {"$set": {
                    "hwid": None, 
                    "status": "unactivated", 
                    "owner_id": None,
                    "expires": None
                }}
            )
            await interaction.response.send_message("✅ **HWID Reset Successful!**\nYou can now use your key again with a new HWID by clicking **Redeem Key**.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ **Error:** You do not have an active key linked to this Discord account.", ephemeral=True)
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
    await ctx.send(f"✅ {amount} keys added to pool.")

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
