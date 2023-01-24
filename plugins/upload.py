import os
import requests
import aiohttp
from pyrogram import Client, filters
from config import MAX_FILE_SIZE


@Client.on_message(
    filters.private
    & (filters.document | filters.photo | filters.audio | filters.video))
async def upload(client, message):
  # Checking if file size is greater than the defined limit
  if (message.document and message.document.file_size > MAX_FILE_SIZE):
    await message.reply_text(
        f'File is too big.\n\nFile size: {message.document.file_size}')
    return

  if (message.photo and message.photo.file_size > MAX_FILE_SIZE):
    await message.reply_text(
        f'Photo is too big.\n\nFile size: {message.photo.file_size}')
    return

  if (message.audio and message.audio.file_size > MAX_FILE_SIZE):
    await message.reply_text(
        f'Audio is too big.\n\nFile size: {message.audio.file_size}')
    return

  if (message.video and message.video.file_size > MAX_FILE_SIZE):
    await message.reply_text(
        f'Video is too big.\n\nFile size: {message.video.file_size}')
    return

  # TODO: Make it work for all media types
  # TODO: Photo object doesn't have file_name field
  # Getting file name from message
  file_name = None
  if message.document:
    file_name = message.document.file_name
  elif message.photo:
    file_name = message.photo.file_name
  elif message.audio:
    file_name = message.audio.file_name
  elif message.video:
    file_name = message.video.file_name

  # Uploading the file to transfer.sh
  await message.reply_text('Mirroring the file...', quote=True)

  # Mirroring the file from Telegram to transfer.sh
  link = None
  data = aiohttp.FormData()
  data.add_field('file', client.stream_media(message),
                 filename=file_name,
                 content_type='multipart/form-data')

  async with aiohttp.ClientSession() as session:
      async with session.post('https://transfer.sh/',
                              data=data) as response:
          link = (await response.content.read()).decode('utf-8')

  # Sending download link to user
  if link == None:
    await message.reply_text(
        'Failed to upload the file. Please try again later...', quote=True)
  else:
    parts = link.split('/')
    parts.insert(3, 'get')
    download_link = '/'.join(parts)
    await message.reply_text(
        f"File's Download Page:\n\n{link}"
        f'\n\nDirect Download Link:\n\n{download_link}'
        f'\n\nDownload Link will be valid for 2 weeks...',
        quote=True)
