import telebot
import os
import json
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound

import controller.dbHandler as dbHandler
import controller.quizHandler as quizHandler
import controller.exceptionHandler as exceptionHandler
import controller.spamHandler as spamHandler

# configuration available both from the env file and in the environment variables
try:
    with open('data/config/env.json') as f:
        data = json.load(f)
        api_key = data['API_KEY']
        admin_id = data['ADMIN_ID']
except Exception as e:
    api_key = os.environ['API_KEY']
    admin_id = os.environ['ADMIN_ID']

bot = telebot.TeleBot(api_key, exception_handler=exceptionHandler.ExceptionHandler())
db = dbHandler.DBHandler('pIm-a-bot.db')
qh = quizHandler.QuizHandler(db, bot)
spammer = spamHandler.spamHandler(bot, db)

db.create_connection()


@bot.message_handler(commands=['start'])
def start_bot(message):
    db.add_user_if_not_exists(message.from_user.id)

    try:

        with open('data/config/motd.txt', 'r') as motd:
            motd_content = motd.read()
        bot.send_message(message.from_user.id, motd_content)
        # TODO: Add a motd controller to customize the motd (something like a jinja template engine)

    except Exception as e:
        print(e)
        print("WARNING: No motd file found")
        bot.reply_to(message,
                     "The bot is having some issues, please try again later or contact the bot's administrator")


@bot.message_handler(commands=['leave'])
def leave_match(message):
    try:
        db.end_match(message.from_user.id)
    except Exception as e:
        if isinstance(e, NoResultFound):
            bot.send_message(message.from_user.id, "Non stai compilando alcun quiz")
            return
        bot.send_message(message.from_user.id, "500 - Internal Error")
        return
    bot.send_message(message.from_user.id, "Quiz terminato!")


@bot.message_handler(commands=['unregister'])
def unregister(message):
    # TODO: Add a confirmation message
    db.delete_user(message.from_user.id)
    bot.reply_to(message, "Ci dispiace vederti andare via, i tuoi dati sono stati cancellati.")


@bot.message_handler(commands=['spam'])
def spam(message):
    if (str(message.from_user.id) == admin_id):
        text = message.text
        text = text.replace('/spam', '')

        if (text == ''):
            bot.reply_to(message, "Devi inserire un messaggio da inviare!")
            return

        text = text[1:]
        spammer.spam(text)


cmds = []
for file in os.listdir('data/questions'):
    if file.endswith('.json'):
        cmds.append(file.split('.')[0])


@bot.message_handler(commands=cmds)
def start_match(message):
    # just for people who are here from v1.0 of so un bot
    db.add_user_if_not_exists(message.from_user.id)

    try:
        db.start_quiz(message.from_user.id, message.text[1:])

    except Exception as e:

        db.rollback()
        if isinstance(e, IntegrityError):

            bot.send_message(message.from_user.id,
                             "Stai giá compilando un quiz! Usa /leave per abbandonarlo e iniziarne un altro")
            return
        else:
            bot.send_message(message.from_user.id, "500 - Internal Error")
            return
    qh.handle_question(message)


@bot.message_handler(func=lambda message: True)
def response(message):
    try:
        if(qh.handle_question(message, True)):
            qh.handle_question(message)
        else:
            bot.send_message(message.from_user.id, "Riprova")
    except Exception as e:
        db.rollback()
        print(e)
        if(isinstance(e, NoResultFound)):
            bot.send_message(message.from_user.id, "Non ho capito, usa /start per vedere i quiz disponibili")
            return
        bot.send_message(message.from_user.id, "500 - Internal Error")


bot.polling()
