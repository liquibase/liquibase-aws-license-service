# Liquibase AWS Marketplace Extension Deployment and Testing Process

## 🚀 Deploying a test extension to AWS Marketplace

1. Check for update of `liquibase-secure.version`: make sure the latest `liquibase-secure.version` is set in both **pom.xml** and **Dockerfile** before submitting an AWS Marketplace version. Check for any dependabot PR's to be merged.

2. Steps that happen for every SECURE release:

a. `dependabot.yml` monitors for new versions and creates PRs:

- Docker image updates (Dockerfile)
- Maven dependency updates (pom.xml)
- When liquibase-secure is released, Dependabot creates two separate PRs

b. `dependabot-sync-and-merge.yml` automatically syncs versions:

- When Docker PR is created, it updates pom.xml to match
- Consolidates updates into a single PR
- Auto-merges after tests pass

   **Note:** Without this workflow, you'll get two separate PRs that need manual merging to keep versions synchronized.

c. `auto-trigger-marketplace-deployment.yml` automatically triggers dry_run deployment when version changes:

- Monitors pushes to main branch that modify Dockerfile or pom.xml
- Detects if liquibase-secure version actually changed (compares HEAD vs HEAD~1)
- Verifies Dockerfile and pom.xml versions match
- Automatically triggers `deploy-extension-to-marketplace.yml` in dry_run mode with a random test version tag
- Only runs when version truly changes (not on every commit)

d. `deploy-extension-to-marketplace.yml` (dry run) publishes a **test_image** to AWS Marketplace:

- Builds Docker image with new liquibase-secure version
- Tags image with random test tag (e.g., `test-a7k2m9x3`)
- Pushes to AWS Marketplace ECR registry
- Creates change set via AWS Marketplace Catalog API

e. AWS Marketplace processes and approves the test image (~30 min):

- Validates and scans the Docker image
- Change set status moves from PROCESSING → SUCCEEDED

f. AWS EventBridge polling automation detects approval and triggers testing:

- EventBridge Scheduler runs Lambda function every 5 minutes
- Lambda (`PollMarketplaceChangeSetStatus`) polls for SUCCEEDED change sets
- Detects newly approved test images (containing `test-` prefix)
- Automatically triggers `run-task-definitions.yml` via GitHub API
- Records processed change sets in DynamoDB to prevent duplicates

g. `run-task-definitions.yml` executes ECS tasks to test the approved image:

- Runs test tasks on `aws-mp-test-cluster`
- Tests the approved marketplace image
- If all tests pass, automatically restricts the test image

### Complete Automation Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Dependabot detects liquibase-secure version update          │
│ (e.g., 5.0.1 → 5.0.2)                                       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ Creates & merges PRs to main branch                         │
│ (Dockerfile + pom.xml version sync)                         │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ auto-trigger-marketplace-deployment.yml                     │
│ - Detects version change                                    │
│ - Generates test tag: test-a7k2m9x3                        │
│ - Triggers deploy workflow                                  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ deploy-extension-to-marketplace.yml (dry_run=true)          │
│ - Builds Docker image with new version                      │
│ - Pushes to AWS Marketplace as test-a7k2m9x3                │
│ - Creates change set via AWS API                            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ AWS Marketplace (~30 min)                                   │
│ - Validates image                                           │
│ - Scans for vulnerabilities                                 │
│ - Change set: PROCESSING → SUCCEEDED                        │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ EventBridge Scheduler (every 5 min)                         │
│ - Triggers PollMarketplaceChangeSetStatus Lambda            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ Lambda: PollMarketplaceChangeSetStatus                      │
│ - Lists recent change sets from AWS Marketplace             │
│ - Finds SUCCEEDED change set for test-a7k2m9x3              │
│ - Checks DynamoDB (not processed yet)                       │
│ - Extracts image tag: test-a7k2m9x3                         │
│ - Calls GitHub API to trigger run-task-definitions.yml      │
│ - Records in DynamoDB to prevent duplicates                 │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ run-task-definitions.yml                                    │
│ - Runs ECS tasks on aws-mp-test-cluster                     
│ - Tests marketplace image: test-a7k2m9x3                    │
│ - If tests pass: Restricts test image from public access    │
└─────────────────────────────────────────────────────────────┘
```

### Automation Timing

| Phase | Duration | Component |
|-------|----------|-----------|
| Version detection | ~1 day | Dependabot |
| PR merge | Manual | GitHub |
| Auto-trigger deploy | ~30 sec | GitHub Actions |
| Deploy to Marketplace | ~5 min | GitHub Actions |
| AWS Marketplace approval | ~30 min | AWS |
| Detection by polling | 0-5 min | EventBridge + Lambda |
| GitHub workflow trigger | ~5 sec | Lambda → GitHub API |
| ECS task execution | ~10 min | GitHub Actions |
| **Total (after PR merge)** | **~50 min** | Fully automated |

### :crystal_ball: Run Task definitions

### ⚠️ IMPORTANT: This workflow is ONLY for testing versions, NOT for production releases

**When to Use**:

- ✅ Testing development versions (e.g., `devopstest101`, `devopstest102`)
- ✅ Validating pre-release versions before making them public
- ✅ QA testing of marketplace listings

**When NOT to Use**:

- ❌ DO NOT use for actual production versions (e.g., `4.31.0`, `4.32.0`)
- ❌ DO NOT use for versions you want to keep publicly available
- ❌ DO NOT run on versions already released to customers

**What It Does**:

1. Runs ECS tasks to test the specified image_tag version
2. **Automatically restricts ONLY the tested version using image_tag** in AWS Marketplace after successful testing
3. Other versions remain publicly available

## :ship: Deploy the actual listing after testing

1.**After testing** run the workflow [deploy-extension-to-marketplace.yml](https://github.com/liquibase/liquibase-aws-license-service/blob/main/.github/workflows/deploy-extension-to-marketplace.yml) with actual value eg: `4.31.0` with **disabled** "Run this as dry run"

### :hammer: (If required) Manually test liquibase commands with the Marketplace listing

1. We have a `LiquibaseAWSMP` AWS account where we have listed the extension in the AWS Marketplace.
2. All the QA's and Dev's should have access to this account.
3. We have AWS Fargate Cluster called `aws-mp-test-cluster` setup in this account where we can run the Liquibase commands.
4. Most of the liquibase commands should already be defined under `Task Definitions` section in the ECS Cluster.
5. All you do is navigate to `Tasks` tab, `Run New Task`, under `Family` select the task definition you want to run, and then click on `Create`.

   ![](./image/task_tab.png)

   ![](./image/run_task.png)

6. You can also run the task using the `aws-cli` command.
   ```bash
   aws ecs run-task --cluster aws-mp-test-cluster --task-definition update-liquibase
   ```
7. To check logs of the task, click on the task you just ran under `Tasks` tab. And then navigate to `Logs` tab.

   ![](./image/running_task.png)

   ![](./image/logs_tab.png)

8. To add more commands to test in the `aws-mp-test-cluster`, you can add them in the `Task Definitions` section.
9. Contact the DevOps team to get access to the `LiquibaseAWSMP` AWS account or any other help required.

## :sparkles: New version of `liquibase-aws-license-service`

1. We release a new version of `liquibase-aws-license-service` only when it is required, as this is a SECURE extension.
2. When there is a new `liquibase-aws-license-service` version release, the dependabot in LPM(liquibase package manager) repository creates a PR: example : https://github.com/liquibase/liquibase-package-manager/pull/430/files#diff-0b0a9d274bd84c7dbfff4680de10599cd0d96458b06b74a925b2bcd3e3fc2fadR15. We need to **manually** merge the PR. Make sure to review and merge the PR before proceeding.

## Liquibase AWS License Service Extension

This Docker image provides a pre-configured Liquibase Secure environment with the AWS License Service extension installed for use in AWS Marketplace environments.

## 🏗️ Docker Image Architecture

The Dockerfile uses a multi-stage build approach to create a clean, secure final image:

### Builder Stage

- **Base**: `liquibase/liquibase-secure:5.0.0`
- **Purpose**: Install and configure the AWS License Service extension
- **Components**:
  - Downloads and installs Liquibase Package Manager (LPM) v0.2.11
  - Uses LPM to install `liquibase-aws-license-service` extension
  - Supports both AMD64 and ARM64 architectures

### Final Stage  

- **Base**: Clean `liquibase/liquibase-secure:5.0.0` image
- **Purpose**: Provides production-ready Liquibase with AWS extension
- **Contains**: Only the AWS License Service JAR file (no LPM)
- **Security**: Minimal attack surface by excluding build tools

## 🧪 Testing the Docker Image

### Build the Image

```bash
# Build the Docker image
docker build -t liquibase-aws-license-service .
```

### Verify Extension Installation

```bash
# Check that Liquibase loads the AWS extension
docker run --rm liquibase-aws-license-service liquibase --version

# Expected output should include:
# - lib/liquibase-aws-license-service-X.X.X.jar: Liquibase AWS License Service Extension X.X.X By Liquibase
```

### Verify Clean Final Image

```bash
# Confirm LPM is NOT in the final image (should return empty/error)
docker run --rm liquibase-aws-license-service which lpm

# Verify only extension JARs are present
docker run --rm liquibase-aws-license-service ls -la /liquibase/lib/
```

### Test Liquibase Functionality

```bash
# Test basic Liquibase commands
docker run --rm liquibase-aws-license-service liquibase --help

# Test with environment variable for AWS mode
docker run --rm -e DOCKER_AWS_LIQUIBASE=true liquibase-aws-license-service liquibase --help
```

### Interactive Testing

```bash
# Run container interactively for detailed testing
docker run -it --rm liquibase-aws-license-service /bin/bash

# Inside container, test various scenarios:
liquibase --version
env | grep DOCKER_AWS_LIQUIBASE
ls -la /liquibase/lib/
```

## 🎯 Purpose and Benefits

### What This Image Achieves

1. **AWS Marketplace Integration**: Pre-configured for AWS Marketplace licensing
2. **Security**: Clean final image without build tools or package managers
3. **Performance**: Optimized layer caching with multi-stage builds
4. **Compliance**: Ensures only necessary components in production image

### Key Features

- ✅ **AWS License Service Extension**: Pre-installed and ready to use
- ✅ **Multi-Architecture Support**: Works on both AMD64 and ARM64
- ✅ **Secure Build**: Final image contains no build tools or LPM
- ✅ **Environment Markers**: `DOCKER_AWS_LIQUIBASE=true` for identification
- ✅ **Version Pinning**: Uses specific, tested versions of all components

## Automated Version Management

This repository uses Dependabot and GitHub Actions to automatically monitor and update the `liquibase-secure` Docker image version, ensuring that both the Dockerfile and pom.xml stay synchronized.

### 1. How it works

1. **Dependabot monitors** https://github.com/liquibase/docker/pkgs/container/liquibase-secure for new releases (daily)
2. **When a new version is available**, Dependabot creates a PR updating the Dockerfile:
   ```dockerfile
   FROM liquibase/liquibase-secure:X.Y.Z
   ```
3. **Automated workflow** (`dependabot-sync-and-merge.yml`) triggers on the Dependabot PR:
   - Extracts the new version from the Dockerfile
   - Updates `<liquibase-secure.version>` in pom.xml to match
   - Commits the change to the same Dependabot PR
   - Adds a comment showing the version sync
   - Auto-merges the PR after all checks pass

### 2. Configuration Files

- `.github/dependabot.yml` - Configures Dependabot to monitor Docker, Maven, and GitHub Actions
- `.github/workflows/dependabot-sync-and-merge.yml` - Syncs pom.xml version and auto-merges Dependabot PRs
