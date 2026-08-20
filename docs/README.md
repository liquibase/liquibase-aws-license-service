# Liquibase AWS Marketplace Extension Deployment and Testing Process

## 🗺️ What happens when a new Secure version lands, in plain language

The diagram and per-workflow notes below are the reference. This is the same
story told once, end to end, for anyone who just needs to know what to expect.

**When Liquibase Secure X is published to Docker Hub:**

1. **Dependabot notices** on its daily check and opens **one** pull request bumping the Dockerfile. It used to open two, one for the Dockerfile and one for the pom, which is how the two drifted apart and produced an image labelled 5.2.2 built from a 5.2.1 base. The pom is now ignored for this dependency so there is only ever one pull request.
2. **A bot tidies that pull request**: it syncs `pom.xml` and `amazon.aws.version` to match the Dockerfile, comments what it changed, then arms auto-merge.
3. **It waits for the merge to actually land**, up to 30 minutes. Arming auto-merge is not merging: the merge happens later, once the required checks pass. Everything downstream reads `main`, so acting before the merge lands means reading a `main` that does not have the bump yet.
4. **A test image is built and shipped to the marketplace** as a hidden version, labelled `test-X-<run>.<attempt>`. The run and attempt numbers mean a failed attempt can be retried; marketplace version titles are permanent, so a plain `test-X` label would burn that version's name on the first failure. If the image fails to push, the run goes red instead of carrying on with whatever stale image is already in ECR.
5. **AWS takes roughly 30 to 45 minutes** to accept that hidden version. (The 5.2.2 submission took 42 minutes: change set `5yb1p6ojdo2aet2sse0jjfby1`, 12:24 to 13:06.)
6. **The polling Lambda checks every 15 minutes.** When it sees the hidden version is live, it dispatches the ECS test suite against it.
7. **Tests pass, so the hidden version is withdrawn** from the listing and the tracking table records that this one passed.
8. **The Lambda sees the withdrawal and publishes X publicly.** This is the step that was broken: it looked for the wrong kind of record, and compared a label that kind of record never carries, so it never fired once. Every public version before this fix was dispatched by a human.
9. **The Lambda confirms the listing actually shows X publicly** before calling it done, rather than trusting that the publish request was accepted. A dispatch that GitHub accepts can still fail further down.
10. **A watchdog sweeps every two hours.** Anything stuck part-way for more than two hours turns a run red so somebody finds out. Previously a stall was indistinguishable from an idle pipeline, which is how 5.2.2 sat unnoticed for 30 hours.

End to end: roughly **one to two hours**, mostly waiting on AWS, with no human
touching anything.

### 🏷️ Reading a test tag

`test-5.2.3-482.1` breaks down as:

| Part | Meaning |
|---|---|
| `test-` | Hidden validation image, never served to customers |
| `5.2.3` | The Secure version under test |
| `482` | GitHub Actions run number |
| `.1` | Attempt within that run |

A retry of the same version is `test-5.2.3-482.2`: a new, permitted title that is
still recognisably 5.2.3. Pre-release versions keep their own hyphen, so
`test-5.2.2-beta-482.1` resolves to `5.2.2-beta`; only a trailing numeric suffix
is stripped. Tags predating this scheme still resolve, so `test-5.2.2` yields
`5.2.2`.

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
**What it does:** For Dockerfile PRs, ensures pom.xml uses the same liquibase-secure version; arms auto-merge on all Dependabot PRs; **waits for that merge to land**; then triggers marketplace deployment validation for liquibase-secure updates
**Why needed:** Prevents version mismatches between build and runtime; eliminates manual PR merging; ensures deployment pipeline starts reliably
**The merge wait is load-bearing:** `gh pr merge --auto` only *arms* auto-merge and returns; the merge itself happens minutes later once the required checks pass. The dispatch below hands `new_version` to a workflow that runs against `--ref main` and refuses to proceed when that version is not what `main`'s pom.xml contains. Dispatching immediately after arming auto-merge therefore failed that guard on essentially every bump, and the release survived only on the push-to-main git-diff fallback. The wait polls for up to 30 minutes and fails loudly if the merge never lands, because a bump that did not merge has not been released and must not look like it was.
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
**What it does:** Every two hours, fails the run if a tracked validation has been waiting more than `stall_hours` (default 2) to reach its production release
**Why needed:** Nothing distinguished "no release in progress" from "a release wedged". The 5.2.2 stall logged the same waiting line every 15 minutes for over 30 hours and was noticed only because someone went looking.
**States it watches**, each measured from the moment that state was entered:

| `testStatus` | Meaning | Measured from |
|---|---|---|
| `testing` | Validation was dispatched but the ECS run or the restrict step never reported back | `createdDate` |
| `completed` | Validation passed, waiting on the restriction to be matched | `testCompletedAt` |
| `production_dispatched` | GitHub accepted the release run, but the version is not public on the listing yet | `productionTriggeredAt` |

`testing` matters more than it looks. The polling Lambda's pass 2 only reads
`completed` rows, and the second scan below skips anything whose `imageTag` the
Lambda already tracked, so a row that dies at `testing` is invisible to both and
ages forever. On the first run after this state was added, all three stalls found
on the live table were sitting at `testing`.

**Second scan:** it also reads the listing directly for `test-*` versions that are
still Public and that the Lambda never tracked at all, which is the opposite
failure: the poller being down longer than `LOOKBACK_DAYS`, after which the
version falls out of its window for good.

**Closing a row out:** a validation that is genuinely never going to release (a
superseded workaround image, or historical debris) should be moved to
`testStatus=abandoned` rather than deleted. No reader queries `abandoned`, so the
row stops alerting, while keeping its `imageTag` means the second scan still counts
it as tracked and will not flag the same version from the other direction.

### Automation Timing (Complete End-to-End)

| Phase | Duration | Component |
|-------|----------|-----------|
| Version detection | ~1 day | Dependabot |
| PR sync, then wait for the merge to land | ~2 min, plus up to 30 min waiting | GitHub Actions (dependabot-sync-and-merge.yml) |
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

One caveat on reading the table: the sync step deliberately blocks while auto-merge
waits on required checks, so a bump sitting there for 20 minutes is healthy, not
stuck. Do not "optimise" that wait away; see the note under workflow 2 for what
breaks when the dispatch runs ahead of the merge.

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
