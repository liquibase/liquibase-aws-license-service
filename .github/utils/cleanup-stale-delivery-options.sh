#!/bin/bash
set -e

# This script removes stale delivery options from the AWS Marketplace listing.
# Stale options: "Liquibase Pro Docker Image" and "placeholder title"
# These are leftover from before the product was renamed to Liquibase Secure.
#
# Required environment variables:
#   PRODUCT_ID  - AWS Marketplace product identifier
#   AWS_REGION  - AWS region (e.g., us-east-1)
#
# Usage:
#   PRODUCT_ID=<id> AWS_REGION=us-east-1 ./cleanup-stale-delivery-options.sh

# Stale delivery option titles to remove
STALE_TITLES=("Liquibase Pro Docker Image" "placeholder title")

# Validate required environment variables
if [ -z "$PRODUCT_ID" ]; then
    echo "ERROR: PRODUCT_ID environment variable is required"
    exit 1
fi

if [ -z "$AWS_REGION" ]; then
    echo "ERROR: AWS_REGION environment variable is required"
    exit 1
fi

echo "Fetching product details for ${PRODUCT_ID}..."

ENTITY_DETAILS=$(aws marketplace-catalog describe-entity \
    --catalog "AWSMarketplace" \
    --entity-id "${PRODUCT_ID}" \
    --region "${AWS_REGION}" \
    --output json)

# Collect delivery option IDs matching stale titles
STALE_IDS="[]"

for TITLE in "${STALE_TITLES[@]}"; do
    echo "Searching for delivery options with title: '${TITLE}'..."

    IDS=$(echo "$ENTITY_DETAILS" | jq -c --arg title "$TITLE" \
        '[.Details | fromjson | .Versions[] | .DeliveryOptions[] | select(.Title == $title) | .Id] | unique')

    COUNT=$(echo "$IDS" | jq 'length')

    if [ "$COUNT" -gt 0 ]; then
        echo "  Found $COUNT delivery option(s) for '${TITLE}'"
        echo "  IDs: $IDS"
        STALE_IDS=$(echo "$STALE_IDS $IDS" | jq -s 'add | unique')
    else
        echo "  No delivery options found for '${TITLE}' (may already be removed)"
    fi
done

TOTAL=$(echo "$STALE_IDS" | jq 'length')

if [ "$TOTAL" -eq 0 ]; then
    echo ""
    echo "✅ No stale delivery options found. Listing is clean."
    exit 0
fi

echo ""
echo "=========================================="
echo "⚠️  CLEANUP PREVIEW"
echo "=========================================="
echo "Product ID: ${PRODUCT_ID}"
echo "Total delivery options to restrict: $TOTAL"
echo ""
echo "Breakdown by title:"
for TITLE in "${STALE_TITLES[@]}"; do
    TITLE_COUNT=$(echo "$ENTITY_DETAILS" | jq --arg title "$TITLE" \
        '[.Details | fromjson | .Versions[] | .DeliveryOptions[] | select(.Title == $title)] | length')
    echo "  - ${TITLE}: ${TITLE_COUNT} option(s)"
done
echo ""
echo "The active 'Liquibase Secure Docker Image' options will NOT be affected."
echo "=========================================="
echo ""
echo "Proceeding in 10 seconds... (Ctrl+C to abort)"
sleep 10

# Restrict the stale delivery options
CHANGE_SET_JSON=$(jq -n \
    --arg productId "$PRODUCT_ID" \
    --argjson deliveryIds "$STALE_IDS" \
    '[{
        "ChangeType": "RestrictDeliveryOptions",
        "Entity": {
            "Identifier": $productId,
            "Type": "ContainerProduct@1.0"
        },
        "Details": ({
            "DeliveryOptionIds": $deliveryIds
        } | tostring)
    }]')

CHANGE_SET_RESPONSE=$(aws marketplace-catalog start-change-set \
    --catalog "AWSMarketplace" \
    --region "${AWS_REGION}" \
    --change-set "$CHANGE_SET_JSON" \
    --output json)

CHANGE_SET_ID=$(echo "$CHANGE_SET_RESPONSE" | jq -r '.ChangeSetId')

if [ -z "$CHANGE_SET_ID" ] || [ "$CHANGE_SET_ID" == "null" ]; then
    echo "ERROR: Failed to start change set"
    echo "$CHANGE_SET_RESPONSE"
    exit 1
fi

echo "✅ Stale delivery options restriction submitted successfully"
echo "Change Set ID: $CHANGE_SET_ID"
echo "Monitor: aws marketplace-catalog describe-change-set --catalog AWSMarketplace --change-set-id $CHANGE_SET_ID --region ${AWS_REGION}"
