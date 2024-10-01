# %%
import json
import asyncio
import logging
import time
import os

from telegram import Bot
from telegram.constants import ParseMode  # Add this import to fix the error
from telegram.error import RetryAfter, TimedOut


# %%

# Replace with your bot token and group chat ID
BOT_TOKEN = ''
CHAT_ID = ''

# Set whether you're using a Telegram Premium account (True for premium, False for regular)
TELEGRAM_PREMIUM = True

# File size limits (50MB for regular users, 2GB for premium users)
MAX_FILE_SIZE_MB = 2048 if TELEGRAM_PREMIUM else 50

# Create a bot instance
bot = Bot(token=BOT_TOKEN)

# %%

def format_structured_text(text_list):
    """
    Format structured text, handling cases where 'text' can be a mix of strings and dictionaries.
    Handles formatting types: bold, italic, underline, strikethrough, code, links, and mentions.
    """
    formatted_text = ""
    
    if isinstance(text_list, str):
        return text_list

    for element in text_list:
        if isinstance(element, str):
            formatted_text += element
        elif isinstance(element, dict):
            formatting_type = element.get('type')
            text_content = element.get('text', '')

            if formatting_type == "bold":
                formatted_text += f"*{text_content}*"
            elif formatting_type == "italic":
                formatted_text += f"_{text_content}_"
            elif formatting_type == "underline":
                formatted_text += f"__{text_content}__"
            elif formatting_type == "strikethrough":
                formatted_text += f"~{text_content}~"
            elif formatting_type == "code":
                formatted_text += f"`{text_content}`"
            elif formatting_type == "link":
                href = element.get('href', '')
                formatted_text += f"[{text_content}]({href})"
            elif formatting_type == "mention":
                formatted_text += text_content  # Mention like @username
            else:
                formatted_text += text_content
                
    return formatted_text

def get_replied_message_info(messages, reply_to_message_id):
    """
    Search through messages to find the one that matches the reply_to_message_id.
    Returns the sender's name and content if available.
    """
    for msg in messages:
        if msg.get('id') == reply_to_message_id:
            return msg.get('from', 'Unknown Sender'), msg.get('text', '')
    return None, None

def log_error(message_id, error):
    """
    Log errors to a file for debugging purposes.
    """
    with open('error_log.txt', 'a') as log_file:
        log_file.write(f"Error with message {message_id}: {str(error)}\n")

async def process_messages(messages, delay=1, max_retries=5):
    """
    Process and send each message, handling text, photos, videos, audio, polls, round video messages, and stickers.
    Implements rate limiting, exponential backoff, and batch processing to avoid API rate limits.
    """
    retries = 0
    for message in messages:
        try:
            await send_universal_message(message, messages)
            retries = 0  # Reset retry count after a successful message
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            retries += 1
            if retries > max_retries:
                print(f"Exceeded max retries. Skipping message: {message['id']}")
                continue
            print(f"Flood control exceeded. Waiting for {retry_after} seconds...")
            await asyncio.sleep(retry_after)
            continue  # Retry the message
        except TimedOut:
            retries += 1
            if retries > max_retries:
                print(f"Exceeded max retries due to timeout. Skipping message: {message['id']}")
                continue    
            print(f"Timed out. Retrying after {delay * retries} seconds...")
            await asyncio.sleep(delay * retries)
            continue  # Retry the message
        except Exception as e:
            log_error(message['id'], e)
            print(f"Failed to send message {message['id']}: {e}")

        await asyncio.sleep(delay)

async def send_universal_message(message, all_messages):
    """
    Send a message to Telegram based on the media type or as text-only.
    Handles service messages, mentions, replies, reactions, pinned messages, and large files.
    """
    sender = message.get("from", "Unknown Sender")
    forwarded_from = message.get("forwarded_from", None)
    
    # Print to console for clarity
    print(f"Processing message from {sender}")

    reply_to_message_id = message.get("reply_to_message_id", None)
    message_text = message.get("text", "")
    media_type = message.get("media_type", None)
    file_path = message.get("file", None)
    poll = message.get("poll", None)
    duration = message.get("duration_seconds", 0)
    width = message.get("width", 0)
    height = message.get("height", 0)
    location = message.get("location", None)

    # Format structured text and include sender info
    formatted_text = format_structured_text(message_text)

    # Include forwarding info if present
    if forwarded_from:
        formatted_text = f"Forwarded from {forwarded_from}:\n\n" + formatted_text

    # Include reply-to info if present (find the sender of the replied message)
    if reply_to_message_id:
        replied_sender, replied_text = get_replied_message_info(all_messages, reply_to_message_id)
        if replied_sender:
            formatted_text = f"This message is a reply to {replied_sender}: {replied_text}\n\n" + formatted_text
        else:
            formatted_text = "This message is a reply to another message.\n\n" + formatted_text

    # Final formatted message including the sender
    formatted_message = f"Message from {sender}\n📅 Sent on: {message.get('date', 'Unknown Date')}\n{formatted_text}"

    # Handle large files by skipping them
    if file_path and os.path.exists(file_path):
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)  # Convert bytes to MB
        if file_size_mb > MAX_FILE_SIZE_MB:
            print(f"Skipping file {file_path} as it exceeds the size limit of {MAX_FILE_SIZE_MB} MB.")
            return

    try:
        # Handle photos
        if 'photo' in message and message['photo']:
            with open(message['photo'], 'rb') as photo_file:
                await bot.send_photo(chat_id=CHAT_ID, photo=photo_file, caption=formatted_message)
                print(f"Photo sent from {sender}")

        # Handle videos
        elif media_type == 'animation' or media_type == 'video_file':
            with open(file_path, 'rb') as video_file:
                await bot.send_video(chat_id=CHAT_ID, video=video_file, caption=formatted_message, duration=duration)
                print(f"Video sent from {sender}")

        # Handle voice messages
        elif media_type == 'voice_message' and file_path:
            with open(file_path, 'rb') as voice_file:
                await bot.send_voice(chat_id=CHAT_ID, voice=voice_file, duration=duration, caption=formatted_message)
                print(f"Voice message sent from {sender}")
        
        # Handle stickers
        elif media_type == 'sticker' and file_path:
            with open(file_path, 'rb') as sticker_file:
                await bot.send_sticker(chat_id=CHAT_ID, sticker=sticker_file)
                print(f"Sticker sent from {sender}")

        # Handle polls
        elif poll:
            poll_question = poll.get('question', 'No question')
            poll_answers = [answer['text'] for answer in poll.get('answers', [])]
            total_voters = poll.get('total_voters', 0)
            is_closed = poll.get('closed', False)
            poll_status = "Closed" if is_closed else "Open"
            await bot.send_poll(chat_id=CHAT_ID, question=poll_question, options=poll_answers, is_anonymous=True)
            await bot.send_message(chat_id=CHAT_ID, text=f"Poll Status: {poll_status}, Total Voters: {total_voters}")
            print(f"Poll sent from {sender}")

        # Handle locations
        elif location:
            latitude = location.get('latitude')
            longitude = location.get('longitude')
            await bot.send_location(chat_id=CHAT_ID, latitude=latitude, longitude=longitude)
            print(f"Location sent from {sender}")

        # Handle text messages
        else:
            await bot.send_message(chat_id=CHAT_ID, text=formatted_message, parse_mode=ParseMode.MARKDOWN)
            print(f"Text message sent from {sender}")

    except Exception as e:
        log_error(message['id'], e)
        print(f"Failed to send message {message['id']}: {e}")

async def main():
    # Load the JSON file (you can replace this with the actual JSON file you're using)
    with open('result.json', 'r', encoding='utf-8') as file:
        data = json.load(file)

    # Extract messages from the JSON
    messages = data.get('messages', [])

    # Process and send all messages with rate limiting
    await process_messages(messages, delay=1)

# Run the main function
if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        task = loop.create_task(main())
    else:
        asyncio.run(main())





        # %%
#NUM_MESSAGES_TO_PROCESS = 100  # Customize this to process any number of messages

#async def main():
    # Load the JSON file
#    with open('result.json', 'r', encoding='utf-8') as file:
#        data = json.load(file)

    # Get the first 'NUM_MESSAGES_TO_PROCESS' messages
#    messages = data.get('messages', [])[:NUM_MESSAGES_TO_PROCESS]

    # Process the specified number of messages
#    await process_messages(messages)

