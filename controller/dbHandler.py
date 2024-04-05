# use sqlalchemy to handle database operations for the application using sqlite3
import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    user_id = Column(Integer, primary_key=True)
    registration_date = Column(String)
    streak = Column(Integer)
    quizzes = relationship("Quiz", backref="user", cascade="all, delete-orphan")
    
    def __repr__(self):
        return "<User(user_id='%s', registration_date='%s', streak='%s')>" % \
        (self.user_id, self.registration_date, self.streak)

class Quiz(Base):
    __tablename__ = 'quizzes'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.user_id'), nullable=False)
    filename = Column(String)
    correct_answers = Column(Integer)
    wrong_answers = Column(Integer)
    not_answered = Column(Integer)
    terminated = Column(Boolean)
    last_question = Column(Integer)

    def __repr__(self):
        return "<Quiz(id='%s', user_id='%s', filename='%s', correct_answers='%s', wrong_answers='%s', not_answered='%s', terminated='%s', last_question='%s')>" % \
        (self.id, self.user_id, self.filename, self.correct_answers, self.wrong_answers, self.not_answered, self.terminated, self.last_question)

#TODO: This is just a concept to keep the version of the db so we can migrate it
class DBVersion(Base):
    __tablename__ = 'db_version'
    version = Column(Integer, primary_key=True)

    def __repr__(self):
        return "<DBVersion(version='%s')>" % (self.version)

class DBHandler:
    def __init__(self, db_name):
        self.db_name = db_name
        self.engine = create_engine('sqlite:///data/' + db_name, echo=False)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()
        Base.metadata.create_all(self.engine)

    def create_connection(self):
        self.conn = sqlite3.connect('data/' + self.db_name)
        self.cursor = self.conn.cursor()
        
        self.cursor.execute('''
            PRAGMA foreign_keys = ON
        ''')
        
        # schema creation, should be handled better to archieve the possibility of painless migrations
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY,
                registration_date TEXT,
                streak INTEGER
            )
        ''')

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS quizzes(
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                filename TEXT,
                correct_answers INTEGER,
                wrong_answers INTEGER,
                not_answered INTEGER,
                terminated BOOLEAN,
                last_question INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS db_version(
                version INTEGER PRIMARY KEY
            )
        ''')

        self.cursor.execute('''
            INSERT INTO db_version(version) VALUES(1) ON CONFLICT DO NOTHING
        ''')

        self.cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS check_quiz BEFORE INSERT ON quizzes
            BEGIN
                SELECT CASE WHEN EXISTS(SELECT 1 FROM quizzes WHERE user_id = NEW.user_id AND terminated = 0) THEN
                    RAISE(ABORT, 'User is already in a match')
                END;
            END
        ''')
        
        self.conn.commit()

    def add_user_if_not_exists(self, user_id):
        try:
            user = User(user_id=user_id, registration_date=datetime.now(), streak=0)
            self.session.add(user)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            return "User already exists"

    def start_quiz(self, user_id, quiz_filename):          
        quiz = Quiz(user_id=user_id, filename=quiz_filename, correct_answers=0, wrong_answers=0, not_answered=0, terminated=False)

        self.session.add(quiz)
        self.session.commit()

    def delete_user(self, user_id):
        #since SQLite is shit and doesn't seem to support ON DELETE CASCADE we have to do this manually
        self.session.query(Quiz).filter(Quiz.user_id == user_id).delete()
        self.session.query(User).filter(User.user_id == user_id).delete()
        
        self.session.commit()

    def get_all_users(self):
        return self.session.query(User)

    def end_match(self, user_id):
        quiz = self.session.query(Quiz).filter(Quiz.user_id == user_id).filter(Quiz.terminated == False).one()
        quiz.terminated = True
        self.session.commit()
        
    def is_in_quiz(self, user_id):
        try:
            quiz = self.session.query(Quiz).filter(Quiz.user_id == user_id).one()
            print(not quiz.terminated)
            return not quiz.terminated
        except NoResultFound:
            self.session.rollback()
            return "404 - not found"
        
    def rollback(self):
        self.session.rollback()
        
    def get_quiz(self, user_id):
        
        quiz = self.session.query(Quiz).filter(Quiz.user_id == user_id).filter(Quiz.terminated == False).one()
        return quiz

    def close_connection(self):
        self.conn.close()

    def set_last_question(self, user_id, last_question):
        quiz = self.session.query(Quiz).filter(Quiz.user_id == user_id).filter(Quiz.terminated == False).one()
        quiz.last_question = last_question
        self.session.commit()

    def add_correct_answer(self, user_id):
        quiz = self.session.query(Quiz).filter(Quiz.user_id == user_id).filter(Quiz.terminated == False).one()
        quiz.correct_answers += 1
        self.increment_streak(user_id)
        self.session.commit()

    def add_wrong_answer(self, user_id):
        quiz = self.session.query(Quiz).filter(Quiz.user_id == user_id).filter(Quiz.terminated == False).one()
        quiz.wrong_answers += 1
        self.reset_streak(user_id)
        self.session.commit()
    
    def add_not_answered(self, user_id):
        quiz = self.session.query(Quiz).filter(Quiz.user_id == user_id).filter(Quiz.terminated == False).one()
        quiz.not_answered += 1
        self.reset_streak(user_id)
        self.session.commit()

    def reset_streak(self, user_id):
        user = self.session.query(User).filter(User.user_id == user_id).one()
        user.streak = 0
        self.session.commit()

    def increment_streak(self, user_id):
        user = self.session.query(User).filter(User.user_id == user_id).one()
        user.streak += 1
        self.session.commit()

    def get_streak(self, user_id):
        user = self.session.query(User).filter(User.user_id == user_id).one()
        return user.streak
    
    def get_quiz_stats(self, user_id):
        #return the percentage of correct, wrong and not given answers
        quiz = self.session.query(Quiz).filter(Quiz.user_id == user_id).filter(Quiz.terminated == False).one()

        total = quiz.correct_answers + quiz.wrong_answers + quiz.not_answered

        if total == 0:
            return 0, 0, 0
        
        return quiz.correct_answers / total * 100, quiz.wrong_answers / total * 100, quiz.not_answered / total * 100

    def get_all_quizzes_stats_for_user(self,user_id):

        qry = self.session.query(func.sum(Quiz.correct_answers).label("correct"), func.sum(Quiz.wrong_answers).label("wrong"), func.sum(Quiz.not_answered).label("notgiven")).filter(Quiz.user_id == user_id).filter(Quiz.terminated == True).one()

        total = qry.correct + qry.wrong + qry.notgiven
        return qry.correct / total * 100, qry.wrong / total * 100, qry.notgiven / total * 100

    def __del__(self):
        self.session.close()