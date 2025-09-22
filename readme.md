# Data Migration Script: Fix Missing/Incorrect Team Roles
Date: September 21, 2025

Author: Hariom Vashista

Status: Ready for Execution


## Overview
This script is a one-time data migration tool designed to correct a data inconsistency issue in both our MongoDB and PostgreSQL databases.

The primary function of this script is to ensure that every user who has created a team is correctly assigned the owner and admin roles for that specific team. It is designed to be safe, idempotent, and auditable.

## The Solution
The script performs the correction with the following logic:

It establishes a connection to both the MongoDB and PostgreSQL databases using credentials from a .env file.

It iterates through every document in the teams collection.

For each team, it add roles depending on whether if the user is an owner or normal member

For owners, it adds the owner, admin and member roles.

For normal members, it adds the member role (if it doesn't exist) and removed any other roles since they shouldn't exist.

The above operations take place for both MongoDB and PostgresSQL.

It also deactivates any active team roles present for any user who's not part of a team now.

If a role already exists, the script skips it and moves on, ensuring no duplicates are created.

## Prerequisites
- Python 3.8+

- pip for package installation

- Network access to the target MongoDB and PostgreSQL databases.

- A configured .env file with the correct database credentials.

## Configuration
The script is configured using a .env file in the same directory.

Copy the example configuration file:

```
cp config.env.example .env
```

Edit the .env file and fill in the correct values for the environment you are targeting (e.g., staging or production).


## Execution Plan
This script must be run with extreme care, following these steps precisely.

### Step 1: Install Dependencies
```
pip install -r requirements.txt
```

### Step 2: Perform a Dry Run (Safety Check)
Always execute a dry run first. This will simulate the entire process and report what changes it would make without modifying any data.

```
python fix_roles.py --dry-run
```

Carefully review the output. It will tell you which roles it finds, which it skips, and which it intends to insert. Do not proceed unless the output is exactly what you expect.

### Step 3: Execute the Live Run

Once you are confident in the dry run, execute the script live. It will prompt for a final confirmation before making changes.

```
python fix_roles.py
```

Monitor the output for any errors.

## Safety Features & Idempotency
Idempotent: The script is safe to run multiple times. It checks for the existence of each role before insertion and will simply skip roles that are already present.

Transactional Safety (PostgreSQL): Changes to the PostgreSQL database are committed on a per-team basis. If an error occurs while processing the roles for a single team, all PostgreSQL changes for that team are rolled back, preventing partial data writes.

Dry Run Mode: The --dry-run flag is the most important safety feature, allowing for complete verification before any changes are made.