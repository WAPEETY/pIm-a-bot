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


def sanitize_filename(filename):
    if not isinstance(filename, str):
        return None
    whitelist = re.compile(r'[a-zA-z1-9]+')
    return whitelist.findall(filename)[0]


def has_answer_image(answers):
    for answer in answers:
        if answer['image'] != "":
            return True
    return False


def is_multi_answer(question):
    """Returns True if the question has multiple correct answers (correct is a list)."""
    return 'correct' in question and isinstance(question['correct'], list)


def is_open_question(question):
    """Returns True if the question is an open question (has open_answer field)."""
    return 'open_answer' in question


def format_correct_answers(question):
    """Returns a human-readable string of the correct answer(s) (1-indexed)."""
    if is_open_question(question):
        return question['open_answer']
    if is_multi_answer(question):
        return ', '.join(str(i + 1) for i in question['correct'])
    return str(1 + question['correct'])


def analyze_question(question):
    """
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
        "correct": 1, (starting from 0, or a list e.g. [0, 2] for multi-answer)
    }
    """

    qtype = 0
    if question['image'] != "":
        qtype += 1
    if not is_open_question(question) and has_answer_image(question['answers']):
        qtype += 2

    return qtype


class QuizHandler:
    dic_pick = {
        # "user_id": "your_user_id",
        # "ans": [ 1, 2, 3, 4]
    }

    # Tracks selected answer indices for multi-answer questions
    # { user_id: set of 0-indexed answer indices }
    dic_selection = {}

    def __init__(self, db, bot, admin):
        self.db = db
        self.bot = bot
        self.admin = admin

    def add_entry_to_dic_pick(self, user_id, id_question):
        if user_id in self.dic_pick:
            self.dic_pick[user_id].append(id_question)
        else:
            self.dic_pick[user_id] = [id_question]

    def open_file_and_get_question(self, filename, quest_id=None, user_id=None):
        filename = sanitize_filename(filename)

        with open('data/questions/' + filename + '.json') as f:
            questions = json.load(f)

        length = len(questions)

        # if the user has already answered all the questions we reset the dic_pick
        # so the user can answer the questions again
        if user_id in self.dic_pick and len(self.dic_pick[user_id]) == length:
            self.dic_pick[user_id] = []

        while quest_id is None:
            rand = random.randint(0, length - 1)

            if user_id not in self.dic_pick or (user_id in self.dic_pick and rand not in self.dic_pick[user_id]):
                quest_id = rand
                self.add_entry_to_dic_pick(user_id, rand)

        if quest_id < 0 or quest_id >= length:
            quest_id = quest_id % length

        question = questions[quest_id]
        self.db.set_last_question(user_id, quest_id)
        return question

    def handle_question(self, message, resp=False):
        quiz = self.db.get_quiz(message.from_user.id)
        filename = sanitize_filename(quiz.filename)

        if filename is not None:
            question = self.open_file_and_get_question(filename,
                                                       quest_id=quiz.last_question if resp else None,
                                                       user_id=message.from_user.id)
            try:
                if question is not None:
                    if resp:
                        # All answers are handled via inline callbacks now
                        self.bot.send_message(message.from_user.id,
                                              "Usa i pulsanti per rispondere")
                        return False
                    else:
                        self.send_question(message, question)
                        return True
            except Exception as e:
                print(e)
                self.bot.send_message(message.from_user.id, "404 - File not found")
                self.admin.send_error("Errore nella domanda: " + str(e))
                return False
        else:
            self.bot.send_message(message.from_user.id, "500 - Errore nella gestione del quiz")
            self.admin.send_error("Errore nella gestione del quiz, filename = None")
            return False

    def decode_and_send_image(self, message, image, caption, max_length):
        image = base64.b64decode(image)
        if len(caption) > max_length:
            self.bot.send_photo(message.chat.id, image)
            self.send_multipart_message(message, caption, max_length)
        else:
            self.bot.send_photo(message.chat.id, image, caption=caption)

    def send_multipart_message(self, message, buffer, max_length):
        for i in range(0, len(buffer), max_length):
            self.bot.send_message(message.chat.id, buffer[i:i + max_length], parse_mode='html')

    def send_question(self, message, question):
        qtype = analyze_question(question)

        if is_open_question(question):
            # Open question: just show the question text (no answer choices)
            buffer = question['quest']
        elif qtype == question_type_enum["text"] or qtype == question_type_enum["image_in_question"]:
            buffer = question['quest']

            for i, answer in enumerate(question['answers']):
                buffer += "\n\n" + str(i + 1) + ". " + answer['text']

        elif (qtype == question_type_enum["image_in_answer"]
              or qtype == question_type_enum["image_in_question_and_answer"]):
            buffer = question['quest']

        else:
            self.bot.send_message(message.chat.id, "500 - Internal Error")
            self.admin.send_error("Errore nella gestione della domanda, tipo di domanda non valido")
            return

        max_length = 3000  # 4096
        max_length_image = 715  # 1024

        buffer = sanitize_html(buffer)

        if is_open_question(question):
            # Open question: just send the question text
            if question['image'] != "":
                self.decode_and_send_image(message, question['image'], buffer, max_length)
            else:
                self.send_multipart_message(message, buffer, max_length)
        elif qtype == question_type_enum["text"]:
            self.send_multipart_message(message, buffer, max_length)

        elif qtype == question_type_enum["image_in_question"]:
            self.decode_and_send_image(message, question['image'], buffer, max_length)

        elif (qtype == question_type_enum["image_in_answer"]
              or qtype == question_type_enum["image_in_question_and_answer"]):

            if qtype == question_type_enum["image_in_answer"]:
                self.send_multipart_message(message, buffer, max_length)
            else:
                self.decode_and_send_image(message, question['image'], buffer, max_length)

            for i, answer in enumerate(question['answers']):
                if question['answers'][i]['image'] == "":
                    self.send_multipart_message(message, str(i + 1) + ") " + answer['text'], max_length)
                else:
                    self.decode_and_send_image(message, answer['image'], str(i + 1) + ")", max_length_image)

        # send the inline keyboard
        if is_open_question(question):
            prompt = "Pensa alla risposta, poi premi per rivelarla 👁"
        elif is_multi_answer(question):
            self.dic_selection[message.chat.id] = set()
            prompt = "Seleziona le risposte corrette e poi premi Conferma ✅"
        else:
            prompt = "Scegli la risposta"

        keyboard = self._build_keyboard(question, message.chat.id)
        self.bot.send_message(message.chat.id, prompt, reply_markup=keyboard)

    def _build_keyboard(self, question, user_id):
        """Builds an InlineKeyboardMarkup for any question type."""
        keyboard = telebot.types.InlineKeyboardMarkup(row_width=1)

        if is_open_question(question):
            # Open question: reveal answer button
            keyboard.add(telebot.types.InlineKeyboardButton(
                text="Mostra risposta 👁", callback_data="reveal"))
        elif is_multi_answer(question):
            # Multi-answer: toggle buttons + confirm
            selected = self.dic_selection.get(user_id, set())
            for i, answer in enumerate(question['answers']):
                icon = "✅" if i in selected else "⬜"
                keyboard.add(telebot.types.InlineKeyboardButton(
                    text=icon + " " + str(i + 1) + ". " + answer['text'],
                    callback_data="toggle_" + str(i)
                ))
            keyboard.add(telebot.types.InlineKeyboardButton(
                text="Conferma ✅", callback_data="confirm"))
        else:
            # Single-answer: direct answer buttons (instant confirm on click)
            for i, answer in enumerate(question['answers']):
                keyboard.add(telebot.types.InlineKeyboardButton(
                    text=str(i + 1) + ". " + answer['text'],
                    callback_data="answer_" + str(i)
                ))

        keyboard.add(telebot.types.InlineKeyboardButton(
            text="Passa 🟡", callback_data="skip"))
        return keyboard

    def handle_callback(self, call):
        """Handles inline button presses for all question types."""
        user_id = call.from_user.id

        try:
            quiz = self.db.get_quiz(user_id)
        except Exception:
            self.bot.answer_callback_query(call.id, "Non stai compilando alcun quiz")
            return

        filename = sanitize_filename(quiz.filename)
        if filename is None:
            self.bot.answer_callback_query(call.id, "Errore")
            return

        question = self.open_file_and_get_question(filename,
                                                   quest_id=quiz.last_question,
                                                   user_id=user_id)

        data = call.data

        if data.startswith("answer_"):
            # Single-answer: instant confirm
            idx = int(data.split("_")[1])
            if question['correct'] == idx:
                self.db.add_correct_answer(user_id)
                correct, wrong, not_answered = self.db.get_quiz_stats(user_id)
                self.bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="✅ Risposta corretta!"
                         "\n<code>Correttezza: " + str(round(correct, 2))
                         + "%</code>\n<code>Streak attuale: " + str(self.db.get_streak(user_id))
                         + "</code>",
                    parse_mode='html'
                )
            else:
                self.db.add_wrong_answer(user_id)
                self.bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="❌ Risposta errata. La risposta corretta era la " + format_correct_answers(question)
                )
            self.bot.answer_callback_query(call.id)
            self._send_next_question(call, user_id)

        elif data == "reveal":
            # Open question: reveal the answer and show correct/wrong buttons
            answer_text = sanitize_html(question['open_answer'])
            grading_keyboard = telebot.types.InlineKeyboardMarkup(row_width=2)
            grading_keyboard.row(
                telebot.types.InlineKeyboardButton(text="Corretto ✅", callback_data="mark_correct"),
                telebot.types.InlineKeyboardButton(text="Sbagliato ❌", callback_data="mark_wrong")
            )
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="💡 <b>Risposta:</b>\n" + answer_text,
                parse_mode='html',
                reply_markup=grading_keyboard
            )
            self.bot.answer_callback_query(call.id)

        elif data == "mark_correct":
            # Open question: self-graded as correct
            self.db.add_correct_answer(user_id)
            correct, wrong, not_answered = self.db.get_quiz_stats(user_id)
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="✅ Segnata come corretta!"
                     "\n<code>Correttezza: " + str(round(correct, 2))
                     + "%</code>\n<code>Streak attuale: " + str(self.db.get_streak(user_id))
                     + "</code>",
                parse_mode='html'
            )
            self.bot.answer_callback_query(call.id)
            self._send_next_question(call, user_id)

        elif data == "mark_wrong":
            # Open question: self-graded as wrong
            self.db.add_wrong_answer(user_id)
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="❌ Segnata come errata."
            )
            self.bot.answer_callback_query(call.id)
            self._send_next_question(call, user_id)

        elif data.startswith("toggle_"):
            # Multi-answer: toggle selection
            idx = int(data.split("_")[1])
            selected = self.dic_selection.setdefault(user_id, set())
            if idx in selected:
                selected.discard(idx)
            else:
                selected.add(idx)
            new_keyboard = self._build_keyboard(question, user_id)
            try:
                self.bot.edit_message_reply_markup(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    reply_markup=new_keyboard
                )
            except Exception:
                pass
            self.bot.answer_callback_query(call.id)

        elif data == "confirm":
            # Multi-answer: confirm selection
            selected = self.dic_selection.pop(user_id, set())
            correct_set = set(question['correct'])

            if len(selected) == 0:
                self.db.add_not_answered(user_id)
                self.bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="🟡 Le risposte corrette erano: " + format_correct_answers(question)
                )
            elif selected == correct_set:
                self.db.add_correct_answer(user_id)
                correct, wrong, not_answered = self.db.get_quiz_stats(user_id)
                self.bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="✅ Risposta corretta!"
                         "\n<code>Correttezza: " + str(round(correct, 2))
                         + "%</code>\n<code>Streak attuale: " + str(self.db.get_streak(user_id))
                         + "</code>",
                    parse_mode='html'
                )
            else:
                self.db.add_wrong_answer(user_id)
                self.bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="❌ Risposta errata. Le risposte corrette erano: " + format_correct_answers(question)
                )

            self.bot.answer_callback_query(call.id)
            self._send_next_question(call, user_id)

        elif data == "skip":
            self.dic_selection.pop(user_id, None)
            self.db.add_not_answered(user_id)
            if is_open_question(question):
                text = "🟡 Risposta saltata. La risposta era:\n" + sanitize_html(question['open_answer'])
            else:
                text = "🟡 La risposta corretta era: " + format_correct_answers(question)
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=text
            )
            self.bot.answer_callback_query(call.id)
            self._send_next_question(call, user_id)

    def _send_next_question(self, call, user_id):
        """Helper to send the next question after a callback."""
        try:
            quiz = self.db.get_quiz(user_id)
            filename = sanitize_filename(quiz.filename)
            if filename is not None:
                question = self.open_file_and_get_question(filename, user_id=user_id)
                if question is not None:
                    self.send_question(call.message, question)
        except Exception as e:
            print(e)