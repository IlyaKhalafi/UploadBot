# UploadBot
Simple telegram bot to upload and download files on telegram messenger

## Usage
This bot is made to be simple and has only 3 commands:

- Shows bot welcome message through `/start` command
- Send any document, audio, video, photo to bot and it will upload it to `transfer.sh` and sends you the download link
- Send it a link to a file on the internet and it will download and send it to you on telegram

## Installation

Use the bash commands below to install and run the bot:

````bash
git clone https://github.com/IlyaKhalafi/UploadBot
pip3 install -r requirements.txt
# <Create config.py appropriately>
python3 main.py
````

### Requirements

* Python 3.6 or higher
* Pyrogram
* TgCrypto (Optional for Speedup)
* uvloop (Optional for Speedup)

### Variables

* `APP_ID` Your API ID from my.telegram.org
* `API_HASH` Your API Hash from my.telegram.org
* `BOT_TOKEN` Your bot token from @BotFather
* `MAX_FILE_SIZE` Maximum file size to upload in bytes, default is 200 MB
* `REPL_URL` If you are running this bot on repl.it, you need to set this to your repl.it URL so bot will ping itself to keep it alive. Also using **uptimerobot.com** is highly recommended.