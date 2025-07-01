from pydantic import BaseModel
from typing import List

class SubscriberInfo(BaseModel):
    telegram_id: int
    display_name: str

class WhoUser(BaseModel):
    nickname: str

class WhoChannelGroup(BaseModel):
    channel_name: str
    users: List[WhoUser]
