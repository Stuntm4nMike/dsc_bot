import discord
import asyncio
import io
import ctypes
import re
import os
import time
import datetime
import math
import multiprocessing as mp
import concurrent.futures
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
download_inprogress = False

cache_limit = 5
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
        while voice_client == None or not voice_client.is_connected():
            await asyncio.sleep(0.5)
            print(f"{func.__name__}: Waiting for VC")
        return await func(*args, **kwargs)

    return wrapper


async def wait_for_download(q_idx):
    global audio_queue

    while not audio_queue[q_idx]["downloaded"]:
        await asyncio.sleep(0.5)
        print("Waiting for download")


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


def get_video_url(url):
    global yt_base_url

    ctx = {
        "http_chunk_size" : 10485760
    }

    with YoutubeDL(ctx) as yt_dl:
        if yt_base_url.match(url) != None:
            print(f"Download from url")
            track_info = yt_dl.extract_info(url.split("&")[0], download=False)
        else:
            print("from serch term")
            track_info = yt_dl.extract_info(f"ytsearch:{url}", download=False)['entries'][0]

    return [s for s in track_info["formats"] if s["format_id"] == "251"][0]["url"]


async def add_to_queue(s_t):
    global audio_queue
    if len(audio_queue) == 0:
        video_url = get_video_url(s_t)
    else:
        with concurrent.futures.ProcessPoolExecutor() as exc:
            video_url = await loop.run_in_executor(exc, get_video_url, s_t)

    audio_queue.append({"search_term" : s_t, "video_url" : video_url, "f_index" : None, "downloaded" : False, "downloading" : False})


async def handle_cache():
    global cache_limit
    global download_inprogress
    global f_id

    for q_i in range(0, cache_limit):
        if q_i >= len(audio_queue):
            return

        q_e = audio_queue[q_i]

        if not q_e["downloaded"] and not q_e["downloading"]:
            q_e["downloading"] = True
            while download_inprogress:
                await asyncio.sleep(1)
            with concurrent.futures.ProcessPoolExecutor() as exc:
                download_inprogress = True
                f_index = f_id % cache_limit
                q_e["f_index"] = f_index
                fut = await loop.run_in_executor(exc, download_audio, q_e["video_url"], f_index)
                q_e["downloaded"] = fut
                f_id += 1
                download_inprogress = False


@require_vc
async def change_voicechannel(channel):
    global voice_client
    global channel_change
    global client
    
    channel_change = True

    await voice_client.disconnect()
    while voice_client.is_connected():
        await asyncio.sleep(0.5)
    client.voice_clients.clear()
    del voice_client
    voice_client = None
    voice_client = await channel.connect()


def play_next(err):
    global playback_inprogress
    global channel_change
    global loop

    if not channel_change:
        playback_inprogress = False
        audio_queue.pop(0)
        if len(audio_queue) > 0:
            asyncio.run_coroutine_threadsafe(handle_cache(), loop)
            asyncio.run_coroutine_threadsafe(play_yt(), loop)


@require_vc
async def play_yt(timestamp=0.0):
    global voice_client
    global playback_inprogress
    global playback_timestamp
    global playback_offset
    global audio_queue
    global yt_base_url

    await wait_for_download(0)

    audio_source = await discord.FFmpegOpusAudio.from_probe(f"tmp_{audio_queue[0]['f_index']}.webm", before_options=f"-ss {fstamp_to_str(timestamp)}")
    playback_timestamp = time.time()
    playback_offset = timestamp
    playback_inprogress = True

    print(f"Playback started at {fstamp_to_str(timestamp)}")
    voice_client.play(audio_source, after=play_next)

    
def download_audio(v_url, f_index, rt=0):
    ctx = {
        "outtmpl" : f"tmp_{f_index}.webm",
        "overwrites" : True,
        "http_chunk_size" : 10485760
    }
    try:
        with YoutubeDL(ctx) as yt_dl:
            yt_dl.download([v_url])
        return True
    except:
        if rt >= 5:
            return False
        download_audio(v_url, f_index, rt=rt+1)

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
        if after.channel != None:

            if after.channel != before.channel and before.channel != None:
                print(f"B:{before.channel} A:{after.channel}")
                await asyncio.sleep(1.0)
                await change_voicechannel(after.channel)
            
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

    await message.channel.send("Queue:\n" + "\n".join([f"{q_i + 1}. {q_e['search_term']}" for q_i, q_e in enumerate(audio_queue)]))


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

    search_term = " ".join(message.content.split()[1:])

    await add_to_queue(search_term)
    await message.channel.send("Track added to queue")
    await handle_cache()
    
    if not playback_inprogress:
        await play_yt()


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

if __name__ == "__main__":
    with open("./token", "r") as t_f:
        token = t_f.read()
        loop.create_task(client.start(token))


    loop.run_forever()
    loop.close()
