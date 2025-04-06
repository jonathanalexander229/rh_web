from tinydb import TinyDB, Query
import datetime
import json
from pathlib import Path

# Ensure data directory exists
data_dir = Path('data')
data_dir.mkdir(exist_ok=True)

# Initialize the database
db = TinyDB(data_dir / 'options_data.json')
Snapshot = Query()

def save_options_data(data):
    """Save options data to database and mark as latest"""
    # Add timestamp
    timestamp = datetime.datetime.now().isoformat()
    
    # Mark all previous entries as not latest
    db.update({'is_latest': False})
    
    # Insert new data
    db.insert({
        'timestamp': timestamp,
        'data': data,
        'is_latest': True
    })
    
    # Limit to last 30 snapshots (to manage file size)
    snapshots = db.all()
    snapshots.sort(key=lambda x: x['timestamp'], reverse=True)
    
    if len(snapshots) > 30:
        for old in snapshots[30:]:
            db.remove(doc_ids=[old.doc_id])
    
    return {'timestamp': timestamp, 'data': data}

def get_latest_options_data():
    """Retrieve the most recent options data"""
    result = db.search(Snapshot.is_latest == True)
    if result:
        return result[0]
    return None

def get_earliest_open_position_date():
    """Get the earliest date of an open position or None if no data exists"""
    latest_data = get_latest_options_data()
    if not latest_data or not latest_data['data']['open_positions']:
        return None
        
    # Find earliest open date among open positions
    try:
        earliest_date = None
        for position in latest_data['data']['open_positions']:
            open_date = position.get('open_date')
            if open_date and (earliest_date is None or open_date < earliest_date):
                earliest_date = open_date
                
        if earliest_date:
            # Convert to datetime object
            return datetime.datetime.strptime(earliest_date, '%Y-%m-%d %H:%M')
    except Exception as e:
        print(f"Error finding earliest open position date: {e}")
    
    return None

def get_options_data_by_date(start_date=None, end_date=None):
    """Retrieve options data within a date range"""
    snapshots = db.all()
    
    if start_date or end_date:
        filtered = []
        for snapshot in snapshots:
            timestamp = snapshot['timestamp']
            
            if start_date and timestamp < start_date:
                continue
                
            if end_date and timestamp > end_date:
                continue
                
            filtered.append(snapshot)
        
        return sorted(filtered, key=lambda x: x['timestamp'], reverse=True)
    
    # If no date filters, return all sorted by timestamp
    return sorted(snapshots, key=lambda x: x['timestamp'], reverse=True)

def is_database_empty():
    """Check if the database is empty"""
    return len(db) == 0