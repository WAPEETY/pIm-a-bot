import json
import re
import random
import base64

question_type_enum = {
    "text": 0,
    "image_in_question": 1,
    "image_in_answer": 2,
    "image_in_question_and_answer": 3
}

class QuizHandler:

    dic_pick = {
        #"user_id": "your_user_id",
        #"ans": [ 1, 2, 3, 4]
    }


    def __init__(self,db,bot):
        self.db = db
        self.bot = bot

    def add_entry_to_dic_pick(self, user_id, id_question):
        if user_id in self.dic_pick:
            self.dic_pick[user_id].append(id_question)
        else:
            self.dic_pick[user_id] = [id_question]

    def open_file_and_get_question(self, filename, id = None, user_id = None):
        filename = self.sanitize_filename(filename)
        questions = None
    
        with open('questions/' + filename + '.json') as f:
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
        return question
    
    def sanitize_filename(self, filename):
        if not isinstance(filename, str):
            return None
        whitelist = re.compile(r'[a-zA-z]+')
        return whitelist.findall(filename)[0]

    def handle_question(self,message):
        quiz = self.db.get_quiz(message.from_user.id)
        filename = self.sanitize_filename(quiz.filename)
        
        if(filename is not None):
            question = self.open_file_and_get_question(filename, user_id=message.from_user.id)
            try:
                if question is not None:
                    self.send_question(message, question)
            except Exception as e:
                print(e)
                self.bot.send_message(message.from_user.id, "404 - File not found")
                return
        else:
            self.bot.send_message(message.from_user.id, "401 - Non risulta nessun quiz attivo")

    def analyze_question(self,question):

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
            "correct": 0,
        }
        '''

        qtype = 0
        if question['image'] is not "":
            qtype += 1
        if self.has_answer_image(question['answers']):
            qtype += 2
        
        return qtype

    def has_answer_image(self,answers):
        for answer in answers:
            if answer['image'] is not "":
                return True
        return False
    
    def decode_and_send_image(self,message,image, caption, max_length):
        image = base64.b64decode(image)
        if(len(caption) > max_length):
            self.bot.send_photo(message.from_user.id, image)
            self.send_multipart_message(message,caption,max_length)
        else:
            self.bot.send_photo(message.from_user.id, image, caption=caption)
        
    
    def send_multipart_message(self,message,buffer,max_length):
        for i in range(0, len(buffer), max_length):
                self.bot.send_message(message.from_user.id, buffer[i:i+max_length])

    def send_question(self,message,question):
        qtype = self.analyze_question(question)

        print("qtype: ", qtype)

        if qtype == question_type_enum["text"] or qtype == question_type_enum["image_in_question"]:
            buffer = question['quest']

            for i, answer in enumerate(question['answers']):
                buffer += "\n" + str(i + 1) + ") " + answer['text']

        elif qtype == question_type_enum["image_in_answer"] or qtype == question_type_enum["image_in_question_and_answer"]:
            buffer = question['quest']
        
        # type 0: send all the buffer
        # type 1: send the buffer as the caption of the photo
        # type 2: send the buffer as a message and each answer as a photo with the number as caption
        # type 3: send the buffer as the caption of the photo and each answer as a photo with the number as caption
        max_length = 3000 #4096
        max_length_image = 715 #1024

        if qtype == question_type_enum["text"]:
            # send the buffer as n messages if the length is greater than max_length
            self.send_multipart_message(message,buffer,max_length)

        elif qtype == question_type_enum["image_in_question"]:
            self.decode_and_send_image(message,question['image'],buffer,max_length)
        
        elif qtype == question_type_enum["image_in_answer"]:
            # send the buffer as a message and each answer as a photo with the number as caption
            self.send_multipart_message(message,buffer,max_length)
            
            for i, answer in enumerate(question['answers']):
                if(question['answers'][i]['image'] is ""):
                    self.send_multipart_message(message, str(i + 1) + ") " + answer['text'],max_length)
                else:
                    self.decode_and_send_image(message,answer['image'],str(i + 1) + ")",max_length_image)
        
        elif qtype == question_type_enum["image_in_question_and_answer"]:
            self.decode_and_send_image(message,question['image'],buffer,max_length)

            for i, answer in enumerate(question['answers']):
                if(question['answers'][i]['image'] is ""):
                    self.send_multipart_message(message, str(i + 1) + ") " + answer['text'],max_length)
                else:
                    self.decode_and_send_image(message,answer['image'],str(i + 1) + ")",max_length_image)

    def check(self,message):
        pass

'''
    def check(self,message):
        quiz = self.db.get_quiz(message.from_user.id)
        
        filename = quiz.filename
        
        if filename is not None:
            
            question = self.open_file_and_get_question(filename)



            try:
                with open('questions/' + filename + '.json') as f:
                    questions = json.load(f)

                    last_question = quiz.last_question
                    if last_question is None or last_question >= len(questions):
                        self.bot.reply_to(message, "500 - Internal Error")

                    question = questions[last_question]
                    
                    try:
                        answer = int(message.text)
                    except ValueError:
                        self.bot.reply_to(message, "Invalid answer")
                        return
                    
                    answer -= 1

                    if(question['correct'] == answer):
                        quiz.correct_answers += 1
                        self.bot.reply_to(message, "Correct")

            except Exception as e:
                self.bot.reply_to(message, "404 - File not found")
                return

        else:
            self.bot.reply_to(message, "You're not in a match")
        return
'''