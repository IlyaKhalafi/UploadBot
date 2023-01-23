from pyrogram import Client, filters

@Client.on_message(filters.text & filters.private)
async def download(client, message):
    pass