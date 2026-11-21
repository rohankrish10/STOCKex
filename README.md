# STOCKex — The Ultimate Trading Challenge

STOCKex is a browser-based stock-market simulation for classroom competitions, workshops and team events. Participants register with a name and team, receive virtual cash, and trade 12 fictional companies while an administrator controls the market and releases news events.

The application uses Python's standard library and SQLite for local persistence. No third-party Python packages or frontend build tools are required.

## Features

- **Live trading floor:** 12 fictional stocks with continuously changing prices, sparkline charts, buy/sell controls and portfolio tracking.
- **Market-moving news:** administrators can release 16 prepared news events that affect selected stock prices.
- **Admin dashboard:** start/pause the game, release news, reset prices, reset the session and monitor the leaderboard.
- **Persistent state:** player accounts, balances, positions, prices, price history and news are checkpointed to a local SQLite database.
- **Company directory:** participants can read each fictional company's business profile and investment drivers.
- **Responsive interface:** use the app from desktop and mobile browsers on the same network.

## Requirements

- Python 3.9 or newer (recommended).
- No `pip install` step is required.

## Quick start

### 1. Download the project

Clone the repository:

```bash
git clone https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
cd YOUR-REPOSITORY
```

Or download the repository ZIP from GitHub and extract it.

### 2. Set an admin password

Set `STOCKEX_ADMIN_PASSWORD` before starting the server. Choose a strong password and do not commit it to GitHub.

**Windows PowerShell:**

```powershell
$env:STOCKEX_ADMIN_PASSWORD = "choose-a-strong-password"
```

**Windows Command Prompt:**

```bat
set STOCKEX_ADMIN_PASSWORD=choose-a-strong-password
```

**macOS / Linux:**

```bash
export STOCKEX_ADMIN_PASSWORD='choose-a-strong-password'
```

If you do not set this variable, STOCKex generates a random password for that run and prints it in the terminal. It changes the next time the server starts.

### 3. Run the application

```bash
python stockex.py
```

Open:

- Player registration: <http://localhost:8080>
- Admin panel: <http://localhost:8080/admin>
- Company directory: <http://localhost:8080/directory>

The server attempts to open the player page in your default browser. If it does not, open the URL manually.

Press `Ctrl+C` in the terminal to stop the server. The application saves its current state when it shuts down normally.

## Let participants join

### Same Wi-Fi / local network

The server listens on all network interfaces by default. Find the computer's local IPv4 address and share:

```text
http://YOUR-LAN-IP:8080
```

All participants must be connected to a network that can reach the host computer. Allow Python through the computer's firewall for private networks if prompted.

### Remote participants

Do not expose this development server directly to the public internet. For a remote event, use a properly secured deployment/reverse proxy or a private network/VPN. A temporary tunnel can expose the service, but the built-in server is intended for trusted event use, not production-grade public hosting.

## How to play

1. Participants open the player URL and register with a name and team.
2. Each participant starts with **₹100,000** in virtual cash.
3. The administrator starts the game. Prices move while the game is active.
4. Participants buy and sell shares subject to available cash and holdings.
5. The administrator releases news events. Each event changes the prices of the specified companies.
6. The leaderboard ranks participants by total portfolio value: available cash plus the market value of their holdings.

This is a simulation. No real securities are traded and no real money is involved.

## Admin panel

Open `http://localhost:8080/admin` and sign in using the password configured in `STOCKEX_ADMIN_PASSWORD` (or the one-time generated password shown in the server terminal).

The panel supports:

- **Start / Pause:** enable or pause trading and price updates.
- **Release news:** publish a prepared market event and apply its configured price impact.
- **Reset prices:** return stock prices to their base values.
- **Full reset:** remove all players and return the market to its initial state.
- **Leaderboard:** monitor portfolio values, gains/losses and trade counts.

## Configuration

Set these environment variables before starting the server:

| Variable | Purpose | Default |
|---|---|---|
| `STOCKEX_HOST` | Network interface to bind | `0.0.0.0` |
| `STOCKEX_PORT` | HTTP port | `8080` |
| `STOCKEX_ADMIN_PASSWORD` | Admin password | Random password generated at startup |

The main simulation settings, including price tick interval, mean reversion and per-stock volatility, are defined near the top of `stockex.py`.

## Project structure

```text
.
├── stockex.py        # Server, simulation logic and browser interface
├── README.md         # Project documentation
├── requirements.txt  # No third-party dependencies
├── .gitignore        # Excludes local data, secrets and Python cache files
└── data/             # Created automatically; local SQLite database/backups
```

## Data and privacy

- The SQLite database is created automatically under `data/`.
- Database backups are stored under `data/backups/`.
- The `data/` directory is excluded by `.gitignore`. Do not upload a live event database: it can contain participant names, teams and portfolio information.
- The uploaded `stockex_players.json` sample/test data is intentionally not part of the repository.
- Back up `data/` separately if you need to retain event results. Do not commit it to a public repository.

## Security and limitations

STOCKex is designed for trusted classroom/workshop sessions. It is not a hardened public-facing trading platform. Use a strong admin password, keep the database private, and do not expose the built-in HTTP server directly to the public internet. For public deployment, add production-grade HTTPS termination, request protections, rate limiting, robust session management and operational monitoring.

## License

No license is included. Unless you add a license, GitHub users may view the code but do not automatically receive permission to reuse, modify or redistribute it.
