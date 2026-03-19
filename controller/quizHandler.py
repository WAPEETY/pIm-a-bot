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
    # Per-user history of recently shown question indices (ordered, most recent last)
    # { user_id: [q_index, q_index, ...] }
    recent_questions = {}

    # Cooldown per box: how many other questions must be shown before this one can repeat
    BOX_COOLDOWNS = {0: 3, 1: 5, 2: 10, 3: None}  # None = until all others seen

    # Weights for weighted random selection
    BOX_WEIGHTS = {0: 8, 1: 4, 2: 2, 3: 1}

    # Tracks selected answer indices for multi-answer questions
    # { user_id: set of 0-indexed answer indices }
    dic_selection = {}

    def __init__(self, db, bot, admin):
        self.db = db
        self.bot = bot
        self.admin = admin

    def _is_on_cooldown(self, user_id, question_index, box, total_questions):
        """Check if a question is still on cooldown based on its box level."""
        history = self.recent_questions.get(user_id, [])
        if not history:
            return False

        cooldown = self.BOX_COOLDOWNS.get(box, 3)

        if cooldown is None:
            # Box 3: excluded until all other questions have been seen
            seen = set(history)
            unseen_others = [i for i in range(total_questions) if i != question_index and i not in seen]
            return len(unseen_others) > 0

        # Check if question appeared within the last 'cooldown' entries
        recent_window = history[-cooldown:] if cooldown <= len(history) else history
        return question_index in recent_window

    def open_file_and_get_question(self, filename, quest_id=None, user_id=None):
        filename = sanitize_filename(filename)

        with open('data/questions/' + filename + '.json') as f:
            questions = json.load(f)

        length = len(questions)

        if quest_id is None:
            # Get box levels for weighted selection
            boxes = self.db.get_question_boxes(user_id, filename) if user_id else {}
            history = self.recent_questions.get(user_id, [])

            # Build candidates: questions not on cooldown
            candidates = [
                i for i in range(length)
                if not self._is_on_cooldown(user_id, i, boxes.get(i, 0), length)
            ]

            if not candidates:
                # All on cooldown, fall back to all questions
                candidates = list(range(length))

            weights = [self.BOX_WEIGHTS.get(boxes.get(i, 0), 8) for i in candidates]
            quest_id = random.choices(candidates, weights=weights, k=1)[0]

            # Hard safety guard: never pick the same question consecutively
            if history and quest_id == history[-1] and len(candidates) > 1:
                other_candidates = [c for c in candidates if c != quest_id]
                other_weights = [w for c, w in zip(candidates, weights) if c != quest_id]
                quest_id = random.choices(other_candidates, weights=other_weights, k=1)[0]

            # Record in history
            if user_id not in self.recent_questions:
                self.recent_questions[user_id] = []
            self.recent_questions[user_id].append(quest_id)

            print(f"[QUIZ] user={user_id} file={filename} picked=Q{quest_id} "
                  f"candidates={candidates} boxes={boxes} history_len={len(history)}")

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
            is_correct = question['correct'] == idx
            if is_correct:
                self.db.add_correct_answer(user_id)
                p_correct, _, _, n_correct, n_wrong, n_na = self.db.get_quiz_stats(user_id)
                total = n_correct + n_wrong + n_na
                self.bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="✅ Risposta corretta!"
                         "\n<code>Correttezza: " + str(round(p_correct, 2))
                         + "% (" + str(n_correct) + " / " + str(total) + ")"
                         + "</code>\n<code>Streak attuale: " + str(self.db.get_streak(user_id))
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
            self.db.update_question_box(user_id, filename, quiz.last_question, is_correct)
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
            self.db.update_question_box(user_id, filename, quiz.last_question, True)
            p_correct, _, _, n_correct, n_wrong, n_na = self.db.get_quiz_stats(user_id)
            total = n_correct + n_wrong + n_na
            self.bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="✅ Segnata come corretta!"
                     "\n<code>Correttezza: " + str(round(p_correct, 2))
                     + "% (" + str(n_correct) + " / " + str(total) + ")"
                     + "</code>\n<code>Streak attuale: " + str(self.db.get_streak(user_id))
                     + "</code>",
                parse_mode='html'
            )
            self.bot.answer_callback_query(call.id)
            self._send_next_question(call, user_id)

        elif data == "mark_wrong":
            # Open question: self-graded as wrong
            self.db.add_wrong_answer(user_id)
            self.db.update_question_box(user_id, filename, quiz.last_question, False)
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
                self.db.update_question_box(user_id, filename, quiz.last_question, False)
                self.bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="🟡 Le risposte corrette erano: " + format_correct_answers(question)
                )
            elif selected == correct_set:
                self.db.add_correct_answer(user_id)
                self.db.update_question_box(user_id, filename, quiz.last_question, True)
                p_correct, _, _, n_correct, n_wrong, n_na = self.db.get_quiz_stats(user_id)
                total = n_correct + n_wrong + n_na
                self.bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="✅ Risposta corretta!"
                         "\n<code>Correttezza: " + str(round(p_correct, 2))
                         + "% (" + str(n_correct) + " / " + str(total) + ")"
                         + "</code>\n<code>Streak attuale: " + str(self.db.get_streak(user_id))
                         + "</code>",
                    parse_mode='html'
                )
            else:
                self.db.add_wrong_answer(user_id)
                self.db.update_question_box(user_id, filename, quiz.last_question, False)
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
            self.db.update_question_box(user_id, filename, quiz.last_question, False)
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