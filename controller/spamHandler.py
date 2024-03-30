import time

class spamHandler:

    def __init__(self, bot, db):
        self.bot = bot
        self.db = db

    def spam(self, text):
        users = self.db.get_all_users()
        for user in users:
            try:
                self.bot.send_message(user[0], text)
                time.sleep(0.5)
            except:
                print("Couldn't send message to user " + str(user[0]))