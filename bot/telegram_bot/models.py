from pydantic import BaseModel


class SubscriberInfo(BaseModel):
    telegram_id: int
    display_name: str
    teamtalk_username: str | None = None


class WhoUser(BaseModel):
    nickname: str


class WhoChannelGroup(BaseModel):
    channel_name: str
    users: list[WhoUser]
