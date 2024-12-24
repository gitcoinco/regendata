import pandas as pd
import numpy as np
from datetime import datetime, timezone
import psycopg2 as pg
import networkx as nx
import itertools
from collections import defaultdict
import os
import logging
import hashlib
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Try to load .env file if it exists (for local development)
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

def run_query(query):
    """Run query and return results"""
    try:
        conn = pg.connect(host=host, port=port, dbname=dbname, user=user, password=password)
        cur = conn.cursor()
        cur.execute(query)
        col_names = [desc[0] for desc in cur.description]
        results = pd.DataFrame(cur.fetchall(), columns=col_names)
        logger.info(f"Successfully executed query and returned {len(results)} rows")
    except pg.Error as e:
        logger.error(f"Failed to execute query: {e}")
    finally:
        conn.close()
    return results

def safe_upload_table(df, final_table_name, conn):
    """Upload table with minimal downtime using temporary table"""
    temp_table = f"{final_table_name}_temp"
    
    # Create SQLAlchemy engine from connection parameters
    engine = create_engine(f'postgresql://{user}:{password}@{host}:{port}/{dbname}')
    
    # Upload to temp table
    df.to_sql(temp_table, engine, if_exists='replace', index=False)  # Use engine instead of conn
    logger.info(f"Uploaded to temporary table: {temp_table}")
        
    # Atomic swap
    with engine.connect() as connection:  # Use engine to create a connection
        with connection.begin():  # Start a transaction
            connection.execute(text(f"DROP TABLE IF EXISTS {final_table_name};"))  # Use text() to wrap the command
            connection.execute(text(f"ALTER TABLE {temp_table} RENAME TO {final_table_name};"))  # Use text() here as well
            logger.info(f"Successfully swapped tables: {temp_table} to {final_table_name}")

def clean_github(url_or_name):
    if pd.isna(url_or_name):
        return np.nan
    # Remove 'https://github.com/' if it's present
    url_or_name = url_or_name.replace('https://github.com/', '').replace('http://github.com/', '')
    if '/' in url_or_name:
        # If it's a URL or a 'username/repo' string, split by '/' and take the first part
        return url_or_name.split('/')[0].lower()
    else:
        # If it's a username, return it as is
        return url_or_name.lower()

def generate_hash_group_id(group):
    first_project_id = group['project_id'].iloc[0]  # Get the first project_id in the group
    return hashlib.sha256(first_project_id.encode()).hexdigest()  # Generate the hash


cgrants_query = '''
    SELECT
        cg.grantid AS project_id,
        cg.name AS title,
        cg.websiteurl AS website,
        LOWER(cg.payoutaddress) AS payout_address,
        cg.twitter AS project_twitter,
        cg.github AS project_github,
        cg.createdon AS created_at,
        ad.amount_donated, 
        ad.last_donation,
        'cGrants' as source
    FROM
        public."cgrantsGrants" cg
    LEFT JOIN (
        SELECT
            grant_id,
            SUM("amountUSD") AS amount_donated,
            max("created_on") AS last_donation
        FROM
            public."cgrantsContributions"
        GROUP BY
            grant_id
    ) ad ON cg.grantid = ad.grant_id;
    '''

indexer_query = '''
    SELECT
        project_id,
        metadata #>> '{application, project, projectGithub}' AS project_github,
        metadata #>> '{application, project, projectTwitter}' AS project_twitter,
        metadata #>> '{application, project, title}' AS title,
        metadata #>> '{application, project, website}' AS website,
        metadata #>> '{application, recipient}' AS payout_address,
        TO_TIMESTAMP(CAST((metadata #>> '{application, project, createdAt}') AS bigint)/1000) AS "created_at",
        total_amount_donated_in_usd AS "amount_donated",
        'indexer' AS source
    FROM
        applications
    WHERE 
        chain_id != 11155111 ;
    '''

manual_links = run_query('SELECT * FROM manual_project_links') # a table with two columns: project_id_1, project_id_2
# Set the minimum number of shared attributes required to draw an edge
min_shared_attributes = 3  # Number of shared attributes required to draw an edge

cgrants_data = run_query(cgrants_query)
indexer_data = run_query(indexer_query)
cgrants_data['project_id'] = cgrants_data['project_id'].astype(str)
data = pd.concat([cgrants_data, indexer_data], ignore_index=True)

# Pre-cleaning
eth_address_pattern = r'^0x[a-fA-F0-9]{40}$'
data['payout_address'] = data['payout_address'].astype(str)
data['payout_address'] = data['payout_address'].str.lower()
data = data[data['payout_address'].str.match(eth_address_pattern)]
data['title'] = data['title'].astype(str)
data['title'] = data['title'].str.lower()
data['title'] = data['title'].str.replace(r'[^\w\s]', '', regex=True)  # Remove punctuation
data['title'] = data['title'].str.replace(r'\s+', ' ', regex=True)  # Replace multiple spaces with a single space
data['title'] = data['title'].str.strip()  # Remove leading/trailing whitespace
data['project_twitter'] = data['project_twitter'].str.lower()
data['project_github'] = data['project_github'].astype(str)
data['project_github'] = data['project_github'].str.lower()
data['project_github'] = data['project_github'].apply(clean_github)
data['website'] = data['website'].str.rstrip('/')
data.replace('nan', np.nan, inplace=True)
# Convert empty strings to NaN and drop them
data['title'].replace('', np.nan, inplace=True)
data.dropna(subset=['title'], inplace=True)
logger.info("Dropped rows with empty titles")

# Reset group_id 
data['group_id'] = 0
logger.info("Reset group_id to 0 for all rows")

# Create a graph
G = nx.Graph()
# Add nodes
for i, row in data.iterrows():
    G.add_node(i)
logger.info("Added nodes to the graph")

# First, create edges for matching project_ids and manual links
project_groups = data.groupby('project_id')
for _, group in project_groups:
    if len(group) > 1:
        # Create edges between all rows with the same project_id
        for i1, i2 in itertools.combinations(group.index, 2):
            G.add_edge(i1, i2)
logger.info("Created edges for matching project_ids")

# Create edges for manual links
for _, row in manual_links.iterrows():
    project_id_1 = row['project_id_1']
    project_id_2 = row['project_id_2']
    # Find the indices of the rows with the given project_ids
    index_1 = data[data['project_id'] == project_id_1].index[0]
    index_2 = data[data['project_id'] == project_id_2].index[0]
    G.add_edge(index_1, index_2)
logger.info("Created edges for manual links")

# Then continue with the attribute matching logic
shared_attributes_counter = defaultdict(int)
for attribute in ['title', 'website', 'payout_address', 'project_twitter', 'project_github']:
    attribute_data = data.dropna(subset=[attribute])
    for _, group in attribute_data.groupby(attribute):
        for i1, i2 in itertools.combinations(group.index, 2):
            pair = tuple(sorted((i1, i2)))
            shared_attributes_counter[pair] += 1
logger.info("Counted shared attributes for edges")

# Add edges for pairs with at least min_shared_attributes shared attributes
for pair, count in shared_attributes_counter.items():
    if count >= min_shared_attributes:
        G.add_edge(*pair)
logger.info(f"Added edges for pairs with at least {min_shared_attributes} shared attributes")

group_id = 0
for component in nx.connected_components(G):
    data.loc[list(component), 'group_id'] = group_id
    group_id += 1

data['group_id'] = data['group_id'].astype(str)

logger.info(f"Count of groups: {group_id}")

# Create a DataFrame of the latest group information
group_info = data.copy()

# Group by 'group_id' and calculate aggregations
group_info_agg = group_info.groupby('group_id').agg({
    'amount_donated': 'sum',
    'created_at': ['min', 'max'],  # Get both first and last dates
    'project_id': 'count'
})
group_info_agg.columns = ['total_amount_donated', 'first_created_application', 'latest_created_application', 'application_count']
logger.info("Calculated aggregations for group_info")

# Merge the aggregated data back to the group_info DataFrame
group_info = pd.merge(group_info, group_info_agg, on='group_id')

# Get first entries
group_info.sort_values(by='created_at', inplace=True)
first_entries = group_info.drop_duplicates(subset='group_id', keep='first')
first_entries = first_entries.rename(columns={
    'website': 'first_website',
    'payout_address': 'first_payout_address',
    'project_twitter': 'first_project_twitter',
    'project_github': 'first_project_github',
    'source': 'first_source',
    'project_id': 'first_created_project_id'
})
first_entries = first_entries[['group_id', 'first_created_project_id', 'first_website', 'first_payout_address', 
                             'first_project_twitter', 'first_project_github', 'first_source']]
logger.info("Extracted first entries for each group")

# Get latest entries (keep existing logic)
group_info.sort_values(by='created_at', inplace=True)
group_info.drop_duplicates(subset='group_id', keep='last', inplace=True)
group_info.drop(['created_at', 'amount_donated', 'last_donation'], axis=1, inplace=True)
group_info.rename(columns={
    'project_id': 'latest_created_project_id',
    'website': 'latest_website',
    'payout_address': 'latest_payout_address',
    'project_twitter': 'latest_project_twitter',
    'project_github': 'latest_project_github',
    'source': 'latest_source'
}, inplace=True)
logger.info("Extracted latest entries for each group")

# Combine first and latest information
project_groups_summary = pd.merge(group_info, first_entries, on='group_id')
project_groups_summary = project_groups_summary[[
    'group_id', 'title', 'total_amount_donated', 'application_count',
    'latest_created_project_id', 'latest_website', 'latest_payout_address', 'latest_project_twitter',
    'latest_project_github', 'latest_source',
    'first_created_project_id', 'first_website', 'first_payout_address', 'first_project_twitter', 
    'first_project_github', 'first_source'
]]
project_groups_summary.reset_index(drop=True, inplace=True)
logger.info("Combined first and latest information for project groups summary")

# Upload project_lookup
project_lookup = data[['group_id', 'project_id', 'source']]
project_lookup = project_lookup.sort_values(by='group_id')
conn = pg.connect(host=host, port=port, dbname=dbname, user=user, password=password)
try:
    safe_upload_table(project_lookup, 'project_lookup', conn)
    logger.info("Successfully uploaded project_lookup table")
except Exception as e:
    logger.error(f"Failed to upload project_lookup: {e}")

# Upload project_groups_summary
try:
    safe_upload_table(project_groups_summary, 'project_groups_summary', conn)
    logger.info("Successfully uploaded project_groups_summary table")
except Exception as e:
    logger.error(f"Failed to upload project_groups_summary: {e}")
finally:
    conn.close()
