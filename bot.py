import discord
import asyncio
import io
import ctypes
import re
import os
from yt_dlp import YoutubeDL
from contextlib import redirect_stdout
from pathlib import Path

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
loop = asyncio.new_event_loop()

audio_queue = []
playback_inprogress = False

yt_base_url = re.compile("https:\/\/www.you")

cache_limit = 5
cache_height = 0
f_id = 0


async def say_hello(message):
    await message.channel.send("Hello")


async def show_queue(message):
    await message.channel.send("\n".join([q_e["search_term"] for q_e in audio_queue]))


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


async def add_to_queue(message):
    global audio_queue
    global playback_inprogress

    audio_queue.append({"channel" : message.author.voice.channel, "search_term" : " ".join(message.content.split()[1:]), "f_index" : None})
    await handle_cache()
    
    if not playback_inprogress:
        await play_yt("")
    await message.channel.send("Track added to queue")


async def skip_track(message):
    global playback_inprogress

    if playback_inprogress:
        client.voice_clients[0].stop()


def play_next(err):
    global cache_height
    global loop

    cache_height -= 1
    asyncio.run_coroutine_threadsafe(play_yt(err), loop)


async def play_yt(err):
    global playback_inprogress
    global audio_queue
    global yt_base_url

    if len(audio_queue) > 0:
        await handle_cache()

        playback_inprogress = True
        voice_channel = audio_queue[0]["channel"]
        audio_source = await discord.FFmpegOpusAudio.from_probe(f"tmp_{audio_queue[0]['f_index']}.webm")

        if voice_channel not in [vc.channel for vc in client.voice_clients]:
            await voice_channel.connect()

        audio_queue.pop(0)
        client.voice_clients[0].play(audio_source, after=play_next)
    else:
        playback_inprogress = False


    
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
#            print(f"Download from url: {url.split('&')[0]}")
            print("from serch term")
            track_info = yt_dl.extract_info(f"ytsearch:{search_term}", download=False)['entries'][0]

        src = [s for s in track_info["formats"] if s["format_id"] == "251"][0]["url"]
        yt_dl.download([src])


async def show_cmds(message):
    await message.channel.send("Available commands:\n" + "\n".join([cmd for cmd in responses.keys()]))


@client.event
async def on_ready():
    print(f"Loading opus")
    discord.opus.load_opus(ctypes.util.find_library("opus"))
    print(f"Opus loaded:{discord.opus.is_loaded()}")
    print(f'We have logged in as {client.user}')


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    msg_cont = message.content.split()
    await responses[msg_cont[0]](message)


responses = {"!hello" : say_hello, "!help" : show_cmds, "!play" : add_to_queue, "!queue" : show_queue, "!skip" : skip_track}

with open("./token", "r") as t_f:
    token = t_f.read()
    loop.create_task(client.start(token))

print(f"Loading opus")
loop.run_forever()
loop.close()
