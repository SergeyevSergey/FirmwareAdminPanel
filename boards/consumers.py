from channels.generic.websocket import AsyncJsonWebsocketConsumer


class BoardsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add("boards", self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard("boards", self.channel_name)

    async def board_create(self, event):
        data = event.get("data")
        await self.send_json({
            "event": "board_create",
            "data": data
        })

    async def board_update(self, event):
        data = event.get("data")
        command = event.get("command")
        await self.send_json({
            "event": "board_update",
            "command": command,
            "data": data
        })

    async def board_timeout(self, event):
        data = event.get("data")
        command = event.get("command")
        await self.send_json({
            "event": "board_timeout",
            "command": command,
            "data": data
        })
