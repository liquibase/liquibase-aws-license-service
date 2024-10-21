#!/bin/bash

# Check if DRY_RUN is true or false
if [ "$DRY_RUN" == "false" ]; then
  DETAILS_JSON=$(cat <<EOF
{
    "Version": {
        "VersionTitle": "$IMAGE_TAG",
        "ReleaseNotes": "https://docs.liquibase.com/start/release-notes/liquibase-release-notes/liquibase-$IMAGE_TAG.html"
      },
      "DeliveryOptions": [
        {
          "DeliveryOptionTitle": "Liquibase Pro Docker Image",
          "Details": {
            "EcrDeliveryOptionDetails": {
              "ContainerImages": [
                "$AWS_MP_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG"
              ],
              "CompatibleServices": [
                "ECS", "EKS"
              ],
              "Description": "This is the official Docker image for Liquibase Pro.",
              "UsageInstructions": "Product install instructions are available at https://contribute.liquibase.com/extensions-integrations/directory/integration-docs/liquibase-container-aws-ecs-eks/"
            }
          }
        }
      ]
}
EOF
  );
else
  # DRY RUN: Construct a JSON string with restricted visibility
  DETAILS_JSON=$(cat <<EOF
{
    "Version": {
        "VersionTitle": "$IMAGE_TAG",
        "ReleaseNotes": "https://docs.liquibase.com/start/release-notes/liquibase-release-notes/liquibase-$IMAGE_TAG.html"
      },
      "DeliveryOptions": [
        {
          "DeliveryOptionTitle": "Liquibase Pro Docker Image",
          "Details": {
            "EcrDeliveryOptionDetails": {
              "ContainerImages": [
                "$AWS_MP_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG"
              ],
              "CompatibleServices": [
                "ECS", "EKS"
              ],
              "Description": "This is the official Docker image for Liquibase Pro.",
              "UsageInstructions": "Product install instructions are available at https://contribute.liquibase.com/extensions-integrations/directory/integration-docs/liquibase-container-aws-ecs-eks/"
            }
          }
        }
      ],
      "Visibility": "Restricted"
}
EOF
  );
fi

# Convert the JSON string to a single line for the AWS CLI command
DETAILS_JSON_STRING="$(echo "${DETAILS_JSON}" | jq 'tostring';)";

# Notify user of the submission process
echo "Submitting new version for verification";

# Submit the new version for verification
aws marketplace-catalog start-change-set \
    --catalog "AWSMarketplace" \
    --region "${AWS_REGION}" \
    --change-set '[
      {
        "ChangeType": "'"$( [ "$DRY_RUN" == "true" ] && echo "UpdateVisibility" || echo "AddDeliveryOptions" )"'",
        "Entity": {
          "Identifier": "'"${PRODUCT_ID}"'",
          "Type": "ContainerProduct@1.0"
        },
        "Details": '"${DETAILS_JSON_STRING}"'
      }
      ]';