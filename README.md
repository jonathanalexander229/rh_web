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
└── rh_web.py
```

## Component Overview

- **main.js**: Core functionality and initialization
- **rendering.js**: Data rendering functions for all views
- **filters.js**: Advanced filtering including date range filtering
- **sorting.js**: Table sorting functionality
- **styles.css**: Responsive styling

## Setup and Running

1. Install dependencies:
   ```
   pip install flask robin-stocks pandas
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