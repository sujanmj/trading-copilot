from telethon.sync import TelegramClient
from telethon.sessions import StringSession

# Put your credentials here temporarily just to generate the string
API_ID = 33933958 
API_HASH = d4acc786c97267ff3a925136b86fc1bb

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print("\n" + "="*60)
    print("YOUR SESSION STRING IS BELOW. COPY EVERYTHING!")
    print("="*60)
    print(client.session.save())
    print("="*60)