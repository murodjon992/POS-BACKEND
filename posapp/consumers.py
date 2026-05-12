import json
from channels.generic.websocket import AsyncWebsocketConsumer

class PosConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.group_name = "pos_updates"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def pos_message(self, event):
        # Event ichidagi action va payloadni olamiz
        # 'type' kalitini olib tashlaymiz, u frontenda kerak emas
        data_to_send = {
            "action": event.get("action"),
            "payload": event.get("payload")
        }
        await self.send(text_data=json.dumps(data_to_send))