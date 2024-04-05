import time

class spamHandler:

    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    def spam(self, text):
        users = self.db.get_all_users()
        for user in users:
            try:
                print("Sending message to user " + str(user))
                self.bot.send_message(user.user_id, text)
                time.sleep(0.5)
            except:
                print("Couldn't send message to user " + str(user))