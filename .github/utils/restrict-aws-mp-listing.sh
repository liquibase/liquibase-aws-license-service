#!/bin/bash
set -e  # Exit on error

# This script restricts the AWS Marketplace listing after successful task definition runs
# This script is intended to be run as part of a GitHub Actions workflow

# Validate required environment variables
if [ -z "$IMAGE_TAG" ]; then
    echo "ERROR: IMAGE_TAG environment variable is required"
    exit 1
fi

echo "Restricting delivery options for version: ${IMAGE_TAG}"
echo "Fetching delivery options for product ${PRODUCT_ID}..."

# Get the product entity details to retrieve delivery option IDs
ENTITY_DETAILS=$(aws marketplace-catalog describe-entity \
    --catalog "AWSMarketplace" \
    --entity-id "${PRODUCT_ID}" \
    --region "${AWS_REGION}" \
    --output json)

# SAFETY CHECK 1: Verify the version exists before attempting to extract
echo "Verifying version ${IMAGE_TAG} exists in product..."
VERSION_EXISTS=$(echo "$ENTITY_DETAILS" | jq --arg version "$IMAGE_TAG" \
    '.Details | fromjson | [.Versions[] | select(.VersionTitle == $version)] | length')

if [ "$VERSION_EXISTS" -eq 0 ]; then
    echo "❌ ERROR: Version '${IMAGE_TAG}' not found in product ${PRODUCT_ID}"
    echo ""
    echo "Available versions:"
    echo "$ENTITY_DETAILS" | jq -r '.Details | fromjson | .Versions[] | "  - \(.VersionTitle) (Status: \(.Status // "Unknown"))"'
    exit 1
fi

echo "✓ Version ${IMAGE_TAG} found"

# SAFETY CHECK 2: Extract delivery option IDs using a SINGLE jq command (no pipeline)
DELIVERY_OPTION_IDS=$(echo "$ENTITY_DETAILS" | jq -c --arg version "$IMAGE_TAG" \
    '.Details | fromjson | [.Versions[] | select(.VersionTitle == $version) | .DeliveryOptions[].Id]')

# SAFETY CHECK 3: Verify we extracted IDs
NUM_IDS=$(echo "$DELIVERY_OPTION_IDS" | jq 'length')

if [ "$NUM_IDS" -eq 0 ]; then
    echo "❌ ERROR: No delivery options found for version ${IMAGE_TAG}"
    echo "This version exists but has no delivery options to restrict."
    exit 1
fi

echo "✓ Found $NUM_IDS delivery option(s) for version ${IMAGE_TAG}"

# SAFETY CHECK 4: Verify we matched exactly ONE version (no duplicates)
MATCHED_VERSIONS=$(echo "$ENTITY_DETAILS" | jq -r --arg version "$IMAGE_TAG" \
    '.Details | fromjson | [.Versions[] | select(.VersionTitle == $version)] | length')

if [ "$MATCHED_VERSIONS" -ne 1 ]; then
    echo "❌ ERROR: Expected to match 1 version, but matched $MATCHED_VERSIONS"
    echo "This indicates duplicate versions or a filter logic error."
    exit 1
fi

echo "✓ Verified exactly 1 version matched (no duplicates)"

# SAFETY CHECK 5: Display exactly what will be restricted
echo ""
echo "=========================================="
echo "⚠️  RESTRICTION PREVIEW"
echo "=========================================="
echo "Product ID: ${PRODUCT_ID}"
echo "Version to restrict: ${IMAGE_TAG}"
echo "Delivery option IDs: $DELIVERY_OPTION_IDS"
echo ""
echo "This will ONLY restrict version ${IMAGE_TAG}."
echo "Other versions will remain PUBLIC."
echo "=========================================="
echo ""
echo "Proceeding in 10 seconds... (Cancel the GitHub Actions workflow run to abort if IMAGE_TAG=${IMAGE_TAG} looks incorrect)"
sleep 10

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