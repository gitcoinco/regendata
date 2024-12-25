import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from sqlalchemy import create_engine
import json
import os
import logging
import numpy as np
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    if load_dotenv():
        logger.info("Loaded .env file")
    else:
        logger.info("No .env file found or loaded")
except ImportError:
    logger.info("dotenv not installed, skipping .env file loading")

# Load database credentials from environment variables
host = os.environ['DB_HOST']
port = os.environ['DB_PORT']
dbname = 'Grants'
user = os.environ['DB_USER']
password = os.environ['DB_PASSWORD']

# Load Google credentials from environment variables
google_creds_json = json.loads(os.environ['GOOGLE_CREDENTIALS'])  # Assumes JSON string
creds = ServiceAccountCredentials.from_json_keyfile_dict(google_creds_json, ["https://spreadsheets.google.com/feeds",'https://www.googleapis.com/auth/drive'])
client = gspread.authorize(creds)

def upload_sheet_to_postgres(spreadsheet_id, table_name):
    # Open the spreadsheet and get the first sheet
    sheet = client.open_by_key(spreadsheet_id).sheet1
    data = sheet.get_all_records()
    logger.info(f"Sheet for {table_name} read successfully, containing {len(data)} rows")
    df = pd.DataFrame(data)

    # Convert to DataFrame and add special handling for certain columns
    if table_name == 'AlloRoundsOutsideIndexer':
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['amount_in_usd'] = df['amount_in_usd'].replace('[\$,]', '', regex=True).astype(float)
    elif table_name == 'program_round_labels':
        df['round_id'] = df['round_id'].astype(str).str.lower()
        df['round_number'] = df['round_number'].astype(str).str.extract('(\d+)').replace('', pd.NA)
        # Replace empty strings with NaN, then convert to numeric
        for col in ['chain_id', 'matching_pool']:
            if col in df.columns:
                df[col] = df[col].replace('', pd.NA)
                df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # UPLOAD df TO POSTGRES
    engine = create_engine(f'postgresql://{user}:{password}@{host}:{port}/{dbname}')
    try:
        with engine.begin() as conn:  # begin() automatically handles commit/rollback
            conn.execute(text('SET statement_timeout = 300000;'))  # 5 minutes
            logger.info(f"Deleting existing data from {table_name}...")
            
            # Simple delete for small tables
            result = conn.execute(text(f'DELETE FROM "public"."{table_name}";'))
            logger.info(f"Deleted {result.rowcount} rows from {table_name}")
            
            df.to_sql(table_name, engine, if_exists='append', index=False, schema='public')
            
    except Exception as e:
        logger.error(f"Failed to write data to database table {table_name}: {e}")
        raise

# Define a list of sheets to process
sheets_to_process = [
    {'spreadsheet_id': '1Jx3RgIKkuhhzVFvUSjRgOEJcpRfpu-7WlPd8wLUGdxE', 'table_name': 'AlloRoundsOutsideIndexer'},
    {'spreadsheet_id': '1dhB_HxxulDNi0EowQeJqH-Uzbbx7CLXLKleAVo-tZtY', 'table_name': 'manual_project_links'},
    {'spreadsheet_id': '1d1d53xStoPMsLCvjLnqCmNicpak-Ji3gpSaRqiZp2sA', 'table_name': 'program_round_labels'},
    # Add more sheets as needed
]

# Main process to iterate through sheets
for sheet_info in sheets_to_process:
    upload_sheet_to_postgres(sheet_info['spreadsheet_id'], sheet_info['table_name'])

