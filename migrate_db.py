import sqlite3
import os

# Use the same database path as the Flask app
db_path = os.path.join(os.getcwd(), 'chess.db')
print(f'Using database: {db_path}')
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check what tables exist
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in cursor.fetchall()]
print('Tables:', tables)

if 'game' in tables:
    # Check if columns exist
    cursor.execute('PRAGMA table_info(game)')
    columns = [row[1] for row in cursor.fetchall()]
    print('Current game columns:', columns)

    if 'halfmove_clock' not in columns:
        cursor.execute('ALTER TABLE game ADD COLUMN halfmove_clock INTEGER DEFAULT 0')
        print('Added halfmove_clock column')

    if 'position_history' not in columns:
        cursor.execute('ALTER TABLE game ADD COLUMN position_history TEXT DEFAULT ""')
        print('Added position_history column')
else:
    print('Game table does not exist yet')

conn.commit()
conn.close()
print('Migration completed')
