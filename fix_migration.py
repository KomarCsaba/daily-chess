from app import app, db
from models import User, Game
import sqlite3

with app.app_context():
    # Create tables if they don't exist
    db.create_all()
    print('Database tables created')
    
    # Now add the new columns using raw SQL
    db_path = 'chess.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if columns exist
    cursor.execute('PRAGMA table_info(game)')
    columns = [row[1] for row in cursor.fetchall()]
    print('Current columns:', columns)
    
    if 'halfmove_clock' not in columns:
        cursor.execute('ALTER TABLE game ADD COLUMN halfmove_clock INTEGER DEFAULT 0')
        print('Added halfmove_clock column')
    
    if 'position_history' not in columns:
        cursor.execute("ALTER TABLE game ADD COLUMN position_history TEXT DEFAULT ''")
        print('Added position_history column')
    
    conn.commit()
    conn.close()
    print('Migration completed successfully')
