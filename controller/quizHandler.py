import json
import re
import random
import base64
import telebot

question_type_enum = {
    "text": 0,
    "image_in_question": 1,
    "image_in_answer": 2,
    "image_in_question_and_answer": 3
}


def sanitize_html(text):
    return (text.replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("&lt;code&gt;", "<code>")
            .replace("&lt;/code&gt;", "</code>")
            .replace("&lt;pre&gt;", "<pre>")
            .replace("&lt;/pre&gt;", "</pre>")
            .replace("&lt;/pre&gt;", "</pre>")
            .replace("&lt;b&gt;", "<b>")
            .replace("&lt;/b&gt;", "</b>"))


class QuizHandler:
    dic_pick = {
        # "user_id": "your_user_id",
        # "ans": [ 1, 2, 3, 4]
    }

    def __init__(self, db, bot):
        self.db = db
        self.bot = bot

    def add_entry_to_dic_pick(self, user_id, id_question):
        if user_id in self.dic_pick:
            self.dic_pick[user_id].append(id_question)
        else:
            self.dic_pick[user_id] = [id_question]

    def open_file_and_get_question(self, filename, id=None, user_id=None):
        filename = self.sanitize_filename(filename)
        questions = None

        with open('data/questions/' + filename + '.json') as f:
            questions = json.load(f)

        length = len(questions)
        question = None

        # if the user has already answered all the questions we reset the dic_pick
        # so the user can answer the questions again
        if user_id in self.dic_pick and len(self.dic_pick[user_id]) == length:
            self.dic_pick[user_id] = []

        while id is None:
            rand = random.randint(0, length - 1)

            if user_id not in self.dic_pick or (user_id in self.dic_pick and rand not in self.dic_pick[user_id]):
                id = rand
                self.add_entry_to_dic_pick(user_id, rand)

        if id < 0 or id >= length:
            id = id % length

        question = questions[id]
        self.db.set_last_question(user_id, id)
        return question

    def sanitize_filename(self, filename):
        if not isinstance(filename, str):
            return None
        whitelist = re.compile(r'[a-zA-z1-9]+')
        return whitelist.findall(filename)[0]

    def handle_question(self, message, resp=False):
        quiz = self.db.get_quiz(message.from_user.id)
        filename = self.sanitize_filename(quiz.filename)

        if (filename is not None):
            question = self.open_file_and_get_question(filename, id=quiz.last_question if resp else None,
                                                       user_id=message.from_user.id)
            try:
                if question is not None:
                    if (resp):
                        if not self.check_question(message, question):
                            return False
                        return True
                    else:
                        self.send_question(message, question)
                        return True
            except Exception as e:
                print(e)
                self.bot.send_message(message.from_user.id, "404 - File not found")
                return False
        else:
            self.bot.send_message(message.from_user.id, "500 - Errore nella gestione del quiz")
            return False

    def analyze_question(self, question):

        '''
        JSON structure:
        {
            "quest": "question",
            "image": "base64image",
            "answers": 
            [
                {
                    "text": "answer1",
                    "image": "base64image"
                }
            ],
            "correct": 1, (starting from 1 since 0 is for not answered questions)
        }
        '''

        qtype = 0
        if question['image'] != "":
            qtype += 1
        if self.has_answer_image(question['answers']):
            qtype += 2

        return qtype

    def has_answer_image(self, answers):
        for answer in answers:
            if answer['image'] != "":
                return True
        return False

    def decode_and_send_image(self, message, image, caption, max_length):
        image = base64.b64decode(image)
        if (len(caption) > max_length):
            self.bot.send_photo(message.from_user.id, image)
            self.send_multipart_message(message, caption, max_length)
        else:
            self.bot.send_photo(message.from_user.id, image, caption=caption)

    def send_multipart_message(self, message, buffer, max_length):
        for i in range(0, len(buffer), max_length):
            self.bot.send_message(message.from_user.id, buffer[i:i + max_length], parse_mode='html')

    def send_question(self, message, question):
        qtype = self.analyze_question(question)

        if qtype == question_type_enum["text"] or qtype == question_type_enum["image_in_question"]:
            buffer = question['quest']

            for i, answer in enumerate(question['answers']):
                buffer += "\n" + str(i + 1) + ") " + answer['text']

        elif qtype == question_type_enum["image_in_answer"] or qtype == question_type_enum["image_in_question_and_answer"]:
            buffer = question['quest']

        else:
            self.bot.send_message(message.from_user.id, "500 - Internal Error")
            return

        # type 0: send all the buffer
        # type 1: send the buffer as the caption of the photo
        # type 2: send the buffer as a message and each answer as a photo with the number as caption
        # type 3: send the buffer as the caption of the photo and each answer as a photo with the number as caption
        max_length = 3000  # 4096
        max_length_image = 715  # 1024

        buffer = sanitize_html(buffer)

        if qtype == question_type_enum["text"]:
            # send the buffer as n messages if the length is greater than max_length
            self.send_multipart_message(message, buffer, max_length)

        elif qtype == question_type_enum["image_in_question"]:
            self.decode_and_send_image(message, question['image'], buffer, max_length)

        elif qtype == question_type_enum["image_in_answer"]:
            # send the buffer as a message and each answer as a photo with the number as caption
            self.send_multipart_message(message, buffer, max_length)

            for i, answer in enumerate(question['answers']):
                if (question['answers'][i]['image'] == ""):
                    self.send_multipart_message(message, str(i + 1) + ") " + answer['text'], max_length)
                else:
                    self.decode_and_send_image(message, answer['image'], str(i + 1) + ")", max_length_image)

        elif qtype == question_type_enum["image_in_question_and_answer"]:
            self.decode_and_send_image(message, question['image'], buffer, max_length)

            for i, answer in enumerate(question['answers']):
                if (question['answers'][i]['image'] == ""):
                    self.send_multipart_message(message, str(i + 1) + ") " + answer['text'], max_length)
                else:
                    self.decode_and_send_image(message, answer['image'], str(i + 1) + ")", max_length_image)

        keyboard = telebot.types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True, one_time_keyboard=True)
        for i, answer in enumerate(question['answers']):
            keyboard.add(telebot.types.InlineKeyboardButton(text=str(i + 1)))

        keyboard.add(telebot.types.InlineKeyboardButton(text="Passa"))
               
        self.bot.send_message(message.from_user.id, "Scegli la risposta", reply_markup=keyboard)

    def check_question(self, message, question):

        try:
            answer = int(message.text)
        except ValueError:
            #this is the worst way to handle this, but I'm too lazy to do it properly
            if message.text == "Passa":
                answer = 0
            else:
                self.bot.send_message(message.from_user.id, "Risposta non valida")
                return False

        if answer == 0:
            self.db.add_not_answered(message.from_user.id)
            self.bot.send_message(message.from_user.id, "🟡 La risposta corretta era la " + str(1 + question['correct']))
        elif question['correct'] == answer - 1:
            self.db.add_correct_answer(message.from_user.id)
            self.bot.send_message(message.from_user.id, "✅ Risposta corretta!")
        else:
            self.db.add_wrong_answer(message.from_user.id)
            self.bot.send_message(message.from_user.id, "❌ Risposta errata. La risposta corretta era la " + str(1 + question['correct']))

        return True
