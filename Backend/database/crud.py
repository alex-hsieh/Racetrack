from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from database.database import engine

load_dotenv()

def get_db_connection():
    """Get a raw DBAPI connection from the app's single SQLAlchemy engine pool."""
    conn = engine.raw_connection()
    # conn is a pool proxy (_ConnectionFairy); cursor_factory has to be set on
    # the real psycopg2 connection it wraps, not the proxy, or plain conn.cursor()
    # calls below silently ignore it and return tuples instead of dict rows.
    conn.dbapi_connection.cursor_factory = RealDictCursor
    return conn

def return_connection(conn):
    """Return a connection to the pool (alias kept for call-site clarity)."""
    conn.close()

def db_connection():
    """Context manager for database connections"""
    conn = get_db_connection()
    try:
        yield conn
    finally:
        return_connection(conn)

def execute_query(query, params=None, fetchone=False, fetchall=True):
    """Helper function to execute queries using connection pool"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(query, params)
        
        if fetchone:
            result = cursor.fetchone()
        elif fetchall:
            result = cursor.fetchall()
        else:
            result = None
        
        return result
    finally:
        cursor.close()
        return_connection(conn)

def get_all_races(year=None):
   
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if year:
        cursor.execute("SELECT * FROM races WHERE year = %s ORDER BY date", (year,))
    else:
        cursor.execute("SELECT * FROM races ORDER BY date DESC")
    
    races = cursor.fetchall()
    cursor.close()
    #return_connection(conn)
    return_connection(conn)
    return races

def get_upcoming_race():
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM races 
        WHERE date >= CURRENT_DATE 
        ORDER BY date ASC 
        LIMIT 1
    """)
    
    race = cursor.fetchone()
    cursor.close()
    return_connection(conn)
    return race

def get_race_by_id(race_id):
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM races WHERE race_id = %s", (race_id,))
    race = cursor.fetchone()
    
    cursor.close()
    #return_connection(conn)
    return_connection(conn)
    return race

def get_race_by_year_round(year, round_num):
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM races WHERE year = %s AND round = %s", (year, round_num))
    race = cursor.fetchone()
    
    cursor.close()
    return_connection(conn)
    return race



def get_all_drivers():
   
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM drivers ORDER BY driver_full_name")
    drivers = cursor.fetchall()
    
    cursor.close()
    return_connection(conn)
    return drivers

def get_driver_by_id(driver_id):
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM drivers WHERE driver_id = %s", (driver_id,))
    driver = cursor.fetchone()
    
    cursor.close()
    return_connection(conn)
    return driver

def get_active_drivers(year):
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DISTINCT d.*, t.team_name
        FROM drivers d
        JOIN race_results rr ON d.driver_id = rr.driver_id
        JOIN races r ON rr.race_id = r.race_id
        LEFT JOIN teams t ON d.team_id = t.team_id
        WHERE r.year = %s
        ORDER BY d.driver_full_name
    """, (year,))
    
    drivers = cursor.fetchall()
    cursor.close()
    return_connection(conn)
    return drivers


def get_current_grid(year):
    """Current F1 grid for a season, with each driver's team derived from
    their most recent race_result within that season (drivers.team_id is
    never populated by the sync pipeline). Raw SQL/RealDictCursor rather
    than the SQLAlchemy ORM — a `db.query(Driver, RaceResult.team_id...)`
    version of this same query was observed in production to return
    corrupted values (a SQLAlchemy auto-label string like 'races_race_id'
    in place of the real column value), an ORM result-mapping issue never
    seen in this raw-SQL pattern anywhere else in this codebase."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        WITH latest_results AS (
            SELECT
                rr.driver_id,
                rr.team_id AS current_team_id,
                ROW_NUMBER() OVER (
                    PARTITION BY rr.driver_id
                    ORDER BY r.date DESC, rr.race_id DESC
                ) AS rn
            FROM race_results rr
            JOIN races r ON r.race_id = rr.race_id
            WHERE r.year = %s
        )
        SELECT
            d.driver_id, d.driver_number, d.driver_code, d.driver_forename,
            d.driver_surname, d.driver_full_name, d.nationality,
            lr.current_team_id AS team_id
        FROM drivers d
        JOIN latest_results lr ON lr.driver_id = d.driver_id
        WHERE lr.rn = 1
    """, (year,))

    rows = cursor.fetchall()
    cursor.close()
    return_connection(conn)
    return rows


def get_driver_data_for_race(race_id):
    """
    Get all drivers for a specific race with their grid positions.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DISTINCT 
            d.driver_id,
            d.driver_full_name,
            d.driver_code,
            d.nationality,
            d.team_id,
            t.team_name,
            rr.grid_position
        FROM drivers d
        JOIN race_results rr ON d.driver_id = rr.driver_id
        LEFT JOIN teams t ON d.team_id = t.team_id
        WHERE rr.race_id = %s
        ORDER BY rr.grid_position ASC NULLS LAST
    """, (race_id,))
    
    drivers = cursor.fetchall()
    cursor.close()
    return_connection(conn)
    return drivers


def get_all_teams():
   
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM teams ORDER BY team_name")
    teams = cursor.fetchall()
    
    cursor.close()
    return_connection(conn)
    return teams

def get_team_by_id(team_id):
   
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM teams WHERE team_id = %s", (team_id,))
    team = cursor.fetchone()
    
    cursor.close()
    return_connection(conn)
    return team

def get_active_teams(year):
   
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DISTINCT t.*
        FROM teams t
        JOIN race_results rr ON t.team_id = rr.team_id
        JOIN races r ON rr.race_id = r.race_id
        WHERE r.year = %s
        ORDER BY t.team_name
    """, (year,))
    
    teams = cursor.fetchall()
    cursor.close()
    return_connection(conn)
    return teams



def get_race_results(race_id):
   
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT rr.*, d.driver_full_name, d.driver_code, t.team_name
        FROM race_results rr
        JOIN drivers d ON rr.driver_id = d.driver_id
        JOIN teams t ON rr.team_id = t.team_id
        WHERE rr.race_id = %s
        ORDER BY rr.finish_position ASC NULLS LAST
    """, (race_id,))
    
    results = cursor.fetchall()
    cursor.close()
    #return_connection(conn)
    return_connection(conn)
    return results

def get_grid_positions_for_race(race_id):
    """Real grid positions for a race, keyed by driver_id — used by the
    predictor to respect actual qualifying/grid data instead of guessing."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT driver_id, grid_position
        FROM race_results
        WHERE race_id = %s AND grid_position IS NOT NULL
    """, (race_id,))

    rows = cursor.fetchall()
    cursor.close()
    return_connection(conn)
    return {row['driver_id']: row['grid_position'] for row in rows}

def get_driver_results(driver_id, year=None, end_year=None):
   
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if year:
        cursor.execute("""
            SELECT rr.*, r.race_name, r.date, r.circuit_name, r.circuit_id, r.round, 
                   r.year, t.team_name, rr.team_id
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            LEFT JOIN teams t ON rr.team_id = t.team_id
            WHERE rr.driver_id = %s AND r.year = %s
            ORDER BY r.date
        """, (driver_id, year))
    elif end_year:
        cursor.execute("""
            SELECT rr.*, r.race_name, r.date, r.year, r.circuit_name, r.circuit_id, r.round,
                   t.team_name, rr.team_id
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            LEFT JOIN teams t ON rr.team_id = t.team_id
            WHERE rr.driver_id = %s AND r.year < %s
            ORDER BY r.date DESC
        """, (driver_id, end_year))
    else:
        cursor.execute("""
            SELECT rr.*, r.race_name, r.date, r.year, r.circuit_name, r.circuit_id, r.round,
                   t.team_name, rr.team_id
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            LEFT JOIN teams t ON rr.team_id = t.team_id
            WHERE rr.driver_id = %s
            ORDER BY r.date DESC
        """, (driver_id,))
    
    results = cursor.fetchall()
    cursor.close()
    return_connection(conn)
    return results

def get_team_results(team_id, year=None):
   
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if year:
        cursor.execute("""
            SELECT rr.*, r.race_name, r.date, r.circuit_name, d.driver_full_name
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            JOIN drivers d ON rr.driver_id = d.driver_id
            WHERE rr.team_id = %s AND r.year = %s
            ORDER BY r.date, rr.finish_position
        """, (team_id, year))
    else:
        cursor.execute("""
            SELECT rr.*, r.race_name, r.date, r.year, r.circuit_name, d.driver_full_name
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            JOIN drivers d ON rr.driver_id = d.driver_id
            WHERE rr.team_id = %s
            ORDER BY r.date DESC
        """, (team_id,))
    
    results = cursor.fetchall()
    cursor.close()
    return_connection(conn)
    return results



def get_driver_standings(year):
   
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            d.driver_id,
            d.driver_full_name,
            d.driver_code,
            SUM(rr.points_scored) as total_points,
            COUNT(CASE WHEN rr.finish_position = 1 THEN 1 END) as wins,
            COUNT(CASE WHEN rr.finish_position <= 3 THEN 1 END) as podiums,
            COUNT(*) as races_entered
        FROM race_results rr
        JOIN races r ON rr.race_id = r.race_id
        JOIN drivers d ON rr.driver_id = d.driver_id
        WHERE r.year = %s
        GROUP BY d.driver_id, d.driver_full_name, d.driver_code
        ORDER BY total_points DESC, wins DESC
    """, (year,))
    
    standings = cursor.fetchall()
    cursor.close()
    return_connection(conn)
    return standings

def get_team_standings(year):
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            t.team_id,
            t.team_name,
            SUM(rr.points_scored) as total_points,
            COUNT(CASE WHEN rr.finish_position = 1 THEN 1 END) as wins,
            COUNT(CASE WHEN rr.finish_position <= 3 THEN 1 END) as podiums
        FROM race_results rr
        JOIN races r ON rr.race_id = r.race_id
        JOIN teams t ON rr.team_id = t.team_id
        WHERE r.year = %s
        GROUP BY t.team_id, t.team_name
        ORDER BY total_points DESC, wins DESC
    """, (year,))
    
    standings = cursor.fetchall()
    cursor.close()
    return_connection(conn)
    return standings



def get_driver_stats(driver_id):
   
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            COUNT(*) as total_races,
            SUM(points) as total_points,
            COUNT(CASE WHEN finish_position = 1 THEN 1 END) as wins,
            COUNT(CASE WHEN finish_position <= 3 THEN 1 END) as podiums,
            COUNT(CASE WHEN finish_position <= 10 THEN 1 END) as points_finishes,
            COUNT(CASE WHEN dnf = true THEN 1 END) as dnfs,
            AVG(finish_position) FILTER (WHERE finish_position IS NOT NULL) as avg_finish_position
        FROM race_results
        WHERE driver_id = %s
    """, (driver_id,))
    
    stats = cursor.fetchone()
    cursor.close()
    return_connection(conn)
    return stats

def get_circuit_timezone(circuit_id):
    """IANA timezone string for a circuit, or None. Raw SQL rather than the
    SQLAlchemy ORM — `db.query(Circuit).filter(...).first()` then
    `.timezone` was observed in production returning the literal string
    'circuits_timezone' (a SQLAlchemy auto-label) instead of the real value,
    the same ORM result-mapping corruption seen elsewhere in this codebase."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT timezone FROM circuits WHERE circuit_id = %s", (circuit_id,))
    row = cursor.fetchone()
    cursor.close()
    return_connection(conn)
    return row["timezone"] if row else None


def get_circuit_results(circuit_id, limit=10):
   
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT r.year, r.race_name, r.date, 
               rr.finish_position, d.driver_full_name, t.team_name, rr.points
        FROM races r
        JOIN race_results rr ON r.race_id = rr.race_id
        JOIN drivers d ON rr.driver_id = d.driver_id
        JOIN teams t ON rr.team_id = t.team_id
        WHERE r.circuit_id = %s AND rr.finish_position = 1
        ORDER BY r.date DESC
        LIMIT %s
    """, (circuit_id, limit))
    
    results = cursor.fetchall()
    cursor.close()
    return_connection(conn)
    return results



def save_prediction(race_id, predicted_winner_id, confidence_score, predicted_top_3):
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO predictions (race_id, predicted_winner_id, confidence_score, predicted_top_3)
        VALUES (%s, %s, %s, %s)
        RETURNING prediction_id
    """, (race_id, predicted_winner_id, confidence_score, predicted_top_3))
    
    prediction_id = cursor.fetchone()['prediction_id']
    conn.commit()
    cursor.close()
    return_connection(conn)
    return prediction_id

def get_predictions_for_race(race_id):
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT p.*, d.driver_full_name as predicted_winner_name, r.race_name, r.date
        FROM predictions p
        JOIN drivers d ON p.predicted_winner_id = d.driver_id
        JOIN races r ON p.race_id = r.race_id
        WHERE p.race_id = %s
        ORDER BY p.created_at DESC
    """, (race_id,))
    
    predictions = cursor.fetchall()
    cursor.close()
    return_connection(conn)
    return predictions

def upsert_driver(driver_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO drivers (driver_id, driver_number, driver_code, driver_forename, 
                           driver_surname, driver_full_name, nationality, team_id)
        VALUES (%(driver_id)s, %(driver_number)s, %(driver_code)s, %(driver_forename)s,
                %(driver_surname)s, %(driver_full_name)s, %(nationality)s, %(team_id)s)
        ON CONFLICT (driver_id) DO UPDATE SET
            driver_number = EXCLUDED.driver_number,
            driver_code = EXCLUDED.driver_code,
            driver_forename = EXCLUDED.driver_forename,
            driver_surname = EXCLUDED.driver_surname,
            driver_full_name = EXCLUDED.driver_full_name,
            nationality = EXCLUDED.nationality,
            team_id = EXCLUDED.team_id,
            updated_at = CURRENT_TIMESTAMP
    """, driver_data)
    
    conn.commit()
    cursor.close()
    return_connection(conn)  # return to pool instead of closing

def upsert_team(team_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO teams (team_id, team_name)
        VALUES (%(team_id)s, %(team_name)s)
        ON CONFLICT (team_id) DO UPDATE SET
            team_name = EXCLUDED.team_name,
            updated_at = CURRENT_TIMESTAMP
    """, team_data)
    
    conn.commit()
    cursor.close()
    return_connection(conn)  # return to pool instead of closing