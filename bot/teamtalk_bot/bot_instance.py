from datetime import datetime
import pytalk
from bot.config import app_config

tt_bot = pytalk.TeamTalkBot(client_name=app_config.CLIENT_NAME)
current_tt_instance: pytalk.instance.TeamTalkInstance | None = None
login_complete_time: datetime | None = None # Used to ignore initial flood of user logins
