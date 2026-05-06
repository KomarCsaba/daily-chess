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
    join_code = db.Column(db.String(8), unique=True, nullable=True)
    time_control = db.Column(db.String(20), default="daily")
    time_control_mode = db.Column(db.String(20), default="per_move")
    turn_time_seconds = db.Column(db.Integer, default=86400)
    white_time_remaining = db.Column(db.Integer, nullable=True)
    black_time_remaining = db.Column(db.Integer, nullable=True)
    last_move_uci = db.Column(db.String(10), nullable=True)
    last_move_flags = db.Column(db.String(120), nullable=True)
    
    # For fifty-move rule and threefold repetition
    halfmove_clock = db.Column(db.Integer, default=0)  # Moves since last capture/pawn move
    position_history = db.Column(db.Text, default="")  # FEN positions separated by |

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
    
    def get_position_history(self):
        """Get list of FEN positions from history"""
        if not self.position_history:
            return []
        return self.position_history.split("|")
    
    def add_position_to_history(self, fen):
        """Add current position to history"""
        history = self.get_position_history()
        history.append(fen)
        self.position_history = "|".join(history) if history else ""
    
    def is_threefold_repetition(self):
        """Check if current position has occurred three times"""
        current_fen = self.board_fen.split()[0]  # Only position part, ignore move counters
        history = self.get_position_history()
        count = sum(1 for pos in history if pos.split()[0] == current_fen)
        return count >= 3
    
    def is_fifty_move_rule(self):
        """Check if fifty-move rule applies (100 halfmoves without capture/pawn move)"""
        return self.halfmove_clock >= 100
