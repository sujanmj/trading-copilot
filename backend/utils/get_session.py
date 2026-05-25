# Save this locally as get_session.py and run it ONCE on your PC.
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

# Paste the credentials from my.telegram.org here just for this script
API_ID = 12345678  # Replace with your API ID (Integer)
API_HASH = 'your_api_hash_here' # Replace with your API Hash (String)

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print("\n" + "="*60)
    print("YOUR SESSION STRING IS BELOW. COPY EVERYTHING AND SAVE IT!")
    print("="*60)
    print(client.session.save())
    print("="*60)