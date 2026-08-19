# Liquibase AWS Marketplace Extension Deployment and Testing Process

## 🚀 Deploying a test extension to AWS Marketplace

### Complete Automation Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Dependabot opens ONE PR bumping the Dockerfile              │
│ (e.g., 5.2.1 → 5.2.2); liquibase-commercial is ignored in   │
│ dependabot.yml and synced from the Dockerfile instead       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ dependabot-sync-and-merge.yml                               │
│ - Syncs Dockerfile + pom.xml versions                       │
│ - Auto-merges PR to main                                    │
│ - Triggers auto-trigger-marketplace-deployment.yml          │
│   for liquibase-secure updates (via workflow_dispatch        │
│   with version passed as input)                              │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ auto-trigger-marketplace-deployment.yml                     │
│ - Triggered by: push to main OR workflow_dispatch from      │
│   dependabot-sync-and-merge.yml (with version input)        │
│ - Detects version change via input or git diff fallback     │
│ - Generates test tag:                                       │
│     test-<version>-<run_number>.<run_attempt>               │
│ - Triggers deploy workflow                                  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌───────────────────────────────────────────────────────────────┐
│ deploy-extension-to-marketplace.yml (dry_run=true)            │
│ - Builds Docker image with new version                        │
│ - Pushes to AWS Marketplace as                                │
│     test-<version>-<run_number>.<run_attempt>                 │
│ - Creates change set via AWS API                              │
└────────────────────────┬──────────────────────────────────────┘
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
│ EventBridge Scheduler (every 15 min)                        │
│ - Triggers PollMarketplaceChangeSetStatus Lambda            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌───────────────────────────────────────────────────────────────────────────────┐
│ Lambda: PollMarketplaceChangeSetStatus                                        │
│ - Finds SUCCEEDED change sets for versions titled test-*                      │
│ - Checks DynamoDB (not processed yet)                                         │
│ - Extracts the version title, e.g. test-5.2.2-482.1                          │
│ - Calls GitHub API to trigger run-task-definitions.yml                        │
│ - Records in DynamoDB to prevent duplicates                                   │
└────────────────────────┬──────────────────────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ run-task-definitions.yml                                    │
│ - Runs ECS tasks on aws-mp-test-cluster                     |
│ - Tests marketplace image:                                  │
│     test-<version>-<run_number>.<run_attempt>               │
│ - If tests pass: Restricts test image from public access    │
│ - Marks test as completed in DynamoDB                       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ Test image restriction processing (~15 min)                 │
│ - AWS processes the restriction change set                  │
│ - Change set status: PROCESSING → SUCCEEDED                 │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ↓
┌───────────────────────────────────────────────────────────────────────────────┐
│ Lambda: PollMarketplaceChangeSetStatus (next 15-min cycle)                    │
│ - Scans DynamoDB for TestStatus=completed                                     │
│ - Maps the version title to its delivery option ids (DescribeEntity)          │
│ - Finds the RestrictDeliveryOptions change set withdrawing those ids          │
│ - Verifies restriction Status=SUCCEEDED. FAILED and CANCELLED are terminal:   │
│   it reports and stops rather than waiting on a change set that is done       │
│ - Triggers deploy-extension-to-marketplace.yml with dry_run=false and         │
│   validated_version=<version>, NOT image_tag: that input is the ECR tag to    │
│   build, and the manual release path still uses it that way                   │
│ - Updates DynamoDB: TestStatus=production_dispatched                          │
│ - A later cycle promotes it to production_released, but only once the version │
│   is actually Public on the listing. A dispatch GitHub accepted is not a      │
│   release: the run can still fail at the push or the validated-version gate   │
└────────────────────────┬──────────────────────────────────────────────────────┘
                         │
                         ↓
┌───────────────────────────────────────────────────────────────┐
│ deploy-extension-to-marketplace.yml (dry_run=false)           │
│ - Builds production Docker image (e.g., 5.0.2)                │
│ - Pushes to AWS Marketplace for public release                │
│ - Creates production change set via AWS API                   │
└────────────────────────┬──────────────────────────────────────┘
                         │
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ AWS Marketplace approval (~30 min)                          │
│ - Validates production image                                │
│ - Once approved: Version available to customers             │
└─────────────────────────────────────────────────────────────┘
```

### Workflow Descriptions

#### 1. `dependabot.yml` - Version Monitoring
**What it does:** Automatically monitors for new liquibase-secure Docker images and Maven dependencies daily
**Why needed:** Keeps the extension up-to-date with latest Liquibase Secure versions without manual checking
**Creates:** One PR per liquibase-secure release, bumping the Dockerfile
**Note:** `com.liquibase:liquibase-commercial` is deliberately in the maven `ignore` list. It used to get its own PR, which merged in seconds while the Dockerfile PR waited, leaving `main` with a pom and Dockerfile on different versions. `liquibase-secure.version` is synced from the Dockerfile instead, so one PR is always self-consistent. `software.amazon.awssdk:*` is ignored for a different reason (see TECHOPS-622).

#### 2. `dependabot-sync-and-merge.yml` - Version Synchronization
**What it does:** For Dockerfile PRs, ensures pom.xml uses the same liquibase-secure version; auto-merges all Dependabot PRs; triggers marketplace deployment validation for liquibase-secure updates
**Why needed:** Prevents version mismatches between build and runtime; eliminates manual PR merging; ensures deployment pipeline starts reliably
**Important:** Version sync only runs when the Dockerfile is modified in the PR. Non-Dockerfile PRs (e.g., Maven dependency bumps) skip the sync to avoid regressing pom.xml from a stale branch.
**Without this:** You'd need to manually sync versions and rely solely on push events to trigger deployment

#### 3. `auto-trigger-marketplace-deployment.yml` - Smart Deployment Trigger
**What it does:** Detects when liquibase-secure version changes in main branch and triggers test deployment
**Why needed:** Automates the testing process immediately after version updates
**Triggered by:** Push to main (Dockerfile/pom.xml changes) or workflow_dispatch from dependabot-sync-and-merge.yml (with version input)
**Concurrency:** Uses a concurrency group to prevent duplicate deployments if both triggers fire simultaneously
**Version detection:** Uses version passed via workflow_dispatch input when available; falls back to git diff for push events. Only triggers when the actual version number changes

#### 4. `deploy-extension-to-marketplace.yml` - Test Image Publisher
**What it does:** Builds Docker image and submits it to AWS Marketplace with test tag (e.g., `test-5.0.2`)
**Why needed:** Creates a test version for validation before production release
**Concurrency:** Uses a concurrency group (`deploy-to-marketplace`) to queue runs instead of running in parallel, preventing duplicate marketplace submissions
**Modes:**
- **dry_run=true**: Test image (auto-restricted after testing)
- **dry_run=false**: Production release (publicly available)

#### 5. AWS EventBridge + Lambda - Approval Detection
**What it does:** Polls AWS Marketplace every 15 minutes to detect when test images are approved
**Why needed:** AWS doesn't send real-time approval notifications; polling ensures we catch approvals
**Components:**
- **EventBridge Scheduler**: Triggers Lambda every 15 minutes
- **Lambda (`PollMarketplaceChangeSetStatus`)**: Checks for SUCCEEDED change sets
- **DynamoDB**: Tracks processed change sets to prevent duplicate test runs

**Source:** [`lambda/marketplace-poller/`](../lambda/marketplace-poller/), deployed by `deploy-marketplace-poller-lambda.yml`. Do not edit the function in the console: Terraform owns its configuration and ignores the code, and this workflow owns the code.
**Tag selection:** only version titles *starting with* `test-` are adopted. Titles published by hand such as `devopstest-5.2.2` contain `test-` but must stay manual, so the check is a prefix and not a substring.
**Scan window:** `LOOKBACK_DAYS` (default 7) bounds how far back new versions are looked for, so the poller cannot re-validate long-released tags.

#### 6. `run-task-definitions.yml` - Automated Testing
**What it does:** Runs ECS tasks to test the approved marketplace image, then restricts it and marks as completed
**Why needed:** Validates the image works correctly in AWS Marketplace environment
**After completion:** Marks test as completed in DynamoDB, signaling Lambda to trigger production release
**Important:** Only use for test images (titles starting with `test-`), never production versions

#### 7. Lambda Production Release Trigger (Extended Polling)
**What it does:** Polls for completed tests, verifies restriction succeeded, then triggers production release
**Why needed:** Ensures restriction is complete before submitting production version (AWS doesn't allow simultaneous change sets)
**Process:**
- Scans DynamoDB for `testStatus = completed`
- Maps the test image's version title to its delivery option ids via `DescribeEntity` on the product
- Finds the `RestrictDeliveryOptions` change set that withdrew those ids and checks `Status = SUCCEEDED`
- Triggers `deploy-extension-to-marketplace.yml` with `dry_run=false`
**Timing:** Triggers within 0-15 minutes after restriction completes

**Why the id mapping:** a `RestrictDeliveryOptions` change set records only the delivery option ids it withdrew and carries no version title, so matching on a title cannot work. Getting this wrong is what stalled the 5.2.2 release for 30 hours: the lookup matched a change type that is never submitted and then compared a field that does not exist, so it always answered "not restricted yet" and the release never fired. `RESTRICTION_CHANGE_TYPE` in the Lambda must stay equal to the change type `.github/utils/restrict-aws-mp-listing.sh` submits; a test asserts it.

#### 8. `deploy-marketplace-poller-lambda.yml` - Lambda Code Deployment
**What it does:** Runs the poller's tests on a PR, and on merge to `main` packages and ships the code to `PollMarketplaceChangeSetStatus`
**Why needed:** The Terraform for that function ignores `filename` and `source_code_hash` on the assumption that CI deploys the code, but no pipeline existed. The only copy of the code was the deployed zip, so it could not be diffed or reviewed, and a defect in it survived an earlier round of fixes to the same function.

#### 9. `marketplace-release-watchdog.yml` - Stall Detection
**What it does:** Every two hours, fails the run if a validated test image has been waiting more than `stall_hours` (default 2) for its production release
**Why needed:** Nothing distinguished "no release in progress" from "a release wedged". The 5.2.2 stall logged the same waiting line every 15 minutes for over 30 hours and was noticed only because someone went looking.

### Automation Timing (Complete End-to-End)

| Phase | Duration | Component |
|-------|----------|-----------|
| Version detection | ~1 day | Dependabot |
| PR sync & merge | ~2 min | GitHub Actions (dependabot-sync-and-merge.yml) |
| Auto-trigger test deploy | ~30 sec | GitHub Actions |
| Deploy test image | ~5 min | GitHub Actions |
| AWS Marketplace test approval | ~30 min | AWS |
| Detection by Lambda polling | 0-15 min | EventBridge + Lambda |
| Run ECS tests | ~10 min | GitHub Actions |
| Restrict test image | ~15 min | AWS Marketplace |
| Lambda detects restriction complete | 0-15 min | EventBridge + Lambda |
| Trigger production release | ~5 sec | Lambda → GitHub API |
| Deploy production image | ~5 min | GitHub Actions |
| AWS Marketplace prod approval | ~30 min | AWS |
| **Total (test to production)** | **~2 hours** | Fully automated |
| **Total (PR merge to public)** | **~2 hours** | Fully automated |

These are the intended timings. Until the restriction-matching fix, the production
release leg never fired at all and every public version was dispatched by hand, so
treat any release exceeding this envelope as broken rather than slow. The watchdog
exists to make that call for you.

### :mag: If a release does not appear

1. `marketplace-release-watchdog.yml` fails when something has been waiting too long. Start with its most recent run.
2. Check the poller's logs: log group `/aws/lambda/PollMarketplaceChangeSetStatus`, us-east-1, `LiquibaseAWSMP`. A repeating `No restriction change set found yet for <tag>` means the restriction lookup is not matching.
3. Confirm the restriction change set actually succeeded:
   ```bash
   aws marketplace-catalog list-change-sets --catalog AWSMarketplace --region us-east-1 \
     --filter-list '[{"Name":"EntityId","ValueList":["prod-l2panlvbozc5e"]}]' \
     --sort '{"SortBy":"StartTime","SortOrder":"DESCENDING"}' --max-results 5
   ```
4. Do not trust a green deploy run on its own. Grep its log for `buildx failed`: a push to an existing immutable ECR tag fails the push, and the run used to report success anyway.
5. AWS rejects simultaneous change sets on one product. If a submission failed, check whether another change set was in flight at the time.

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
   - Checks if the Dockerfile was modified in the PR (version sync only applies to Dockerfile changes)
   - For Dockerfile PRs: extracts the new version, updates `<liquibase-secure.version>` in pom.xml to match, commits the change, and adds a comment showing the version sync
   - For non-Dockerfile PRs (e.g., Maven dependency bumps): skips version sync to prevent regressing pom.xml from a stale branch
   - Auto-merges the PR after all checks pass

### 2. Configuration Files

- `.github/dependabot.yml` - Configures Dependabot to monitor Docker, Maven, and GitHub Actions
- `.github/workflows/dependabot-sync-and-merge.yml` - Syncs pom.xml version, auto-merges Dependabot PRs, and triggers marketplace deployment for liquibase-secure updates
- `.github/workflows/auto-trigger-marketplace-deployment.yml` - Validates version change and triggers test deployment to AWS Marketplace
