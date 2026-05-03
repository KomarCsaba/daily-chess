from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from models import db, User, Game
import chess
import uuid
import os
import threading
from datetime import datetime
import logging
import requests

logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev_secret_key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///chess.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# email config
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_TIMEOUT"] = 10
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_USERNAME")

app.config["BASE_URL"] = os.environ.get(
    "BASE_URL",
    "http://localhost:8080"
)

app.config["RESEND_API_KEY"] = os.environ.get("RESEND_API_KEY")


database_url = os.environ.get("DATABASE_URL", "sqlite:///chess.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url

db.init_app(app)
mail = Mail(app)
print("MAIL_USERNAME:", app.config["MAIL_USERNAME"])
print("MAIL_PASSWORD exists:", bool(app.config["MAIL_PASSWORD"]))
login_manager = LoginManager(app)
login_manager.login_view = "index"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def send_turn_notification(game, recipient):
    try:
        game_url = f"{app.config['BASE_URL']}/game/{game.id}"

        requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {app.config['RESEND_API_KEY']}",
                "Content-Type": "application/json"
            },
            json={
                "from": "Daily Chess <onboarding@resend.dev>",
                "to": recipient.email,
                "subject": "Your move!",
                "text": f"""
Hi {recipient.username},

It's your turn in your Daily Chess game.

Play here:
{game_url}
"""
            }
        )

        print(f"Email sent to {recipient.email}")

    except Exception as e:
        print(f"Email error: {e}")



# --- ROUTES ---

@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("index.html")

@app.route("/register", methods=["POST"])
def register():
    username = request.form.get("username")
    email = request.form.get("email")
    password = request.form.get("password")

    if User.query.filter_by(username=username).first():
        flash("Username already taken")
        return redirect(url_for("index"))

    if User.query.filter_by(email=email).first():
        flash("Email already registered")
        return redirect(url_for("index"))

    user = User(
        username=username,
        email=email,
        password=generate_password_hash(password)
    )
    db.session.add(user)
    db.session.commit()
    login_user(user)
    return redirect(url_for("dashboard"))

@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username")
    password = request.form.get("password")
    user = User.query.filter_by(username=username).first()

    if not user or not check_password_hash(user.password, password):
        flash("Invalid username or password")
        return redirect(url_for("index"))

    login_user(user)
    return redirect(url_for("dashboard"))

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    games = current_user.get_games()
    return render_template("dashboard.html", games=games)

@app.route("/new_game")
@login_required
def new_game():
    game = Game(
        id=str(uuid.uuid4()),
        white_id=current_user.id,
        board_fen=chess.Board().fen(),
        status="waiting"
    )
    db.session.add(game)
    db.session.commit()
    return redirect(url_for("game", game_id=game.id))

@app.route("/join/<game_id>")
@login_required
def join_game(game_id):
    game = Game.query.get(game_id)

    if not game:
        flash("Game not found")
        return redirect(url_for("dashboard"))

    if game.status != "waiting":
        flash("Game already started")
        return redirect(url_for("dashboard"))

    if game.white_id == current_user.id:
        flash("You can't join your own game")
        return redirect(url_for("dashboard"))

    game.black_id = current_user.id
    game.status = "active"
    db.session.commit()
    return redirect(url_for("game", game_id=game.id))

@app.route("/game/<game_id>")
@login_required
def game(game_id):
    game = Game.query.get(game_id)
    if not game:
        flash("Game not found")
        return redirect(url_for("dashboard"))
    return render_template("game.html", game=game)


@app.route("/move/<game_id>", methods=["POST"])
@login_required
def make_move(game_id):
    game = Game.query.get(game_id)
    if not game or game.status != "active":
        return {"error": "Game not found or not active"}, 400

    if not game.is_players_turn(current_user.id):
        return {"error": "Not your turn"}, 400

    move_uci = request.json.get("move")

    board = chess.Board(game.board_fen)
    try:
        move = chess.Move.from_uci(move_uci)
        if move not in board.legal_moves:
            return {"error": "Illegal move"}, 400

        san = board.san(move)
        board.push(move)

        # Update move history
        moves = game.get_moves_list()
        moves.append(san)
        game.move_history = ",".join(moves)
        game.board_fen = board.fen()

        next_turn = "black" if game.turn == "white" else "white"
        game.turn = next_turn
        game.last_move_at = datetime.utcnow()

        # IMPORTANT FIX:
        # Only clear draw offer if the OPPONENT is the one moving
        # (i.e. they are implicitly declining the draw)
        if game.draw_offered_by == current_user.id:
            # Offerer is moving → keep the offer active
            pass
        else:
            # Opponent is moving → they decline the draw
            game.draw_offered_by = None

        # ... rest of the code (checkmate, stalemate, etc.)

        if board.is_checkmate():
            game.status = "finished"
            winner = "white" if next_turn == "black" else "black"
            game.result = f"{winner}_wins"
        elif board.is_stalemate() or board.is_insufficient_material():
            game.status = "finished"
            game.result = "draw"

        db.session.commit()

        # notify opponent...
        opponent = game.get_opponent(current_user.id)
        if opponent and game.status == "active" and opponent.email:
            threading.Thread(
                target=send_turn_notification,
                args=(game, opponent)
            ).start()

        return {"success": True, "fen": board.fen()}

    except Exception as e:
        print(f"Move error: {e}")
        return {"error": str(e)}, 400


@app.route("/legal_moves/<game_id>/<int:col>/<int:row>")
@login_required
def legal_moves(game_id, col, row):
    game = Game.query.get(game_id)
    if not game:
        return {"moves": []}

    board = chess.Board(game.board_fen)
    square = chess.square(col, 7 - row)
    moves = []
    for move in board.legal_moves:
        if move.from_square == square:
            to_col = chess.square_file(move.to_square)
            to_row = 7 - chess.square_rank(move.to_square)
            moves.append(f"{to_col},{to_row}")

    return {"moves": moves}

@app.route("/resign/<game_id>", methods=["POST"])
@login_required
def resign(game_id):
    game = Game.query.get(game_id)
    if not game or game.status != "active":
        flash("Invalid game")
        return redirect(url_for("dashboard"))

    if not game.is_players_turn(current_user.id):
        flash("Not your turn")
        return redirect(url_for("game", game_id=game_id))

    # Determine winner
    if game.white_id == current_user.id:
        game.result = "black_wins"
    else:
        game.result = "white_wins"

    game.status = "finished"
    db.session.commit()
    flash("You resigned")
    return redirect(url_for("game", game_id=game_id))


@app.route("/offer_draw/<game_id>", methods=["POST"])
@login_required
def offer_draw(game_id):
    game = Game.query.get(game_id)
    if not game or game.status != "active" or not game.is_players_turn(current_user.id):
        return redirect(url_for("game", game_id=game_id))

    game.draw_offered_by = current_user.id
    db.session.commit()
    flash("Draw offered")
    return redirect(url_for("game", game_id=game_id))


@app.route("/accept_draw/<game_id>", methods=["POST"])
@login_required
def accept_draw(game_id):
    game = Game.query.get(game_id)
    if not game or game.status != "active":
        return redirect(url_for("dashboard"))

    if game.draw_offered_by and game.draw_offered_by != current_user.id:
        game.status = "finished"
        game.result = "draw"
        db.session.commit()
        flash("Draw accepted")
    return redirect(url_for("game", game_id=game_id))

@app.route("/join_by_code", methods=["POST"])
@login_required
def join_by_code():
    code = request.form.get("code", "").strip()
    # extract game id from full URL or just use it directly
    game_id = code.split("/join/")[-1] if "/join/" in code else code
    return redirect(url_for("join_game", game_id=game_id))

# create tables on startup
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)