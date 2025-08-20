#!/bin/bash

# This script restricts the AWS Marketplace listing after successful task definition runs
# This script is intended to be run as part of a GitHub Actions workflow

# Notify user of the restriction process
echo "Restricting AWS Marketplace listing for product ${PRODUCT_ID}";

# Restrict the marketplace listing by removing delivery options
aws marketplace-catalog start-change-set \
    --catalog "AWSMarketplace" \
    --region "${AWS_REGION}" \
    --change-set '[
      {
        "ChangeType": "RestrictDeliveryOptions",
        "Entity": {
          "Identifier": "'"${PRODUCT_ID}"'",
          "Type": "ContainerProduct@1.0"
        },
        "Details": "{\"DeliveryOptionIds\": []}"
      }
      ]';

echo "Marketplace listing restriction request submitted successfully";