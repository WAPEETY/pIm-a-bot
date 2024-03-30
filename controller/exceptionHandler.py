import telebot
import controller.dbHandler as dbHandler

class ExceptionHandler(telebot.ExceptionHandler):
    def handle(self, exception):
        print(exception)
        #FIXME: I think that's a better way to check if the user is deactivated or blocked
        if "user is deactivated" in str(exception) or "user is blocked" in str(exception) or "bot was kicked" in str(exception):
            user_id = exception.args[0].user_id
            dbHandler.delete_user(user_id)
        return True