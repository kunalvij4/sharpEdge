import sqlite3
import os
from contextlib import contextmanager

class DatabaseConnection:
    def __init__(self, db_path="data/sharpedge.db"):
        """
        Initialize database connection.
        
        Parameters:
        - db_path (str): Path to SQLite database file
        """
        # Ensure the data directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Create tables if they don't exist."""
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        
        with open(schema_path, 'r') as f:
            schema_sql = f.read()
        
        with self.get_connection() as conn:
            conn.executescript(schema_sql)
            conn.commit()
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        try:
            yield conn
        finally:
            conn.close()
    
    def test_connection(self):
        """Test database connection and return basic info."""
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row[0] for row in cursor.fetchall()]
            
            # Get row counts for each table
            table_info = {}
            for table in tables:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                table_info[table] = cursor.fetchone()[0]
            
            return {
                "database_path": self.db_path,
                "tables": tables,
                "row_counts": table_info
            }