from telethon import TelegramClient, events
import requests

api_id = 23312577
api_hash = 'e879a3e9fd3d45cee98ef55214092805'

# List of private channel IDs
channel_ids = [-1002925960104, -1001630692598]

MAKE_WEBHOOK_URL = 'https://hook.eu2.make.com/y2od16qhv046ht3lwbx3ovtoj5eu345l'

client = TelegramClient('session_name', api_id, api_hash)

async def main():
    # Fetch entities for all channels
    channels = []
    for channel_id in channel_ids:
        channel = await client.get_entity(channel_id)
        channels.append(channel)

    @client.on(events.NewMessage(chats=channels))
    async def handle_new_message(event):
        channel = event.chat
        message_data = {
            'channel': channel.title if channel else "Unknown",
            'message_text': event.message.text,
            'date': event.message.date.isoformat(),
            'message_id': event.message.id,
            'sender_id': event.sender_id,
        }

        print(f"New message in {message_data['channel']}: {message_data['message_text']}")

        try:
            response = requests.post(MAKE_WEBHOOK_URL, json=message_data)
            print(f"Sent to Make.com: {response.status_code}")
        except Exception as e:
            print(f"Error sending to Make.com: {e}")

    print("🚀 Started listening for new messages on multiple channels...")
    await client.run_until_disconnected()

with client:
    client.loop.run_until_complete(main())
