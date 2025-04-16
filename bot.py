import discord
import asyncio
import io
import ctypes
import re
import os
import time
import datetime
import math
from yt_dlp import YoutubeDL
from contextlib import redirect_stdout
from pathlib import Path

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
voice_client = None
loop = asyncio.new_event_loop()

audio_queue = []
playback_inprogress = False
playback_timestamp = time.time()
playback_offset = 0.0

yt_base_url = re.compile("https:\/\/www.you")

cache_limit = 5
cache_height = 0
f_id = 0

commands = {}
command_prefix = "!"

channel_change = False
followed_user = None

def cmd(func):
    global commands

    commands.update({f"{command_prefix}{func.__name__}" : func})

    return func


def require_vc(func):
    global voice_client

    async def wrapper(*args, **kwargs):
        while voice_client == None:
            await asyncio.sleep(0.5)
            print(f"{func.__name__}: Waiting for VC")
        return await func(*args, **kwargs)

    return wrapper


def int_to_padded_str(num, padding=1):
    padded_num = str(num)
    padded_num = "0"*(padding+1 - len(padded_num)) + padded_num

    return padded_num


def fstamp_to_str(ts):
    int_ts = math.floor(ts)
    seconds = int_to_padded_str(int_ts % 60)
    minutes  = int_to_padded_str((int_ts//60) % 60)
    hours = int_to_padded_str((int_ts//3600))
    hun_sec = int_to_padded_str(math.floor(100*(ts - int_ts)))

    return f"{hours}:{minutes}:{seconds}.{hun_sec}"


async def handle_cache():
    global cache_height
    global cache_limit
    global f_id

    if(cache_height < cache_limit):
        uncached = [q_e for q_e in audio_queue if q_e["f_index"] == None]
        if len(uncached) > 0:
            queue_entry = uncached[0]

            f_index = f_id % cache_limit
            await download_audio(queue_entry["search_term"], f_index)
            queue_entry["f_index"] = f_index
            f_id += 1
            cache_height += 1


async def change_voicechannel(channel):
    global voice_client
    global channel_change
    global client
    
    channel_change = True

    await voice_client.disconnect()
    client.voice_clients.clear()
    del voice_client
    voice_client = None
    voice_client = await channel.connect()


def play_next(err):
    global playback_inprogress
    global cache_height
    global channel_change
    global loop

    if not channel_change:
        playback_inprogress = False
        cache_height -= 1
        audio_queue.pop(0)
        if len(audio_queue) > 0:
            asyncio.run_coroutine_threadsafe(play_yt(), loop)


@require_vc
async def play_yt(timestamp=0.0):
    global voice_client
    global playback_inprogress
    global playback_timestamp
    global playback_offset
    global audio_queue
    global yt_base_url

    await handle_cache()

    audio_source = await discord.FFmpegOpusAudio.from_probe(f"tmp_{audio_queue[0]['f_index']}.webm", before_options=f"-ss {fstamp_to_str(timestamp)}")
    playback_timestamp = time.time()
    playback_offset = timestamp
    playback_inprogress = True

    print(f"Playback started at {fstamp_to_str(timestamp)}")
    voice_client.play(audio_source, after=play_next)

    
async def download_audio(search_term, f_index):
    global yt_base_url
    ctx = {
        "outtmpl" : f"tmp_{f_index}.webm",
        "overwrites" : True,
        "http_chunk_size" : 10000000
    }

    with YoutubeDL(ctx) as yt_dl:
        if yt_base_url.match(search_term) != None:
            print(f"Download from url")
            track_info = yt_dl.extract_info(search_term.split("&")[0], download=False)
        else:
            print("from serch term")
            track_info = yt_dl.extract_info(f"ytsearch:{search_term}", download=False)['entries'][0]

        src = [s for s in track_info["formats"] if s["format_id"] == "251"][0]["url"]
        yt_dl.download([src])


async def renew_playback():
    global playback_timestamp
    global playback_offset

    resume_ts = time.time() - playback_timestamp + playback_offset
    await play_yt(timestamp=resume_ts)


@client.event
async def on_ready():
    print(f"Loading opus")
    discord.opus.load_opus(ctypes.util.find_library("opus"))
    print(f"Opus loaded:{discord.opus.is_loaded()}")
    print(f'We have logged in as {client.user}')


@client.event
async def on_message(message):
    global commands

    if message.author != client.user:
        msg_cont = message.content.split()
        await commands[msg_cont[0]](message)


@client.event
async def on_voice_state_update(member, before, after):
    global playback_inprogress
    global channel_change
    global followed_user

    if member.id == client.user.id and playback_inprogress:
        if before.channel == None:
            channel_change = False
            await renew_playback()
    elif followed_user == member.id:
        if after.channel != None:
            await asyncio.sleep(0.5)
            await change_voicechannel(after.channel)
        else:
            followed_user = None
        


@cmd
async def hello(message):
    await message.channel.send("Hello")


@cmd
async def queue(message):
    global audio_queue

    await message.channel.send("\n".join([q_e["search_term"] for q_e in audio_queue]))


@cmd
async def help(message):
    global commands

    await message.channel.send("Available commands:\n" + "\n".join([cmd for cmd in commands.keys()]))


@cmd
async def play(message):
    global audio_queue
    global playback_inprogress
    global voice_client

    if voice_client == None:
        voice_channel = message.author.voice.channel
        voice_client = await voice_channel.connect()

    audio_queue.append({"search_term" : " ".join(message.content.split()[1:]), "f_index" : None})
    await handle_cache()
    
    if not playback_inprogress:
        await play_yt()
    else:
        await message.channel.send("Track added to queue")


@cmd
async def skip(message):
    global voice_client
    global playback_inprogress

    if playback_inprogress:
        voice_client.stop()


@cmd
async def come(message):
    await change_voicechannel(message.author.voice.channel)


@cmd
async def follow(message):
    global followed_user

    followed_user = message.author.id
    await message.channel.send(f"Following {message.author.display_name}")


with open("./token", "r") as t_f:
    token = t_f.read()
    loop.create_task(client.start(token))


loop.run_forever()
loop.close()
