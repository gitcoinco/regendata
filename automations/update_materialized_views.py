import os
import psycopg2
import logging
import time
from decimal import Decimal
from typing import Dict, Optional, List
from dune_client.client import DuneClient
import pandas as pd 
import hashlib


# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Try to load .env file if it exists (for local development)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Database configuration
DB_PARAMS = {
    'host': os.environ.get('DB_HOST'),
    'port': os.environ.get('DB_PORT'),
    'dbname': 'Grants',
    'user': os.environ.get('DB_USER'),
    'password': os.environ.get('DB_PASSWORD')
}

# Validate DB_PARAMS
if not all(DB_PARAMS.values()):
    raise ValueError("Missing database connection parameters. Please check your environment variables.")

# Define materialized view configurations
BASE_MATVIEWS = {
    'applications': {
        'index_columns': ['id', 'chain_id', 'round_id'],
        'order_by': 'id DESC, chain_id DESC, round_id DESC',
        'amount_column': None
    },
    'rounds': {
        'index_columns': ['id', 'chain_id'],
        'order_by': 'id DESC, chain_id DESC',
        'amount_column': 'total_amount_donated_in_usd + CASE WHEN matching_distribution IS NOT NULL THEN match_amount_in_usd ELSE 0 END'
    },
     'donations': {
         'index_columns': ['id'],
         'order_by': 'id DESC',
         'amount_column': 'amount_in_usd'
     },
    'applications_payouts': {
        'index_columns': ['id'],
        'order_by': 'id DESC',
        'amount_column': 'amount_in_usd'
    },
    'round_roles': {
        'index_columns': ['chain_id', 'round_id', 'address', 'role'],
        'order_by': 'chain_id DESC, round_id DESC, address DESC, role DESC',
        'amount_column': None
    },
    'allov2_distribution_events_for_leaderboard': {
        'index_columns': ['tx_timestamp', 'event_signature'],
        'order_by': 'tx_timestamp DESC, event_signature DESC',
        'amount_column': None,
        'refresh_type': 'dune'  # indicates this needs special handling
    }
}

DEPENDENT_MATVIEWS = {
    'indexer_matching': {
        'query_file': 'automations/queries/indexer_matching.sql',
        'amount_column': 'match_amount_in_usd',
        'schema': 'public'  
    },
    'all_donations': {
        'query_file': 'automations/queries/all_donations.sql',
        'amount_column': 'amount_in_usd',
        'schema': 'public'
    },
    'all_matching': {
        'query_file': 'automations/queries/all_matching.sql',
        'amount_column': 'match_amount_in_usd',
        'schema': 'public'
    },
    'allo_gmv_leaderboard_events': {
        'query_file': 'automations/queries/allo_gmv_with_ens.sql',
        'amount_column': 'gmv',
        'schema': 'experimental_views'
    }
}

def get_connection():
    """Establish database connection with proper settings."""
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        with conn.cursor() as cursor:
            # Set keepalive parameters
            cursor.execute("SET tcp_keepalives_idle = 60;")  # 1 minute
            cursor.execute("SET tcp_keepalives_interval = 30;")  # 30 seconds
            cursor.execute("SET statement_timeout = '1800000';")  # 30 minutes
        return conn
    except psycopg2.Error as e:
        logger.error(f"Failed to connect to the database: {e}")
        raise

def execute_command(connection, command: str, params: tuple = None) -> None:
    """Execute a database command with proper error handling."""
    logger.info(f"Executing command: {command[:100]}...")
    try:
        # First ensure we're in a clean transaction state
        connection.rollback()
        
        with connection.cursor() as cursor:
            if params:
                cursor.execute(command, params)
            else:
                cursor.execute(command)
        connection.commit()
        logger.info("Command executed successfully.")
    except psycopg2.Error as e:
        logger.error(f"Database error: {e}")
        connection.rollback()  # Ensure we rollback on error
        raise

def get_matview_total(connection, matview: str, config: dict, schema: str = 'public') -> Optional[Decimal]:
    amount_column = config.get('amount_column')
    if not amount_column:
        return None 

    query = f"""
    SELECT SUM({amount_column})
    FROM {schema}.{matview}
    WHERE {amount_column} IS NOT NULL
    """
    
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            result = cursor.fetchone()
            return result[0] if result and result[0] else Decimal('0')
    except psycopg2.Error as e:
        logger.error(f"Error fetching matview total for {schema}.{matview}: {e}")
        return None

def cleanup_leftover_views(connection) -> None:
    """Clean up any leftover _new views and tables from previous failed runs."""
    logger.info("Cleaning up any leftover _new views and tables...")
    
    cleanup_commands = []
    
    # Clean up base views
    for matview in BASE_MATVIEWS.keys():
        cleanup_commands.append(f"DROP MATERIALIZED VIEW IF EXISTS public.{matview}_new CASCADE;")
    
    # Clean up dependent views
    for matview, config in DEPENDENT_MATVIEWS.items():
        schema = config.get('schema', 'public')
        cleanup_commands.append(f"DROP MATERIALIZED VIEW IF EXISTS {schema}.{matview}_new CASCADE;")
    
    execute_command(connection, "\n".join(cleanup_commands))

# Add new function for Dune refresh
def refresh_dune_base_view(connection, dune_api_key: str) -> None:
    """Refresh the Dune-based view using the API."""
    try:
        # Initialize Dune client and get query results
        logger.info("Initializing Dune client")
        dune = DuneClient(dune_api_key)
        logger.info("Fetching latest results from query 4118421")
        query_result = dune.get_latest_result(4118421)
        logger.info("Successfully retrieved query results")
        query_result_df = pd.DataFrame(query_result.result.rows)
        # Sort dataframe and add row number column
        query_result_df = query_result_df.sort_values(by=['tx_timestamp','role', 'address', 'gmv'])
        query_result_df['row_number'] = range(1, len(query_result_df) + 1)
        
        # Create hash_id by concatenating and hashing relevant columns
        query_result_df['event_signature'] = query_result_df.apply(
            lambda row: hashlib.sha256(
                f"{row['tx_timestamp']}{row['tx_hash']}{row['address']}{row['gmv']}{row['role']}{row['row_number']}".encode()
            ).hexdigest(),
            axis=1
        )

        # validation
        if len(query_result_df) == 0:
            raise ValueError("Empty result set from Dune")

        # Convert dataframe to SQL values
        values = []
        for _, row in query_result_df.iterrows():
            value_list = [
                f"'{str(v)}'" if isinstance(v, (str, pd.Timestamp)) else str(v) if v is not None else 'NULL'
                for v in row.values
            ]
            values.append(f"({', '.join(value_list)})")

        create_command = f"""
        DROP MATERIALIZED VIEW IF EXISTS public.allov2_distribution_events_for_leaderboard_new CASCADE;
        CREATE MATERIALIZED VIEW public.allov2_distribution_events_for_leaderboard_new AS
        SELECT * FROM (
            VALUES {','.join(values)}
        ) AS t({', '.join(f'"{col}"' for col in query_result_df.columns)});
        """

        execute_command(connection, create_command)
        logger.info(f"Successfully created materialized view with {len(query_result_df)} rows")

    except Exception as e:
        logger.error(f"Failed to refresh Dune view: {e}")
        raise


def create_base_matview(connection, matview: str, config: dict) -> None:
    """Create a new base materialized view."""
    index_columns = ', '.join(config['index_columns'])

    # Base SQL structure with subqueries wrapped in parentheses
    base_sql = """
    DROP MATERIALIZED VIEW IF EXISTS public.{matview}_new CASCADE;
    CREATE MATERIALIZED VIEW public.{matview}_new AS
    WITH ranked_data AS (
        SELECT 
            *,
            ROW_NUMBER() OVER (
                PARTITION BY {index_columns}
                ORDER BY 
                    CASE 
                        WHEN source = 'indexer' THEN 1 
                        WHEN source = 'static' THEN 2 
                    END
            ) as row_num
        FROM (
            (SELECT *, 'indexer' as source 
            FROM indexer.{matview} 
            WHERE chain_id != 11155111)
            UNION ALL
            (SELECT *, 'static' as source 
            FROM static_indexer_chain_data_75.{matview} 
            WHERE chain_id != 11155111)
        ) combined_data
    )
    SELECT * FROM ranked_data WHERE row_num = 1;
    """
    
    create_command = base_sql.format(
        matview=matview,
        index_columns=index_columns
    )
    
    execute_command(connection, create_command)

def create_dependent_matview(connection, matview: str, config: dict) -> None:
    query_file = config['query_file']
    schema = config.get('schema', 'public')
    
    with open(query_file, 'r') as file:
        query = file.read()

    if matview == 'allo_gmv_leaderboard_events':
        # Find the first CTE
        with_start = query.find('WITH')
        first_select = query.find('SELECT', with_start)
        
        # Insert our table mappings right after the WITH
        base_tables_cte = """
            donations AS (SELECT * FROM public.donations_new),
            rounds AS (SELECT * FROM public.rounds_new),
            applications AS (SELECT * FROM public.applications_new),
            applications_payouts AS (SELECT * FROM public.applications_payouts_new),
            allov2_distribution_events_for_leaderboard AS (SELECT * FROM public.allov2_distribution_events_for_leaderboard_new),
            chain_mapping AS (
        """
        
        # Stitch it together
        new_query = (
            query[:with_start + 4] +  # "WITH"
            "\n" + base_tables_cte + 
            query[first_select:]  # start from the SELECT of first CTE
        )
        
        logger.info(f"Original query start:\n{query[:500]}...")
        logger.info(f"Modified query start:\n{new_query[:500]}...")
        
        query = new_query
    else:
        # For other views, use the existing string replacement logic
        for view in list(BASE_MATVIEWS.keys()) + list(DEPENDENT_MATVIEWS.keys()):
            from_pattern = f"FROM {view} "
            if from_pattern in query:
                query = query.replace(from_pattern, f"FROM {view}_new ")
            join_pattern = f"JOIN {view} "
            if join_pattern in query:
                query = query.replace(join_pattern, f"JOIN {view}_new ")

    create_command = f"""
    DROP MATERIALIZED VIEW IF EXISTS {schema}.{matview}_new CASCADE;
    
    CREATE MATERIALIZED VIEW {schema}.{matview}_new AS
    {query}
    """
    
    logger.info(f"Creating {matview}_new with schema {schema}")
    if matview == 'allo_gmv_leaderboard_events':
        # Extra logging for our problematic view
        logger.info(f"Final create command start:\n{create_command[:1000]}...")
    
    execute_command(connection, create_command)

def create_indexes(connection, matview: str, config: dict) -> None:
    """Create indexes for a materialized view."""
    if 'index_columns' in config:
        index_columns = ', '.join(config['index_columns'])
        index_name = f"{matview}_idx"
        
        index_command = f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {index_name}
        ON public.{matview} ({index_columns});
        """
        
        execute_command(connection, index_command)

def validate_refresh(connection, matview: str, config: dict, old_total: Optional[Decimal]) -> None:
    """Validate the refresh operation for a materialized view."""
    new_total = get_matview_total(connection, matview, config)
    
    if old_total is not None and new_total is not None:
        if new_total < old_total:
            logger.warning(
                f"Total amount for {matview} has decreased: {old_total} -> {new_total}"
            )
        elif new_total > old_total:
            logger.info(
                f"Total amount for {matview} has increased: {old_total} -> {new_total}"
            )
        else:
            logger.info(f"Total amount for {matview} remains unchanged at {new_total}")

def check_view_exists(connection, schema: str, matview: str) -> bool:
    """Check if a materialized view exists and log its status and data."""
    check_query = """
    SELECT EXISTS (
        SELECT FROM pg_matviews 
        WHERE schemaname = %s 
        AND matviewname = %s
    );
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(check_query, (schema, matview))
            exists = cursor.fetchone()[0]
            logger.info(f"=== HEALTH CHECK: {schema}.{matview} ===")
            logger.info(f"View status: {'EXISTS' if exists else 'DOES NOT EXIST'}")
            if exists:
                try:
                    # If it exists, check its data
                    cursor.execute(f"SELECT COUNT(*) FROM {schema}.{matview}")
                    count = cursor.fetchone()[0]
                    logger.info(f"Row count: {count}")
                except psycopg2.Error as e:
                    logger.error(f"Error checking row count: {e}")
            return exists
    except psycopg2.Error as e:
        logger.error(f"Error checking view existence: {e}")
        return False


def refresh_materialized_views(connection) -> None:
    """Refresh all materialized views while maintaining dependencies."""
    try:

        # Step 1: Store current totals for validation (base views only)
        logger.info("Recording current totals...")
        old_totals = {}
        for matview, config in BASE_MATVIEWS.items():
            old_totals[matview] = get_matview_total(connection, matview, config)

        # Step 2: Create all new base views
        logger.info("Creating new base materialized views...")
        for matview, config in BASE_MATVIEWS.items():
            logger.info(f"Creating {matview}_new...")
            if config.get('refresh_type') == 'dune':
                # Get Dune API key from environment
                dune_api_key = os.environ.get('DUNE_API_KEY')
                if not dune_api_key:
                    raise ValueError("DUNE_API_KEY environment variable is required")
                refresh_dune_base_view(connection, dune_api_key)
            else:
                create_base_matview(connection, matview, config)
            create_indexes(connection, f"{matview}_new", config)

        # Step 3: Create all new dependent views
        logger.info("Creating new dependent materialized views...")
        for matview, config in DEPENDENT_MATVIEWS.items():
            logger.info(f"Creating {matview}_new...")
            create_dependent_matview(connection, matview, config)
            if 'index_columns' in config:
                create_indexes(connection, f"{matview}_new", config)

        # Step 4: Atomic swap of all views
        logger.info("Performing atomic swap of all views...")
        swap_commands = ["BEGIN;"]

        # Add swap commands for all views
        for matview, config in BASE_MATVIEWS.items():
            schema = 'public'  # base views are always in public
            swap_commands.extend([
                f"DROP MATERIALIZED VIEW IF EXISTS {schema}.{matview}_old CASCADE;",
                f"ALTER MATERIALIZED VIEW IF EXISTS {schema}.{matview} RENAME TO {matview}_old;",
                f"ALTER MATERIALIZED VIEW {schema}.{matview}_new RENAME TO {matview};"
            ])

        for matview, config in DEPENDENT_MATVIEWS.items():
            schema = config.get('schema', 'public')
            swap_commands.extend([
                f"DROP MATERIALIZED VIEW IF EXISTS {schema}.{matview}_old CASCADE;",
                f"ALTER MATERIALIZED VIEW IF EXISTS {schema}.{matview} RENAME TO {matview}_old;",
                f"ALTER MATERIALIZED VIEW {schema}.{matview}_new RENAME TO {matview};"
            ])

        swap_commands.append("COMMIT;")


        execute_command(connection, "\n".join(swap_commands))

        logger.info("=== POST-SWAP HEALTH CHECK ===")
        check_view_exists(connection, 'experimental_views', 'allo_gmv_leaderboard_events')

        # Step 5: Validate
        logger.info("Validating refreshed views...")
        for matview, config in BASE_MATVIEWS.items():
            validate_refresh(connection, matview, config, old_totals[matview])
            
        for matview, config in DEPENDENT_MATVIEWS.items():
            schema = config.get('schema', 'public')
            new_total = get_matview_total(connection, matview, config, schema)
            logger.info(f"New dependent view {schema}.{matview} total: {new_total}")

        logger.info("=== PRE-CLEANUP HEALTH CHECK ===")
        check_view_exists(connection, 'experimental_views', 'allo_gmv_leaderboard_events')

        # Step 6: Cleanup
        logger.info("Cleaning up old views...")
        cleanup_commands = []
        for matview, config in BASE_MATVIEWS.items():
            cmd = f"DROP MATERIALIZED VIEW IF EXISTS public.{matview}_old CASCADE;"
            cleanup_commands.append(cmd)
            logger.info(f"Adding cleanup command for base view: {cmd}")

        for matview, config in DEPENDENT_MATVIEWS.items():
            schema = config.get('schema', 'public')
            cmd = f"DROP MATERIALIZED VIEW IF EXISTS {schema}.{matview}_old CASCADE;"
            cleanup_commands.append(cmd)
            logger.info(f"Adding cleanup command for dependent view: {cmd}")

        # Before executing them all
        logger.info("About to execute cleanup commands:")
        for cmd in cleanup_commands:
            logger.info(f"Will execute: {cmd}")

        execute_command(connection, "\n".join(cleanup_commands))
        
        logger.info("=== POST-CLEANUP HEALTH CHECK ===")
        check_view_exists(connection, 'experimental_views', 'allo_gmv_leaderboard_events')


    except Exception as e:
        logger.error(f"Failed to refresh materialized views: {e}", exc_info=True)
        raise

def main():
    """Main execution function."""
    connection = None
    start_time = time.time()
    
    # Add argument parsing
    
    try:
        connection = get_connection()
        refresh_materialized_views(connection)
        
        end_time = time.time()
        logger.info(f"Total refresh time: {end_time - start_time:.2f} seconds")
        
    except Exception as e:
        logger.error(f"An error occurred during execution: {e}", exc_info=True)
        raise
    finally:
        if connection:
            connection.close()

if __name__ == "__main__":
    main()

