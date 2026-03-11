from logging import Logger

import disnake
from disnake.ext.commands import Bot as OriginalBot


class Bot(OriginalBot):
    def __init__(self, logger: Logger, **kwargs):
        super().__init__(**kwargs)
        self.logger = logger

    async def on_ready(self):
        self.logger.info(f"The bot is ready! Logged in as {self.user}")
        await self.change_presence(
            status=disnake.Status.online,
            activity=disnake.Activity(
                type=disnake.ActivityType.watching,
                name="社交媒體連結"
            ),
        )
