#!/bin/bash
set -e  # Exit on error

# This script restricts the AWS Marketplace listing after successful task definition runs
# This script is intended to be run as part of a GitHub Actions workflow

echo "Fetching delivery options for product ${PRODUCT_ID}..."

# Get the product entity details to retrieve delivery option IDs
ENTITY_DETAILS=$(aws marketplace-catalog describe-entity \
    --catalog "AWSMarketplace" \
    --entity-id "${PRODUCT_ID}" \
    --region "${AWS_REGION}" \
    --output json)

# Extract all delivery option IDs from the product
DELIVERY_OPTION_IDS=$(echo "$ENTITY_DETAILS" | jq -r '.Details' | jq -r '.Versions[].DeliveryOptions[].Id' | jq -R -s -c 'split("\n") | map(select(length > 0))')

# Check if we found any delivery options
if [ "$DELIVERY_OPTION_IDS" == "[]" ] || [ -z "$DELIVERY_OPTION_IDS" ]; then
    echo "ERROR: No delivery options found for product ${PRODUCT_ID}"
    echo "Entity details:"
    echo "$ENTITY_DETAILS" | jq '.Details'
    exit 1
fi

echo "Found delivery options to restrict: $DELIVERY_OPTION_IDS"

# Restrict the marketplace listing by removing delivery options
echo "Restricting AWS Marketplace listing for product ${PRODUCT_ID}..."

# Use jq to properly construct the change-set JSON with correct escaping
CHANGE_SET_JSON=$(jq -n \
  --arg productId "$PRODUCT_ID" \
  --argjson deliveryIds "$DELIVERY_OPTION_IDS" \
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

echo "✅ Marketplace listing restriction request submitted successfully"
echo "Change Set ID: $CHANGE_SET_ID"
echo "Monitor progress with: aws marketplace-catalog describe-change-set --catalog AWSMarketplace --change-set-id $CHANGE_SET_ID --region ${AWS_REGION}"