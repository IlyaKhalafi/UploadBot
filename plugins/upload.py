import os
import requests
from pyrogram import Client, filters
from config import MAX_FILE_SIZE


def upload_to_transfersh(file_path):

    url = 'https://transfer.sh/'
    file = {'{}'.format(file_path): open(file_path, 'rb')}
    response = requests.post(url, files=file)
    download_link = response.content.decode('utf-8')
    return download_link


@Client.on_message(filters.private
                   & (filters.document | filters.photo | filters.audio | filters.video))
async def upload(client, message):

    # Checking if file size is greater than the defined limit
    if (message.document and message.document.file_size > MAX_FILE_SIZE):
        await message.reply_text(
            f'File is too big.\n\nFile size: {message.document.file_size}'
        )
        return
    if (message.photo and message.photo.file_size > MAX_FILE_SIZE):
        await message.reply_text(
            f'Photo is too big.\n\nFile size: {message.photo.file_size}'
        )
        return
    if (message.audio and message.audio.file_size > MAX_FILE_SIZE):
        await message.reply_text(
            f'Audio is too big.\n\nFile size: {message.audio.file_size}'
        )
        return
    if (message.video and message.video.file_size > MAX_FILE_SIZE):
        await message.reply_text(
            f'Video is too big.\n\nFile size: {message.video.file_size}'
        )
        return

    # Downloading the file
    await message.reply_text('Downloading file...', quote=True)
    path = await message.download()
    if not path:
        await message.reply_text('Failed to download the file. Please try again later...', quote=True)
        return

    # Uploading the file to transfer.sh
    await message.reply_text('Uploading the file to transfer.sh...', quote=True)
    link = upload_to_transfersh(path).removesuffix('\n')

    # remove file in from local storage
    os.remove(path)

    # Sending download link to user
    parts = link.split('/')
    parts.insert(3, 'get')
    download_link = '/'.join(parts)
    await message.reply_text(f"File's Download Page:\n\n{link}"
                             f'\n\nDirect Download Link:\n\n{download_link}'
                             f'\n\nDownload Link will be valid for 2 weeks...', quote=True)
