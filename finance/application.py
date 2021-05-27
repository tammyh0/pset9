import os
import datetime

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""

    # Get current cash amount
    cash_available = db.execute("SELECT cash FROM users WHERE id=?", session.get("user_id"))[0]["cash"]

    # Track grand total
    grand_total = cash_available

    # Get bought stocks
    bought_rows = db.execute("SELECT id, symbol, name, SUM(shares) AS shares FROM history WHERE id=? AND transaction_type=? GROUP BY symbol",
                             session.get("user_id"), "buy")

    # Initialize portfolio
    db.execute("DELETE FROM portfolio")

    # Update portfolio with bought shares
    for bought_row in bought_rows:
        db.execute("INSERT INTO portfolio (id, symbol, name, shares, current_price, total) VALUES(?, ?, ?, ?, ?, ?)",
                   bought_row["id"], bought_row["symbol"], bought_row["name"], bought_row["shares"], lookup(bought_row["symbol"])["price"], lookup(bought_row["symbol"])["price"] * bought_row["shares"])

    # Query portfolio after adding bought shares
    portfolio_after_bought_rows = db.execute("SELECT * FROM portfolio WHERE id=? ORDER BY shares", session.get("user_id"))

    # Get sold stocks
    sold_rows = db.execute("SELECT symbol, SUM(shares) AS shares FROM history WHERE id=? AND transaction_type=? GROUP BY symbol",
                           session.get("user_id"), "sell")

    # Update portfolio with sold stocks
    for portfolio_after_bought_row in portfolio_after_bought_rows:
        for sold_row in sold_rows:
            if sold_row["symbol"] == portfolio_after_bought_row["symbol"]:
                db.execute("UPDATE portfolio SET shares=?, total=? WHERE symbol=? AND id=?",
                           sold_row["shares"] + portfolio_after_bought_row["shares"], (sold_row["shares"] + portfolio_after_bought_row["shares"]) * lookup(
                               sold_row["symbol"])["price"],
                           sold_row["symbol"], session.get("user_id"))

    # Query portfolio after calculating differences
    after_difference_rows = db.execute("SELECT * FROM portfolio ORDER BY shares")

    # Get grand total
    for after_difference_row in after_difference_rows:
        if after_difference_row["shares"] == 0:
            db.execute("DELETE FROM portfolio WHERE shares=?", 0)
        grand_total += after_difference_row["total"]

    # Query updated portfolio
    current_rows = db.execute("SELECT * FROM portfolio ORDER BY shares DESC")

    return render_template("index.html", cash_available=cash_available, grand_total=grand_total, current_rows=current_rows)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure symbol was submitted
        if not request.form.get("symbol"):
            return apology("must provide symbol")

        # Ensure shares was submitted
        elif not request.form.get("shares"):
            return apology("must provide shares")

        # Check symbol
        lookup_response = lookup(request.form.get("symbol"))

        # Symbol not found
        if not lookup_response:
            return apology("invalid symbol")

        # Ensure shares don't contain non-numbers
        if not request.form.get("shares").isdigit():
            return apology("must provide positive integer")

        # Get shares
        shares = float(request.form.get("shares"))

        # Shares not valid
        if shares < 1:
            return apology("must provide positive integer")

        # Determine if able to buy
        current_price = lookup(request.form.get("symbol"))['price'] * shares
        cash_available = db.execute("SELECT cash FROM users WHERE id=?", session.get("user_id"))[0]["cash"]

        # Cannot afford shares
        if current_price > cash_available:
            return apology("cannot afford shares at current price")

        # Log purchase
        db.execute("INSERT INTO history (id, transaction_type, timestamp, symbol, name, price, shares) VALUES(?, ?, ?, ?, ?, ?, ?)",
                   session.get("user_id"), "buy", datetime.datetime.now(), lookup_response["symbol"], lookup_response["name"], lookup_response["price"], shares)

        # Update user's cash
        db.execute("UPDATE users SET cash=? WHERE id=?", cash_available - current_price, session.get("user_id"))

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""

    # Query database
    rows = db.execute("SELECT symbol, shares, price, timestamp FROM history")

    return render_template("history.html", rows=rows)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username")

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password")

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = ?", request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password")

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure symbol was submitted
        if not request.form.get("symbol"):
            return apology("must provide symbol")

        # Check symbol
        lookup_response = lookup(request.form.get("symbol"))
        if lookup_response:
            name = lookup_response['name']
            price = usd(lookup_response['price'])
            symbol = lookup_response['symbol']
            return render_template("quoted.html", name=name, price=price, symbol=symbol)

        # Symbol not found
        else:
            return apology("invalid symbol")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username")

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password")

        # Query database for username
        rows = db.execute("SELECT username FROM users")

        # Ensure username doesn't already exist
        for row in rows:
            if request.form.get("username") in row["username"]:
                return apology("username taken, choose a different one")

        # Check for matching passwords
        if request.form.get("password") != request.form.get("confirmation"):
            return apology("must provide passwords that match")

        # Username and password are valid, store new user information
        password_hash = generate_password_hash(request.form.get("password"))
        db.execute("INSERT INTO users (username, hash) VALUES(?, ?)", request.form.get("username"), password_hash)

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        # Display registration form
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure stock was selected
        if not request.form.get("symbol"):
            return apology("must select symbol")

        # Ensure shares was submitted
        elif not request.form.get("shares"):
            return apology("must provide shares")

        # Query database for owned shares
        rows = db.execute("SELECT symbol, SUM(shares) AS shares FROM history WHERE id=? AND transaction_type=? GROUP BY symbol",
                          session.get("user_id"), "buy")

        # Get list of owned stocks
        owned_stocks = []
        for row in rows:
            owned_stocks.append(row["symbol"])

        # Ensure user owns shares of selected stock
        if request.form.get("symbol") not in owned_stocks:
            return apology("you do not own any shares of this stock, must select valid symbol")

        # Ensure shares don't contain non-numbers
        if not request.form.get("shares").isdigit():
            return apology("must provide positive integer")

        # Get shares
        shares = float(request.form.get("shares"))

        # Shares not valid
        if shares < 1:
            return apology("must provide positive integer")

        # Ensure user owns that many shares of stock
        if shares > db.execute("SELECT SUM(shares) AS owned_shares FROM history WHERE id=? AND transaction_type=? AND symbol=? GROUP BY symbol",
                               session.get("user_id"), "buy", request.form.get("symbol"))[0]["owned_shares"]:
            return apology("you do not own that many shares of this stock, must select valid shares")

        # Log sold shares
        db.execute("INSERT INTO history (id, transaction_type, timestamp, symbol, name, price, shares) VALUES(?, ?, ?, ?, ?, ?, ?)",
                   session.get("user_id"), "sell", datetime.datetime.now(), request.form.get("symbol"), lookup(request.form.get(
                       "symbol"))["name"],
                   lookup(request.form.get("symbol"))["price"], shares * -1)

        # Update user's cash
        cash_available = db.execute("SELECT cash FROM users WHERE id=?", session.get("user_id"))[0]["cash"]
        cash_earned = lookup(request.form.get("symbol"))["price"] * shares
        db.execute("UPDATE users SET cash=? WHERE id=?", cash_available + cash_earned, session.get("user_id"))

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:

        # Query database for owned shares
        rows = db.execute("SELECT symbol FROM history WHERE id=? AND transaction_type=? GROUP BY symbol",
                          session.get("user_id"), "buy")

        # Get owned shares
        symbols = []
        for row in rows:
            symbols.append(row["symbol"])

        return render_template("sell.html", symbols=symbols)


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
