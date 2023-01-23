from pyrogram import Client, filters

@Client.on_message(filters.command('start') & filters.private & ~filters.bot)
async def start(client, message):
    await message.reply_text(
        f'Hi {message.from_user.first_name}!\n\n'
        f'Send me a file and I will upload it to transfer.sh and send you the download link.\n\n'
    )
