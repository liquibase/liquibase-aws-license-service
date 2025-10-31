# ECS Task Definitions

This directory contains task definition templates for AWS Marketplace ECS tasks.

## Task Definitions

### 1. version-command.json
- **Purpose**: Verifies Liquibase Pro installation and version
- **Command**: `--version`
- **Container Name**: `Liquibase-Secure`
- **Log Group**: `/ecs/connect-command`
- **Resources**: 1024 CPU, 3072 MB memory

### 2. update-command-dynamodb.json
- **Purpose**: Runs Liquibase update command against DynamoDB
- **Command**: Liquibase update with DynamoDB changelog from S3
- **Container Name**: `Liquibase-Secure`
- **Log Group**: `/ecs/update-sql-command`
- **Resources**: 1024 CPU, 3072 MB memory
- **Environment Variables**:
  - `AWS_REGION=us-east-1`
- **Volumes**: `common_volume` mounted at `/common`

### 3. dropall-command.json
- **Purpose**: Drops all database objects (cleanup task)
- **Command**: `dropall` with S3 configuration
- **Container Name**: `Liquibase-Secure`
- **Log Group**: `/ecs/dropall-command`
- **Resources**: 1024 CPU, 3072 MB memory
- **Environment Variables**:
  - `INSTALL_MYSQL=true`
  - `AWS_REGION=us-east-1`

## Usage

These templates are used by the `run-task-definitions.yml` workflow:

1. The workflow copies the appropriate template
2. Replaces `PLACEHOLDER_IMAGE_URI` with the actual image URI from AWS Marketplace
3. Registers the task definition with ECS
4. Runs the task on the `aws-mp-test-cluster`

## Image URI Format

The image URI is constructed as:
```
709825985650.dkr.ecr.us-east-1.amazonaws.com/liquibase/liquibase/liquibasepro:<TAG>
```

Where `<TAG>` is provided as input to the workflow (e.g., `devopstest101`, `4.31.0`).

## Modifying Task Definitions

To modify a task definition:

1. Edit the JSON file in this directory
2. Commit the changes
3. The next workflow run will use the updated template

**Note**: Keep `"image": "PLACEHOLDER_IMAGE_URI"` - this is replaced at runtime.

## Required IAM Permissions

### Task Execution Role
The task execution role (`arn:aws:iam::804611071420:role/ecsTaskExecutionRole`) needs:
- **ECR access** to pull images
- **CloudWatch Logs access** to create log streams

### Task Role
The task role (`arn:aws:iam::804611071420:role/ecsTaskExecutionRole`) needs:
- **S3 access** to read configuration files from `s3://aws-marketplace-listing-files/`
- **DynamoDB access** for update and dropall commands
- **Proper permissions** for AWS SDK authentication

## Environment Variables

Tasks that access AWS services (S3, DynamoDB) include these environment variables:
- `AWS_REGION=us-east-1` - Specifies the AWS region
- `AWS_SDK_LOAD_CONFIG=true` - Enables SDK configuration loading
- `AWS_EC2_METADATA_DISABLED=false` - Allows ECS task role credentials from metadata

These variables help resolve AWS SDK authentication issues in containerized environments.
