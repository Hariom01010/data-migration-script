# Data Migration Script: Fix Missing Team Creator Roles
Date: September 21, 2025
Author: Hariom Vashista
Status: Ready for Execution

1. Overview
This script is a one-time data migration tool designed to correct a data inconsistency issue in both our MongoDB and PostgreSQL databases.

The primary function of this script is to ensure that every user who has created a team is correctly assigned the owner and admin roles for that specific team. It is designed to be safe, idempotent, and auditable.

2. The Problem
Due to a past API bug, the workflow for creating a new team did not consistently create the associated user_roles documents for the team's creator. This resulted in a state where a user could be the owner of a team (as referenced by the created_by field in the teams collection) but lack the necessary owner and admin role permissions to manage it.

Affected Systems:

MongoDB: The user_roles collection is missing the corresponding role documents.

PostgreSQL: The postgres_user_roles table, which is meant to be a synchronized copy, is also missing these role records.

3. The Solution
The script performs the correction with the following logic:

It establishes a connection to both the MongoDB and PostgreSQL databases using credentials from a .env file.

It iterates through every document in the teams collection.

For each team, it identifies the creator's user ID (created_by) and the team's ID (_id).

It then checks the user_roles collection to see if the creator has the owner, admin, and member roles for that team.

If a role is missing, the script inserts a new document into the user_roles collection in MongoDB.

Immediately after a successful insertion into MongoDB, it inserts a corresponding record into the postgres_user_roles table in PostgreSQL, ensuring both databases are consistent.

If a role already exists, the script skips it and moves on, ensuring no duplicates are created.

4. Prerequisites
Python 3.8+

pip for package installation

Network access to the target MongoDB and PostgreSQL databases.

A configured .env file with the correct database credentials.

5. Configuration
The script is configured using a .env file in the same directory.

Copy the example configuration file:

cp config.env.example .env

Edit the .env file and fill in the correct values for the environment you are targeting (e.g., staging or production).

# .env

# --- MongoDB Configuration ---
MONGO_URI="mongodb://user:password@host:port/"
MONGO_DB_NAME="your_mongo_db_name"

# --- PostgreSQL Configuration ---
PG_HOST="your_postgres_host"
PG_PORT="5432"
PG_DB_NAME="your_postgres_db_name"
PG_USER="your_postgres_user"
PG_PASSWORD="your_postgres_password"

6. Execution Plan
This script must be run with extreme care, following these steps precisely.

Step 1: Install Dependencies
pip install -r requirements.txt

Step 2: Perform a Dry Run (Safety Check)
Always execute a dry run first. This will simulate the entire process and report what changes it would make without modifying any data.

python fix_roles.py --dry-run

Carefully review the output. It will tell you which roles it finds, which it skips, and which it intends to insert. Do not proceed unless the output is exactly what you expect.

Step 3: Clean Up Partial Data (If Necessary)
If a previous live run failed, it may have left partial data in MongoDB. Run this command in mongosh or MongoDB Compass to clean it up before the final run.

db.user_roles.deleteMany({ "created_by": "migration_script_roles_fix" })

Step 4: Execute the Live Run
!! CRITICAL: Take a complete backup of both databases before proceeding. !!

Once you are confident in the dry run, execute the script live. It will prompt for a final confirmation before making changes.

python fix_roles.py

Monitor the output for any errors.

7. Safety Features & Idempotency
Idempotent: The script is safe to run multiple times. It checks for the existence of each role before insertion and will simply skip roles that are already present.

Transactional Safety (PostgreSQL): Changes to the PostgreSQL database are committed on a per-team basis. If an error occurs while processing the roles for a single team, all PostgreSQL changes for that team are rolled back, preventing partial data writes.

No Data Deletion: This script only performs INSERT operations and does not modify or delete any existing data.

Dry Run Mode: The --dry-run flag is the most important safety feature, allowing for complete verification before any changes are made.