import asyncio

# uvloop is optional, but it's recommended to install it for better performance of pyrogram
try:
  import uvloop
except:
  print("uvloop is not installed")

from pyrogram import Client
from config import API_ID, API_HASH, BOT_TOKEN
import keep_alive

if __name__ == '__main__':

  # If you are deploying on Replit, you can use this code to keep your bot alive
  if 'y' in input('Are you deploying on Replit? (y/n): ').lower():
    from config import REPL_URL
    keep_alive.awake(REPL_URL, False)

  # Setting up uvloop
  try:
    uvloop.install()
  except:
    print("Could not apply uvloop on project")

  # Defining path to plugins
  plugins = dict(root="plugins")

  # Defining the pyrogram client's instance
  Client("UploadBot",
         api_id=API_ID,
         api_hash=API_HASH,
         bot_token=BOT_TOKEN,
         plugins=plugins).run()
