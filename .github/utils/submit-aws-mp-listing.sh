#!/bin/bash

# Construct a JSON string with details about the new version to be submitted to AWS Marketplace
# This script is intended to be run as part of a GitHub Actions workflow
DETAILS_JSON=$(cat <<EOF
{
    "Version": {
        "VersionTitle": "$IMAGE_TAG",
        "ReleaseNotes": "https://docs.liquibase.com/start/release-notes/liquibase-release-notes/liquibase-$IMAGE_TAG.html"
      },
      "DeliveryOptions": [
        {
          "DeliveryOptionTitle": "Liquibase Secure Docker Image",
          "Details": {
            "EcrDeliveryOptionDetails": {
              "ContainerImages": [
                "$AWS_MP_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG"
              ],
              "CompatibleServices": [
                "ECS", "EKS"
              ],
              "Description":"This is the official Docker image for Liquibase Secure.",
              "UsageInstructions":"- How to launch Liquibase on AWS: https://docs.liquibase.com/tools-integrations/aws-mp/get-started-aws.html - How to run Liquibase commands on the launched container: https://docs.liquibase.com/tools-integrations/aws-mp/create-task-def.html"
              }
          }
        }
      ]
}
EOF
);

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
        "ChangeType": "AddDeliveryOptions",
        "Entity": {
          "Identifier": "'"${PRODUCT_ID}"'",
          "Type": "ContainerProduct@1.0"
        },
        "Details": '"${DETAILS_JSON_STRING}"'
      }
      ]';
