import time

class adminHandler:

    def __init__(self, bot, db, user_id):
        self.bot = bot
        self.db = db
        self.user_id = user_id

    def spam(self, text):
        users = self.db.get_all_users()
        for user in users:
            try:
                print("Sending message to user " + str(user))
                self.bot.send_message(user.user_id, text)
                time.sleep(0.5)
            except:
                print("Couldn't send message to user " + str(user))

    def send_error(self, text):
        if not isinstance(text, str):
            text = str(text)
        text = "Errore: \n" + text
        self.bot.send_message(self.user_id, text)