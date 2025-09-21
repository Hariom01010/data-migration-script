import os
import sys
import argparse
import pymongo
import psycopg2
from dotenv import load_dotenv
from bson.objectid import ObjectId
from datetime import datetime, timezone
from enum import Enum

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

class TeamRole(Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"

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
    
    created_count = 0
    skipped_count = 0
    deleted_count = 0
    deactivated_count = 0
    error_count = 0
    
    try:
        # --- 1. Connect to Databases ---
        print("\nConnecting to MongoDB...")
        mongo_client = pymongo.MongoClient(MONGO_URI)
        mongo_db = mongo_client[MONGO_DB_NAME]
        print("MongoDB connection successful.")
        teams_collection = mongo_db['teams']
        user_team_details_collection = mongo_db['user_team_details']
        user_roles_collection = mongo_db['user_roles']

        print("\nConnecting to PostgreSQL...")
        pg_conn = psycopg2.connect(
            dbname=PG_DB_NAME,
            user=PG_USER,
            password=PG_PASSWORD,
            host=PG_HOST,
            port=PG_PORT
        )
        pg_cursor = pg_conn.cursor()
        print("PostgreSQL connection successful.")
        print("\n")
        # --- 2. Identify Corrupted Data ---
        print("\n--- Phase 1: Auditing roles for current team members ---")
        teams_data = list(teams_collection.find({}))
        teams_creator_id = []
        roles_scope = 'TEAM'
        
        for teams in teams_data:
            team_id = str(teams['_id'])
            team_member_details = list(user_team_details_collection.find({"team_id": team_id}))
            print(f"\nProcessing Team: {team_id}")
            for member in team_member_details:
                if member["user_id"] == teams["created_by"]:
                    teams_creator_id = teams['created_by']
                    print(f"  Verifying Owner roles for User: {member["user_id"]}")
                    for role in TeamRole:
                        try:
                            query_filter = {
                                'user_id': teams_creator_id,
                                'team_id': team_id,
                                'scope': roles_scope,
                                'role_name': role.value,
                                'is_active': True
                            }
                            result = list(user_roles_collection.find(query_filter))
                        
                            if dry_run:
                                if result:
                                    print(f"    [SKIP] Would skip Role '{role.value}'. Role already exists.")
                                    skipped_count += 1
                                    continue
                                
                                print(f"    [CREATE] Would create missing role '{role.value}'.")
                                created_count += 1
                                continue
                            else:
                                if result:
                                    print(f"    [SKIP] Role '{role.value}' already exists.")
                                    skipped_count += 1
                                    continue
                                print(f"    [CREATE] Creating missing role '{role.value}'...")
                                current_time = datetime.now(timezone.utc)
                                role_data = {
                                    "user_id": teams_creator_id,
                                    "role_name": role.value,
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
                                    mongo_id_str, teams_creator_id, role.value, 'TEAM', team_id, 
                                    True, role_data['created_at'], 'system', 'SYNCED', current_time
                                )
                                pg_cursor.execute(pg_insert_sql, pg_insert_params)
                                pg_conn.commit()
                                created_count += 1
                        except Exception as e:
                            print(f"    [ERROR] Failed to process role '{role.value}' for owner {member["user_id"]}. Reason: {e}")
                            error_count += 1
                            if not dry_run: pg_conn.rollback()
                            break
                else:
                    try:
                        print(f"  Verifying Member roles for User: {member["user_id"]}")
                        query_filter = {
                                'user_id': member["user_id"],
                                'team_id': team_id,
                                'scope': roles_scope,
                                'is_active': True
                            }
                        user_roles = list(user_roles_collection.find(query_filter))
                        has_member_role = False
                        for role in user_roles:
                            if role["role_name"] == TeamRole.MEMBER.value:
                                has_member_role = True
                                if dry_run:
                                    print(f"    [SKIP] Would skip Role '{role["role_name"]}'. Role already exists.")
                                    skipped_count += 1
                                    continue
                                print(f"    [SKIP] Skipped Role '{role["role_name"]}'. Role already exists.")
                                skipped_count += 1
                            else:
                                if dry_run:
                                    print(f"    [DELETE] Would delete incorrect role '{role['role_name']}' for User: {member["user_id"]}")
                                    deleted_count +=1
                                    continue
                                print(f"    [DELETE] Deleting incorrect role '{role['role_name']}' for User: {member["user_id"]}...")
                                user_roles_collection.delete_one({"_id": role["_id"]})
                                pg_delete_sql = """
                                    DELETE FROM postgres_user_roles 
                                    WHERE user_id=%s
                                    AND team_id=%s
                                    AND role_name=%s
                                    AND scope=%s
                                """
                                pg_insert_params = (
                                    member["user_id"], team_id, role["role_name"], 'TEAM' 
                                )
                                pg_cursor.execute(pg_delete_sql, pg_insert_params)
                                pg_conn.commit()
                                deleted_count += 1
                                print(f"  - Deleted role '{role['role_name']}' for user {member['user_id']}")
                        if not has_member_role:
                            if dry_run:
                                print(f"    [CREATE] Would create missing 'member' role for User: {member["user_id"]}")
                                created_count += 1
                                continue
                            print(f"    [CREATE] Creating missing 'member' role for User: {member["user_id"]}...")
                            current_time = datetime.now(timezone.utc)
                            role_data = {
                                "user_id": member["user_id"],
                                "role_name": TeamRole.MEMBER.value,
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
                                mongo_id_str, member["user_id"], TeamRole.MEMBER.value, 'TEAM', team_id, 
                                True, role_data['created_at'], 'system', 'SYNCED', current_time
                            )
                            pg_cursor.execute(pg_insert_sql, pg_insert_params)
                            pg_conn.commit()
                            fixed_count += 1
                    except Exception as e:
                        print(f"    [ERROR] Failed processing roles for member {member["user_id"]}. Reason: {e}")
                        error_count += 1
                        if not dry_run: pg_conn.rollback()
                        break
                    
        print("\n--- Phase 2: Auditing for lingering roles (removed members) ---")
        all_active_roles = list(user_roles_collection.find({'is_active': True, 'scope': 'TEAM'}))
        for role in all_active_roles:
            user_id = role["user_id"]
            team_id = role["team_id"]
            
            user_still_member = user_team_details_collection.find_one({
                "user_id": user_id,
                "team_id": team_id
            })
            
            if not user_still_member:
                if dry_run:
                    print(f"  [DEACTIVATE] Would deactivate lingering role '{role['role_name']}' for User: {member["user_id"]} in Team: {team_id}")
                    deactivated_count += 1
                    continue
                else:
                    print(f"  [DEACTIVATE] Deactivating lingering role '{role['role_name']}' for User: {member["user_id"]} in Team: {team_id}...")
                    try:
                        current_time = datetime.now(timezone.utc)
                        
                        # Deactivate in MongoDB
                        user_roles_collection.update_one(
                            {'_id': role["_id"]},
                            {'$set': {'is_active': False}}
                        )
                        
                        # Deactivate in PostgreSQL
                        pg_update_sql = """
                            UPDATE postgres_user_roles
                            SET is_active = %s, last_sync_at = %s
                            WHERE mongo_id = %s;
                        """
                        pg_cursor.execute(pg_update_sql, (False, current_time, str(role["_id"])))
                        
                        pg_conn.commit()
                        deactivated_count += 1

                    except Exception as e:
                        print(f"  [ERROR] Failed to deactivate role {role['_id']}. Reason: {e}")
                        error_count += 1
                        pg_conn.rollback()

    except Exception as e:
        print(f"\nA critical error occurred: {e}", file=sys.stderr)
        if pg_conn and not dry_run:
            pg_conn.rollback()
    
    finally:
        # --- 4. Clean Up and Report ---
        print("\n--- Final Summary ---")
        print(f"Roles Created: {created_count}")
        print(f"Roles Deleted: {deleted_count}")
        print(f"Roles Deactivated: {deactivated_count}")
        print(f"Roles Skipped (already correct): {skipped_count}")
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
