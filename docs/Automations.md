# Automations
We use Github Actions to automate our ETL process. The following are the automations we have set up:
### **Every Day Action**: 
  - **Workflow**: `.github/workflows/every_day.yml`
    - **Tasks**:
      - **Upload non-GS Allo data from Google Sheets**: 
        - **Script**: `automations/upload_non_gs_allo_data.py`
        - **Purpose**: Connects to Google Sheets using OAuth credentials, retrieves data, and uploads it to the Grants database. This ensures that the latest data from external sources is integrated into the system.
      - **Upload Passport Model Scores**: 
        - **Script**: `automations/upload_passport_model_scores.py`
        - **Purpose**: Processes and uploads model scores data into the database. It involves reading data from a specified source, transforming it as needed, and updating the database to reflect the latest scores.

### **Every 4 Hours Action**: 
  - **Workflow**: `.github/workflows/every_four_hours.yml`
    - **Tasks**:
      - **Update Foreign Schema**: 
        - **Script**: `automations/update_foreign_schema.py`
        - **Purpose**: This script synchronizes the Grants Stack Indexer and MACI databases' schema with their source counterparts. 
        - **How**: It does this by dropping and recreating foreign tables. The script checks the latest schema version for each database and updates the local schema accordingly. It tracks versions using the `schema_versions.json` file, which contains the current version and last checked timestamp. This allows the script to determine if an update is needed and ensures the local schema is current. The script specifically tracks chain data schema versions by number to identify and apply the latest changes.
      - **Update Materialized Views**: 
        - **Script**: `automations/update_materialized_views.py`
        - **Purpose**: Refreshes materialized views in the database to ensure they are up-to-date with the latest data, optimizing query performance.
        - **How**: This is the most complex script. It's explained in detail in [MaterializedViewsRefresh](MaterializedViewsRefresh.md).
      - **Update Permissions**: 
        - **Script**: `automations/create_foreign_data_users.py`
        - **Purpose**: Manages database permissions, ensuring that the correct access rights are set for users interacting with foreign data. 
        - **How**: The script creates necessary users and grants them access to schemas, in particular to foreign data (Indexer and MACI). This ensures that the correct access rights are set for users interacting with foreign data. This is necessary because foreign data tables are periodically recreated during schema updates, which can cause existing permissions to be lost. By reapplying permissions, we ensure that users retain the necessary access to foreign data.

### Notes on Credentials
- Each action uses some credentials to manage access to the DB and other services.
- When doing local development, you can load in credentials from our .env file. This is gitignored so it's not checked into the repo but you can ask a team member (Ed) for it.
- When running in Github Actions, the credentials are stored in the repo secrets. 



