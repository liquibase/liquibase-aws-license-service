# 🛰️ Marketplace polling Lambda

Source for `PollMarketplaceChangeSetStatus` in the `LiquibaseAWSMP` account
(`804611071420`, `us-east-1`). It runs every 15 minutes on an EventBridge
schedule and moves a Liquibase Secure release along the marketplace pipeline.

## 🔁 What it does

Two independent passes per invocation:

| Pass | Trigger | Action |
|---|---|---|
| 1 | A version titled `test-*` reaches `SUCCEEDED` on the listing | Dispatch `run-task-definitions.yml` to validate it on ECS |
| 2 | A tracked validation passed *and* its test image has since been restricted | Dispatch `deploy-extension-to-marketplace.yml` with `dry_run=false` |

State lives in the DynamoDB table `liquibase-secure-marketplace-changesets`,
keyed on `changeSetId`. Attribute names are camelCase and must stay that way, the
table's GSI and TTL depend on `status` / `createdDate` / `expirationTime`.

## ⚠️ The constraint that matters

Pass 2 has to answer "has the test image been withdrawn yet?". A restriction
change set does **not** say which version it restricted. It carries only the
delivery option ids:

```json
{ "ChangeType": "RestrictDeliveryOptions",
  "DetailsDocument": { "DeliveryOptionIds": ["676c131d-..."] } }
```

So the version title is resolved to its delivery option ids via
`DescribeEntity` on the product, and restrictions are matched on those ids. Two
things follow:

- The function needs `aws-marketplace:DescribeEntity`. Without it the lookup
  always returns nothing and no release ever fires.
- `RESTRICTION_CHANGE_TYPE` must equal the change type submitted by
  [`restrict-aws-mp-listing.sh`](../../.github/utils/restrict-aws-mp-listing.sh).
  A test asserts this, because a mismatch between the two is exactly what stalled
  the 5.2.2 release for over 30 hours without any alert.

## 🚀 Deploying

Do not edit the function in the console. Terraform owns the configuration and
ignores the code; `deploy-marketplace-poller-lambda.yml` owns the code. Merge to
`main` and it ships.

To read what is currently deployed:

```bash
export AWS_PROFILE=LiquibaseAWSMP-account-ViewOnlyAccess
URL=$(aws lambda get-function --function-name PollMarketplaceChangeSetStatus \
  --region us-east-1 --query 'Code.Location' --output text)
curl -sL "$URL" -o poller.zip && unzip -o poller.zip
```

## 🧪 Tests

```bash
python -m pip install boto3 urllib3 pytest
python -m pytest test_lambda_function.py -v
```

The fixtures are copied from real change sets on the listing, so a regression
that reintroduces the original defect fails here instead of silently parking a
release.

## 🔧 Tunables

Environment variables, all optional. Terraform ignores `environment` changes, so
these can be set on the function without fighting a Terraform run.

| Variable | Default | Purpose |
|---|---|---|
| `MARKETPLACE_PRODUCT_ID` | `prod-l2panlvbozc5e` | Container product behind the listing |
| `CHANGESET_TABLE` | `liquibase-secure-marketplace-changesets` | Tracking table |
| `LOOKBACK_DAYS` | `7` | How far back pass 1 looks. Bounded so a fixed poller does not re-validate every historical tag |
| `MAX_PAGES` | `10` | Cap on `ListChangeSets` pagination |
| `MAX_DESCRIBES` | `40` | Cap on change sets described per restriction lookup |

Reaching a cap is logged, never passed over silently.

## 🏷️ Tag selection

Pass 1 only adopts titles that **start with** `test-`. That is a prefix and not a
substring on purpose: hand-published titles such as `devopstest-5.2.2` and
`devopstests-5.2.1` contain `test-`, and a substring match would pull them into
the automation and eventually publish them. Manual tags stay manual.
