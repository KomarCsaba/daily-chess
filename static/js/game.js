const {
    gameId,
    myColor,
    currentFen: initialFen,
    isMyTurn: initialTurn,
    gameStatus: initialStatus,
    drawOfferedBy,
    myId,
    gameResult,
    turn: initialTurnColor,
    turnDeadline: initialTurnDeadline,
    turnTimeHours,
    turnTimeSeconds,
    timeControlLabel,
    timeControlDescription,
    timeControlMode: initialTimeControlMode,
    whiteTimeRemaining: initialWhiteTimeRemaining,
    blackTimeRemaining: initialBlackTimeRemaining
} = window.GAME_CONFIG;

const PIECES = {
    K: "♔", Q: "♕", R: "♖", B: "♗", N: "♘", P: "♙",
    k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟"
};

let currentFen = initialFen;
let isMyTurn = initialTurn;
let gameStatus = initialStatus;

let selectedSquare = null;
let legalMoves = [];

let currentDrawOfferedBy = drawOfferedBy;
let currentResult = gameResult;
let currentTurn = initialTurnColor;
let currentTurnDeadline = initialTurnDeadline;
let currentTimeControlMode = initialTimeControlMode;
let currentWhiteTimeRemaining = initialWhiteTimeRemaining;
let currentBlackTimeRemaining = initialBlackTimeRemaining;
let timeoutSyncRequested = false;

let checkedKingSquare = null;
let lastMoveSquares = null;

const INITIAL_PIECE_COUNTS = {
    white: { p: 8, n: 2, b: 2, r: 2, q: 1 },
    black: { p: 8, n: 2, b: 2, r: 2, q: 1 }
};

const audioContext = window.AudioContext || window.webkitAudioContext;
let soundCtx = null;

/* =========================
   WebSocket Setup
========================= */

const socket = io();

socket.on("connect", () => {
    socket.emit("join_game", { game_id: gameId });
});

socket.on("game_update", async (data) => {
    const previousFenBeforeUpdate = currentFen;
    currentFen = data.fen;
    gameStatus = data.status;
    currentResult = data.result;
    currentDrawOfferedBy = data.draw_offered_by ?? null;
    currentTurn = data.turn;
    currentTurnDeadline = data.turn_deadline;
    currentTimeControlMode = data.time_control_mode;
    currentWhiteTimeRemaining = data.white_time_remaining;
    currentBlackTimeRemaining = data.black_time_remaining;
    timeoutSyncRequested = false;

    // Determine whose turn it is from the server payload
    if (data.white_id && data.black_id) {
        const myColorFromId = data.white_id == myId ? "white" : "black";
        isMyTurn = data.turn === myColorFromId && gameStatus === "active";
    } else {
        // Fallback: re-fetch is_my_turn from REST if IDs aren't in payload
        try {
            const res = await fetch(`/game_state/${gameId}`);
            const stateData = await res.json();
            isMyTurn = stateData.is_my_turn;
        } catch (e) {
            console.error("Failed to fetch turn state", e);
        }
    }

    clearSelection();
    setCheckedKingSquare(data.checked_king_square);
    setLastMoveSquares(previousFenBeforeUpdate, currentFen, currentTurn);
    renderMoveList(data.move_history || []);
    updateBoard();
    updateCapturedPieces();
    updateStatus();
    updateTimer();
    updateActions();
    maybePlayMoveSound(previousFenBeforeUpdate, currentFen, data.checked_king_square);
});

/* =========================
   Utilities
========================= */

function fenToBoard(fen) {
    const pieces = {};
    const rows = fen.split(" ")[0].split("/");

    for (let r = 0; r < 8; r++) {
        let c = 0;
        for (const char of rows[r]) {
            if (isNaN(char)) {
                pieces[`${c},${r}`] = char;
                c++;
            } else {
                c += parseInt(char);
            }
        }
    }
    return pieces;
}

function colRowToUci(col, row) {
    return String.fromCharCode(97 + col) + (8 - row);
}

function isPlayersPiece(piece) {
    if (!piece) return false;
    return (
        (myColor === "white" && piece === piece.toUpperCase()) ||
        (myColor === "black" && piece === piece.toLowerCase())
    );
}

function clearSelection() {
    selectedSquare = null;
    legalMoves = [];
}

function getOrCreateAudioContext() {
    if (!audioContext) return null;
    if (!soundCtx) soundCtx = new audioContext();
    if (soundCtx.state === "suspended") {
        soundCtx.resume().catch(() => {});
    }
    return soundCtx;
}

function playTone(frequency, durationSeconds, volume = 0.03) {
    const ctx = getOrCreateAudioContext();
    if (!ctx) return;

    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.type = "triangle";
    oscillator.frequency.value = frequency;
    gain.gain.value = volume;
    oscillator.connect(gain);
    gain.connect(ctx.destination);

    const now = ctx.currentTime;
    gain.gain.setValueAtTime(volume, now);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + durationSeconds);
    oscillator.start(now);
    oscillator.stop(now + durationSeconds);
}

function playCaptureSound() {
    playTone(280, 0.16, 0.04);
    setTimeout(() => playTone(220, 0.12, 0.03), 55);
}

function playCheckSound() {
    playTone(880, 0.16, 0.045);
    setTimeout(() => playTone(1175, 0.19, 0.035), 65);
}

function countPiecesByColor(pieces) {
    const counts = {
        white: { p: 0, n: 0, b: 0, r: 0, q: 0 },
        black: { p: 0, n: 0, b: 0, r: 0, q: 0 }
    };

    Object.values(pieces).forEach(piece => {
        const lower = piece.toLowerCase();
        if (!(lower in counts.white) || lower === "k") return;
        if (piece === piece.toUpperCase()) counts.white[lower]++;
        else counts.black[lower]++;
    });

    return counts;
}

function getCapturedPiecesByColor() {
    const boardCounts = countPiecesByColor(fenToBoard(currentFen));
    const captured = { white: [], black: [] };
    const pieceOrder = ["q", "r", "b", "n", "p"];

    pieceOrder.forEach(type => {
        const missingWhite = Math.max(0, INITIAL_PIECE_COUNTS.white[type] - boardCounts.white[type]);
        const missingBlack = Math.max(0, INITIAL_PIECE_COUNTS.black[type] - boardCounts.black[type]);
        for (let i = 0; i < missingWhite; i++) captured.white.push(type.toUpperCase());
        for (let i = 0; i < missingBlack; i++) captured.black.push(type);
    });

    return captured;
}

function updateCapturedPieces() {
    const whiteCapturedEl = document.getElementById("white-captured");
    const blackCapturedEl = document.getElementById("black-captured");
    if (!whiteCapturedEl || !blackCapturedEl) return;

    const captured = getCapturedPiecesByColor();
    whiteCapturedEl.textContent = captured.white.map(piece => PIECES[piece]).join(" ");
    blackCapturedEl.textContent = captured.black.map(piece => PIECES[piece]).join(" ");
}

function setLastMoveSquares(previousFenValue, nextFenValue, nextTurn) {
    if (!previousFenValue || !nextFenValue || previousFenValue === nextFenValue) {
        lastMoveSquares = null;
        return;
    }

    const previousBoard = fenToBoard(previousFenValue);
    const nextBoard = fenToBoard(nextFenValue);
    const moverColor = nextTurn === "white" ? "black" : "white";
    const changedSquares = [];

    for (let col = 0; col < 8; col++) {
        for (let row = 0; row < 8; row++) {
            const key = `${col},${row}`;
            if ((previousBoard[key] || null) !== (nextBoard[key] || null)) {
                changedSquares.push({ col, row, key });
            }
        }
    }

    if (!changedSquares.length) {
        lastMoveSquares = null;
        return;
    }

    const fromCandidates = changedSquares.filter(square => {
        const prevPiece = previousBoard[square.key];
        const nextPiece = nextBoard[square.key];
        if (!prevPiece) return false;
        const isMoverPiece = moverColor === "white"
            ? prevPiece === prevPiece.toUpperCase()
            : prevPiece === prevPiece.toLowerCase();
        return isMoverPiece && !nextPiece;
    });

    const toCandidates = changedSquares.filter(square => {
        const nextPiece = nextBoard[square.key];
        const prevPiece = previousBoard[square.key];
        if (!nextPiece) return false;
        const isMoverPiece = moverColor === "white"
            ? nextPiece === nextPiece.toUpperCase()
            : nextPiece === nextPiece.toLowerCase();
        return isMoverPiece && prevPiece !== nextPiece;
    });

    if (!fromCandidates.length || !toCandidates.length) {
        lastMoveSquares = null;
        return;
    }

    let from = fromCandidates[0];
    let to = toCandidates[0];

    const kingChar = moverColor === "white" ? "K" : "k";
    const kingFrom = fromCandidates.find(square => previousBoard[square.key] === kingChar);
    const kingTo = toCandidates.find(square => nextBoard[square.key] === kingChar);
    if (kingFrom && kingTo) {
        from = kingFrom;
        to = kingTo;
    }

    lastMoveSquares = {
        from: { col: from.col, row: from.row },
        to: { col: to.col, row: to.row }
    };
}

function didCapture(previousFenValue, nextFenValue) {
    if (!previousFenValue || !nextFenValue || previousFenValue === nextFenValue) return false;
    return Object.keys(fenToBoard(nextFenValue)).length < Object.keys(fenToBoard(previousFenValue)).length;
}

function maybePlayMoveSound(previousFenValue, nextFenValue, checkedSquare) {
    if (!previousFenValue || !nextFenValue || previousFenValue === nextFenValue) return;
    if (checkedSquare) {
        playCheckSound();
        return;
    }
    if (didCapture(previousFenValue, nextFenValue)) {
        playCaptureSound();
    }
}

/* =========================
   Board Rendering
========================= */

function buildBoard() {
    const boardEl = document.getElementById("board");
    boardEl.innerHTML = "";

    const rows = myColor === "black" ? [7,6,5,4,3,2,1,0] : [0,1,2,3,4,5,6,7];
    const cols = myColor === "black" ? [7,6,5,4,3,2,1,0] : [0,1,2,3,4,5,6,7];

    for (const row of rows) {
        for (const col of cols) {
            const square = document.createElement("div");
            square.className = `square ${(row + col) % 2 === 0 ? "light" : "dark"}`;
            square.dataset.col = col;
            square.dataset.row = row;
            square.addEventListener("click", onSquareClick);
            boardEl.appendChild(square);
        }
    }
}

function updateBoard() {
    const pieces = fenToBoard(currentFen);
    const squares = document.querySelectorAll(".square");

    squares.forEach(square => {
        const col = parseInt(square.dataset.col);
        const row = parseInt(square.dataset.row);
        const key = `${col},${row}`;
        const piece = pieces[key];

        square.className = `square ${(row + col) % 2 === 0 ? "light" : "dark"}`;
        square.textContent = "";

        if (piece) {
            square.textContent = PIECES[piece];
            square.classList.add(piece === piece.toUpperCase() ? "piece-white" : "piece-black");
        }

        if (selectedSquare && selectedSquare.col === col && selectedSquare.row === row) {
            square.classList.add("selected");
        }

        const isLegalMove = legalMoves.some(move => move.col === col && move.row === row);
        if (isLegalMove) {
            square.classList.add("possible-move");
            if (piece) square.classList.add("has-piece");
        }

        if (checkedKingSquare !== null && checkedKingSquare.col === col && checkedKingSquare.row === row) {
            square.classList.add("check");
        }

        const isLastMoveFrom = lastMoveSquares
            && lastMoveSquares.from.col === col
            && lastMoveSquares.from.row === row;
        const isLastMoveTo = lastMoveSquares
            && lastMoveSquares.to.col === col
            && lastMoveSquares.to.row === row;
        if (isLastMoveFrom || isLastMoveTo) {
            square.classList.add("last-move");
        }
    });
}

/* =========================
   Legal Moves
========================= */

async function getLegalMoves(col, row) {
    try {
        const res = await fetch(`/legal_moves/${gameId}/${col}/${row}`);
        const data = await res.json();
        legalMoves = data.moves.map(move => {
            const [c, r] = move.split(",").map(Number);
            return { col: c, row: r };
        });
        updateBoard();
    } catch (err) {
        console.error("Failed to fetch legal moves", err);
    }
}

/* =========================
   Input Handling
========================= */

async function onSquareClick(event) {
    if (!isMyTurn || gameStatus !== "active") return;

    const col = parseInt(event.currentTarget.dataset.col);
    const row = parseInt(event.currentTarget.dataset.row);

    const pieces = fenToBoard(currentFen);
    const piece = pieces[`${col},${row}`];

    if (selectedSquare === null) {
        if (isPlayersPiece(piece)) {
            selectedSquare = { col, row };
            await getLegalMoves(col, row);
        }
        return;
    }

    if (selectedSquare.col === col && selectedSquare.row === row) {
        clearSelection();
        updateBoard();
        return;
    }

    if (isPlayersPiece(piece)) {
        selectedSquare = { col, row };
        await getLegalMoves(col, row);
        return;
    }

    const from = colRowToUci(selectedSquare.col, selectedSquare.row);
    const to = colRowToUci(col, row);
    let moveStr = from + to;

    const fromPiece = pieces[`${selectedSquare.col},${selectedSquare.row}`];
    if (
        fromPiece?.toLowerCase() === "p" &&
        ((myColor === "white" && row === 0) || (myColor === "black" && row === 7))
    ) {
        moveStr += "q";
    }

    await makeMove(moveStr);
}

/* =========================
   Move Submission
========================= */

async function makeMove(move) {
    try {
        const previousFenBeforeMove = currentFen;
        const res = await fetch(`/move/${gameId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ move })
        });

        const data = await res.json();

        if (!data.success) {
            alert(data.error || "Illegal move");
            clearSelection();
            updateBoard();
            return;
        }

        // Optimistically update own side; the server will broadcast to opponent
        currentFen = data.fen;
        gameStatus = data.game_status;
        isMyTurn = false;
        currentTurn = data.turn;
        currentTurnDeadline = data.turn_deadline;
        currentWhiteTimeRemaining = data.white_time_remaining ?? currentWhiteTimeRemaining;
        currentBlackTimeRemaining = data.black_time_remaining ?? currentBlackTimeRemaining;
        timeoutSyncRequested = false;

        clearSelection();
        setCheckedKingSquare(data.checked_king_square);
        setLastMoveSquares(previousFenBeforeMove, currentFen, currentTurn);
        updateBoard();
        updateCapturedPieces();
        updateStatus();
        updateTimer();
        updateActions();
        maybePlayMoveSound(previousFenBeforeMove, currentFen, data.checked_king_square);
        // Move list will arrive via game_update broadcast

    } catch (err) {
        console.error("Move failed", err);
    }
}

/* =========================
   Status
========================= */

function updateStatus() {
    const statusEl = document.getElementById("status");
    statusEl.className = "status";

    if (gameStatus === "finished") {
        statusEl.textContent = "Game Over";
        return;
    }

    if (isMyTurn && gameStatus === "active") {
        statusEl.textContent = "Your move";
        statusEl.classList.add("your-turn");
    } else {
        statusEl.textContent = "Waiting for opponent...";
        statusEl.classList.add("waiting");
    }
}

function formatDuration(totalSeconds) {
    const seconds = Math.max(0, Math.floor(totalSeconds));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainingSeconds = seconds % 60;

    if (hours >= 24) {
        const days = Math.floor(hours / 24);
        const dayHours = hours % 24;
        return `${days}d ${dayHours}h`;
    }

    if (hours >= 1) {
        return `${hours}h ${String(minutes).padStart(2, "0")}m`;
    }

    return `${minutes}m ${String(remainingSeconds).padStart(2, "0")}s`;
}

function updateTimer() {
    const labelEl = document.getElementById("timer-label");
    const valueEl = document.getElementById("timer-value");
    if (!labelEl || !valueEl) return;

    valueEl.className = "timer-value";

    if (gameStatus === "waiting") {
        labelEl.textContent = `${timeControlLabel} starts when opponent joins`;
        valueEl.textContent = timeControlDescription;
        updatePlayerClocks(null);
        return;
    }

    if (gameStatus === "finished") {
        labelEl.textContent = `${timeControlLabel} game finished`;
        valueEl.textContent = currentResult === "draw" ? "Draw" : "Clock stopped";
        updatePlayerClocks(null);
        return;
    }

    if (!currentTurnDeadline) {
        labelEl.textContent = "Clock unavailable";
        valueEl.textContent = "";
        return;
    }

    const deadline = Date.parse(currentTurnDeadline);
    const secondsLeft = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));

    labelEl.textContent = currentTurn === myColor ? `${timeControlLabel}: Your clock` : `${timeControlLabel}: Opponent clock`;
    valueEl.textContent = formatDuration(secondsLeft);

    if (secondsLeft <= 3600) {
        valueEl.classList.add("timer-danger");
    } else if (secondsLeft <= 6 * 3600) {
        valueEl.classList.add("timer-warning");
    }

    if (secondsLeft === 0 && !timeoutSyncRequested) {
        timeoutSyncRequested = true;
        syncGameState();
    }

    updatePlayerClocks(secondsLeft);
}

function getDisplayedClockSeconds(color, activeSecondsLeft) {
    if (currentTimeControlMode !== "clock") {
        return color === currentTurn ? activeSecondsLeft : turnTimeSeconds;
    }

    if (color === currentTurn) {
        return activeSecondsLeft;
    }

    return color === "white" ? currentWhiteTimeRemaining : currentBlackTimeRemaining;
}

function renderPlayerClock(element, color, activeSecondsLeft) {
    if (!element) return;

    element.className = "player-clock";
    const seconds = getDisplayedClockSeconds(color, activeSecondsLeft);
    element.textContent = formatDuration(seconds ?? turnTimeSeconds);

    if (gameStatus === "active" && color === currentTurn) {
        element.classList.add("clock-active");
    }

    if (seconds <= 60) {
        element.classList.add("clock-danger");
    } else if (seconds <= 5 * 60) {
        element.classList.add("clock-warning");
    }
}

function updatePlayerClocks(activeSecondsLeft) {
    const myClock = document.getElementById("my-clock");
    const opponentClock = document.getElementById("opponent-clock");
    const opponentColor = myColor === "white" ? "black" : "white";

    renderPlayerClock(myClock, myColor, activeSecondsLeft);
    renderPlayerClock(opponentClock, opponentColor, activeSecondsLeft);
}

/* =========================
   Move List
========================= */

function renderMoveList(moves) {
    const movesEl = document.getElementById("moves");
    movesEl.innerHTML = "";

    if (!moves.length) {
        movesEl.innerHTML = `<div class="empty-moves">No moves yet</div>`;
        return;
    }

    for (let i = 0; i < moves.length; i += 2) {
        const row = document.createElement("div");
        row.className = "move-row";

        const moveNumber = document.createElement("span");
        moveNumber.className = "move-number";
        moveNumber.textContent = `${Math.floor(i / 2) + 1}.`;

        const whiteMove = document.createElement("span");
        whiteMove.className = "move white-move";
        whiteMove.textContent = moves[i] || "";

        const blackMove = document.createElement("span");
        blackMove.className = "move black-move";
        blackMove.textContent = moves[i + 1] || "";

        if (i === moves.length - 1) {
            whiteMove.classList.add("latest-move");
        } else if (i + 1 === moves.length - 1) {
            blackMove.classList.add("latest-move");
        }

        row.appendChild(moveNumber);
        row.appendChild(whiteMove);
        row.appendChild(blackMove);
        movesEl.appendChild(row);
    }

    movesEl.scrollTop = movesEl.scrollHeight;
}

/* =========================
   Actions
========================= */

function createButton(text, className = "btn") {
    const button = document.createElement("button");
    button.type = "submit";
    button.className = className;
    button.textContent = text;
    return button;
}

function updateActions() {
    const actionsEl = document.getElementById("actions");
    actionsEl.innerHTML = "";

    if (gameStatus === "finished") {
        const rematchBtn = document.createElement("a");
        rematchBtn.href = `/rematch/${gameId}`;
        rematchBtn.className = "btn";
        rematchBtn.textContent = "Rematch";
        rematchBtn.style.textAlign = "center";
        actionsEl.appendChild(rematchBtn);

        const resultDiv = document.createElement("div");
        resultDiv.style.cssText = `text-align: center; font-size: 14px; color: #aaa; margin-top: 6px;`;

        if (currentResult === "draw") {
            resultDiv.textContent = "Game ended in a draw";
        } else if (
            (currentResult === "white_wins" && myColor === "white") ||
            (currentResult === "black_wins" && myColor === "black")
        ) {
            resultDiv.textContent = "🏆 You won!";
            resultDiv.style.color = "#5a9e6f";
        } else {
            resultDiv.textContent = "You lost";
        }

        actionsEl.appendChild(resultDiv);
        return;
    }

    if (gameStatus !== "active") return;

    if (currentDrawOfferedBy && currentDrawOfferedBy !== myId) {
        const form = document.createElement("form");
        form.action = `/accept_draw/${gameId}`;
        form.method = "POST";
        const button = createButton("Accept Draw");
        button.style.cssText = `width: 100%; background-color: #5a7a9e;`;
        form.appendChild(button);
        actionsEl.appendChild(form);
    }

    if (!isMyTurn) return;

    if (!currentDrawOfferedBy) {
        const form = document.createElement("form");
        form.action = `/offer_draw/${gameId}`;
        form.method = "POST";
        const button = createButton("Offer Draw", "btn btn-secondary");
        button.style.width = "100%";
        form.appendChild(button);
        actionsEl.appendChild(form);
    } else if (currentDrawOfferedBy === myId) {
        const pending = document.createElement("div");
        pending.style.cssText = `text-align: center; font-size: 13px; color: #aaa; padding: 8px;`;
        pending.textContent = "Draw offer pending...";
        actionsEl.appendChild(pending);
    }

    const resignForm = document.createElement("form");
    resignForm.action = `/resign/${gameId}`;
    resignForm.method = "POST";
    resignForm.onsubmit = () => confirm("Are you sure you want to resign?");

    const resignBtn = createButton("Resign", "btn btn-secondary");
    resignBtn.style.cssText = `width: 100%; background-color: #6b2b2b;`;
    resignForm.appendChild(resignBtn);
    actionsEl.appendChild(resignForm);
}

/* =========================
   Coordinates
========================= */

function renderCoordinates() {
    const files = myColor === "white"
        ? ["a","b","c","d","e","f","g","h"]
        : ["h","g","f","e","d","c","b","a"];
    const ranks = myColor === "white"
        ? ["8","7","6","5","4","3","2","1"]
        : ["1","2","3","4","5","6","7","8"];

    const topFiles = document.getElementById("top-files");
    const bottomFiles = document.getElementById("bottom-files");
    const leftRanks = document.getElementById("left-ranks");
    const rightRanks = document.getElementById("right-ranks");

    [topFiles, bottomFiles, leftRanks, rightRanks].forEach(el => el.innerHTML = "");

    files.forEach(file => {
        const top = document.createElement("div"); top.textContent = file;
        const bottom = document.createElement("div"); bottom.textContent = file;
        topFiles.appendChild(top);
        bottomFiles.appendChild(bottom);
    });

    ranks.forEach(rank => {
        const left = document.createElement("div"); left.textContent = rank;
        const right = document.createElement("div"); right.textContent = rank;
        leftRanks.appendChild(left);
        rightRanks.appendChild(right);
    });
}

/* =========================
   Check Highlight
========================= */

function setCheckedKingSquare(square) {
    if (!square) {
        checkedKingSquare = null;
        return;
    }

    const parts = square.split(",");
    if (parts.length !== 2) {
        checkedKingSquare = null;
        return;
    }

    checkedKingSquare = { col: Number(parts[0]), row: Number(parts[1]) };
}

/* =========================
   Initial Sync
========================= */

async function syncGameState() {
    try {
        const previousFenBeforeSync = currentFen;
        const res = await fetch(`/game_state/${gameId}`);
        const data = await res.json();

        currentFen = data.fen;
        gameStatus = data.status;
        isMyTurn = data.is_my_turn;
        currentResult = data.result;
        currentDrawOfferedBy = data.draw_offered_by;
        currentTurn = data.turn;
        currentTurnDeadline = data.turn_deadline;
        currentTimeControlMode = data.time_control_mode;
        currentWhiteTimeRemaining = data.white_time_remaining;
        currentBlackTimeRemaining = data.black_time_remaining;
        timeoutSyncRequested = false;

        setCheckedKingSquare(data.checked_king_square);
        setLastMoveSquares(previousFenBeforeSync, currentFen, currentTurn);
        updateBoard();
        updateCapturedPieces();
        updateStatus();
        updateTimer();
        updateActions();
        renderMoveList(data.move_history || []);
        maybePlayMoveSound(previousFenBeforeSync, currentFen, data.checked_king_square);
    } catch (err) {
        console.error("Failed initial sync", err);
    }
}

/* =========================
   Initialize
========================= */

renderCoordinates();
buildBoard();
syncGameState();
setInterval(updateTimer, 1000);
