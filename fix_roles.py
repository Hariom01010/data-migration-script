import os
import sys
import argparse
import pymongo
import psycopg2
from dotenv import load_dotenv
from bson.objectid import ObjectId
from datetime import datetime, timezone

# --- Configuration ---
# Load environment variables from a .env file
load_dotenv()

# MongoDB Configuration
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")

# PostgreSQL Configuration
PG_HOST = os.getenv("PG_HOST")
PG_PORT = os.getenv("PG_PORT")
PG_DB_NAME = os.getenv("PG_DB_NAME")
PG_USER = os.getenv("PG_USER")
PG_PASSWORD = os.getenv("PG_PASSWORD")


def run_data_fix(dry_run=True):
    """
    Connects to MongoDB and PostgreSQL to find and fix corrupted data.
    
    Args:
        dry_run (bool): If True, the script will only report the changes it
                        would make without executing them.
    """
    if dry_run:
        print("--- RUNNING IN DRY-RUN MODE. NO CHANGES WILL BE MADE. ---")
    else:
        print("--- RUNNING IN LIVE MODE. CHANGES WILL BE APPLIED. ---")
        input("Press ENTER to continue or CTRL+C to abort...")

    mongo_client = None
    pg_conn = None
    
    fixed_count = 0
    skip_count = 0
    error_count = 0
    
    try:
        # --- 1. Connect to Databases ---
        print("\nConnecting to MongoDB...")
        mongo_client = pymongo.MongoClient(MONGO_URI)
        mongo_db = mongo_client[MONGO_DB_NAME]
        
        print("MongoDB connection successful.")
        teams_collection = mongo_db['teams']
        user_roles_collection = mongo_db['user_roles']

        print("Connecting to PostgreSQL...")
        pg_conn = psycopg2.connect(
            dbname=PG_DB_NAME,
            user=PG_USER,
            password=PG_PASSWORD,
            host=PG_HOST,
            port=PG_PORT
        )
        pg_cursor = pg_conn.cursor()
        print("PostgreSQL connection successful.")

        # --- 2. Identify Corrupted Data ---
        teams_data = list(teams_collection.find({}))
        teams_creator_id = []
        roles_to_ensure = ['owner', 'admin', 'member']
        roles_scope = 'TEAM'
        for teams in teams_data:
            team_id = str(teams['_id'])
            teams_creator_id = teams['created_by']
            print(f"\nProcessing Team ID: {team_id} | Owner ID: {teams_creator_id}")
            
            
            for role in roles_to_ensure:
                print(f"  - Ensuring role: '{role}'")
                try:
                    query_filter = {
                        'user_id': teams_creator_id,
                        'team_id': team_id,
                        'scope': roles_scope,
                        'role_name': role,
                        'is_active': True
                    }
                    result = list(user_roles_collection.find(query_filter))
                    print(f"  - {role} Role:")
                    print(f"    {result}")
                    
                    if dry_run:
                        if result:
                            print("  - INFO: Role exists in MongoDB. Assuming it's synced to PostgreSQL. Skipping.")
                            print("\n")
                            skip_count += 1
                            continue
                        else:
                            print(f"  [DRY-RUN] Would upsert MongoDB doc with filter: {query_filter}")
                            print("\n")
                            fixed_count += 1
                    else:
                        if result:
                            print("  - INFO: Role exists in MongoDB. Assuming it's synced to PostgreSQL. Skipping.")
                            print("\n")
                            skip_count += 1
                            continue
                        else:
                            current_time = datetime.now(timezone.utc)
                            role_data = {
                                "user_id": teams_creator_id,
                                "role_name": role,
                                "scope": roles_scope,
                                "team_id": team_id,
                                "is_active": True,
                                "created_by": "system",
                                "created_at": current_time               
                            }
                            result = user_roles_collection.insert_one(role_data)
                            mongo_id_str = str(result.inserted_id)
                            pg_insert_sql = """
                                INSERT INTO postgres_user_roles (
                                    mongo_id, user_id, role_name, scope, team_id, 
                                    is_active, created_at, created_by, sync_status, last_sync_at
                                )
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                            """
                            pg_insert_params = (
                                mongo_id_str, teams_creator_id, role, 'TEAM', team_id, 
                                True, role_data['created_at'], 'system', 'SYNCED', current_time
                            )
                            pg_cursor.execute(pg_insert_sql, pg_insert_params)
                            pg_conn.commit()
                            fixed_count += 1
                except Exception as e:
                    print(f"    - ERROR processing role '{role}'. Reason: {e}")
                    error_count += 1
                    if not dry_run: pg_conn.rollback()
                    break
    except Exception as e:
        print(f"\nA critical error occurred: {e}", file=sys.stderr)
        if pg_conn and not dry_run:
            pg_conn.rollback()
    
    finally:
        # --- 4. Clean Up and Report ---
        print("\n--- Final Summary ---")
        print(f"Roles Inserted: {fixed_count}")
        print(f"Roles Skipped: {skip_count}")
        print(f"Errors: {error_count}")
        print("-----------------------")
        if mongo_client:
            mongo_client.close()
            print("MongoDB connection closed.")
        if pg_conn:
            pg_conn.close()
            print("PostgreSQL connection closed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fix data corruption in MongoDB and sync changes to PostgreSQL."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the script without making any actual changes to the databases."
    )
    args = parser.parse_args()

    run_data_fix(dry_run=args.dry_run)
