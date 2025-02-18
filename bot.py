import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp as youtube_dl
from discord import FFmpegPCMAudio
from datetime import datetime, timedelta
import asyncio
import socket
import struct
from discord.ui import Button, View
import mysql.connector
from mysql.connector import Error
from contextlib import contextmanager
import secrets
import hashlib
from typing import Optional
from discord.ext import tasks

# Load token dari file .env
load_dotenv()

# Setup intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Tambahin ini buat akses member
intents.guilds = True   # Tambahin ini buat akses guild/server

# Bikin instance bot
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Simpan tiket yang aktif
active_tickets = {}

# Tambahin variabel buat welcome message
# welcome_messages = {}  # Hapus
# welcome_channels = {}  # Hapus

# Tambahin dictionary buat nyimpen queue musik per server
music_queue = {}
current_song = {}

# Tambahin di atas
permission_levels = {
    'admin': 3,
    'mod': 2,
    'staff': 1,
    'member': 0
}

# Dictionary buat nyimpen role per server
server_roles = {}  # {guild_id: {'admin': role_id, 'mod': role_id, 'staff': role_id}}
temp_permissions = {}  # {user_id: {'role_id': expiry_timestamp}}

# Tambahin di atas, buat dokumentasi permission
ROLE_PERMISSIONS = {
    'Owner/Admin': {
        'level': 3,
        'permissions': [
            '- Akses semua command bot',
            '- Manage server settings',
            '- Manage roles & permissions',
            '- Ban/unban members',
            '- Manage channels',
            '- Set permission roles',
            '- View audit logs'
        ]
    },
    'Moderator': {
        'level': 2,
        'permissions': [
            '- Manage messages',
            '- Kick members',
            '- Mute/unmute members',
            '- Lock/unlock channels',
            '- Handle tickets',
            '- Manage voice channels',
            '- Timeout members'
        ]
    },
    'Staff': {
        'level': 1,
        'permissions': [
            '- Basic moderation',
            '- Handle tickets',
            '- Welcome new members',
            '- Manage music bot',
            '- Post announcements',
            '- Help members'
        ]
    },
    'Member': {
        'level': 0,
        'permissions': [
            '- Create tickets',
            '- Use music commands',
            '- View channels',
            '- Send messages',
            '- Join voice channels'
        ]
    }
}

temp_roles = {}  # {user_id: {role_id: expiry_timestamp}}
role_hierarchy = {
    5: "Administrator",    # Highest
    4: "Server Moderator",
    3: "Channel Moderator",
    2: "Chat Moderator",
    1: "Member"           # Lowest
}

# Tambahin di atas
filter_words = {}  # {guild_id: {'words': [], 'links': bool, 'invites': bool}}
filter_channels = {}  # {guild_id: [channel_ids]}
filter_bypass = {}  # {guild_id: [role_ids]}

# Simpan dev sessions di memory
dev_sessions = {}  # {user_id: {'session_id': str, 'expires_at': timestamp}}

def create_db_connection():
    """Buat koneksi ke database"""
    try:
        connection = mysql.connector.connect(
            host=os.getenv('DB_HOST'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME')
        )
        return connection
    except Error as e:
        print(f"Error connecting to MySQL Database: {e}")
        return None

def create_tables():
    """Buat tabel yang dibutuhkan"""
    connection = create_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            
            # Tabel untuk welcome messages
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS welcome_messages (
                    guild_id BIGINT PRIMARY KEY,
                    message TEXT,
                    channel_id BIGINT
                )
            """)
            
            # Tabel untuk music queue
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS music_queue (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    guild_id BIGINT,
                    url TEXT,
                    title VARCHAR(255),
                    duration VARCHAR(10),
                    position INT
                )
            """)
            
            # Tabel untuk roles
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS server_roles (
                    guild_id BIGINT,
                    role_type VARCHAR(50),
                    role_id BIGINT,
                    PRIMARY KEY (guild_id, role_type)
                )
            """)
            
            # Tabel untuk temporary roles
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS temp_roles (
                    user_id BIGINT,
                    role_id BIGINT,
                    guild_id BIGINT,
                    expiry TIMESTAMP,
                    PRIMARY KEY (user_id, role_id)
                )
            """)
            
            # Tabel untuk filter words
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS filter_words (
                    guild_id BIGINT,
                    word VARCHAR(255),
                    PRIMARY KEY (guild_id, word)
                )
            """)
            
            # Tabel untuk developer credentials
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dev_credentials (
                    user_id BIGINT PRIMARY KEY,
                    username VARCHAR(255),
                    token VARCHAR(255),
                    last_login TIMESTAMP NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Tabel untuk dev sessions
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dev_sessions (
                    session_id VARCHAR(64) PRIMARY KEY,
                    user_id BIGINT,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES dev_credentials(user_id)
                )
            """)
            
            # Tabel untuk dev logs
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dev_logs (
                    log_id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT,
                    action VARCHAR(255),
                    details TEXT,
                    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES dev_credentials(user_id)
                )
            """)
            
            # Tabel untuk custom responses
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS custom_responses (
                    response_id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    guild_id BIGINT,
                    trigger_word VARCHAR(100),
                    response TEXT,
                    created_by BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE,
                    UNIQUE KEY unique_trigger (guild_id, trigger_word)
                )
            """)
            
            connection.commit()
            print("Database tables created successfully")
            
        except Error as e:
            print(f"Error creating tables: {e}")
        finally:
            cursor.close()
            connection.close()

@contextmanager
def get_db_cursor():
    """Context manager untuk database cursor"""
    connection = create_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            yield cursor
            connection.commit()
        except Error as e:
            print(f"Database error: {e}")
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

@bot.event
async def on_ready():
    print(f'Waduh! {bot.user} udah online nih!')
    create_tables()  # Setup database tables
    
    @bot.event
    async def on_command_error(ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ Lu ga punya permission buat pake command ini bre! Admin only 😎")
        elif isinstance(error, commands.CommandNotFound):
            await ctx.send("❌ Command ga ada bre! Coba cek !help")

    # Start background task
    check_trial_reminders.start()

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

    
@bot.command(name='sw')
@commands.has_permissions(administrator=True)
async def set_welcome(ctx, *, message):
    """Set welcome message"""
    try:
        with get_db_cursor() as cursor:
            # Simpan atau update welcome message
            sql = """INSERT INTO welcome_messages (guild_id, message)
                     VALUES (%s, %s)
                     ON DUPLICATE KEY UPDATE message = %s"""
            cursor.execute(sql, (ctx.guild.id, message, message))
            
        await ctx.send(f'Sip bre! Welcome message udah diset:\n{message}')
    except Error as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='swc')
@commands.has_permissions(administrator=True)
async def set_welcome_channel(ctx, channel: discord.TextChannel):
    """Set channel buat welcome message"""
    try:
        with get_db_cursor() as cursor:
            # Update atau insert channel
            sql = """INSERT INTO welcome_messages (guild_id, channel_id)
                     VALUES (%s, %s)
                     ON DUPLICATE KEY UPDATE channel_id = %s"""
            cursor.execute(sql, (ctx.guild.id, channel.id, channel.id))
            
        await ctx.send(f'Oke bre! Welcome message bakal muncul di {channel.mention}')
    except Error as e:
        await ctx.send(f"Error: {str(e)}")

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

@bot.command(name='play')
async def play(ctx, *, query):
    if ctx.author.voice is None:
        await ctx.send("Lu join voice channel dulu dong bro!")
        return
        
    if ctx.voice_client is None:
        await ctx.invoke(bot.get_command('join'))
    
    # Setup yt-dlp
    YDL_OPTIONS = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'ytsearch',
        'source_address': '0.0.0.0'
    }
    FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}
    
    with youtube_dl.YoutubeDL(YDL_OPTIONS) as ydl:
        try:
            # Kalo bukan URL, search dulu
            if not query.startswith('https://'):
                await ctx.send(f'🔎 Nyari: {query}')
                query = f'ytsearch:{query}'
            
            info = ydl.extract_info(query, download=False)
            
            # Kalo hasil search, ambil video pertama
            if 'entries' in info:
                info = info['entries'][0]
            
            URL = info['url']
            title = info['title']
            duration = info.get('duration', 0)  # Dapetin durasi dalam detik
            
            # Format durasi jadi menit:detik
            minutes = duration // 60
            seconds = duration % 60
            duration_text = f'{minutes}:{seconds:02d}'
            
            # Tambahin ke queue kalo udah ada yang main
            if ctx.voice_client.is_playing():
                if ctx.guild.id not in music_queue:
                    music_queue[ctx.guild.id] = []
                music_queue[ctx.guild.id].append({'url': URL, 'title': title, 'duration': duration_text})
                await ctx.send(f'Added to queue: {title} ({duration_text})')
                return
            
            # Main musiknya
            ctx.voice_client.play(FFmpegPCMAudio(URL, **FFMPEG_OPTIONS))
            current_song[ctx.guild.id] = {'title': title, 'duration': duration_text}
            await ctx.send(f'Now playing: {title} ({duration_text}) 🎶')
            
        except Exception as e:
            await ctx.send(f'Waduh error bre: {str(e)}')

@bot.command(name='skip')
async def skip(ctx):
    if ctx.voice_client is None:
        await ctx.send("Gua ga lagi main musik bre!")
        return
    
    if not ctx.voice_client.is_playing():
        await ctx.send("Ga ada yang lagi main bre!")
        return
        
    ctx.voice_client.stop()
    await ctx.send("Skipped! ⏭️")
    
    # Main lagu selanjutnya dari queue
    if ctx.guild.id in music_queue and music_queue[ctx.guild.id]:
        next_song = music_queue[ctx.guild.id].pop(0)
        FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}
        ctx.voice_client.play(FFmpegPCMAudio(next_song['url'], **FFMPEG_OPTIONS))
        current_song[ctx.guild.id] = next_song['title']
        await ctx.send(f'Now playing: {next_song["title"]} 🎶')

@bot.command(name='queue')
async def queue(ctx):
    if ctx.guild.id not in music_queue or not music_queue[ctx.guild.id]:
        await ctx.send("Queue kosong bre!")
        return
        
    queue_list = "🎵 Queue:\n"
    for i, song in enumerate(music_queue[ctx.guild.id], 1):
        queue_list += f"{i}. {song['title']} ({song['duration']})\n"
    
    if ctx.guild.id in current_song:
        current = current_song[ctx.guild.id]
        queue_list = f"🎵 Now Playing: {current['title']} ({current['duration']})\n\n" + queue_list
        
    await ctx.send(queue_list)

@bot.command(name='vc')  # Singkatan dari 'voice channel'
@commands.has_permissions(manage_channels=True)
async def create_voice(ctx, *, name):
    """Bikin voice channel
    Contoh: !vc Gaming Room"""
    try:
        channel = await ctx.guild.create_voice_channel(name=name)
        await ctx.send(f'✅ Voice channel {channel.mention} dibuat!')
    except Exception as e:
        await ctx.send(f'Error: {str(e)}')

@bot.command(name='tc')  # Singkatan dari 'text channel'
@commands.has_permissions(manage_channels=True)
async def create_text(ctx, *, name):
    """Bikin text channel
    Contoh: !tc gaming-chat"""
    try:
        channel = await ctx.guild.create_text_channel(name=name)
        await ctx.send(f'✅ Text channel {channel.mention} dibuat!')
    except Exception as e:
        await ctx.send(f'Error: {str(e)}')

@bot.command(name='cat')  # Singkatan dari 'category'
@commands.has_permissions(manage_channels=True)
async def create_category(ctx, *, name):
    """Bikin category
    Contoh: !cat GAMING"""
    try:
        category = await ctx.guild.create_category(name=name.upper())
        await ctx.send(f'✅ Category {category.name} dibuat!')
    except Exception as e:
        await ctx.send(f'Error: {str(e)}')

@bot.command(name='del')  # Singkatan dari 'delete'
@commands.has_permissions(manage_channels=True)
async def delete_channel(ctx, channel: discord.TextChannel | discord.VoiceChannel):
    """Hapus channel
    Contoh: !del #gaming-chat"""
    try:
        await channel.delete()
        await ctx.send(f'❌ Channel dihapus!')
    except Exception as e:
        await ctx.send(f'Error: {str(e)}')

@bot.command(name='mv')  # Singkatan dari 'move'
@commands.has_permissions(manage_channels=True)
async def move_channel(ctx, channel: discord.TextChannel | discord.VoiceChannel, *, category):
    """Pindahin channel ke category
    Contoh: !mv #gaming-chat GAMING"""
    try:
        cat = discord.utils.get(ctx.guild.categories, name=category.upper())
        if not cat:
            return await ctx.send('Category ga ketemu!')
        await channel.edit(category=cat)
        await ctx.send(f'✅ {channel.mention} dipindah ke {cat.name}!')
    except Exception as e:
        await ctx.send(f'Error: {str(e)}')

@bot.command(name='lock')
@commands.has_permissions(manage_channels=True)
async def lock_channel(ctx, channel: discord.TextChannel | discord.VoiceChannel = None):
    """Kunci channel
    Contoh: !lock #secret-chat"""
    channel = channel or ctx.channel
    try:
        perms = channel.overwrites_for(ctx.guild.default_role)
        perms.send_messages = False if isinstance(channel, discord.TextChannel) else None
        perms.connect = False if isinstance(channel, discord.VoiceChannel) else None
        await channel.set_permissions(ctx.guild.default_role, overwrite=perms)
        await ctx.send(f'🔒 {channel.mention} dikunci!')
    except Exception as e:
        await ctx.send(f'Error: {str(e)}')

@bot.command(name='unlock')
@commands.has_permissions(manage_channels=True)
async def unlock_channel(ctx, channel: discord.TextChannel | discord.VoiceChannel = None):
    """Buka kunci channel
    Contoh: !unlock #general-chat"""
    channel = channel or ctx.channel
    try:
        perms = channel.overwrites_for(ctx.guild.default_role)
        perms.send_messages = True if isinstance(channel, discord.TextChannel) else None
        perms.connect = True if isinstance(channel, discord.VoiceChannel) else None
        await channel.set_permissions(ctx.guild.default_role, overwrite=perms)
        await ctx.send(f'🔓 {channel.mention} dibuka!')
    except Exception as e:
        await ctx.send(f'Error: {str(e)}')

@bot.command(name='setrole')
@commands.has_permissions(administrator=True)
async def set_permission_role(ctx, level: str, role: discord.Role):
    """Set role buat tiap permission level
    Contoh: !setrole mod @Moderator"""
    
    if level.lower() not in permission_levels:
        return await ctx.send("Level invalid! Pilih: admin/mod/staff")
        
    if ctx.guild.id not in server_roles:
        server_roles[ctx.guild.id] = {}
    
    server_roles[ctx.guild.id][level.lower()] = role.id
    await ctx.send(f'✅ Role {role.mention} udah diset sebagai {level.upper()}!')

@bot.command(name='temprole')
@commands.has_permissions(administrator=True)
async def temp_role(ctx, member: discord.Member, role: discord.Role, duration: int):
    """Kasih role sementara (dalam jam)
    Contoh: !temprole @user @Staff 24"""
    
    # Set expiry time
    expiry = datetime.now() + timedelta(hours=duration)
    
    # Simpan ke temp_permissions
    if member.id not in temp_permissions:
        temp_permissions[member.id] = {}
    
    temp_permissions[member.id][role.id] = expiry.timestamp()
    
    # Kasih rolenya
    await member.add_roles(role)
    await ctx.send(f'✅ {member.mention} dapet role {role.mention} selama {duration} jam!')

@bot.command(name='checkperm')
async def check_permissions(ctx, member: discord.Member = None):
    """Cek permission level user
    Contoh: !checkperm @user"""
    
    member = member or ctx.author
    level = 'member'  # Default level
    
    # Cek role yang dipunya
    if ctx.guild.id in server_roles:
        for perm_level, role_id in server_roles[ctx.guild.id].items():
            if discord.utils.get(member.roles, id=role_id):
                if permission_levels[perm_level] > permission_levels.get(level, 0):
                    level = perm_level
    
    # Cek temporary roles
    temp_roles = []
    if member.id in temp_permissions:
        current_time = datetime.now().timestamp()
        for role_id, expiry in temp_permissions[member.id].items():
            if current_time < expiry:
                role = discord.utils.get(ctx.guild.roles, id=role_id)
                if role:
                    temp_roles.append(f"{role.name} (expires <t:{int(expiry)}:R>)")
            else:
                # Hapus role yang udah expired
                role = discord.utils.get(ctx.guild.roles, id=role_id)
                if role and role in member.roles:
                    await member.remove_roles(role)
    
    # Bikin embed
    embed = discord.Embed(
        title="🔑 Permission Check",
        color=discord.Color.blue()
    )
    embed.add_field(name="User", value=member.mention, inline=False)
    embed.add_field(name="Level", value=level.upper(), inline=True)
    embed.add_field(name="Permission Value", value=permission_levels[level], inline=True)
    
    if temp_roles:
        embed.add_field(name="Temporary Roles", value="\n".join(temp_roles), inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='listroles')
@commands.has_permissions(administrator=True)
async def list_permission_roles(ctx):
    """Liat semua role permission yang udah diset"""
    
    if ctx.guild.id not in server_roles or not server_roles[ctx.guild.id]:
        return await ctx.send("Belom ada role yang diset bre!")
    
    embed = discord.Embed(
        title="🔑 Permission Roles",
        description="Role yang udah diset buat tiap level:",
        color=discord.Color.gold()
    )
    
    for level, role_id in server_roles[ctx.guild.id].items():
        role = discord.utils.get(ctx.guild.roles, id=role_id)
        if role:
            embed.add_field(
                name=level.upper(),
                value=f"{role.mention}\nLevel: {permission_levels[level]}",
                inline=True
            )
    
    await ctx.send(embed=embed)

# Function buat cek permission level
def get_permission_level(member: discord.Member) -> int:
    guild_id = member.guild.id
    if guild_id not in server_roles:
        return 0  # Default ke member
        
    highest_level = 0
    for level, role_id in server_roles[guild_id].items():
        if discord.utils.get(member.roles, id=role_id):
            if permission_levels[level] > highest_level:
                highest_level = permission_levels[level]
    
    return highest_level

# Decorator custom buat cek permission
def require_permission_level(level: int):
    async def predicate(ctx):
        return get_permission_level(ctx.author) >= level
    return commands.check(predicate)

# Contoh pake decorator
@bot.command(name='modcommand')
@require_permission_level(2)  # Perlu level mod (2) atau lebih tinggi
async def mod_only_command(ctx):
    await ctx.send("Command ini cuma bisa dipake mod ke atas!")

@bot.command(name='perms')
async def show_permissions(ctx, role: str = None):
    """Liat permission tiap role
    Contoh: !perms admin"""
    
    if role:
        # Liat permission specific role
        role = role.lower()
        for role_name, data in ROLE_PERMISSIONS.items():
            if role_name.lower().startswith(role):
                embed = discord.Embed(
                    title=f"🔑 {role_name} Permissions",
                    description=f"Level: {data['level']}",
                    color=discord.Color.blue()
                )
                embed.add_field(
                    name="Permissions",
                    value="\n".join(data['permissions']),
                    inline=False
                )
                return await ctx.send(embed=embed)
        await ctx.send("Role ga ketemu bre! Coba: admin/mod/staff/member")
    else:
        # Liat semua permission
        embed = discord.Embed(
            title="🔑 Server Permissions",
            description="Permission tiap role di server:",
            color=discord.Color.gold()
        )
        
        for role_name, data in ROLE_PERMISSIONS.items():
            perms = "\n".join(data['permissions'][:3]) + "\n..."  # Show first 3 perms
            embed.add_field(
                name=f"{role_name} (Level {data['level']})",
                value=perms,
                inline=False
            )
        
        embed.set_footer(text="Ketik !perms [role] buat liat detail permission")
        await ctx.send(embed=embed)

@bot.command(name='setuproles')
@commands.has_permissions(administrator=True)
async def setup_default_roles(ctx):
    """Setup default roles dengan permission yang recommended"""
    try:
        roles_created = []
        
        # Bikin role dari atas ke bawah (highest to lowest)
        for role_name, data in ROLE_PERMISSIONS.items():
            # Skip kalo role udah ada
            if discord.utils.get(ctx.guild.roles, name=role_name):
                continue
                
            # Set permission dan color per role
            if role_name == 'Owner/Admin':
                color = discord.Color.red()
                perms = discord.Permissions(administrator=True)
            elif role_name == 'Moderator':
                color = discord.Color.blue()
                perms = discord.Permissions(
                    manage_messages=True,
                    kick_members=True,
                    mute_members=True,
                    manage_channels=True
                )
            elif role_name == 'Staff':
                color = discord.Color.green()
                perms = discord.Permissions(
                    manage_messages=True,
                    mute_members=True
                )
            else:  # Member
                color = discord.Color.default()
                perms = discord.Permissions(
                    send_messages=True,
                    read_messages=True,
                    connect=True
                )
            
            # Bikin rolenya
            role = await ctx.guild.create_role(
                name=role_name,
                color=color,
                permissions=perms,
                hoist=True,  # Pisahin di member list
                mentionable=True
            )
            
            roles_created.append(role.mention)
            
            # Set role ke permission system
            await ctx.invoke(
                bot.get_command('setrole'),
                level=role_name.split('/')[0].lower(),
                role=role
            )
        
        if roles_created:
            await ctx.send(f"✅ Role yang udah dibuat:\n" + "\n".join(roles_created))
        else:
            await ctx.send("Semua role udah ada bre!")
            
    except Exception as e:
        await ctx.send(f"Error bre: {str(e)}")

@bot.command(name='setchannelaccess')
@commands.has_permissions(administrator=True)
async def set_channel_access(ctx, channel: discord.TextChannel | discord.VoiceChannel, role: discord.Role, access_type: str):
    """Set akses channel buat role tertentu
    Contoh: 
    !setchannelaccess #staff-chat @Staff view  (Cuma bisa liat)
    !setchannelaccess #staff-chat @Staff write (Bisa chat/ngomong)
    !setchannelaccess #staff-chat @Staff deny  (Ga bisa akses)"""
    
    try:
        if access_type.lower() == 'view':
            await channel.set_permissions(role, 
                read_messages=True,
                send_messages=False if isinstance(channel, discord.TextChannel) else None,
                connect=False if isinstance(channel, discord.VoiceChannel) else None
            )
            await ctx.send(f'✅ {role.mention} sekarang bisa liat {channel.mention}')
            
        elif access_type.lower() == 'write':
            await channel.set_permissions(role,
                read_messages=True,
                send_messages=True if isinstance(channel, discord.TextChannel) else None,
                connect=True if isinstance(channel, discord.VoiceChannel) else None,
                speak=True if isinstance(channel, discord.VoiceChannel) else None
            )
            await ctx.send(f'✅ {role.mention} sekarang bisa chat/ngomong di {channel.mention}')
            
        elif access_type.lower() == 'deny':
            await channel.set_permissions(role,
                read_messages=False,
                send_messages=False,
                connect=False,
                speak=False
            )
            await ctx.send(f'❌ {role.mention} ga bisa akses {channel.mention}')
            
        else:
            await ctx.send('Invalid access type! Pilih: view/write/deny')
            
    except Exception as e:
        await ctx.send(f'Error bre: {str(e)}')

@bot.command(name='channelaccess')
@commands.has_permissions(administrator=True)
async def check_channel_access(ctx, channel: discord.TextChannel | discord.VoiceChannel):
    """Cek siapa aja yang bisa akses channel
    Contoh: !channelaccess #staff-chat"""
    
    try:
        embed = discord.Embed(
            title=f"🔒 Channel Access: {channel.name}",
            color=discord.Color.blue()
        )
        
        # Cek permission overwrites
        for role, perms in channel.overwrites.items():
            if isinstance(role, discord.Role):
                access = []
                if perms.read_messages:
                    access.append("View ✅")
                if perms.send_messages or perms.connect:
                    access.append("Write/Speak ✅")
                if perms.read_messages == False:
                    access.append("Denied ❌")
                    
                if access:
                    embed.add_field(
                        name=role.name,
                        value="\n".join(access),
                        inline=True
                    )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f'Error bre: {str(e)}')

@bot.command(name='createprivatechannel')
@commands.has_permissions(administrator=True)
async def create_private_channel(ctx, channel_name: str, *roles: discord.Role):
    """Bikin private channel buat role tertentu
    Contoh: !createprivatechannel staff-chat @Staff @Mod @Admin"""
    
    try:
        # Set permission default (deny all)
        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(
                read_messages=False,
                send_messages=False
            )
        }
        
        # Kasih akses ke role yang disebutin
        for role in roles:
            overwrites[role] = discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True
            )
        
        # Bikin channelnya
        channel = await ctx.guild.create_text_channel(
            name=channel_name,
            overwrites=overwrites
        )
        
        # Bikin embed buat konfirmasi
        embed = discord.Embed(
            title="🔒 Private Channel Created",
            description=f"Channel: {channel.mention}",
            color=discord.Color.green()
        )
        
        roles_text = ", ".join([role.mention for role in roles])
        embed.add_field(name="Access Granted to:", value=roles_text)
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f'Error bre: {str(e)}')

@bot.command(name='tr')  # temp role
@commands.has_permissions(administrator=True)
async def temp_role(ctx, member: discord.Member, level: int, duration: int):
    """Kasih role sementara (dalam jam)
    Contoh: !tr @user 2 24 (Kasih level 2 selama 24 jam)"""
    try:
        if level not in permission_levels:
            return await ctx.send(f"❌ Level invalid! Coba cek `!rhelp`")
            
        # Bikin role name
        role_name = f"Temp {role_hierarchy[level]}"
        
        # Cari role yang udah ada atau bikin baru
        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if not role:
            permission_list = {}
            for perm_level in range(1, level + 1):
                for perm in permission_levels.values():
                    permission_list[perm] = True
                    
            role = await ctx.guild.create_role(
                name=role_name,
                permissions=discord.Permissions(**permission_list),
                color=discord.Color.orange(),
                reason="Temporary Role"
            )
        
        # Set expiry
        expiry = datetime.now() + timedelta(hours=duration)
        if member.id not in temp_roles:
            temp_roles[member.id] = {}
        temp_roles[member.id][role.id] = expiry.timestamp()
        
        # Kasih rolenya
        await member.add_roles(role)
        
        embed = discord.Embed(
            title="⏳ Temporary Role Added",
            color=discord.Color.orange()
        )
        embed.add_field(name="User", value=member.mention, inline=True)
        embed.add_field(name="Role", value=role.mention, inline=True)
        embed.add_field(name="Duration", value=f"{duration} jam", inline=True)
        embed.add_field(name="Expires", value=f"<t:{int(expiry.timestamp())}:R>", inline=True)
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f'Error: {str(e)}')

@bot.command(name='rcheck')  # role check
async def role_check(ctx, member: discord.Member = None):
    """Cek role dan permission user
    Contoh: !rcheck @user"""
    member = member or ctx.author
    
    try:
        embed = discord.Embed(
            title=f"👤 Role Check: {member.name}",
            color=member.color
        )
        
        # List regular roles
        regular_roles = [role for role in member.roles[1:] if role.id not in 
                        [r for roles in temp_roles.values() for r in roles]]
        if regular_roles:
            embed.add_field(
                name="Regular Roles",
                value="\n".join([role.mention for role in regular_roles]),
                inline=False
            )
        
        # List temporary roles
        if member.id in temp_roles:
            temp_list = []
            current_time = datetime.now().timestamp()
            
            for role_id, expiry in temp_roles[member.id].items():
                if current_time < expiry:
                    role = discord.utils.get(ctx.guild.roles, id=role_id)
                    if role:
                        temp_list.append(f"{role.mention} (expires <t:{int(expiry)}:R>)")
                else:
                    # Hapus role yang expired
                    role = discord.utils.get(ctx.guild.roles, id=role_id)
                    if role and role in member.roles:
                        await member.remove_roles(role)
                        
            if temp_list:
                embed.add_field(
                    name="Temporary Roles",
                    value="\n".join(temp_list),
                    inline=False
                )
        
        # Highest permission level
        highest_level = 1
        for role in member.roles:
            for level, perms in permission_levels.items():
                if any(getattr(role.permissions, perm) for perm in perms):
                    highest_level = max(highest_level, level)
        
        embed.add_field(
            name="Permission Level",
            value=f"Level {highest_level} ({role_hierarchy[highest_level]})",
            inline=True
        )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f'Error: {str(e)}')

# Update rhelp command
@bot.command(name='rhelp')
async def role_help(ctx):
    """Liat panduan role dan permission"""
    embed = discord.Embed(
        title="🔑 Role System Guide",
        color=discord.Color.blue()
    )
    
    # Permission levels
    levels = ""
    for level, name in role_hierarchy.items():
        perms = permission_levels.values()
        levels += f"\n**Level {level} - {name}**\n• " + "\n• ".join(perms)
    
    embed.add_field(
        name="Permission Levels",
        value=levels,
        inline=False
    )
    
    # Commands
    embed.add_field(
        name="Commands",
        value="""
        **Regular Roles:**
        `!ar [name] [color] [level]` - Bikin role baru
        `!rp @role [level]` - Update permission role
        
        **Temporary Roles:**
        `!tr @user [level] [hours]` - Kasih role sementara
        
        **Info & Check:**
        `!rcheck @user` - Cek role user
        `!rinfo @role` - Liat info role
        `!rl` - List semua role
        """,
        inline=False
    )
    
    await ctx.send(embed=embed)

@bot.command(name='stats')
@commands.has_permissions(administrator=True)
async def setup_stats(ctx):
    """Setup channel statistik server
    Contoh: !stats"""
    try:
        # Bikin category stats
        category = await ctx.guild.create_category("📊 SERVER STATS")
        
        # Bikin voice channels buat stats
        stats_channels = {
            "👥 Members": lambda g: len(g.members),
            "🟢 Online": lambda g: len([m for m in g.members if m.status != discord.Status.offline]),
            "🎮 In Game": lambda g: len([m for m in g.members if m.activity and m.activity.type == discord.ActivityType.playing]),
            "🎵 In Voice": lambda g: len([m for m in g.members if m.voice])
        }
        
        channels = {}
        for name, counter in stats_channels.items():
            channel = await ctx.guild.create_voice_channel(
                name=f"{name}: {counter(ctx.guild)}",
                category=category
            )
            # Set permission biar ga bisa join
            await channel.set_permissions(ctx.guild.default_role, connect=False)
            channels[name] = channel
        
        await ctx.send("✅ Channel stats udah dibuat!")
        
        # Update stats tiap 5 menit
        while True:
            await asyncio.sleep(300)  # 5 menit
            for name, counter in stats_channels.items():
                channel = channels[name]
                try:
                    await channel.edit(name=f"{name}: {counter(ctx.guild)}")
                except:
                    pass
                    
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='statscustom')
@commands.has_permissions(administrator=True)
async def custom_stats(ctx, *, name):
    """Bikin stats channel custom
    Contoh: !statscustom 🏆 Top Players"""
    try:
        # Cari category stats, kalo ga ada bikin baru
        category = discord.utils.get(ctx.guild.categories, name="📊 SERVER STATS")
        if not category:
            category = await ctx.guild.create_category("📊 SERVER STATS")
        
        # Bikin channel
        channel = await ctx.guild.create_voice_channel(
            name=f"{name}: 0",
            category=category
        )
        await channel.set_permissions(ctx.guild.default_role, connect=False)
        
        await ctx.send(f"✅ Stats channel `{name}` udah dibuat!")
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='statsremove')
@commands.has_permissions(administrator=True)
async def remove_stats(ctx, *, channel: discord.VoiceChannel):
    """Hapus stats channel
    Contoh: !statsremove "👥 Members" """
    try:
        if channel.category and channel.category.name == "📊 SERVER STATS":
            await channel.delete()
            await ctx.send(f"✅ Stats channel udah dihapus!")
        else:
            await ctx.send("❌ Itu bukan stats channel!")
            
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='statsupdate')
@commands.has_permissions(administrator=True)
async def update_stats(ctx):
    """Update manual stats channel
    Contoh: !statsupdate"""
    try:
        category = discord.utils.get(ctx.guild.categories, name="📊 SERVER STATS")
        if not category:
            return await ctx.send("❌ Stats category ga ketemu!")
            
        for channel in category.voice_channels:
            name = channel.name.split(':')[0].strip()
            
            if name == "👥 Members":
                count = len(ctx.guild.members)
            elif name == "🟢 Online":
                count = len([m for m in ctx.guild.members if m.status != discord.Status.offline])
            elif name == "🎮 In Game":
                count = len([m for m in ctx.guild.members if m.activity and m.activity.type == discord.ActivityType.playing])
            elif name == "🎵 In Voice":
                count = len([m for m in ctx.guild.members if m.voice])
            else:
                continue
                
            await channel.edit(name=f"{name}: {count}")
            
        await ctx.send("✅ Stats udah diupdate!")
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='ban')
@commands.has_permissions(ban_members=True)
async def ban_member(ctx, member: discord.Member, *, reason=None):
    """Ban member dari server
    Contoh: !ban @user Toxic gaming"""
    try:
        if member.top_role >= ctx.author.top_role:
            return await ctx.send("❌ Lu ga bisa ban member dengan role yang sama/lebih tinggi!")
            
        # Kirim DM ke member yang diban
        embed = discord.Embed(
            title="🔨 You've Been Banned",
            description=f"Lu udah diban dari {ctx.guild.name}",
            color=discord.Color.red()
        )
        embed.add_field(name="Reason", value=reason or "No reason provided")
        embed.add_field(name="Banned By", value=ctx.author.name)
        
        try:
            await member.send(embed=embed)
        except:
            pass  # Skip kalo ga bisa DM
            
        # Ban membernya
        await member.ban(reason=f"Banned by {ctx.author.name}: {reason}")
        
        # Kirim konfirmasi
        embed = discord.Embed(
            title="🔨 Member Banned",
            description=f"{member.mention} udah diban!",
            color=discord.Color.red()
        )
        embed.add_field(name="Banned By", value=ctx.author.mention)
        embed.add_field(name="Reason", value=reason or "No reason provided")
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='unban')
@commands.has_permissions(ban_members=True)
async def unban_member(ctx, *, member):
    """Unban member
    Contoh: !unban User#1234"""
    try:
        # Get ban entries
        bans = [ban_entry async for ban_entry in ctx.guild.bans()]
        
        # Cari member yang mau di-unban
        for ban_entry in bans:
            user = ban_entry.user
            
            if str(user) == member:
                await ctx.guild.unban(user)
                
                embed = discord.Embed(
                    title="✅ Member Unbanned",
                    description=f"{user.mention} udah di-unban!",
                    color=discord.Color.green()
                )
                embed.add_field(name="Unbanned By", value=ctx.author.mention)
                embed.set_thumbnail(url=user.display_avatar.url)
                
                return await ctx.send(embed=embed)
                
        await ctx.send(f"Member `{member}` ga ketemu di ban list!")
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='timeout')
@commands.has_permissions(moderate_members=True)
async def timeout_member(ctx, member: discord.Member, duration: int, *, reason=None):
    """Timeout/suspend member (dalam menit)
    Contoh: !timeout @user 60 Spam chat"""
    try:
        if member.top_role >= ctx.author.top_role:
            return await ctx.send("❌ Lu ga bisa timeout member dengan role yang sama/lebih tinggi!")
            
        # Convert duration ke timedelta
        duration = timedelta(minutes=duration)
        
        # Timeout membernya
        await member.timeout(duration, reason=reason)
        
        # Kirim DM ke member
        embed = discord.Embed(
            title="⏰ You've Been Timed Out",
            description=f"Lu kena timeout di {ctx.guild.name}",
            color=discord.Color.orange()
        )
        embed.add_field(name="Duration", value=f"{duration.total_seconds()/60:.0f} minutes")
        embed.add_field(name="Reason", value=reason or "No reason provided")
        embed.add_field(name="Timed Out By", value=ctx.author.name)
        
        try:
            await member.send(embed=embed)
        except:
            pass
            
        # Kirim konfirmasi
        embed = discord.Embed(
            title="⏰ Member Timed Out",
            description=f"{member.mention} udah di-timeout!",
            color=discord.Color.orange()
        )
        embed.add_field(name="Duration", value=f"{duration.total_seconds()/60:.0f} minutes")
        embed.add_field(name="Reason", value=reason or "No reason provided")
        embed.add_field(name="Timed Out By", value=ctx.author.mention)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='untimeout')
@commands.has_permissions(moderate_members=True)
async def untimeout_member(ctx, member: discord.Member):
    """Remove timeout dari member
    Contoh: !untimeout @user"""
    try:
        # Remove timeout
        await member.timeout(None)
        
        embed = discord.Embed(
            title="✅ Timeout Removed",
            description=f"Timeout {member.mention} udah dihapus!",
            color=discord.Color.green()
        )
        embed.add_field(name="Removed By", value=ctx.author.mention)
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='kick')
@commands.has_permissions(kick_members=True)
async def kick_member(ctx, member: discord.Member, *, reason=None):
    """Kick member dari server
    Contoh: !kick @user Spam invite"""
    try:
        if member.top_role >= ctx.author.top_role:
            return await ctx.send("❌ Lu ga bisa kick member dengan role yang sama/lebih tinggi!")
            
        # Kirim DM ke member
        embed = discord.Embed(
            title="👢 You've Been Kicked",
            description=f"Lu udah dikick dari {ctx.guild.name}",
            color=discord.Color.orange()
        )
        embed.add_field(name="Reason", value=reason or "No reason provided")
        embed.add_field(name="Kicked By", value=ctx.author.name)
        
        try:
            await member.send(embed=embed)
        except:
            pass
            
        # Kick membernya
        await member.kick(reason=f"Kicked by {ctx.author.name}: {reason}")
        
        # Kirim konfirmasi
        embed = discord.Embed(
            title="👢 Member Kicked",
            description=f"{member.mention} udah dikick!",
            color=discord.Color.orange()
        )
        embed.add_field(name="Kicked By", value=ctx.author.mention)
        embed.add_field(name="Reason", value=reason or "No reason provided")
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='addfilter')
@commands.has_permissions(administrator=True)
async def add_filter(ctx, *, words):
    """Tambahin kata/frasa yang mau difilter
    Contoh: !addfilter promosi jual beli dagang"""
    try:
        with get_db_cursor() as cursor:
            added_words = []
            for word in words.lower().split():
                sql = """INSERT IGNORE INTO filter_words (guild_id, word)
                         VALUES (%s, %s)"""
                cursor.execute(sql, (ctx.guild.id, word))
                added_words.append(word)
            
            if added_words:
                await ctx.send(f"✅ Kata yang ditambahkan: `{', '.join(added_words)}`")
            else:
                await ctx.send("❌ Tidak ada kata yang ditambahkan!")
                
    except Error as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='removefilter')
@commands.has_permissions(administrator=True)
async def remove_filter(ctx, *, words):
    """Hapus kata dari filter
    Contoh: !removefilter promosi jual"""
    try:
        guild_id = ctx.guild.id
        
        if guild_id not in filter_words:
            return await ctx.send("❌ Belum ada filter yang diset!")
        
        # Hapus kata dari filter
        removed_words = []
        for word in words.lower().split():
            if word in filter_words[guild_id]['words']:
                filter_words[guild_id]['words'].remove(word)
                removed_words.append(word)
        
        if removed_words:
            embed = discord.Embed(
                title="✅ Filter Updated",
                description="Kata yang dihapus dari filter:",
                color=discord.Color.green()
            )
            embed.add_field(name="Words", value="`" + "`, `".join(removed_words) + "`")
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Kata-kata itu ga ada di filter!")
            
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='filters')
@commands.has_permissions(administrator=True)
async def show_filters(ctx):
    """Liat semua filter yang aktif"""
    try:
        guild_id = ctx.guild.id
        
        if guild_id not in filter_words:
            return await ctx.send("❌ Belum ada filter yang diset!")
            
        embed = discord.Embed(
            title="📋 Active Filters",
            color=discord.Color.blue()
        )
        
        # List filtered words
        if filter_words[guild_id]['words']:
            embed.add_field(
                name="Filtered Words/Phrases",
                value="`" + "`, `".join(filter_words[guild_id]['words']) + "`",
                inline=False
            )
        
        # Show other filters
        other_filters = []
        if filter_words[guild_id].get('links'):
            other_filters.append("🔗 All Links")
        if filter_words[guild_id].get('invites'):
            other_filters.append("📨 Discord Invites")
            
        if other_filters:
            embed.add_field(
                name="Other Filters",
                value="\n".join(other_filters),
                inline=False
            )
            
        # Show filtered channels
        if guild_id in filter_channels:
            channels = [ctx.guild.get_channel(id).mention for id in filter_channels[guild_id] if ctx.guild.get_channel(id)]
            if channels:
                embed.add_field(
                    name="Filtered Channels",
                    value="\n".join(channels),
                    inline=False
                )
                
        # Show bypass roles
        if guild_id in filter_bypass:
            roles = [ctx.guild.get_role(id).mention for id in filter_bypass[guild_id] if ctx.guild.get_role(id)]
            if roles:
                embed.add_field(
                    name="Bypass Roles",
                    value="\n".join(roles),
                    inline=False
                )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='togglelink')
@commands.has_permissions(administrator=True)
async def toggle_link_filter(ctx):
    """Toggle filter semua link"""
    try:
        guild_id = ctx.guild.id
        
        if guild_id not in filter_words:
            filter_words[guild_id] = {'words': [], 'links': False, 'invites': False}
            
        filter_words[guild_id]['links'] = not filter_words[guild_id]['links']
        
        status = "ON 🟢" if filter_words[guild_id]['links'] else "OFF 🔴"
        await ctx.send(f"Link filter: {status}")
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='toggleinvite')
@commands.has_permissions(administrator=True)
async def toggle_invite_filter(ctx):
    """Toggle filter invite Discord"""
    try:
        guild_id = ctx.guild.id
        
        if guild_id not in filter_words:
            filter_words[guild_id] = {'words': [], 'links': False, 'invites': False}
            
        filter_words[guild_id]['invites'] = not filter_words[guild_id]['invites']
        
        status = "ON 🟢" if filter_words[guild_id]['invites'] else "OFF 🔴"
        await ctx.send(f"Invite filter: {status}")
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='filterchannel')
@commands.has_permissions(administrator=True)
async def set_filter_channel(ctx, channel: discord.TextChannel):
    """Set channel yang mau difilter
    Contoh: !filterchannel #general"""
    try:
        guild_id = ctx.guild.id
        
        if guild_id not in filter_channels:
            filter_channels[guild_id] = []
            
        if channel.id in filter_channels[guild_id]:
            filter_channels[guild_id].remove(channel.id)
            await ctx.send(f"✅ Filter dimatiin di {channel.mention}")
        else:
            filter_channels[guild_id].append(channel.id)
            await ctx.send(f"✅ Filter dinyalain di {channel.mention}")
            
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='bypassrole')
@commands.has_permissions(administrator=True)
async def set_bypass_role(ctx, role: discord.Role):
    """Set role yang bisa bypass filter
    Contoh: !bypassrole @Mod"""
    try:
        guild_id = ctx.guild.id
        
        if guild_id not in filter_bypass:
            filter_bypass[guild_id] = []
            
        if role.id in filter_bypass[guild_id]:
            filter_bypass[guild_id].remove(role.id)
            await ctx.send(f"✅ {role.mention} udah ga bisa bypass filter")
        else:
            filter_bypass[guild_id].append(role.id)
            await ctx.send(f"✅ {role.mention} sekarang bisa bypass filter")
            
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

# Event handler buat check messages
@bot.event
async def on_message(message):
    # Skip bot messages
    if message.author.bot:
        return

    # Handle DM messages
    if isinstance(message.channel, discord.DMChannel):
        await bot.process_commands(message)
        return
        
    # Untuk pesan di server/guild
    try:
        guild_id = message.guild.id
        
        # Process filter words
        if guild_id in filter_words:
            # Check bypass roles
            if guild_id in filter_bypass:
                for role_id in filter_bypass[guild_id]:
                    role = message.guild.get_role(role_id)
                    if role and role in message.author.roles:
                        break
                else:  # No bypass role found
                    # Check if channel is filtered
                    if guild_id in filter_channels and message.channel.id in filter_channels[guild_id]:
                        content = message.content.lower()
                        
                        # Check filtered words
                        for word in filter_words[guild_id]['words']:
                            if word in content:
                                await message.delete()
                                await message.channel.send(f"⚠️ {message.author.mention} Message lu ada kata yang difilter!", delete_after=5)
                                return
                        
                        # Check links
                        if filter_words[guild_id].get('links') and ('http://' in content or 'https://' in content):
                            await message.delete()
                            await message.channel.send(f"⚠️ {message.author.mention} Dilarang kirim link!", delete_after=5)
                            return
                        
                        # Check Discord invites
                        if filter_words[guild_id].get('invites') and ('discord.gg/' in content or 'discordapp.com/invite/' in content):
                            await message.delete()
                            await message.channel.send(f"⚠️ {message.author.mention} Dilarang kirim invite Discord!", delete_after=5)
                            return
    
    except Exception as e:
        print(f"Error in on_message: {e}")
    
    # Process commands
    await bot.process_commands(message)

@bot.command(name='samp')
async def samp_status(ctx, ip, port: int = 7777):
    """Cek status server SAMP
    Contoh: !samp 127.0.0.1 7777"""
    try:
        # Query server
        query = SAMPQuery(ip, port)
        info = query.get_server_info()
        
        if info:
            # Bikin embed
            embed = discord.Embed(
                title="🎮 SAMP Server Status",
                description=f"`{ip}:{port}`",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            # Server info
            embed.add_field(
                name="Server Name", 
                value=info['hostname'],
                inline=False
            )
            
            # Player count dengan progress bar
            player_percent = (info['players'] / info['maxplayers']) * 100
            blocks = int(player_percent / 10)
            progress = "█" * blocks + "░" * (10 - blocks)
            
            embed.add_field(
                name="Players",
                value=f"`{progress}` {info['players']}/{info['maxplayers']} ({player_percent:.1f}%)",
                inline=False
            )
            
            # Game info
            embed.add_field(name="Gamemode", value=info['gamemode'], inline=True)
            embed.add_field(name="Language", value=info['language'], inline=True)
            embed.add_field(
                name="Password", 
                value="🔒 Yes" if info['password'] else "🔓 No",
                inline=True
            )
            
            await ctx.send(embed=embed)
            
        else:
            await ctx.send("❌ Server offline atau ga bisa diakses!")
            
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='sampauto')
@commands.has_permissions(administrator=True)
async def setup_samp_monitor(ctx, ip, port: int = 7777, *, channel: discord.TextChannel = None):
    """Setup auto-monitor server SAMP
    Contoh: !sampauto 127.0.0.1 7777 #samp-status"""
    try:
        channel = channel or ctx.channel
        
        # Bikin message yang bakal diupdate
        embed = discord.Embed(
            title="🎮 SAMP Server Monitor",
            description=f"Monitoring `{ip}:{port}`\nUpdated every 5 minutes",
            color=discord.Color.blue()
        )
        
        status_msg = await channel.send(embed=embed)
        
        # Update loop
        while True:
            query = SAMPQuery(ip, port)
            info = query.get_server_info()
            
            if info:
                # Update embed
                embed = discord.Embed(
                    title="🎮 SAMP Server Monitor",
                    description=f"Server: `{ip}:{port}`",
                    color=discord.Color.green(),
                    timestamp=datetime.now()
                )
                
                embed.add_field(
                    name="Server Name",
                    value=info['hostname'],
                    inline=False
                )
                
                # Player count dengan progress bar
                player_percent = (info['players'] / info['maxplayers']) * 100
                blocks = int(player_percent / 10)
                progress = "█" * blocks + "░" * (10 - blocks)
                
                embed.add_field(
                    name="Players",
                    value=f"`{progress}` {info['players']}/{info['maxplayers']} ({player_percent:.1f}%)",
                    inline=False
                )
                
                embed.add_field(name="Gamemode", value=info['gamemode'], inline=True)
                embed.add_field(name="Language", value=info['language'], inline=True)
                embed.add_field(
                    name="Status",
                    value="🟢 Online",
                    inline=True
                )
                
            else:
                # Server offline
                embed = discord.Embed(
                    title="🎮 SAMP Server Monitor",
                    description=f"Server: `{ip}:{port}`",
                    color=discord.Color.red(),
                    timestamp=datetime.now()
                )
                
                embed.add_field(
                    name="Status",
                    value="🔴 Offline",
                    inline=False
                )
            
            await status_msg.edit(embed=embed)
            await asyncio.sleep(300)  # Update tiap 5 menit
            
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='movecat')
@commands.has_permissions(administrator=True)
async def move_category(ctx, category: discord.CategoryChannel, position: int):
    """Pindahin posisi category
    Contoh: !movecat "GAMING" 1"""
    try:
        # Check posisi valid
        if position < 0:
            return await ctx.send("❌ Posisi harus lebih dari 0!")
            
        # Get max position
        max_position = len(ctx.guild.categories) - 1
        if position > max_position:
            return await ctx.send(f"❌ Posisi maksimal adalah {max_position}!")
            
        # Move category
        await category.edit(position=position)
        
        embed = discord.Embed(
            title="✅ Category Moved",
            description=f"Category {category.mention} dipindah ke posisi {position}",
            color=discord.Color.green()
        )
        
        # Show category order
        categories = sorted(ctx.guild.categories, key=lambda c: c.position)
        order = "\n".join([f"`{i}.` {c.name}" for i, c in enumerate(categories)])
        embed.add_field(
            name="Current Order",
            value=order,
            inline=False
        )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='catlist')
@commands.has_permissions(administrator=True)
async def list_categories(ctx):
    """Liat urutan category"""
    try:
        embed = discord.Embed(
            title="📋 Category List",
            description="Urutan category dari atas ke bawah:",
            color=discord.Color.blue()
        )
        
        # Get sorted categories
        categories = sorted(ctx.guild.categories, key=lambda c: c.position)
        
        # List categories with their channels
        for i, category in enumerate(categories):
            # Get channels in category
            text_channels = len([c for c in category.text_channels])
            voice_channels = len([c for c in category.voice_channels])
            
            value = f"Text Channels: {text_channels}\nVoice Channels: {voice_channels}"
            embed.add_field(
                name=f"{i}. {category.name}",
                value=value,
                inline=True
            )
            
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='swapcats')
@commands.has_permissions(administrator=True)
async def swap_categories(ctx, cat1: discord.CategoryChannel, cat2: discord.CategoryChannel):
    """Tuker posisi 2 category
    Contoh: !swapcats "GAMING" "CHAT" """
    try:
        # Get positions
        pos1 = cat1.position
        pos2 = cat2.position
        
        # Swap positions
        await cat1.edit(position=pos2)
        await cat2.edit(position=pos1)
        
        embed = discord.Embed(
            title="✅ Categories Swapped",
            description=f"Posisi category dituker:",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name=cat1.name,
            value=f"Moved to position {pos2}",
            inline=True
        )
        embed.add_field(
            name=cat2.name,
            value=f"Moved to position {pos1}",
            inline=True
        )
        
        # Show new order
        categories = sorted(ctx.guild.categories, key=lambda c: c.position)
        order = "\n".join([f"`{i}.` {c.name}" for i, c in enumerate(categories)])
        embed.add_field(
            name="New Order",
            value=order,
            inline=False
        )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='bothelp')
async def help_command(ctx):
    """Shows help message"""
    try:
        # Bikin embed pages
        pages = []
        
        # Page 1: Admin Commands
        admin_embed = discord.Embed(
            title="👑 Command Admin/Mod",
            description="Command khusus buat lu yang jadi admin/mod server",
            color=discord.Color.gold()
        )
        admin_embed.set_thumbnail(url="https://i.imgur.com/XwVLN6G.gif")
        
        admin_embed.add_field(
            name="🛠️ Manage Server",
            value="""
            `!cat` - Bikin category baru
            `!movecat` - Pindahin posisi category
            `!catlist` - Liat urutan category
            `!mv` - Pindahin channel ke category lain
            `!del` - Hapus channel
            `!lock` - Kunci channel
            """,
            inline=False
        )
        
        admin_embed.add_field(
            name="👮 Manage Member",
            value="""
            `!kick @user` - Tendang member
            `!ban @user` - Ban member
            `!unban User#1234` - Unban member
            `!createprivatechannel` - Bikin channel private buat role tertentu
            """,
            inline=False
        )
        
        pages.append(admin_embed)
        
        # Page 2: Filter Commands
        filter_embed = discord.Embed(
            title="🛡️ Filter System",
            description="Biar server lu bebas dari spam & konten sampah",
            color=discord.Color.green()
        )
        filter_embed.set_thumbnail(url="https://i.imgur.com/qH3S0Ym.gif")
        
        filter_embed.add_field(
            name="📝 Setup Filter",
            value="""
            `!addfilter [kata]` - Tambahin kata ke filter
            `!filters` - Liat semua filter yang aktif
            `!filterchannel #channel` - Set channel yang difilter
            `!bypassrole @role` - Kasih role yang bisa bypass
            """,
            inline=False
        )
        
        pages.append(filter_embed)
        
        # Page 3: SAMP Commands
        samp_embed = discord.Embed(
            title="🎮 SAMP Commands",
            description="Buat lu yang main SAMP",
            color=discord.Color.blue()
        )
        samp_embed.set_thumbnail(url="https://i.imgur.com/dQw4w9W.gif")
        
        samp_embed.add_field(
            name="📊 Server Status",
            value="""
            `!players` - Cek berapa player online
            `!serverinfo` - Info lengkap server
            `!sampauto #channel` - Auto update status server
            """,
            inline=False
        )
        
        pages.append(samp_embed)
        
        # Page 4: Utility Commands
        util_embed = discord.Embed(
            title="🔧 Command Utility",
            description="Command umum yang bisa dipake semua member",
            color=discord.Color.purple()
        )
        util_embed.set_thumbnail(url="https://i.imgur.com/7K1x0dN.gif")
        
        util_embed.add_field(
            name="ℹ️ Info Commands",
            value="""
            `!help` - Liat command yang ada
            `!ping` - Cek bot delay
            `!checkperm` - Cek permission lu
            `!listroles` - Liat role yang ada
            """,
            inline=False
        )
        
        pages.append(util_embed)
        
        # Navigation
        current_page = 0
        
        class HelpView(View):
            def __init__(self):
                super().__init__(timeout=60.0)
                
            @discord.ui.button(label="◀️", style=discord.ButtonStyle.green)
            async def prev_button(self, interaction: discord.Interaction, button: Button):
                nonlocal current_page
                current_page = (current_page - 1) % len(pages)
                await interaction.response.edit_message(embed=pages[current_page])
                
            @discord.ui.button(label="❌", style=discord.ButtonStyle.red)
            async def close_button(self, interaction: discord.Interaction, button: Button):
                await interaction.message.delete()
                
            @discord.ui.button(label="▶️", style=discord.ButtonStyle.green)
            async def next_button(self, interaction: discord.Interaction, button: Button):
                nonlocal current_page
                current_page = (current_page + 1) % len(pages)
                await interaction.response.edit_message(embed=pages[current_page])
                
            async def on_timeout(self):
                try:
                    await self.message.edit(view=None)
                except:
                    pass

        view = HelpView()
        message = await ctx.send(embed=pages[current_page], view=view)
        view.message = message
                
    except Exception as e:
        await ctx.send(f"Error: {str(e)}")

# Jalanin bot pake token
bot.run(os.getenv('DISCORD_TOKEN'))

@bot.event
async def on_member_join(member):
    """Handle member join event"""
    try:
        with get_db_cursor() as cursor:
            # Get welcome message dan channel
            cursor.execute("""
                SELECT message, channel_id 
                FROM welcome_messages 
                WHERE guild_id = %s
            """, (member.guild.id,))
            
            result = cursor.fetchone()
            if result and result[0] and result[1]:  # Pastikan message dan channel ada
                message, channel_id = result
                channel = member.guild.get_channel(channel_id)
                
                if channel:
                    welcome_msg = message.replace('{member}', member.mention)
                    await channel.send(welcome_msg)
                    
    except Error as e:
        print(f"Error handling member join: {e}")

def hash_token(token: str) -> str:
    """Hash token dengan SHA-256"""
    return hashlib.sha256(token.encode()).hexdigest()

def check_dev_session(user_id: int) -> bool:
    """Cek apakah dev session masih valid"""
    if user_id not in dev_sessions:
        return False
        
    if datetime.now().timestamp() > dev_sessions[user_id]['expires_at']:
        del dev_sessions[user_id]
        return False
        
    return True

@bot.command(name='devlogin')
async def dev_login(ctx):
    """Developer login - DM only"""
    # Cek apakah dari DM
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.message.delete()
        return await ctx.send("❌ Command ini hanya bisa dipakai di DM!", delete_after=5)
        
    try:
        with get_db_cursor() as cursor:
            # Cek apakah user adalah developer
            cursor.execute("""
                SELECT token FROM dev_credentials 
                WHERE user_id = %s AND is_active = TRUE
            """, (ctx.author.id,))
            result = cursor.fetchone()
            
            if not result:
                return
                
            # Cek apakah sudah login
            if check_dev_session(ctx.author.id):
                return await ctx.send("✅ Anda sudah login sebagai developer!")
                
            # Minta token
            await ctx.send("🔐 Masukkan developer token:")
            
            try:
                msg = await bot.wait_for(
                    'message',
                    timeout=30.0,
                    check=lambda m: m.author == ctx.author and isinstance(m.channel, discord.DMChannel)
                )
                
                # Verify token
                if hash_token(msg.content) == result[0]:
                    # Generate session
                    session_id = secrets.token_urlsafe(32)
                    expires_at = datetime.now() + timedelta(hours=1)
                    
                    # Simpan session ke database
                    cursor.execute("""
                        INSERT INTO dev_sessions (session_id, user_id, expires_at)
                        VALUES (%s, %s, %s)
                    """, (session_id, ctx.author.id, expires_at))
                    
                    # Update last login
                    cursor.execute("""
                        UPDATE dev_credentials 
                        SET last_login = CURRENT_TIMESTAMP 
                        WHERE user_id = %s
                    """, (ctx.author.id,))
                    
                    # Simpan di memory
                    dev_sessions[ctx.author.id] = {
                        'session_id': session_id,
                        'expires_at': expires_at.timestamp()
                    }
                    
                    # Log login
                    cursor.execute("""
                        INSERT INTO dev_logs (user_id, action, details)
                        VALUES (%s, %s, %s)
                    """, (ctx.author.id, 'LOGIN', f'Login from {ctx.author}'))
                    
                    embed = discord.Embed(
                        title="✅ Login Berhasil",
                        description="Selamat datang kembali, Developer!",
                        color=discord.Color.green()
                    )
                    embed.add_field(
                        name="Session Info",
                        value=f"Expires: <t:{int(expires_at.timestamp())}:R>",
                        inline=False
                    )
                    embed.add_field(
                        name="Commands",
                        value="`!dev` - Open developer panel\n`!devlogout` - Logout",
                        inline=False
                    )
                    
                    await ctx.send(embed=embed)
                    
                else:
                    # Log failed attempt
                    cursor.execute("""
                        INSERT INTO dev_logs (user_id, action, details)
                        VALUES (%s, %s, %s)
                    """, (ctx.author.id, 'FAILED_LOGIN', f'Invalid token attempt from {ctx.author}'))
                    
                    await ctx.send("❌ Token salah!")
                
                # Hapus pesan yang berisi token
                await msg.delete()
                
            except asyncio.TimeoutError:
                await ctx.send("❌ Timeout! Coba lagi.")
                
    except Error as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='dev')
async def dev_command(ctx):
    """Developer commands"""
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.message.delete()
        return await ctx.send("❌ Command ini cuma bisa dipake di DM!", delete_after=5)
        
    try:
        with get_db_cursor() as cursor:
            # Cek apakah user adalah developer
            cursor.execute("""
                SELECT user_id, token 
                FROM dev_credentials 
                WHERE user_id = %s AND is_active = TRUE
            """, (ctx.author.id,))
            
            result = cursor.fetchone()
            if not result:
                return await ctx.send("❌ Lu bukan developer bre!")
                
            # Generate session token
            session_id = secrets.token_hex(32)
            expires_at = datetime.now() + timedelta(hours=24)
            
            # Simpan session
            cursor.execute("""
                INSERT INTO dev_sessions (session_id, user_id, expires_at)
                VALUES (%s, %s, %s)
            """, (session_id, ctx.author.id, expires_at))
            
            # Update last login
            cursor.execute("""
                UPDATE dev_credentials 
                SET last_login = CURRENT_TIMESTAMP
                WHERE user_id = %s
            """, (ctx.author.id,))
            
            # Kirim konfirmasi
            embed = discord.Embed(
                title="✅ Login Berhasil!",
                description="Lu udah login sebagai developer",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Session Expires",
                value=f"<t:{int(expires_at.timestamp())}:R>",
                inline=True
            )
            
            await ctx.send(embed=embed)
            
    except Error as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='dev')
async def dev_panel(ctx):
    """Developer control panel - DM only"""
    # Cek apakah dari DM
    if not isinstance(ctx.channel, discord.DMChannel):
        return
        
    # Cek session
    if not check_dev_session(ctx.author.id):
        return await ctx.send("❌ Silakan login dulu dengan `!devlogin`")
        
    # Show panel
    embed = discord.Embed(
        title="👨‍💻 Developer Control Panel",
        description="Welcome back, Developer!",
        color=discord.Color.gold()
    )
    
    # Stats
    total_servers = len(bot.guilds)
    total_users = sum(g.member_count for g in bot.guilds)
    
    embed.add_field(
        name="📊 Bot Stats",
        value=f"Servers: {total_servers}\nUsers: {total_users}",
        inline=True
    )
    
    # Uptime
    uptime = datetime.now() - bot.start_time
    hours = uptime.seconds // 3600
    minutes = (uptime.seconds % 3600) // 60
    
    embed.add_field(
        name="⏰ Uptime",
        value=f"{uptime.days}d {hours}h {minutes}m",
        inline=True
    )
    
    # Control buttons
    class DevView(View):
        def __init__(self):
            super().__init__(timeout=60)
            
        @discord.ui.button(label="Broadcast", style=discord.ButtonStyle.green)
        async def broadcast(self, interaction: discord.Interaction, button: Button):
            await interaction.response.send_message("Masukkan pesan broadcast:")
            
            try:
                msg = await bot.wait_for(
                    'message',
                    timeout=60.0,
                    check=lambda m: m.author == ctx.author and isinstance(m.channel, discord.DMChannel)
                )
                
                with get_db_cursor() as cursor:
                    # Create broadcast entry
                    cursor.execute("""
                        INSERT INTO broadcast_messages (user_id, message, total_servers)
                        VALUES (%s, %s, %s)
                    """, (ctx.author.id, msg.content, len(bot.guilds)))
                    
                    broadcast_id = cursor.lastrowid
                    
                    # Update status
                    cursor.execute("""
                        UPDATE broadcast_messages 
                        SET status = 'sending' 
                        WHERE broadcast_id = %s
                    """, (broadcast_id,))
                
                # Broadcast ke semua server
                success = 0
                failed = 0
                
                for guild in bot.guilds:
                    try:
                        channel = next((ch for ch in guild.text_channels if ch.permissions_for(guild.me).send_messages), None)
                        if channel:
                            await channel.send(msg.content)
                            success += 1
                    except:
                        failed += 1
                        continue
                
                # Update hasil
                with get_db_cursor() as cursor:
                    cursor.execute("""
                        UPDATE broadcast_messages 
                        SET status = 'completed',
                            successful_sends = %s,
                            failed_sends = %s
                        WHERE broadcast_id = %s
                    """, (success, failed, broadcast_id))
                
                await ctx.send(f"✅ Broadcast selesai!\nSuccess: {success}\nFailed: {failed}")
                
            except asyncio.TimeoutError:
                await ctx.send("❌ Timeout! Coba lagi.")
                
        @discord.ui.button(label="Server List", style=discord.ButtonStyle.blurple)
        async def server_list(self, interaction: discord.Interaction, button: Button):
            servers = []
            for guild in bot.guilds:
                servers.append(f"• {guild.name}\n  ID: {guild.id}\n  Members: {guild.member_count}")
            
            # Split jika terlalu panjang
            chunks = [servers[i:i+10] for i in range(0, len(servers), 10)]
            
            for i, chunk in enumerate(chunks):
                embed = discord.Embed(
                    title=f"🌐 Server List (Page {i+1}/{len(chunks)})",
                    description="\n".join(chunk),
                    color=discord.Color.blue()
                )
                await interaction.response.send_message(embed=embed)
                
        @discord.ui.button(label="View Logs", style=discord.ButtonStyle.gray)
        async def view_logs(self, interaction: discord.Interaction, button: Button):
            with get_db_cursor() as cursor:
                cursor.execute("""
                    SELECT action, details, executed_at
                    FROM dev_logs
                    WHERE user_id = %s
                    ORDER BY executed_at DESC
                    LIMIT 10
                """, (ctx.author.id,))
                
                logs = cursor.fetchall()
                
                if logs:
                    embed = discord.Embed(
                        title="📝 Recent Logs",
                        color=discord.Color.blue()
                    )
                    
                    for log in logs:
                        embed.add_field(
                            name=f"{log[0]} - {log[2]}",
                            value=log[1],
                            inline=False
                        )
                else:
                    embed = discord.Embed(
                        title="📝 Logs",
                        description="No logs found",
                        color=discord.Color.red()
                    )
                    
                await interaction.response.send_message(embed=embed)
                
        @discord.ui.button(label="Logout", style=discord.ButtonStyle.red)
        async def logout(self, interaction: discord.Interaction, button: Button):
            with get_db_cursor() as cursor:
                cursor.execute("""
                    DELETE FROM dev_sessions 
                    WHERE user_id = %s
                """, (ctx.author.id,))
                
                cursor.execute("""
                    INSERT INTO dev_logs (user_id, action, details)
                    VALUES (%s, %s, %s)
                """, (ctx.author.id, 'LOGOUT', f'Logout from panel'))
                
            del dev_sessions[ctx.author.id]
            await interaction.response.send_message("👋 Logged out!")
            
    await ctx.send(embed=embed, view=DevView())

@bot.command(name='addresponse')
@commands.has_permissions(administrator=True)
async def add_response(ctx, trigger: str, *, response: str):
    """Tambahin auto response (Premium only)"""
    # Cek premium
    if not await is_premium(ctx.guild.id):
        return await ctx.send("❌ Command ini khusus premium bre! Ketik `!trial` buat dapetin trial 7 hari")
        
    try:
        with get_db_cursor() as cursor:
            # Cek apakah trigger udah ada
            cursor.execute("""
                SELECT response 
                FROM custom_responses 
                WHERE guild_id = %s AND trigger_word = %s AND is_active = TRUE
            """, (ctx.guild.id, trigger.lower()))
            
            if cursor.fetchone():
                return await ctx.send("❌ Trigger ini udah ada bre!")
                
            # Tambahin response baru
            cursor.execute("""
                INSERT INTO custom_responses 
                (guild_id, trigger_word, response, created_by)
                VALUES (%s, %s, %s, %s)
            """, (ctx.guild.id, trigger.lower(), response, ctx.author.id))
            
        await ctx.send(f"✅ Oke bre! Bot bakal jawab `{response}` kalo ada yang ngomong `{trigger}`")
        
    except Error as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='responses')
async def list_responses(ctx):
    """Liat semua auto responses"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT trigger_word, response 
                FROM custom_responses 
                WHERE guild_id = %s AND is_active = TRUE
            """, (ctx.guild.id,))
            
            responses = cursor.fetchall()
            
            if not responses:
                if await is_premium(ctx.guild.id):
                    return await ctx.send("❌ Belom ada auto response bre! Tambahin pake `!addresponse`")
                else:
                    return await ctx.send("❌ Fitur ini khusus premium bre! Ketik `!trial` buat dapetin trial 7 hari")
                    
            embed = discord.Embed(
                title="🤖 Auto Responses",
                description="List semua auto response di server ini",
                color=discord.Color.blue()
            )
            
            for trigger, response in responses:
                embed.add_field(
                    name=f"💬 {trigger}",
                    value=response,
                    inline=False
                )
                
            await ctx.send(embed=embed)
            
    except Error as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='delresponse')
@commands.has_permissions(administrator=True)
async def delete_response(ctx, trigger: str):
    """Hapus auto response"""
    if not await is_premium(ctx.guild.id):
        return await ctx.send("❌ Command ini khusus premium bre! Ketik `!trial` buat dapetin trial 7 hari")
        
    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                UPDATE custom_responses 
                SET is_active = FALSE 
                WHERE guild_id = %s AND trigger_word = %s
            """, (ctx.guild.id, trigger.lower()))
            
            if cursor.rowcount > 0:
                await ctx.send(f"✅ Auto response untuk trigger `{trigger}` udah dihapus!")
            else:
                await ctx.send("❌ Ga ketemu trigger itu bre!")
                
    except Error as e:
        await ctx.send(f"Error: {str(e)}")

# Update on_message event
@bot.event
async def on_message(message):
    # Skip bot messages
    if message.author.bot:
        return
        
    # Handle DM messages
    if isinstance(message.channel, discord.DMChannel):
        await bot.process_commands(message)
        return
        
    # Check auto responses
    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT response 
                FROM custom_responses 
                WHERE guild_id = %s AND trigger_word = %s AND is_active = TRUE
            """, (message.guild.id, message.content.lower()))
            
            result = cursor.fetchone()
            if result:
                await message.channel.send(result[0])
                
    except Error as e:
        print(f"Error checking responses: {e}")
        
    # Process commands
    await bot.process_commands(message)

async def is_premium(guild_id: int) -> bool:
    """Cek apakah server punya akses premium"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT end_date, is_active 
                FROM premium_trials 
                WHERE guild_id = %s
            """, (guild_id,))
            
            result = cursor.fetchone()
            if not result:
                return False
                
            end_date, is_active = result
            
            # Auto update status kalo udah expired
            if datetime.now() > end_date and is_active:
                cursor.execute("""
                    UPDATE premium_trials 
                    SET is_active = FALSE 
                    WHERE guild_id = %s
                """, (guild_id,))
                return False
                
            return is_active and datetime.now() < end_date
            
    except Error:
        return False

@bot.command(name='trial')
@commands.has_permissions(administrator=True)
async def start_trial(ctx):
    """Mulai 7 hari trial premium"""
    try:
        with get_db_cursor() as cursor:
            # Cek apakah server udah pernah trial
            cursor.execute("""
                SELECT * FROM premium_trials 
                WHERE guild_id = %s
            """, (ctx.guild.id,))
            
            if cursor.fetchone():
                return await ctx.send("❌ Server lu udah pernah pake trial bre!")
                
            # Set trial 7 hari
            end_date = datetime.now() + timedelta(days=7)
            cursor.execute("""
                INSERT INTO premium_trials 
                (guild_id, activated_by, end_date) 
                VALUES (%s, %s, %s)
            """, (ctx.guild.id, ctx.author.id, end_date))
            
            embed = discord.Embed(
                title="✨ Trial Premium Aktif!",
                description="Server lu dapet akses premium selama 7 hari",
                color=discord.Color.gold()
            )
            embed.add_field(
                name="Expired",
                value=f"<t:{int(end_date.timestamp())}:R>",
                inline=False
            )
            embed.add_field(
                name="Fitur Premium",
                value="• Custom auto responses\n• Unlimited filter words\n• Advanced welcome system\n• Dan fitur² keren lainnya!",
                inline=False
            )
            
            await ctx.send(embed=embed)
            
    except Error as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='status')
async def check_status(ctx):
    """Cek status premium server"""
    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT end_date, is_active 
                FROM premium_trials 
                WHERE guild_id = %s
            """, (ctx.guild.id,))
            
            result = cursor.fetchone()
            if not result:
                return await ctx.send("❌ Server lu belom pernah trial premium bre! Ketik `!trial` buat mulai")
                
            end_date, is_active = result
            
            if not is_active:
                return await ctx.send("❌ Trial premium lu udah abis bre!")
                
            embed = discord.Embed(
                title="💎 Premium Status",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="Status",
                value="✅ AKTIF" if datetime.now() < end_date else "❌ EXPIRED",
                inline=True
            )
            embed.add_field(
                name="Expired",
                value=f"<t:{int(end_date.timestamp())}:R>",
                inline=True
            )
            
            await ctx.send(embed=embed)
            
    except Error as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='setwelcome')
@commands.has_permissions(administrator=True)
async def set_welcome_embed(ctx):
    """Setup advanced welcome message (Premium only)"""
    if not await is_premium(ctx.guild.id):
        return await ctx.send("❌ Command ini khusus premium bre! Ketik `!trial` buat dapetin trial 7 hari")

    # Bikin view untuk setup
    class WelcomeSetup(View):
        def __init__(self):
            super().__init__(timeout=300)  # 5 menit timeout
            
        @discord.ui.button(label="Set Title", style=discord.ButtonStyle.blurple)
        async def set_title(self, interaction: discord.Interaction, button: Button):
            await interaction.response.send_message("Masukkan title untuk welcome embed:")
            try:
                msg = await bot.wait_for(
                    'message', 
                    timeout=60.0,
                    check=lambda m: m.author == ctx.author and m.channel == ctx.channel
                )
                with get_db_cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO welcome_settings (guild_id, embed_title, is_embed) 
                        VALUES (%s, %s, TRUE)
                        ON DUPLICATE KEY UPDATE embed_title = %s
                    """, (ctx.guild.id, msg.content, msg.content))
                await ctx.send(f"✅ Title diset: {msg.content}")
            except asyncio.TimeoutError:
                await ctx.send("❌ Timeout! Coba lagi.")

        @discord.ui.button(label="Set Description", style=discord.ButtonStyle.blurple)
        async def set_desc(self, interaction: discord.Interaction, button: Button):
            await interaction.response.send_message(
                "Masukkan description untuk welcome embed:\n"
                "Placeholders: {member}, {server}, {count}"
            )
            try:
                msg = await bot.wait_for('message', timeout=60.0, check=lambda m: m.author == ctx.author)
                with get_db_cursor() as cursor:
                    cursor.execute("""
                        UPDATE welcome_settings 
                        SET embed_description = %s, is_embed = TRUE
                        WHERE guild_id = %s
                    """, (msg.content, ctx.guild.id))
                await ctx.send(f"✅ Description diset!")
            except asyncio.TimeoutError:
                await ctx.send("❌ Timeout! Coba lagi.")

        @discord.ui.button(label="Set Color", style=discord.ButtonStyle.green)
        async def set_color(self, interaction: discord.Interaction, button: Button):
            await interaction.response.send_message("Masukkan warna dalam format hex (contoh: #ff0000):")
            try:
                msg = await bot.wait_for('message', timeout=60.0, check=lambda m: m.author == ctx.author)
                if not msg.content.startswith('#') or len(msg.content) != 7:
                    return await ctx.send("❌ Format warna salah! Contoh yang bener: #ff0000")
                with get_db_cursor() as cursor:
                    cursor.execute("""
                        UPDATE welcome_settings 
                        SET embed_color = %s, is_embed = TRUE
                        WHERE guild_id = %s
                    """, (msg.content, ctx.guild.id))
                await ctx.send(f"✅ Color diset ke {msg.content}")
            except asyncio.TimeoutError:
                await ctx.send("❌ Timeout! Coba lagi.")

        @discord.ui.button(label="Set Image", style=discord.ButtonStyle.blurple)
        async def set_image(self, interaction: discord.Interaction, button: Button):
            await interaction.response.send_message("Kirim link gambar untuk welcome embed:")
            try:
                msg = await bot.wait_for('message', timeout=60.0, check=lambda m: m.author == ctx.author)
                with get_db_cursor() as cursor:
                    cursor.execute("""
                        UPDATE welcome_settings 
                        SET embed_image = %s, is_embed = TRUE
                        WHERE guild_id = %s
                    """, (msg.content, ctx.guild.id))
                await ctx.send(f"✅ Image diset!")
            except asyncio.TimeoutError:
                await ctx.send("❌ Timeout! Coba lagi.")

        @discord.ui.button(label="Preview", style=discord.ButtonStyle.gray)
        async def preview(self, interaction: discord.Interaction, button: Button):
            with get_db_cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM welcome_settings WHERE guild_id = %s
                """, (ctx.guild.id,))
                settings = cursor.fetchone()
                
            if not settings:
                return await interaction.response.send_message("❌ Setup welcome message dulu!")

            embed = discord.Embed(
                title=settings[2] or "Welcome!",
                description=(settings[3] or "Welcome {member} to {server}!")
                    .replace("{member}", ctx.author.mention)
                    .replace("{server}", ctx.guild.name)
                    .replace("{count}", str(ctx.guild.member_count)),
                color=discord.Color.from_str(settings[4] or "#7289DA")
            )
            
            if settings[6]:  # embed_image
                embed.set_image(url=settings[6])

            await interaction.response.send_message("Preview welcome message:", embed=embed)

    # Send setup message
    embed = discord.Embed(
        title="🔧 Welcome Message Setup",
        description="Klik button di bawah buat setup welcome message",
        color=discord.Color.blue()
    )
    
    await ctx.send(embed=embed, view=WelcomeSetup())

@bot.command(name='autorole')
@commands.has_permissions(administrator=True)
async def set_autorole(ctx, role: discord.Role):
    """Set role yang auto dikasih ke member baru (Premium only)"""
    if not await is_premium(ctx.guild.id):
        return await ctx.send("❌ Command ini khusus premium bre! Ketik `!trial` buat dapetin trial 7 hari")
        
    try:
        with get_db_cursor() as cursor:
            cursor.execute("""
                INSERT INTO welcome_autoroles (guild_id, role_id)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE role_id = %s
            """, (ctx.guild.id, role.id, role.id))
            
        await ctx.send(f"✅ {role.mention} bakal auto dikasih ke member baru!")
        
    except Error as e:
        await ctx.send(f"Error: {str(e)}")

@bot.event
async def on_member_join(member):
    """Handle member join dengan advanced welcome"""
    try:
        with get_db_cursor() as cursor:
            # Get welcome settings
            cursor.execute("""
                SELECT w.message, w.channel_id, ws.* 
                FROM welcome_messages w
                LEFT JOIN welcome_settings ws ON w.guild_id = ws.guild_id
                WHERE w.guild_id = %s
            """, (member.guild.id,))
            
            result = cursor.fetchone()
            if not result or not result[1]:  # No channel set
                return
                
            channel = member.guild.get_channel(result[1])
            if not channel:
                return
                
            # Check if using embed
            if result[4]:  # is_embed
                embed = discord.Embed(
                    title=result[5] or "Welcome!",  # embed_title
                    description=(result[6] or "Welcome {member} to {server}!")  # embed_description
                        .replace("{member}", member.mention)
                        .replace("{server}", member.guild.name)
                        .replace("{count}", str(member.guild.member_count)),
                    color=discord.Color.from_str(result[7] or "#7289DA")  # embed_color
                )
                
                if result[9]:  # embed_image
                    embed.set_image(url=result[9])
                    
                if result[10]:  # footer_text
                    embed.set_footer(text=result[10])
                    
                await channel.send(embed=embed)
            else:
                # Regular text welcome
                welcome_msg = result[0].replace('{member}', member.mention)
                await channel.send(welcome_msg)
                
            # Check auto roles
            cursor.execute("""
                SELECT role_id FROM welcome_autoroles 
                WHERE guild_id = %s
            """, (member.guild.id,))
            
            for role_id in cursor.fetchall():
                role = member.guild.get_role(role_id[0])
                if role:
                    try:
                        await member.add_roles(role)
                    except:
                        continue
                        
    except Error as e:
        print(f"Error handling member join: {e}")

@bot.command(name='myserver')
async def check_server_trial(ctx):
    """Cek status trial server (DM only)"""
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.message.delete()
        return await ctx.send("❌ Command ini cuma bisa dipake di DM!", delete_after=5)
        
    try:
        # Get semua server yang user punya akses admin
        admin_servers = [
            guild for guild in bot.guilds 
            if guild.get_member(ctx.author.id) and guild.get_member(ctx.author.id).guild_permissions.administrator
        ]
        
        if not admin_servers:
            return await ctx.send("❌ Lu ga punya server yang lu admin bre!")
            
        for guild in admin_servers:
            with get_db_cursor() as cursor:
                cursor.execute("""
                    SELECT end_date, is_active 
                    FROM premium_trials 
                    WHERE guild_id = %s
                """, (guild.id,))
                
                result = cursor.fetchone()
                
                # Bikin embed per server
                embed = discord.Embed(
                    title=f"🔍 Status Premium: {guild.name}",
                    color=discord.Color.blue()
                )
                
                if guild.icon:
                    embed.set_thumbnail(url=guild.icon.url)
                
                if not result:
                    embed.description = "```\n❌ SERVER BELUM TRIAL\n```"
                    embed.add_field(
                        name="Status",
                        value="Belum Aktif",
                        inline=True
                    )
                    embed.add_field(
                        name="Cara Aktivasi",
                        value="Ketik `!trial` di server",
                        inline=True
                    )
                    embed.color = discord.Color.red()
                else:
                    end_date, is_active = result
                    now = datetime.now()
                    
                    if not is_active or now > end_date:
                        embed.description = "```\n⏰ TRIAL SUDAH BERAKHIR\n```"
                        embed.add_field(
                            name="Status",
                            value="Expired",
                            inline=True
                        )
                        embed.color = discord.Color.red()
                    else:
                        # Hitung sisa waktu
                        delta = end_date - now
                        days = delta.days
                        hours = delta.seconds // 3600
                        minutes = (delta.seconds % 3600) // 60
                        seconds = delta.seconds % 60
                        
                        # Bikin progress bar
                        total_seconds = 7 * 24 * 60 * 60  # 7 hari dalam detik
                        elapsed = total_seconds - (delta.days * 24 * 60 * 60 + delta.seconds)
                        progress = int((elapsed / total_seconds) * 20)  # 20 karakter
                        
                        bar = "```\n"
                        bar += "TRIAL PREMIUM AKTIF!\n\n"
                        bar += f"[{'=' * (20-progress)}{' ' * progress}] {((total_seconds-elapsed)/total_seconds)*100:.1f}%\n"
                        bar += f"\n"
                        bar += f"├─ Hari   : {days:02d}\n"
                        bar += f"├─ Jam    : {hours:02d}\n"
                        bar += f"├─ Menit  : {minutes:02d}\n"
                        bar += f"└─ Detik  : {seconds:02d}\n"
                        bar += "```"
                        
                        embed.description = bar
                        embed.color = discord.Color.green()
                        
                        # Tambah fields
                        embed.add_field(
                            name="Expired",
                            value=f"<t:{int(end_date.timestamp())}:R>",
                            inline=True
                        )
                
                # Tambahin footer
                embed.set_footer(text=f"Server ID: {guild.id}")
                
                await ctx.send(embed=embed)
                
    except Error as e:
        await ctx.send(f"Error: {str(e)}")

@bot.command(name='filterset')
@commands.has_permissions(administrator=True)
async def filter_settings(ctx):
    """Setup filter settings (Premium only)"""
    if not await is_premium(ctx.guild.id):
        return await ctx.send("❌ Command ini khusus premium bre! Ketik `!trial` buat dapetin trial 7 hari")
        
    class FilterSetup(View):
        def __init__(self):
            super().__init__(timeout=300)
            
        @discord.ui.button(label="Toggle Links", style=discord.ButtonStyle.blurple)
        async def toggle_links(self, interaction: discord.Interaction, button: Button):
            with get_db_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO filter_settings (guild_id, links_enabled)
                    VALUES (%s, TRUE)
                    ON DUPLICATE KEY UPDATE links_enabled = NOT links_enabled
                """, (ctx.guild.id,))
                
                # Get current status
                cursor.execute("SELECT links_enabled FROM filter_settings WHERE guild_id = %s", (ctx.guild.id,))
                status = cursor.fetchone()[0]
                
            await interaction.response.send_message(
                f"✅ Link filter: {'AKTIF' if status else 'NONAKTIF'}"
            )
            
        @discord.ui.button(label="Toggle Invites", style=discord.ButtonStyle.blurple)
        async def toggle_invites(self, interaction: discord.Interaction, button: Button):
            with get_db_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO filter_settings (guild_id, invites_enabled)
                    VALUES (%s, TRUE)
                    ON DUPLICATE KEY UPDATE invites_enabled = NOT invites_enabled
                """, (ctx.guild.id,))
                
                cursor.execute("SELECT invites_enabled FROM filter_settings WHERE guild_id = %s", (ctx.guild.id,))
                status = cursor.fetchone()[0]
                
            await interaction.response.send_message(
                f"✅ Invite filter: {'AKTIF' if status else 'NONAKTIF'}"
            )
            
        @discord.ui.button(label="Auto Warn", style=discord.ButtonStyle.green)
        async def toggle_warn(self, interaction: discord.Interaction, button: Button):
            with get_db_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO filter_settings (guild_id, auto_warn)
                    VALUES (%s, TRUE)
                    ON DUPLICATE KEY UPDATE auto_warn = NOT auto_warn
                """, (ctx.guild.id,))
                
                cursor.execute("SELECT auto_warn FROM filter_settings WHERE guild_id = %s", (ctx.guild.id,))
                status = cursor.fetchone()[0]
                
            await interaction.response.send_message(
                f"✅ Auto warn: {'AKTIF' if status else 'NONAKTIF'}"
            )
            
        @discord.ui.button(label="Auto Mute", style=discord.ButtonStyle.red)
        async def toggle_mute(self, interaction: discord.Interaction, button: Button):
            with get_db_cursor() as cursor:
                cursor.execute("""
                    INSERT INTO filter_settings (guild_id, auto_mute)
                    VALUES (%s, TRUE)
                    ON DUPLICATE KEY UPDATE auto_mute = NOT auto_mute
                """, (ctx.guild.id,))
                
                cursor.execute("SELECT auto_mute FROM filter_settings WHERE guild_id = %s", (ctx.guild.id,))
                status = cursor.fetchone()[0]
                
            await interaction.response.send_message(
                f"✅ Auto mute: {'AKTIF' if status else 'NONAKTIF'}"
            )
            
    embed = discord.Embed(
        title="⚙️ Filter Settings",
        description="Setup filter settings untuk server lu",
        color=discord.Color.blue()
    )
    
    await ctx.send(embed=embed, view=FilterSetup())

# Update on_message event untuk handle filter
@bot.event
async def on_message(message):
    if message.author.bot:
        return
        
    if isinstance(message.channel, discord.DMChannel):
        await bot.process_commands(message)
        return
        
    try:
        with get_db_cursor() as cursor:
            # Get filter settings
            cursor.execute("""
                SELECT * FROM filter_settings 
                WHERE guild_id = %s
            """, (message.guild.id,))
            
            settings = cursor.fetchone()
            if settings:
                content = message.content.lower()
                violated = False
                reason = ""
                
                # Check filtered words
                cursor.execute("""
                    SELECT word FROM filter_words 
                    WHERE guild_id = %s
                """, (message.guild.id,))
                
                for word in cursor.fetchall():
                    if word[0] in content:
                        violated = True
                        reason = f"Filtered word: {word[0]}"
                        break
                
                # Check links
                if settings[2] and ('http://' in content or 'https://' in content):  # links_enabled
                    violated = True
                    reason = "Link detected"
                
                # Check invites
                if settings[3] and ('discord.gg/' in content or 'discordapp.com/invite/' in content):  # invites_enabled
                    violated = True
                    reason = "Discord invite detected"
                
                if violated:
                    await message.delete()
                    
                    # Handle auto warn
                    if settings[4]:  # auto_warn
                        cursor.execute("""
                            INSERT INTO member_warnings (guild_id, user_id, reason, warned_by)
                            VALUES (%s, %s, %s, %s)
                        """, (message.guild.id, message.author.id, reason, bot.user.id))
                        
                        # Check warn threshold
                        cursor.execute("""
                            SELECT COUNT(*) FROM member_warnings
                            WHERE guild_id = %s AND user_id = %s
                        """, (message.guild.id, message.author.id))
                        
                        warn_count = cursor.fetchone()[0]
                        
                        if warn_count >= settings[7]:  # warn_threshold
                            if settings[5]:  # auto_mute
                                # Implement mute logic here
                                mute_role = discord.utils.get(message.guild.roles, name="Muted")
                                if not mute_role:
                                    mute_role = await message.guild.create_role(name="Muted")
                                    
                                    for channel in message.guild.channels:
                                        await channel.set_permissions(mute_role, send_messages=False)
                                        
                                await message.author.add_roles(mute_role)
                                
                                # Schedule unmute
                                await asyncio.sleep(settings[6])  # mute_duration
                                await message.author.remove_roles(mute_role)
                                
                            await message.channel.send(
                                f"🔇 {message.author.mention} dimute karena terlalu banyak warning!"
                            )
                        else:
                            await message.channel.send(
                                f"⚠️ {message.author.mention} Warning {warn_count}/{settings[7]}: {reason}"
                            )
                    else:
                        await message.channel.send(
                            f"⚠️ {message.author.mention} Message lu ada yang dilarang: {reason}",
                            delete_after=5
                        )
                    
    except Error as e:
        print(f"Error in filter: {e}")
        
    await bot.process_commands(message)

@tasks.loop(hours=1)  # Cek setiap jam
async def check_trial_reminders():
    try:
        with get_db_cursor() as cursor:
            # Get semua trial yang aktif
            cursor.execute("""
                SELECT pt.guild_id, pt.end_date, rs.notify_channel_id, rs.notify_days
                FROM premium_trials pt
                JOIN reminder_settings rs ON pt.guild_id = rs.guild_id
                WHERE pt.is_active = TRUE 
                AND pt.end_date > CURRENT_TIMESTAMP
                AND (rs.last_reminder IS NULL OR 
                     rs.last_reminder < DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 1 DAY))
            """)
            
            for guild_id, end_date, channel_id, notify_days in cursor.fetchall():
                # Hitung sisa hari
                days_left = (end_date - datetime.now()).days
                
                if days_left == notify_days:
                    guild = bot.get_guild(guild_id)
                    if not guild:
                        continue
                        
                    channel = guild.get_channel(channel_id)
                    if not channel:
                        continue
                        
                    # Kirim reminder
                    embed = discord.Embed(
                        title="⚠️ Trial Premium Reminder",
                        description=f"Trial premium server ini akan berakhir dalam {days_left} hari!",
                        color=discord.Color.yellow()
                    )
                    embed.add_field(
                        name="Expired",
                        value=f"<t:{int(end_date.timestamp())}:R>",
                        inline=True
                    )
                    
                    await channel.send(
                        content="@everyone" if days_left == 1 else None,
                        embed=embed
                    )
                    
                    # Update last reminder
                    cursor.execute("""
                        UPDATE reminder_settings 
                        SET last_reminder = CURRENT_TIMESTAMP
                        WHERE guild_id = %s
                    """, (guild_id,))
                    
    except Error as e:
        print(f"Error checking reminders: {e}")

# Start background task
@bot.event
async def on_ready():
    check_trial_reminders.start()

@bot.group(name='dev')
async def dev(ctx):
    """Developer commands"""
    if ctx.invoked_subcommand is None:
        await ctx.send("❌ Command ga valid! Coba `!dev login`")

@dev.command(name='login')
async def dev_login(ctx):
    """Login sebagai developer"""
    # Cek apakah dari DM
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.message.delete()
        return await ctx.send("❌ Command ini cuma bisa dipake di DM!", delete_after=5)
        
    try:
        with get_db_cursor() as cursor:
            # Cek apakah user adalah developer
            cursor.execute("""
                SELECT user_id, token 
                FROM dev_credentials 
                WHERE user_id = %s AND is_active = TRUE
            """, (ctx.author.id,))
            
            result = cursor.fetchone()
            if not result:
                return await ctx.send("❌ Lu bukan developer bre!")
                
            # Generate session token
            session_id = secrets.token_hex(32)
            expires_at = datetime.now() + timedelta(hours=24)
            
            # Simpan session
            cursor.execute("""
                INSERT INTO dev_sessions (session_id, user_id, expires_at)
                VALUES (%s, %s, %s)
            """, (session_id, ctx.author.id, expires_at))
            
            # Update last login
            cursor.execute("""
                UPDATE dev_credentials 
                SET last_login = CURRENT_TIMESTAMP
                WHERE user_id = %s
            """, (ctx.author.id,))
            
            # Kirim konfirmasi
            embed = discord.Embed(
                title="✅ Login Berhasil!",
                description="Lu udah login sebagai developer",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Session Expires",
                value=f"<t:{int(expires_at.timestamp())}:R>",
                inline=True
            )
            
            await ctx.send(embed=embed)
            
    except Error as e:
        await ctx.send(f"Error: {str(e)}")
