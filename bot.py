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

# Tambahin variabel buat welcome message
welcome_messages = {}
welcome_channels = {}

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

class SAMPQuery:
    def __init__(self, ip, port=7777):
        self.ip = ip
        self.port = port
        
    def get_server_info(self):
        try:
            # Bikin socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.0)
            
            # SAMP query packet
            query = b'SAMP'
            query += struct.pack('!BBBB', *map(int, self.ip.split('.')))
            query += struct.pack('!H', self.port)
            query += b'i'
            
            # Kirim query
            sock.sendto(query, (self.ip, self.port))
            
            # Terima response
            response = sock.recvfrom(4096)[0]
            
            if response:
                # Parse response
                offset = 11
                
                password = bool(response[offset])
                offset += 1
                
                players = struct.unpack('!H', response[offset:offset+2])[0]
                offset += 2
                
                maxplayers = struct.unpack('!H', response[offset:offset+2])[0]
                offset += 2
                
                hostname_len = struct.unpack('!I', response[offset:offset+4])[0]
                offset += 4
                hostname = response[offset:offset+hostname_len].decode('latin-1')
                offset += hostname_len
                
                gamemode_len = struct.unpack('!I', response[offset:offset+4])[0]
                offset += 4
                gamemode = response[offset:offset+gamemode_len].decode('latin-1')
                offset += gamemode_len
                
                language_len = struct.unpack('!I', response[offset:offset+4])[0]
                offset += 4
                language = response[offset:offset+language_len].decode('latin-1')
                
                return {
                    'password': password,
                    'players': players,
                    'maxplayers': maxplayers,
                    'hostname': hostname,
                    'gamemode': gamemode,
                    'language': language
                }
                
        except Exception as e:
            print(f"Error querying SAMP server: {e}")
            return None
        finally:
            sock.close()

@bot.event
async def on_ready():
    print(f'Waduh! {bot.user} udah online nih!')
    
    @bot.event
    async def on_command_error(ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ Lu ga punya permission buat pake command ini bre! Admin only 😎")
        elif isinstance(error, commands.CommandNotFound):
            await ctx.send("❌ Command ga ada bre! Coba cek !help")

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
        guild_id = ctx.guild.id
        
        # Setup filter buat server ini
        if guild_id not in filter_words:
            filter_words[guild_id] = {
                'words': [],
                'links': False,
                'invites': False
            }
        
        # Tambahin kata ke filter
        added_words = []
        for word in words.lower().split():
            if word not in filter_words[guild_id]['words']:
                filter_words[guild_id]['words'].append(word)
                added_words.append(word)
        
        if added_words:
            embed = discord.Embed(
                title="✅ Filter Updated",
                description="Kata yang ditambahin ke filter:",
                color=discord.Color.green()
            )
            embed.add_field(name="Words", value="`" + "`, `".join(added_words) + "`")
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Kata-kata itu udah ada di filter!")
            
    except Exception as e:
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
        
    # Check filter
    guild_id = message.guild.id
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

# Jalanin bot pake token
bot.run(os.getenv('DISCORD_TOKEN'))
