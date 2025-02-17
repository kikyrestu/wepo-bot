import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import youtube_dl
from discord import FFmpegPCMAudio
from youtube_dl import YoutubeDL

# Load token dari file .env
load_dotenv()

# Setup intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Tambahin ini buat akses member
intents.guilds = True   # Tambahin ini buat akses guild/server

# Bikin instance bot
bot = commands.Bot(command_prefix='!', intents=intents)

# Simpan tiket yang aktif
active_tickets = {}

# Tambahin variabel baru untuk welcome message
welcome_messages = {}
welcome_channels = {}

# Tambahin dictionary buat nyimpen queue musik per server
music_queue = {}
current_song = {}

@bot.event
async def on_ready():
    print(f'Waduh! {bot.user} udah online nih!')
    
# Setup kategori dan role handler
async def setup_ticket_system(guild):
    # Bikin kategori buat tiket kalo belom ada
    category = discord.utils.get(guild.categories, name='TIKET SUPPORT')
    if not category:
        category = await guild.create_category('TIKET SUPPORT')
    
    # Bikin role staff kalo belom ada
    staff_role = discord.utils.get(guild.roles, name='Staff')
    if not staff_role:
        staff_role = await guild.create_role(name='Staff', color=discord.Color.blue())
    
    return category, staff_role

@bot.command(name='tiket')
async def create_ticket(ctx):
    # Setup sistem tiket
    category, staff_role = await setup_ticket_system(ctx.guild)
    
    # Bikin channel khusus buat tiket
    channel_name = f'tiket-{ctx.author.name.lower()}'
    
    # Cek kalo user udah punya tiket aktif
    if ctx.author.id in active_tickets:
        await ctx.send(f'Lu udah punya tiket yang aktif di <#{active_tickets[ctx.author.id]}> nih!')
        return
    
    # Set permission buat channel tiket
    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
        ctx.author: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        staff_role: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        ctx.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    
    # Bikin channel baru
    ticket_channel = await ctx.guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites
    )
    
    # Simpan tiket ke dictionary
    active_tickets[ctx.author.id] = ticket_channel.id
    
    # Kirim pesan welcome
    embed = discord.Embed(
        title="🎫 Tiket Support",
        description=f"Halo {ctx.author.mention}!\nStaff kita bakal segera bantu lu.\nKalo udah selesai, ketik `!tutup` ya!",
        color=discord.Color.green()
    )
    
    await ticket_channel.send(embed=embed)
    await ctx.send(f'Tiket lu udah dibuat nih di {ticket_channel.mention}!')

@bot.command(name='tutup')
async def close_ticket(ctx):
    # Cek kalo channel ini adalah tiket
    if not ctx.channel.name.startswith('tiket-'):
        return
    
    # Cari user yang bikin tiket
    ticket_owner_id = None
    for user_id, channel_id in active_tickets.items():
        if channel_id == ctx.channel.id:
            ticket_owner_id = user_id
            break
    
    if ticket_owner_id:
        # Hapus dari dictionary
        del active_tickets[ticket_owner_id]
        
        # Kirim pesan sebelum nutup
        embed = discord.Embed(
            title="🎫 Tiket Ditutup",
            description="Tiket ini bakal dihapus dalam 5 detik...",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        
        # Tunggu 5 detik
        import asyncio
        await asyncio.sleep(5)
        
        # Hapus channel
        await ctx.channel.delete()

@bot.command(name='tambahstaff')
@commands.has_permissions(administrator=True)
async def add_staff(ctx, member: discord.Member):
    # Dapetin role staff
    staff_role = discord.utils.get(ctx.guild.roles, name='Staff')
    if not staff_role:
        await ctx.send('Role Staff belom ada nih! Coba bikin tiket dulu ya.')
        return
    
    # Kasih role ke member
    await member.add_roles(staff_role)
    await ctx.send(f'{member.mention} udah dijadiin Staff nih!')

@bot.command(name='sapa')
async def sapa(ctx):
    await ctx.send(f'Halo bang {ctx.author.name}! Apa kabar lu?')

@bot.command(name='ping')
async def ping(ctx):
    await ctx.send(f'Pong! Latency: {round(bot.latency * 1000)}ms')

@bot.command(name='joke')
async def joke(ctx):
    jokes = [
        "Kenapa programmer gak suka keluar? Karena ada bug di luar!",
        "Apa bedanya programmer sama tukang bohong? Kalo programmer bohongnya pake boolean!",
        "Kenapa programmer suka gelap? Karena dark mode lebih enak di mata!",
        "99 bugs in the code, take one down, patch it around... 127 bugs in the code!"
    ]
    import random
    await ctx.send(random.choice(jokes))

@bot.command(name='sw')
@commands.has_permissions(administrator=True)
async def set_welcome(ctx, *, message):
    """Set welcome message. Cara pake:
    !sw Halo {member}! Welcome ke server!
    Note: {member} bakal ke-replace jadi mention member baru"""
    welcome_messages[ctx.guild.id] = message
    await ctx.send(f'Sip bre! Welcome message udah diset:\n{message}')

@bot.command(name='swc')
@commands.has_permissions(administrator=True)
async def set_welcome_channel(ctx, channel: discord.TextChannel):
    """Set channel buat welcome message. Cara pake:
    !swc #nama-channel"""
    welcome_channels[ctx.guild.id] = channel.id
    await ctx.send(f'Oke bre! Welcome message bakal muncul di {channel.mention}')

@bot.command(name='fakeuser')
@commands.has_permissions(administrator=True)
async def fake_join(ctx, count: int = 1):
    """Bikin fake user join buat test welcome message. Cara pake:
    !fakeuser 5 -> bikin 5 fake user
    !fakeuser -> bikin 1 fake user"""
    
    if count > 10:
        await ctx.send('Waduh, jangan kebanyakan bre! Max 10 user aja ya.')
        return
        
    fake_names = [
        "TestUser", "DummyMember", "FakeGuy", "BotTester", 
        "MockUser", "TestDummy", "FakePerson", "TesterBot",
        "DummyUser", "TestPerson"
    ]
    
    import random
    
    # Cek kalo server udah set welcome message dan channel
    if ctx.guild.id not in welcome_messages or ctx.guild.id not in welcome_channels:
        await ctx.send('Setup welcome message dulu bre! Pake !sw dan !swc')
        return
        
    channel_id = welcome_channels[ctx.guild.id]
    channel = ctx.guild.get_channel(channel_id)
    
    if not channel:
        await ctx.send('Channel welcome ga ketemu bre! Setup ulang pake !swc')
        return
        
    # Generate fake users
    for i in range(count):
        fake_name = f"{random.choice(fake_names)}{random.randint(1, 999)}"
        message = welcome_messages[ctx.guild.id].replace('{member}', f"**{fake_name}**")
        await channel.send(message)
    
    await ctx.send(f'Done bre! Udah gw generate {count} fake user di {channel.mention}')

@bot.command(name='join')
async def join(ctx):
    if ctx.author.voice is None:
        await ctx.send("Lu join voice channel dulu dong bro!")
        return
    
    voice_channel = ctx.author.voice.channel
    if ctx.voice_client is None:
        await voice_channel.connect()
    else:
        await ctx.voice_client.move_to(voice_channel)
    
    await ctx.send(f'Joined {voice_channel.name} 🎵')

@bot.command(name='leave')
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("Cabut dulu ya bre! 👋")
    else:
        await ctx.send("Gua ga di voice channel mana-mana bre!")

# Jalanin bot pake token
bot.run(os.getenv('DISCORD_TOKEN'))
