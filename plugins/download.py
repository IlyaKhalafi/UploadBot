from pyrogram import Client, filters

photo_extensions = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'svg']

audio_extensions = ['mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a', 'wma', 'alac', 'opus']

video_extensions = ['mp4', 'mkv', 'avi', 'webm', 'flv', 'wmv', 'mov', 'mpeg', '3gp']

@Client.on_message(filters.text & filters.private)
async def downloadage(client, message):
    try:
        if message.text.endswith(tuple(photo_extensions)):
            await message.reply_photo(photo=message.text, quote=True)
            
        elif message.text.endswith(tuple(audio_extensions)):
            await message.reply_audio(audio=message.text, quote=True)
            
        elif message.text.endswith(tuple(video_extensions)):
            await message.reply_video(video=message.text, quote=True)
            
        else:
            await message.reply_document(document=message.text, quote=True)
            
    except:
        await message.reply_text("Something went wrong. Probably the download link is invalid?", quote=True)
