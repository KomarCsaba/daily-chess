from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify
from flask_migrate import Migrate
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_mail import Mail, Message
from models import db, User, Game
import chess
import uuid
import os
import random
import string
import threading
from datetime import datetime, timedelta
import logging
import requests
import re
import secrets
import hmac
import time
from collections import defaultdict, deque

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

app.config["BASE_URL"] = os.environ.get("BASE_URL", "http://localhost:8080")
app.config["RESEND_API_KEY"] = os.environ.get("RESEND_API_KEY")
app.config["TURN_TIME_HOURS"] = int(os.environ.get("TURN_TIME_HOURS", "24"))
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"

TIME_CONTROLS = {
    "daily": {
        "label": "Daily",
        "mode": "per_move",
        "seconds": app.config["TURN_TIME_HOURS"] * 60 * 60,
        "description": f"{app.config['TURN_TIME_HOURS']}h per move",
    },
    "rapid": {
        "label": "Rapid",
        "mode": "clock",
        "seconds": 10 * 60,
        "description": "10 min",
    },
    "blitz": {
        "label": "Blitz",
        "mode": "clock",
        "seconds": 5 * 60,
        "description": "5 min",
    },
    "bullet": {
        "label": "Bullet",
        "mode": "clock",
        "seconds": 60,
        "description": "1 min",
    },
}

database_url = os.environ.get("DATABASE_URL", "sqlite:///chess.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url

db.init_app(app)
migrate = Migrate(app, db)
mail = Mail(app)

# Allow all origins for dev; tighten in production via CORS_ALLOWED_ORIGINS env var.
# The threading async mode uses simple-websocket in production, avoiding the
# slow HTTP long-polling fallback.
socketio = SocketIO(
    app,
    cors_allowed_origins=os.environ.get("CORS_ALLOWED_ORIGINS", "*"),
    async_mode="threading"
)

print("MAIL_USERNAME:", app.config["MAIL_USERNAME"])
print("MAIL_PASSWORD exists:", bool(app.config["MAIL_PASSWORD"]))

login_manager = LoginManager(app)
login_manager.login_view = "index"

RATE_LIMIT_RULES = {
    "login": (10, 60),          # 10 attempts / minute
    "register": (6, 60),        # 6 attempts / minute
    "join_by_code": (20, 60),   # 20 attempts / minute
    "new_game": (20, 60),       # 20 requests / minute
    "make_move": (120, 60),     # 120 moves / minute
    "offer_draw": (20, 60),
    "accept_draw": (20, 60),
    "resign": (20, 60),
}
rate_limit_buckets = defaultdict(deque)
rate_limit_lock = threading.Lock()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def get_or_create_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": get_or_create_csrf_token}


@app.before_request
def validate_csrf_token():
    if request.method != "POST":
        return

    # Skip CSRF validation for login/register if no session exists yet
    if request.path in ["/login", "/register"] and not session.get("_csrf_token"):
        return

    expected = session.get("_csrf_token")
    provided = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    if expected and provided and hmac.compare_digest(expected, provided):
        return

    if request.path.startswith("/move/") or request.is_json:
        return jsonify({"error": "Invalid CSRF token"}), 400

    flash("Invalid session token. Please try again.")
    return redirect(url_for("index"))


@app.before_request
def enforce_rate_limit():
    if request.method != "POST":
        return

    endpoint = request.endpoint
    if endpoint not in RATE_LIMIT_RULES:
        return

    max_requests, window_seconds = RATE_LIMIT_RULES[endpoint]
    principal = f"user:{current_user.id}" if current_user.is_authenticated else f"ip:{request.remote_addr}"
    bucket_key = f"{endpoint}:{principal}"
    now = time.monotonic()
    window_start = now - window_seconds

    with rate_limit_lock:
        bucket = rate_limit_buckets[bucket_key]
        while bucket and bucket[0] < window_start:
            bucket.popleft()

        if len(bucket) >= max_requests:
            if request.path.startswith("/move/") or request.is_json:
                return jsonify({"error": "Too many requests. Please slow down."}), 429
            flash("Too many requests. Please wait a moment and try again.")
            return redirect(url_for("dashboard" if current_user.is_authenticated else "index"))

        bucket.append(now)


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
                "text": f"Hi {recipient.username},\n\nIt's your turn in your Daily Chess game.\n\nPlay here:\n{game_url}\n"
            }
        )
        print(f"Email sent to {recipient.email}")
    except Exception as e:
        print(f"Email error: {e}")


def get_checked_king_square(board_fen):
    try:
        board = chess.Board(board_fen)
        if not board.is_check():
            return None

        king_square = board.king(board.turn)
        if king_square is None:
            return None

        col = chess.square_file(king_square)
        row = 7 - chess.square_rank(king_square)
        return f"{col},{row}"
    except Exception as e:
        print("Check square error:", e)
        return None


def get_time_control(game):
    return TIME_CONTROLS.get(game.time_control or "daily", TIME_CONTROLS["daily"])


def generate_join_code(length=6):
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choice(alphabet) for _ in range(length))
        if not Game.query.filter_by(join_code=code).first():
            return code


def get_game_invite_url(game):
    return f"{app.config['BASE_URL']}/join/{game.join_code or game.id}"


def user_can_access_game(game, user_id):
    if not game or user_id is None:
        return False
    return user_id in (game.white_id, game.black_id)


def get_time_control_mode(game):
    return game.time_control_mode or get_time_control(game)["mode"]


def get_turn_time_seconds(game):
    return game.turn_time_seconds or get_time_control(game)["seconds"]


def get_turn_deadline(game):
    if game.status != "active" or not game.last_move_at:
        return None

    if get_time_control_mode(game) == "clock":
        remaining = game.white_time_remaining if game.turn == "white" else game.black_time_remaining
        remaining = remaining if remaining is not None else get_turn_time_seconds(game)
        return game.last_move_at + timedelta(seconds=remaining)

    return game.last_move_at + timedelta(seconds=get_turn_time_seconds(game))


def get_clock_seconds(game):
    if get_time_control_mode(game) != "clock":
        return {
            "white": get_turn_time_seconds(game),
            "black": get_turn_time_seconds(game),
        }

    white_seconds = game.white_time_remaining
    black_seconds = game.black_time_remaining

    if white_seconds is None:
        white_seconds = get_turn_time_seconds(game)
    if black_seconds is None:
        black_seconds = get_turn_time_seconds(game)

    if game.status == "active" and game.last_move_at:
        elapsed = max(0, int((datetime.utcnow() - game.last_move_at).total_seconds()))
        if game.turn == "white":
            white_seconds = max(0, white_seconds - elapsed)
        else:
            black_seconds = max(0, black_seconds - elapsed)

    return {"white": white_seconds, "black": black_seconds}


def update_active_clock(game):
    if get_time_control_mode(game) != "clock" or game.status != "active" or not game.last_move_at:
        return

    elapsed = max(0, int((datetime.utcnow() - game.last_move_at).total_seconds()))
    if game.turn == "white":
        remaining = game.white_time_remaining if game.white_time_remaining is not None else get_turn_time_seconds(game)
        game.white_time_remaining = max(0, remaining - elapsed)
    else:
        remaining = game.black_time_remaining if game.black_time_remaining is not None else get_turn_time_seconds(game)
        game.black_time_remaining = max(0, remaining - elapsed)


def apply_timeout_if_needed(game):
    deadline = get_turn_deadline(game)
    if not deadline or datetime.utcnow() < deadline:
        return False

    update_active_clock(game)
    timed_out_color = game.turn
    winner = "black" if timed_out_color == "white" else "white"
    game.status = "finished"
    game.result = f"{winner}_wins"
    db.session.commit()
    return True


def serialize_game_state(game, user_id=None):
    deadline = get_turn_deadline(game)
    seconds_remaining = None
    if deadline:
        seconds_remaining = max(0, int((deadline - datetime.utcnow()).total_seconds()))
    clocks = get_clock_seconds(game)
    time_control = get_time_control(game)

    payload = {
        "fen": game.board_fen,
        "status": game.status,
        "result": game.result,
        "draw_offered_by": game.draw_offered_by,
        "move_history": game.get_moves_list(),
        "white_id": game.white_id,
        "black_id": game.black_id,
        "turn": game.turn,
        "checked_king_square": get_checked_king_square(game.board_fen),
        "turn_deadline": deadline.isoformat() + "Z" if deadline else None,
        "seconds_remaining": seconds_remaining,
        "turn_time_seconds": get_turn_time_seconds(game),
        "turn_time_hours": round(get_turn_time_seconds(game) / 3600, 2),
        "time_control": game.time_control or "daily",
        "time_control_label": time_control["label"],
        "time_control_description": time_control["description"],
        "time_control_mode": get_time_control_mode(game),
        "white_time_remaining": clocks["white"],
        "black_time_remaining": clocks["black"],
        "join_code": game.join_code,
        "invite_url": get_game_invite_url(game),
        "last_move_uci": game.last_move_uci,
        "last_move_flags": game.last_move_flags.split(",") if game.last_move_flags else [],
    }

    if user_id is not None:
        payload["is_my_turn"] = game.is_players_turn(user_id)

    return payload


def broadcast_game_state(game, requesting_user_id=None):
    """Emit a game_update event to everyone in the game's SocketIO room."""
    socketio.emit("game_update", serialize_game_state(game), room=game.id)


# ---------------------------------------------------------------------------
# SocketIO events
# ---------------------------------------------------------------------------

@socketio.on("join_game")
def on_join_game(data):
    game_id = data.get("game_id")
    if not current_user.is_authenticated:
        emit("socket_error", {"error": "Authentication required"})
        return

    if not game_id:
        emit("socket_error", {"error": "Missing game id"})
        return

    game = Game.query.get(game_id)
    if not user_can_access_game(game, current_user.id):
        emit("socket_error", {"error": "Not allowed to join this game"})
        return

    join_room(game_id)
    emit("joined_game", {"game_id": game_id})


@socketio.on("leave_game")
def on_leave_game(data):
    game_id = data.get("game_id")
    if not current_user.is_authenticated or not game_id:
        return

    game = Game.query.get(game_id)
    if not user_can_access_game(game, current_user.id):
        return

    leave_room(game_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

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
    updated_games = []
    for game in games:
        if apply_timeout_if_needed(game):
            updated_games.append(game)
    for game in updated_games:
        broadcast_game_state(game)
    return render_template("dashboard.html", games=games, time_controls=TIME_CONTROLS)


@app.route("/new_game", methods=["GET", "POST"])
@login_required
def new_game():
    selected_control = request.form.get("time_control", "daily") if request.method == "POST" else request.args.get("time_control", "daily")
    time_control = TIME_CONTROLS.get(selected_control, TIME_CONTROLS["daily"])
    selected_control = selected_control if selected_control in TIME_CONTROLS else "daily"

    game = Game(
        id=str(uuid.uuid4()),
        white_id=current_user.id,
        board_fen=chess.Board().fen(),
        status="waiting",
        join_code=generate_join_code(),
        time_control=selected_control,
        time_control_mode=time_control["mode"],
        turn_time_seconds=time_control["seconds"],
        white_time_remaining=time_control["seconds"] if time_control["mode"] == "clock" else None,
        black_time_remaining=time_control["seconds"] if time_control["mode"] == "clock" else None,
        halfmove_clock=0,
        position_history="",
    )
    db.session.add(game)
    db.session.commit()
    return redirect(url_for("game", game_id=game.id))


@app.route("/join/<join_token>")
@login_required
def join_game(join_token):
    game = Game.query.filter_by(join_code=join_token.upper()).first()
    if not game:
        game = Game.query.get(join_token)

    if not game:
        flash("Game not found")
        return redirect(url_for("dashboard"))

    if game.status != "waiting":
        flash("Game already started")
        return redirect(url_for("dashboard"))

    if game.white_id == current_user.id:
        flash("You can't join your own game")
        return redirect(url_for("dashboard"))

    time_control = get_time_control(game)
    game.black_id = current_user.id
    game.status = "active"
    game.time_control = game.time_control or "daily"
    game.time_control_mode = game.time_control_mode or time_control["mode"]
    game.turn_time_seconds = game.turn_time_seconds or time_control["seconds"]
    if get_time_control_mode(game) == "clock":
        game.white_time_remaining = game.white_time_remaining or get_turn_time_seconds(game)
        game.black_time_remaining = game.black_time_remaining or get_turn_time_seconds(game)
    game.last_move_at = datetime.utcnow()
    db.session.commit()

    # Notify the waiting player that an opponent joined
    broadcast_game_state(game)

    return redirect(url_for("game", game_id=game.id))


@app.route("/game/<game_id>")
@login_required
def game(game_id):
    game = Game.query.get(game_id)
    if not game:
        flash("Game not found")
        return redirect(url_for("dashboard"))
    if apply_timeout_if_needed(game):
        broadcast_game_state(game)
    initial_state = serialize_game_state(game, current_user.id)
    if game.status == "waiting" and game.white_id == current_user.id:
        return render_template("waiting_game.html", game=game, initial_state=initial_state)
    return render_template("game.html", game=game, initial_state=initial_state)


@app.route("/moves/<game_id>")
@login_required
def get_moves(game_id):
    game = Game.query.get(game_id)
    if not game:
        return {"moves": []}
    return {"moves": game.get_moves_list()}


@app.route("/move/<game_id>", methods=["POST"])
@login_required
def make_move(game_id):
    game = Game.query.get(game_id)

    if not game or game.status != "active":
        return {"error": "Game not found or not active"}, 400

    if apply_timeout_if_needed(game):
        broadcast_game_state(game)
        return {"error": "Game ended on time", "game_status": game.status}, 400

    if not game.is_players_turn(current_user.id):
        return {"error": "Not your turn"}, 400

    move_uci = (request.json or {}).get("move", "")
    if not isinstance(move_uci, str) or not re.fullmatch(r"^[a-h][1-8][a-h][1-8][qrbn]?$", move_uci):
        return {"error": "Invalid move format"}, 400

    board = chess.Board(game.board_fen)
    try:
        move = chess.Move.from_uci(move_uci)
        if move not in board.legal_moves:
            return {"error": "Illegal move"}, 400

        update_active_clock(game)

        if (
            get_time_control_mode(game) == "clock" and
            ((game.turn == "white" and game.white_time_remaining == 0) or
             (game.turn == "black" and game.black_time_remaining == 0))
        ):
            db.session.commit()
            apply_timeout_if_needed(game)
            broadcast_game_state(game)
            return {"error": "Game ended on time", "game_status": game.status}, 400

        is_capture = board.is_capture(move)
        is_castling = board.is_castling(move)
        is_promotion = move.promotion is not None
        is_pawn_move = board.piece_at(move.from_square).piece_type == chess.PAWN
        
        # Update halfmove clock for fifty-move rule
        if is_capture or is_pawn_move:
            game.halfmove_clock = 0
        else:
            game.halfmove_clock += 1
        
        # Add current position to history before move
        game.add_position_to_history(board.fen())
        
        san = board.san(move)
        board.push(move)

        moves = game.get_moves_list()
        moves.append(san)
        game.move_history = ",".join(moves)
        game.board_fen = board.fen()
        game.last_move_uci = move.uci()

        next_turn = "black" if game.turn == "white" else "white"
        game.turn = next_turn
        game.last_move_at = datetime.utcnow()

        if game.draw_offered_by != current_user.id:
            game.draw_offered_by = None

        move_flags = []
        if is_capture:
            move_flags.append("capture")
        if is_castling:
            move_flags.append("castle")
        if is_promotion:
            move_flags.append("promotion")
        if board.is_check():
            move_flags.append("check")

        if board.is_checkmate():
            move_flags.append("checkmate")
            game.status = "finished"
            winner = "white" if next_turn == "black" else "black"
            game.result = f"{winner}_wins"
        elif board.is_stalemate() or board.is_insufficient_material():
            move_flags.append("draw")
            game.status = "finished"
            game.result = "draw"
        elif game.is_threefold_repetition():
            move_flags.append("draw")
            move_flags.append("threefold_repetition")
            game.status = "finished"
            game.result = "draw"
        elif game.is_fifty_move_rule():
            move_flags.append("draw")
            move_flags.append("fifty_move_rule")
            game.status = "finished"
            game.result = "draw"

        game.last_move_flags = ",".join(move_flags)

        db.session.commit()

        # Push update to both players via WebSocket
        broadcast_game_state(game)

        # Email notification (only when game is still active)
        opponent = game.get_opponent(current_user.id)
        if opponent and game.status == "active" and opponent.email:
            threading.Thread(
                target=send_turn_notification,
                args=(game, opponent)
            ).start()

        response_state = serialize_game_state(game, current_user.id)
        return {
            "success": True,
            "fen": response_state["fen"],
            "game_status": response_state["status"],
            "checked_king_square": response_state["checked_king_square"],
            "turn": response_state["turn"],
            "turn_deadline": response_state["turn_deadline"],
            "seconds_remaining": response_state["seconds_remaining"],
            "time_control_mode": response_state["time_control_mode"],
            "white_time_remaining": response_state["white_time_remaining"],
            "black_time_remaining": response_state["black_time_remaining"],
            "last_move_uci": response_state["last_move_uci"],
            "last_move_flags": response_state["last_move_flags"],
        }

    except Exception as e:
        print(f"Move error: {e}")
        return {"error": "Invalid move"}, 400


@app.route("/rematch/<game_id>")
@login_required
def rematch(game_id):
    old_game = Game.query.get(game_id)
    if not old_game:
        flash("Game not found")
        return redirect(url_for("dashboard"))

    if current_user.id not in (old_game.white_id, old_game.black_id):
        flash("Not your game")
        return redirect(url_for("dashboard"))

    rematch_mode = get_time_control_mode(old_game)
    rematch_seconds = old_game.turn_time_seconds or get_turn_time_seconds(old_game)
    new_game = Game(
        id=str(uuid.uuid4()),
        white_id=old_game.black_id,
        black_id=old_game.white_id,
        board_fen=chess.Board().fen(),
        status="waiting",
        turn="white",
        join_code=generate_join_code(),
        time_control=old_game.time_control or "daily",
        time_control_mode=rematch_mode,
        turn_time_seconds=rematch_seconds,
        white_time_remaining=rematch_seconds if rematch_mode == "clock" else None,
        black_time_remaining=rematch_seconds if rematch_mode == "clock" else None,
        halfmove_clock=0,
        position_history="",
    )
    db.session.add(new_game)
    db.session.commit()

    if old_game.white_id == current_user.id:
        flash("Rematch created! Share the link with your opponent.")
        return redirect(url_for("game", game_id=new_game.id))
    else:
        new_game.black_id = current_user.id
        new_game.status = "active"
        db.session.commit()
        flash("Rematch started!")
        return redirect(url_for("game", game_id=new_game.id))


@app.route("/legal_moves/<game_id>/<int:col>/<int:row>")
@login_required
def legal_moves(game_id, col, row):
    game = Game.query.get(game_id)
    if not game:
        return {"moves": []}

    if apply_timeout_if_needed(game):
        broadcast_game_state(game)
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


@app.route("/game_state/<game_id>")
@login_required
def game_state(game_id):
    game = Game.query.get(game_id)
    if not game:
        return {"error": "Game not found"}, 404

    if apply_timeout_if_needed(game):
        broadcast_game_state(game)

    return serialize_game_state(game, current_user.id)


@app.route("/resign/<game_id>", methods=["POST"])
@login_required
def resign(game_id):
    game = Game.query.get(game_id)
    if not game or game.status != "active":
        flash("Invalid game")
        return redirect(url_for("dashboard"))

    if apply_timeout_if_needed(game):
        broadcast_game_state(game)
        flash("Game ended on time")
        return redirect(url_for("game", game_id=game_id))

    if not game.is_players_turn(current_user.id):
        flash("Not your turn")
        return redirect(url_for("game", game_id=game_id))

    game.result = "black_wins" if game.white_id == current_user.id else "white_wins"
    game.status = "finished"
    db.session.commit()

    broadcast_game_state(game)

    flash("You resigned")
    return redirect(url_for("game", game_id=game_id))


@app.route("/offer_draw/<game_id>", methods=["POST"])
@login_required
def offer_draw(game_id):
    game = Game.query.get(game_id)
    if game and apply_timeout_if_needed(game):
        broadcast_game_state(game)
        return redirect(url_for("game", game_id=game_id))

    if not game or game.status != "active" or not game.is_players_turn(current_user.id):
        return redirect(url_for("game", game_id=game_id))

    game.draw_offered_by = current_user.id
    db.session.commit()

    broadcast_game_state(game)

    flash("Draw offered")
    return redirect(url_for("game", game_id=game_id))


@app.route("/accept_draw/<game_id>", methods=["POST"])
@login_required
def accept_draw(game_id):
    game = Game.query.get(game_id)
    if not game or game.status != "active":
        return redirect(url_for("dashboard"))

    if apply_timeout_if_needed(game):
        broadcast_game_state(game)
        flash("Game ended on time")
        return redirect(url_for("game", game_id=game_id))

    if game.draw_offered_by and game.draw_offered_by != current_user.id:
        game.status = "finished"
        game.result = "draw"
        db.session.commit()

        broadcast_game_state(game)

        flash("Draw accepted")
    return redirect(url_for("game", game_id=game_id))


@app.route("/join_by_code", methods=["POST"])
@login_required
def join_by_code():
    code = request.form.get("code", "").strip()
    join_token = code.split("/join/")[-1] if "/join/" in code else code
    return redirect(url_for("join_game", join_token=join_token))


@app.route("/check_square/<game_id>")
@login_required
def check_square(game_id):
    game = Game.query.get(game_id)
    if not game:
        return {"square": None}

    return {"square": get_checked_king_square(game.board_fen)}


if __name__ == "__main__":
    # Use socketio.run instead of app.run
    socketio.run(app, debug=True)
