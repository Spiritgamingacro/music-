import discord
from discord.ext import commands
from discord.ui import Button, View
from discord import app_commands
import yt_dlp
import asyncio
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# Bot settings
intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent
bot = commands.Bot(command_prefix='.', intents=intents)

# Spotify API setup
SPOTIFY_CLIENT_ID = ''
SPOTIFY_CLIENT_SECRET = ''
spotify = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET
))

# Global variables for the music bot
voice_client = None
queue = []
current_song = None
paused = False

# Event: Bot is ready
@bot.event
async def on_ready():
    print(f'Bot is ready! Logged in as {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

# Slash Command: Play a song by name or URL
@bot.tree.command(name="play", description="Play a song by name or URL.")
@app_commands.describe(song_name="The name or URL of the song to play.")
async def play_slash(interaction: discord.Interaction, song_name: str):
    global queue, voice_client

    await interaction.response.defer()  # Acknowledge the interaction to prevent timeouts

    # Ensure the bot is in a voice channel
    if voice_client is None or not voice_client.is_connected():
        # Get the author's voice channel
        if interaction.user.voice:
            channel = interaction.user.voice.channel
            voice_client = await channel.connect()
        else:
            await interaction.followup.send(embed=discord.Embed(
                description=':x: You need to be in a voice channel to use this command!', color=0xff0000
            ))
            return

    # Stop any current playback
    if voice_client.is_playing():
        voice_client.stop()

    try:
        # Search for the song on YouTube
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'noplaylist': True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_results = ydl.extract_info(f"ytsearch:{song_name}", download=False)['entries']
            if not search_results:
                await interaction.followup.send(embed=discord.Embed(
                    description=':x: Could not find the song on YouTube.', color=0xff0000
                ))
                return

            youtube_url = search_results[0]['url']
            title = search_results[0]['title']
            thumbnail_url = search_results[0].get('thumbnail', None)

            queue.append({
                'url': youtube_url,
                'title': title,
                'thumbnail': thumbnail_url,
                'ctx': interaction.channel  # Use the interaction's channel for follow-up
            })
            await interaction.followup.send(embed=discord.Embed(
                description=f':notes: **Added to queue:** {title}', color=0x00ff00
            ).set_thumbnail(url=thumbnail_url), view=MusicControlView())

        # Play the song immediately if not already playing
        if not voice_client.is_playing():
            await play_next()

    except Exception as e:
        await interaction.followup.send(embed=discord.Embed(
            description=f':x: An error occurred: {e}', color=0xff0000
        ))
        print(f"Error in play_slash command: {e}")

# Slash Command: Pause the current song
@bot.tree.command(name="pause", description="Pause the currently playing song.")
async def pause_slash(interaction: discord.Interaction):
    global paused, voice_client
    if voice_client and voice_client.is_playing():
        voice_client.pause()
        paused = True
        await interaction.response.send_message(embed=discord.Embed(
            description=':pause_button: Paused the music!', color=0x00ff00
        ))
    else:
        await interaction.response.send_message(embed=discord.Embed(
            description=':x: No music to pause!', color=0xff0000
        ))

# Slash Command: Skip the current song
@bot.tree.command(name="skip", description="Skip the currently playing song.")
async def skip_slash(interaction: discord.Interaction):
    global voice_client
    if voice_client.is_playing():
        voice_client.stop()
        await interaction.response.send_message(embed=discord.Embed(
            description=':track_next: Skipping the current song...', color=0x00ff00
        ))
    else:
        await interaction.response.send_message(embed=discord.Embed(
            description=':x: No song is currently playing!', color=0xff0000
        ))

# Slash Command: Ping
@bot.tree.command(name="ping", description="Check the bot's latency.")
async def ping_slash(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)  # Convert to milliseconds
    await interaction.response.send_message(embed=discord.Embed(
        description=f':ping_pong: Pong! Latency is **{latency}ms**.', color=0x00ff00
    ))

# Slash Command: Stop the current playback
@bot.tree.command(name="stop", description="Stop the music playback and clear the queue.")
async def stop_slash(interaction: discord.Interaction):
    global voice_client, queue

    if voice_client and voice_client.is_playing():
        voice_client.stop()
        queue.clear()  # Clear the queue
        await interaction.response.send_message(embed=discord.Embed(
            description=':stop_button: Stopped the playback and cleared the queue!', color=0x00ff00
        ))
    elif voice_client and (voice_client.is_connected() and queue):
        queue.clear()
        await interaction.response.send_message(embed=discord.Embed(
            description=':stop_button: Queue cleared!', color=0x00ff00
        ))
    else:
        await interaction.response.send_message(embed=discord.Embed(
            description=':x: No music is currently playing!', color=0xff0000
        ))

async def play_next():
    global queue, current_song, voice_client

    if queue and voice_client is not None:  # Ensure there's a queue and the bot is connected
        current_song = queue.pop(0)  # Get the next song in the queue

        try:
            # Play the next song using FFmpeg
            if voice_client.is_playing():  # Stop any existing playback
                voice_client.stop()

            source = discord.FFmpegPCMAudio(
                current_song['url'], 
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
            )
            voice_client.play(
                source,
                after=lambda e: asyncio.run_coroutine_threadsafe(play_next(), bot.loop).result()
                if not e else print(f"Error occurred: {e}")
            )

            # Notify the channel about the current song
            embed = discord.Embed(
                title="Now Playing",
                description=f":notes: **{current_song['title']}**",
                color=0x00ff00
            )
            if 'thumbnail' in current_song and current_song['thumbnail']:
                embed.set_thumbnail(url=current_song['thumbnail'])
            
            await current_song['ctx'].send(embed=embed, view=MusicControlView())

        except Exception as e:
            print(f"Error during playback: {e}")
            await asyncio.sleep(1)  # Avoid rapid loops
            await play_next()  # Try playing the next song in case of error
    else:
        current_song = None  # Reset current_song when the queue is empty
    
# Command: Join voice channel
@bot.command()
async def join(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        global voice_client
        if voice_client is None or not voice_client.is_connected():
            voice_client = await channel.connect()
            await ctx.send(embed=discord.Embed(
                description=f':white_check_mark: Joined **{channel}**!', color=0x00ff00
            ))
        else:
            await ctx.send(embed=discord.Embed(
                description=':x: I am already connected to a voice channel!', color=0xff0000
            ))
    else:
        await ctx.send(embed=discord.Embed(
            description=':x: You need to join a voice channel first!', color=0xff0000
        ))

# Music control buttons
class MusicControlView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Play", style=discord.ButtonStyle.green)
    async def play_button(self, interaction: discord.Interaction, button: Button):
        global paused, voice_client
        if voice_client and paused:
            voice_client.resume()
            paused = False
            await interaction.response.send_message(embed=discord.Embed(
                description=':arrow_forward: Resumed the music!', color=0x00ff00
            ), ephemeral=True)
        else:
            await interaction.response.send_message(embed=discord.Embed(
                description=':x: No music to resume!', color=0xff0000
            ), ephemeral=True)

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.red)
    async def pause_button(self, interaction: discord.Interaction, button: Button):
        global paused, voice_client
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            paused = True
            await interaction.response.send_message(embed=discord.Embed(
                description=':pause_button: Paused the music!', color=0x00ff00
            ), ephemeral=True)
        else:
            await interaction.response.send_message(embed=discord.Embed(
                description=':x: No music to pause!', color=0xff0000
            ), ephemeral=True)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        global voice_client
        if voice_client.is_playing():
            voice_client.stop()
            await interaction.response.send_message(embed=discord.Embed(
                description=':track_next: Skipping the current song...', color=0x00ff00
            ), ephemeral=True)
        else:
            await interaction.response.send_message(embed=discord.Embed(
                description=':x: No song is currently playing!', color=0xff0000
            ), ephemeral=True)

    @discord.ui.button(label="Volume Up", style=discord.ButtonStyle.gray)
    async def volume_up_button(self, interaction: discord.Interaction, button: Button):
        # Add volume control logic here
        await interaction.response.send_message(embed=discord.Embed(
            description=':loud_sound: Volume increased!', color=0x00ff00
        ), ephemeral=True)

    @discord.ui.button(label="Volume Down", style=discord.ButtonStyle.gray)
    async def volume_down_button(self, interaction: discord.Interaction, button: Button):
        # Add volume control logic here
        await interaction.response.send_message(embed=discord.Embed(
            description=':sound: Volume decreased!', color=0x00ff00
        ), ephemeral=True)

# Stay command to ensure the bot keeps playing silent audio to remain connected.
@bot.command()
async def stay(ctx):
    global voice_client

    if ctx.author.voice:
        channel = ctx.author.voice.channel
        if voice_client is None or not voice_client.is_connected():
            voice_client = await channel.connect()
            await ctx.send(embed=discord.Embed(
                description=f':white_check_mark: Joined **{channel}** and will stay connected 24/7!', color=0x00ff00
            ))
        else:
            await ctx.send(embed=discord.Embed(
                description=':white_check_mark: I am already connected to a voice channel and staying 24/7.', color=0x00ff00
            ))
        # Play silent audio to prevent Discord from disconnecting the bot
        if not voice_client.is_playing():
            source = discord.FFmpegPCMAudio("silent.mp3")
            voice_client.play(source, after=None)
    else:
        await ctx.send(embed=discord.Embed(
            description=':x: You need to join a voice channel first!', color=0xff0000
        ))

# Command: Play song by name (YouTube search)
@bot.command()
async def play(ctx, *, song_name: str):
    global queue, voice_client

    # Ensure the bot is in a voice channel
    if voice_client is None or not voice_client.is_connected():
        await ctx.invoke(join)

    try:
        # Search for the song on YouTube
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'noplaylist': True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_results = ydl.extract_info(f"ytsearch:{song_name}", download=False)['entries']
            if not search_results:
                await ctx.send(embed=discord.Embed(
                    description=':x: Could not find the song on YouTube.', color=0xff0000
                ))
                return

            youtube_url = search_results[0]['url']
            title = search_results[0]['title']
            thumbnail_url = search_results[0].get('thumbnail', None)

           # Add the song to the queue
            queue.append({
                'url': youtube_url,
                'title': title,
                'thumbnail': thumbnail_url,
                'ctx': ctx
            })
            await ctx.send(embed=discord.Embed(
                description=f':notes: **Added to queue:** {title}', color=0x00ff00
            ).set_thumbnail(url=thumbnail_url), view=MusicControlView())

        # Only play the song immediately if no other song is currently playing
        if not voice_client.is_playing() and len(queue) == 1:
            await play_next()

    except Exception as e:
        await ctx.send(embed=discord.Embed(
            description=f':x: An error occurred: {e}', color=0xff0000
        ))
        print(f"Error in play command: {e}")

# Command: Stop the current playback
@bot.command()
async def stop(ctx):
    global voice_client, queue

    if voice_client and voice_client.is_playing():
        voice_client.stop()
        queue.clear()  # Clear the queue
        await ctx.send(embed=discord.Embed(
            description=':stop_button: Stopped the playback and cleared the queue!', color=0x00ff00
        ))
    elif voice_client and (voice_client.is_connected() and queue):
        queue.clear()
        await ctx.send(embed=discord.Embed(
            description=':stop_button: Queue cleared!', color=0x00ff00
        ))
    else:
        await ctx.send(embed=discord.Embed(
            description=':x: No music is currently playing!', color=0xff0000
        ))

 # Ensure stay (24/7) compatibility in other commands like leave
@bot.command()
async def leave(ctx):
    global voice_client

    if voice_client is not None and voice_client.is_connected():
        if voice_client.is_playing():
            voice_client.stop()
        await voice_client.disconnect()
        voice_client = None
        await ctx.send(embed=discord.Embed(
            description=':white_check_mark: Disconnected from the voice channel!', color=0x00ff00
        ))
    else:
        await ctx.send(embed=discord.Embed(
            description=':x: I am not connected to any voice channel!', color=0xff0000
        ))       

# Command: Play song from Spotify link
@bot.command()
async def spotify_play(ctx, url: str):
    global queue, voice_client

    if voice_client is None or not voice_client.is_connected():
        await ctx.invoke(join)

    try:
        if 'open.spotify.com' in url:
            # Fetch track metadata from Spotify
            results = spotify.track(url)
            track_name = results['name']
            artist_name = results['artists'][0]['name']
            album_art = results['album']['images'][0]['url']
            search_query = f"{track_name} {artist_name}"

            # Search for the song on YouTube
            ydl_opts = {
                'format': 'bestaudio/best',
                'quiet': True,
                'noplaylist': True
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_results = ydl.extract_info(f"ytsearch:{search_query}", download=False)['entries']
                if not search_results:
                    await ctx.send(embed=discord.Embed(
                        description=':x: Could not find the song on YouTube.', color=0xff0000
                    ))
                    return

                youtube_url = search_results[0]['url']
                title = search_results[0]['title']
                queue.append({
                    'url': youtube_url,
                    'title': title,
                    'thumbnail': album_art,
                    'ctx': ctx
                })
                await ctx.send(embed=discord.Embed(
                    description=f':notes: **Added to queue:** {title} (from Spotify)', color=0x00ff00
                ).set_thumbnail(url=album_art), view=MusicControlView())

            # Play if not already playing
            if not voice_client.is_playing():
                await play_next()

        else:
            await ctx.send(embed=discord.Embed(
                description=':x: Please provide a valid Spotify track URL.', color=0xff0000
            ))

    except Exception as e:
        await ctx.send(embed=discord.Embed(
            description=f':x: An error occurred: {e}', color=0xff0000
        ))
        print(f"Error in spotify_play command: {e}")

# Command: Skip current song
@bot.command()
async def skip(ctx):
    global voice_client

    if voice_client.is_playing():
        voice_client.stop()
        await ctx.send(embed=discord.Embed(
            description=':track_next: Skipping the current song...', color=0x00ff00
        ))
    else:
        await ctx.send(embed=discord.Embed(
            description=':x: No song is currently playing!', color=0xff0000
        ))

# Command: Show queue
@bot.command()
async def queue_list(ctx):
    global queue

    if queue:
        description = '\n'.join([f'**{i + 1}.** {song["title"]}' for i, song in enumerate(queue)])
        await ctx.send(embed=discord.Embed(
            title=':cd: Music Queue',
            description=description,
            color=0x00ff00
        ))
    else:
        await ctx.send(embed=discord.Embed(
            description=':x: The queue is empty!', color=0xff0000
        ))

# Slash Command: Register for Active Developer Badge
@bot.tree.command(name="register-badge", description="Register for the Active Developer Badge!")
async def register_badge(interaction: discord.Interaction):
    await interaction.response.send_message(embed=discord.Embed(
        title="Active Developer Badge",
        description="Click [here](https://discord.com/developers/active-developer) to register for the badge.",
        color=0x00ff00
    ), ephemeral=True)

# Replace with your bot token
bot.run('')