#!/bin/bash
# Cleanup script for DynamoDB test tables created by Liquibase tests
# This script safely deletes only test tables while protecting the tracking table
#
# Purpose: Replace Liquibase dropall to prevent accidental deletion of the
#          liquibase-secure-marketplace-changesets tracking table
#
# Usage: ./cleanup-dynamodb-test-tables.sh
# Required: AWS credentials with DynamoDB ListTables and DeleteTable permissions

set -e

AWS_REGION="${AWS_REGION:-us-east-1}"
PROTECTED_TABLE="liquibase-secure-marketplace-changesets"

echo "=========================================="
echo "DynamoDB Test Tables Cleanup"
echo "=========================================="
echo ""
echo "Region: $AWS_REGION"
echo "Protected table: $PROTECTED_TABLE (will NOT be deleted)"
echo ""

# List all DynamoDB tables
echo "Fetching list of DynamoDB tables..."
ALL_TABLES=$(aws dynamodb list-tables --region "$AWS_REGION" --query 'TableNames' --output text)

if [ -z "$ALL_TABLES" ]; then
    echo "No tables found in region $AWS_REGION"
    exit 0
fi

echo "Found tables:"
echo "$ALL_TABLES" | tr '\t' '\n' | sed 's/^/  - /'
echo ""

# Track deletion count
DELETED_COUNT=0
SKIPPED_COUNT=0
PROTECTED_COUNT=0

echo "Processing tables..."
echo ""

for TABLE in $ALL_TABLES; do
    # Skip the protected tracking table
    if [ "$TABLE" = "$PROTECTED_TABLE" ]; then
        echo "🔒 Protected (skipping): $TABLE"
        ((PROTECTED_COUNT++))
        continue
    fi

    # Delete tables matching test patterns
    # Add more patterns here based on your changelog.xml table names
    if [[ "$TABLE" == "DATABASECHANGELOG" ]] || \
       [[ "$TABLE" == "DATABASECHANGELOGLOCK" ]] || \
       [[ "$TABLE" == "liquibase-test-"* ]] || \
       [[ "$TABLE" == "person" ]] || \
       [[ "$TABLE" == "company" ]] || \
       [[ "$TABLE" == "address" ]] || \
       [[ "$TABLE" == "testTable"* ]] || \
       [[ "$TABLE" == "test_"* ]]; then

        echo "🗑️  Deleting: $TABLE"
        if aws dynamodb delete-table --table-name "$TABLE" --region "$AWS_REGION" 2>&1; then
            ((DELETED_COUNT++))
        else
            echo "   ⚠️  Failed to delete $TABLE (may already be deleting)"
            ((SKIPPED_COUNT++))
        fi
    else
        echo "⏭️  Unknown table (skipping): $TABLE"
        ((SKIPPED_COUNT++))
    fi
done

echo ""
echo "=========================================="
echo "✅ Cleanup Complete!"
echo "=========================================="
echo "Tables deleted:   $DELETED_COUNT"
echo "Tables skipped:   $SKIPPED_COUNT"
echo "Tables protected: $PROTECTED_COUNT"
echo ""

if [ $PROTECTED_COUNT -eq 0 ]; then
    echo "⚠️  WARNING: Protected table '$PROTECTED_TABLE' was not found!"
    echo "   This might indicate the table doesn't exist or was already deleted."
fi

exit 0
