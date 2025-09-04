# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Running the Application
```bash
python rh_web.py
```
The application runs on localhost:5000.

### Dependencies
```bash
pip install flask robin-stocks pandas
```

No package.json exists - this is a Python Flask application.

## Architecture

This repository contains two Flask-based web applications:
- Portfolio Dashboard (`rh_web.py`): dashboard for viewing/analyzing Robinhood options orders and positions.
- Risk Manager Web (`risk_manager_web.py`): multi-account long-options risk management with simulation/live order flows.

Below focuses on the Portfolio Dashboard. See `ARCHITECTURE.md` and `README.md` for Risk Manager Web.

### Core Components

- **rh_web.py**: Main Flask application with API endpoints and data processing logic
- **templates/**: HTML templates for the web interface
  - `index.html`: Main dashboard page
  - `login.html`: Authentication page
- **static/**: Frontend assets organized by type
  - `js/main.js`: Core functionality, tab switching, and API calls
  - `js/rendering.js`: Data rendering functions for all views
  - `js/filters.js`: Advanced filtering including date range filtering  
  - `js/sorting.js`: Table sorting functionality
  - `css/styles.css`: Responsive styling

### Data Flow

1. **Authentication**: Users log in with Robinhood credentials via `/login`
2. **Data Fetching**: `/api/options` endpoint calls `fetch_and_process_option_orders()`
3. **Data Processing**: Raw option orders are processed and categorized into:
   - Open positions (active, not expired)
   - Closed positions (manually closed before expiration)
   - Expired positions (expired worthless)
   - All orders (raw data)
4. **Frontend Rendering**: JavaScript modules handle data display and user interactions

### Key Data Processing Logic

The `fetch_and_process_option_orders()` function:
- Fetches option orders from Robinhood API using robin-stocks
- Processes and cleans the data using pandas
- Groups opening and closing positions by option ID
- Calculates P&L for closed positions
- Categorizes positions by status (open/closed/expired)
- Returns JSON-serializable data structure

### Frontend Architecture (Portfolio Dashboard)

- **Modular JavaScript**: Separate files for different concerns (main, rendering, filters, sorting)
- **Tab-based Interface**: Switch between different views of option data
- **Real-time Filtering**: Advanced filtering capabilities including date ranges
- **Responsive Design**: Mobile and desktop compatible

### Security Considerations

- Robinhood credentials are only used for authentication, not stored
- Flask debug mode is enabled (should be disabled in production)
- No explicit session management or CSRF protection implemented

## TODO: Normalized Database Approach (Portfolio Dashboard)

**Current Issue**: The application fetches and processes all data on every request, leading to inefficient API usage and duplicate data processing.

**Proposed Solution**: Implement a normalized SQLite database with incremental data collection:

### Database Schema
```sql
-- Store individual option orders (from Robinhood API)
CREATE TABLE option_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    robinhood_id TEXT UNIQUE,  -- Unique identifier from RH API
    symbol TEXT,
    created_at TEXT,
    position_effect TEXT,  -- 'open' or 'close'
    expiration_date TEXT,
    strike_price TEXT,
    price REAL,
    quantity INTEGER,
    premium REAL,
    strategy TEXT,
    direction TEXT,
    option_type TEXT,
    option_ids TEXT,  -- JSON array of option IDs
    raw_data TEXT,    -- Full JSON for reference
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Store computed positions (paired open/close orders)
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    option_key TEXT UNIQUE,  -- Unique identifier for position
    symbol TEXT,
    open_date TEXT,
    close_date TEXT,
    expiration_date TEXT,
    strike_price TEXT,
    quantity INTEGER,
    open_price REAL,
    close_price REAL,
    open_premium REAL,
    close_premium REAL,
    net_credit REAL,
    strategy TEXT,
    direction TEXT,
    option_type TEXT,
    status TEXT,  -- 'open', 'closed', 'expired'
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Implementation Benefits
- **Incremental Updates**: Only fetch new orders since last update
- **Efficient Storage**: No duplicate data across requests
- **Server-side Processing**: Move complex JSON processing from client to server
- **Better Performance**: Pre-computed positions served instantly
- **Historical Tracking**: Track order evolution over time

### Smart Fetch Strategy
- **Initial**: Fetch 60 days of history for new installs
- **Update**: Only fetch orders since last stored order
- **Deduplication**: Use robinhood_id as unique constraint
- **Position Recomputation**: Rebuild positions table when new orders arrive

### API Changes
- Store individual orders with deduplication
- Pre-compute positions server-side
- Return clean, structured data to client
- Eliminate client-side JSON processing complexity

**Dependencies**: Add `sqlite3` (built-in Python) for database operations

**Note**: Once implemented, remove this TODO section and update the Architecture section above to reflect the new normalized database approach.
