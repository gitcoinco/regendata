# Overview of `update_foreign_schema.py`

The `update_foreign_schema.py` script synchronizes our database with foreign data from the Indexer and MACI databases. This process ensures we have up-to-date access to external data.

## Key Components

### Configuration and Setup
- **Environment Variables:** Uses environment variables for database connections to both local and foreign databases
- **Schema Versioning:** Tracks versions in `schema_versions.json` to identify the version we're on, and the last time we checked for updates.


### Main Process

1. **Check Schema Versions**: Queries both Indexer and MACI databases to get their latest schema versions. 
    - For the indexer, we first check https://grants-stack-indexer-v2.gitcoin.co/version for the latest version. However, this version might not always reflect the most complete data, especially during indexing processes. To ensure we get the most up-to-date version with the most complete data, we also check the previous version (n-1) and run a query to compare the number of donations since September 2024 (where our static dataset ends). We then select the version with the highest number of donations.
2. **Compare Versions**: Checks against local versions stored in schema_versions.json to see if we need to update.
3. **Drop Existing Tables**: If updates needed, drops existing foreign tables
4. **Import New Schema**: Creates new foreign tables from the latest schema
5. **Update Permissions**: Reapplies necessary permissions after schema refresh

### Foreign Data Sources

- **Indexer Database**: 
  - Contains current chain data including:
    - applications
    - rounds
    - donations
    - round_roles
    - application_payouts

- **MACI Database**: 
  - Contains MACI-specific data for matching calculations including:
    - rounds
    - contributions
    - applications
    - round_roles


### NOTE: Static Data Integration Later in Pipeline
The script works in conjunction with static data sources to ensure complete historical coverage:

- **Static Chain Data**: Uses chain_data_75 for historical PGN data
- **Data Union**: Later processes (like materialized views) combine live and static data

