# Robinhood Options Dashboard

A web-based dashboard for viewing and analyzing your Robinhood options trades.

## Features

- View open, closed, and expired options positions
  - Open positions: active positions that haven't reached expiration
  - Closed positions: positions that were manually closed before expiration
  - Expired positions: positions that expired worthless without being closed
- P&L tracking for closed positions
- Filter positions by symbol, strategy, date range, and more
- Sort table columns for better analysis
- Local data storage with TinyDB
  - Cache data to reduce Robinhood API calls
  - Browse historical snapshots
  - Quick loading of data even when offline
- Smart data fetching options
  - Auto: Intelligently fetches only what's needed
  - Update: Only gets data since earliest open position
  - Initial: Gets 60 days of history
  - All: Fetches complete history
- Responsive design for mobile and desktop
- Secure login to your Robinhood account

## File Structure

```
/robinhood-options-dashboard/
├── templates/
│   ├── index.html
│   └── login.html
├── static/
│   ├── css/
│   │   └── styles.css
│   └── js/
│       ├── main.js
│       ├── rendering.js
│       ├── filters.js
│       └── sorting.js
├── data/
│   └── options_data.json  # TinyDB database file (created automatically)
├── db.py                  # Database module
└── rh_web.py              # Main Flask application
```

## Component Overview

- **main.js**: Core functionality and initialization
- **rendering.js**: Data rendering functions for all views
- **filters.js**: Advanced filtering including date range filtering
- **sorting.js**: Table sorting functionality
- **styles.css**: Responsive styling
- **db.py**: Database interface module using TinyDB
- **rh_web.py**: Flask app with API endpoints and Robinhood integration

## Setup and Running

1. Install dependencies:
   ```
   pip install flask robin-stocks pandas tinydb
   ```

2. Run the application:
   ```
   python rh_web.py
   ```

3. Access the dashboard at http://localhost:5000

## Authentication

The app will prompt for Robinhood credentials on first use. For security:
- Credentials are used only for authentication with Robinhood
- No credentials are stored in the application

## Smart Data Fetching

The dashboard uses an intelligent approach to minimize API calls:

1. **Auto Mode** (default):
   - If database is empty: Fetches 60 days of history
   - If database exists: Only fetches data since the earliest open position
   - This ensures you have all the data you need for active trades without unnecessary API calls

2. **Update Mode**:
   - Calculates the earliest open position's date
   - Only fetches data from that date (minus 1 day for safety)
   - Ideal for regular updates

3. **Initial Mode**:
   - Gets 60 days of history
   - Good for new installations or when you want recent data only

4. **All History**:
   - Fetches complete history from Robinhood
   - Use sparingly as it makes the most API calls
   - Useful for account migration or complete historical analysis

All fetched data is stored in the local TinyDB database (options_data.json) for quick access in future sessions.