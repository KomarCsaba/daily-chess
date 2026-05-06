from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # games where this user is white or black
    games_as_white = db.relationship("Game", foreign_keys="Game.white_id", backref="white_player")
    games_as_black = db.relationship("Game", foreign_keys="Game.black_id", backref="black_player")

    def get_games(self):
        return Game.query.filter(
            (Game.white_id == self.id) | (Game.black_id == self.id)
        ).all()


class Game(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    white_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    black_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    board_fen = db.Column(db.String(200), nullable=False, default="startpos")
    turn = db.Column(db.String(5), default="white")
    status = db.Column(db.String(20), default="waiting")
    result = db.Column(db.String(20), nullable=True)

    move_history = db.Column(db.Text, default="")
    last_move_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # NEW
    draw_offered_by = db.Column(db.Integer, nullable=True)
    time_control = db.Column(db.String(20), default="daily")
    time_control_mode = db.Column(db.String(20), default="per_move")
    turn_time_seconds = db.Column(db.Integer, default=86400)
    white_time_remaining = db.Column(db.Integer, nullable=True)
    black_time_remaining = db.Column(db.Integer, nullable=True)

    def get_moves_list(self):
        if not self.move_history:
            return []
        return self.move_history.split(",")

    def is_players_turn(self, user_id):
        if self.turn == "white" and self.white_id == user_id:
            return True
        if self.turn == "black" and self.black_id == user_id:
            return True
        return False

    def get_opponent(self, user_id):
        if self.white_id == user_id:
            return self.black_player
        return self.white_player
