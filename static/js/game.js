const {
    gameId,
    myColor,
    currentFen: initialFen,
    isMyTurn: initialTurn,
    gameStatus: initialStatus,
    drawOfferedBy,
    myId,
    gameResult
} = window.GAME_CONFIG;

const PIECES = {
    K: "♔",
    Q: "♕",
    R: "♖",
    B: "♗",
    N: "♘",
    P: "♙",
    k: "♚",
    q: "♛",
    r: "♜",
    b: "♝",
    n: "♞",
    p: "♟"
};

let currentFen = initialFen;
let isMyTurn = initialTurn;
let gameStatus = initialStatus;

let selectedSquare = null;
let legalMoves = [];
let pollInterval = null;

let currentDrawOfferedBy = drawOfferedBy ?? null;
let currentResult = gameResult;

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

/* =========================
   Board Rendering
========================= */

function buildBoard() {
    const boardEl = document.getElementById("board");
    boardEl.innerHTML = "";

    const rows =
        myColor === "black"
            ? [7, 6, 5, 4, 3, 2, 1, 0]
            : [0, 1, 2, 3, 4, 5, 6, 7];

    const cols =
        myColor === "black"
            ? [7, 6, 5, 4, 3, 2, 1, 0]
            : [0, 1, 2, 3, 4, 5, 6, 7];

    for (const row of rows) {
        for (const col of cols) {
            const square = document.createElement("div");

            square.className = `square ${
                (row + col) % 2 === 0 ? "light" : "dark"
            }`;

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

        square.className = `square ${
            (row + col) % 2 === 0 ? "light" : "dark"
        }`;

        square.textContent = "";

        if (piece) {
            square.textContent = PIECES[piece];

            square.classList.add(
                piece === piece.toUpperCase()
                    ? "piece-white"
                    : "piece-black"
            );
        }

        if (
            selectedSquare &&
            selectedSquare.col === col &&
            selectedSquare.row === row
        ) {
            square.classList.add("selected");
        }

        const isLegalMove = legalMoves.some(
            move => move.col === col && move.row === row
        );

        if (isLegalMove) {
            square.classList.add("possible-move");

            if (piece) {
                square.classList.add("has-piece");
            }
        }
    });
}

/* =========================
   Legal Moves
========================= */

async function getLegalMoves(col, row) {
    try {
        const res = await fetch(
            `/legal_moves/${gameId}/${col}/${row}`
        );

        const data = await res.json();

        legalMoves = data.moves.map(move => {
            const [c, r] = move.split(",").map(Number);

            return {
                col: c,
                row: r
            };
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
    if (!isMyTurn || gameStatus !== "active") {
        return;
    }

    const col = parseInt(event.currentTarget.dataset.col);
    const row = parseInt(event.currentTarget.dataset.row);

    const pieces = fenToBoard(currentFen);
    const piece = pieces[`${col},${row}`];

    // Selecting a piece
    if (selectedSquare === null) {
        if (isPlayersPiece(piece)) {
            selectedSquare = { col, row };

            await getLegalMoves(col, row);
        }

        return;
    }

    // Clicking same square deselects
    if (
        selectedSquare.col === col &&
        selectedSquare.row === row
    ) {
        clearSelection();
        updateBoard();
        return;
    }

    // Selecting another own piece
    if (isPlayersPiece(piece)) {
        selectedSquare = { col, row };

        await getLegalMoves(col, row);
        return;
    }

    // Attempt move
    const from = colRowToUci(
        selectedSquare.col,
        selectedSquare.row
    );

    const to = colRowToUci(col, row);

    let moveStr = from + to;

    // Auto queen promotion
    const fromPiece =
        pieces[
            `${selectedSquare.col},${selectedSquare.row}`
        ];

    if (
        fromPiece?.toLowerCase() === "p" &&
        (
            (myColor === "white" && row === 0) ||
            (myColor === "black" && row === 7)
        )
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
        const res = await fetch(`/move/${gameId}`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ move })
        });

        const data = await res.json();

        if (!data.success) {
            alert(data.error || "Illegal move");

            clearSelection();
            updateBoard();

            return;
        }

        currentFen = data.fen;
        gameStatus = data.game_status;

        isMyTurn = false;

        clearSelection();

        updateBoard();
        updateMoveList();
        updateStatus();
        updateActions();

        if (gameStatus === "active") {
            setTimeout(() => {
                startPolling();
            }, 300);
        }

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

    if (isMyTurn) {
        statusEl.textContent = "Your move";
        statusEl.classList.add("your-turn");
    } else {
        statusEl.textContent = "Waiting for opponent...";
        statusEl.classList.add("waiting");
    }
}

/* =========================
   Improved Move List
========================= */

async function updateMoveList() {
    try {
        const res = await fetch(`/moves/${gameId}`);
        const data = await res.json();

        const movesEl = document.getElementById("moves");

        movesEl.innerHTML = "";

        const moves = data.moves;

        if (!moves.length) {
            movesEl.innerHTML = `
                <div class="empty-moves">
                    No moves yet
                </div>
            `;
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

            row.appendChild(moveNumber);
            row.appendChild(whiteMove);
            row.appendChild(blackMove);

            movesEl.appendChild(row);
        }

        movesEl.scrollTop = movesEl.scrollHeight;

    } catch (err) {
        console.error("Failed to update move list", err);
    }
}

/* =========================
   Polling
========================= */

function startPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
    }

    pollInterval = setInterval(async () => {
        if (isMyTurn || gameStatus !== "active") {
            return;
        }

        try {
            const res = await fetch(`/game_state/${gameId}`);
            const data = await res.json();

            if (data.fen && data.fen !== currentFen) {
                currentFen = data.fen;
                isMyTurn = data.is_my_turn;
                gameStatus = data.status;

                currentResult = data.result;
                currentDrawOfferedBy =
                    data.draw_offered_by ?? null;

                updateBoard();
                updateMoveList();
                updateStatus();
                updateActions();
            } else if (
                data.draw_offered_by !== undefined &&
                data.draw_offered_by !== currentDrawOfferedBy
            ) {
                currentDrawOfferedBy =
                    data.draw_offered_by;

                updateActions();
            }

        } catch (err) {
            console.error("Polling failed", err);
        }
    }, 2500);
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

    // Finished game
    if (gameStatus === "finished") {
        const rematchBtn = document.createElement("a");

        rematchBtn.href = `/rematch/${gameId}`;
        rematchBtn.className = "btn";
        rematchBtn.textContent = "Rematch";

        rematchBtn.style.textAlign = "center";

        actionsEl.appendChild(rematchBtn);

        const resultDiv = document.createElement("div");

        resultDiv.style.cssText = `
            text-align: center;
            font-size: 14px;
            color: #aaa;
            margin-top: 6px;
        `;

        if (currentResult === "draw") {
            resultDiv.textContent =
                "Game ended in a draw";
        } else if (
            (currentResult === "white_wins" &&
                myColor === "white") ||
            (currentResult === "black_wins" &&
                myColor === "black")
        ) {
            resultDiv.textContent = "🏆 You won!";
            resultDiv.style.color = "#5a9e6f";
        } else {
            resultDiv.textContent = "You lost";
        }

        actionsEl.appendChild(resultDiv);

        return;
    }

    if (gameStatus !== "active") {
        return;
    }

    // Accept draw
    if (
        currentDrawOfferedBy &&
        currentDrawOfferedBy !== myId
    ) {
        const form = document.createElement("form");

        form.action = `/accept_draw/${gameId}`;
        form.method = "POST";

        const button = createButton("Accept Draw");

        button.style.cssText = `
            width: 100%;
            background-color: #5a7a9e;
        `;

        form.appendChild(button);

        actionsEl.appendChild(form);
    }

    if (!isMyTurn) {
        return;
    }

    // Offer draw
    if (!currentDrawOfferedBy) {
        const form = document.createElement("form");

        form.action = `/offer_draw/${gameId}`;
        form.method = "POST";

        const button = createButton(
            "Offer Draw",
            "btn btn-secondary"
        );

        button.style.width = "100%";

        form.appendChild(button);

        actionsEl.appendChild(form);

    } else if (currentDrawOfferedBy === myId) {
        const pending = document.createElement("div");

        pending.style.cssText = `
            text-align: center;
            font-size: 13px;
            color: #aaa;
            padding: 8px;
        `;

        pending.textContent = "Draw offer pending...";

        actionsEl.appendChild(pending);
    }

    // Resign
    const resignForm = document.createElement("form");

    resignForm.action = `/resign/${gameId}`;
    resignForm.method = "POST";

    resignForm.onsubmit = () =>
        confirm("Are you sure you want to resign?");

    const resignBtn = createButton(
        "Resign",
        "btn btn-secondary"
    );

    resignBtn.style.cssText = `
        width: 100%;
        background-color: #6b2b2b;
    `;

    resignForm.appendChild(resignBtn);

    actionsEl.appendChild(resignForm);
}

function renderCoordinates() {
    const files =
        myColor === "white"
            ? ["a","b","c","d","e","f","g","h"]
            : ["h","g","f","e","d","c","b","a"];

    const ranks =
        myColor === "white"
            ? ["8","7","6","5","4","3","2","1"]
            : ["1","2","3","4","5","6","7","8"];

    const topFiles = document.getElementById("top-files");
    const bottomFiles = document.getElementById("bottom-files");

    const leftRanks = document.getElementById("left-ranks");
    const rightRanks = document.getElementById("right-ranks");

    topFiles.innerHTML = "";
    bottomFiles.innerHTML = "";

    leftRanks.innerHTML = "";
    rightRanks.innerHTML = "";

    files.forEach(file => {
        const top = document.createElement("div");
        top.textContent = file;

        const bottom = document.createElement("div");
        bottom.textContent = file;

        topFiles.appendChild(top);
        bottomFiles.appendChild(bottom);
    });

    ranks.forEach(rank => {
        const left = document.createElement("div");
        left.textContent = rank;

        const right = document.createElement("div");
        right.textContent = rank;

        leftRanks.appendChild(left);
        rightRanks.appendChild(right);
    });
}

/* =========================
   Initialize
========================= */

renderCoordinates();
buildBoard();
updateBoard();
updateStatus();
updateMoveList();
updateActions();

if (!isMyTurn && gameStatus === "active") {
    startPolling();
}