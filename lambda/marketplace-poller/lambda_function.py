"""Poll AWS Marketplace change sets and drive the Liquibase Secure release pipeline.

Runs on a 15-minute EventBridge schedule as PollMarketplaceChangeSetStatus. Two
independent passes per invocation:

  PART 1  a newly SUCCEEDED test version appeared on the listing, so dispatch the
          ECS validation workflow for it.
  PART 2  a validation run finished and its test image has since been restricted,
          so dispatch the production release.

PART 2 is what silently stalled 5.2.2: it asks find_restriction_changeset()
whether the test image has been withdrawn, and that lookup could never answer
yes. Two independent reasons, both fixed here:

  * The restrict step submits ChangeType 'RestrictDeliveryOptions'. The old code
    matched the substring 'RestrictVersion', which no change type ever carries.
  * A RestrictDeliveryOptions change identifies what it withdrew by delivery
    option id only ({"DeliveryOptionIds": [...]}). It has no VersionTitle, so the
    old title comparison could not have matched even with the type corrected.

The version title is therefore resolved to its delivery option ids through the
product entity, and restrictions are matched on those ids. Keep this in step with
.github/utils/restrict-aws-mp-listing.sh: if the change type submitted there ever
changes, RESTRICTION_CHANGE_TYPE below has to change with it.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import boto3
import urllib3
from botocore.exceptions import ClientError

CATALOG = 'AWSMarketplace'
REGION = 'us-east-1'

marketplace_client = boto3.client('marketplace-catalog', region_name=REGION)
dynamodb = boto3.resource('dynamodb', region_name=REGION)
secrets_client = boto3.client('secretsmanager', region_name=REGION)
http = urllib3.PoolManager()

table = dynamodb.Table(os.environ.get('CHANGESET_TABLE', 'liquibase-secure-marketplace-changesets'))

# Container product backing the Liquibase Secure marketplace listing. Not a
# secret; it is visible on the public listing.
PRODUCT_ID = os.environ.get('MARKETPLACE_PRODUCT_ID', 'prod-l2panlvbozc5e')

GITHUB_OWNER = 'liquibase'
GITHUB_REPO = 'liquibase-aws-license-service'
GITHUB_WORKFLOW_TEST = 'run-task-definitions.yml'
GITHUB_WORKFLOW_PROD = 'deploy-extension-to-marketplace.yml'

# Change type the restrict step submits. Must track restrict-aws-mp-listing.sh.
RESTRICTION_CHANGE_TYPE = 'RestrictDeliveryOptions'

# Only versions whose title starts with this are part of the automated pipeline.
# Deliberately a prefix, not a substring: manually published titles such as
# devopstest-5.2.2 and devopstests-5.2.1 *contain* "test-", and a substring test
# would hand them to the automation and eventually release them publicly. Tags
# people create by hand are meant to stay manual.
TEST_TAG_PREFIX = 'test-'

# Only consider change sets started inside this window. Without it, pagination
# would walk the whole listing history (50+ versions) and dispatch validation
# runs for long-since-released tags.
LOOKBACK_DAYS = int(os.environ.get('LOOKBACK_DAYS', '7'))

# Bounds on how much history a single lookup will read, so a pathological
# listing cannot exhaust the 60-second timeout. Whenever a bound is reached it
# is logged rather than passed over in silence.
MAX_PAGES = int(os.environ.get('MAX_PAGES', '10'))
PAGE_SIZE = 20
MAX_DESCRIBES = int(os.environ.get('MAX_DESCRIBES', '40'))


# Per-invocation memo. The marketplace view does not change underneath a single
# run, and every completed test used to re-describe the product entity and
# re-paginate the whole change set list for itself. Three stalled tests meant
# well over a hundred API calls against a 60-second timeout, so the function got
# slower exactly when something was already wrong.
#
# Lambda reuses execution contexts between invocations, so this MUST be cleared
# at the start of each one or a later run reads a stale listing and concludes a
# restriction is missing when it is not.
_invocation_cache = {}


def reset_invocation_cache():
    """Drop everything memoised for the previous invocation."""
    _invocation_cache.clear()


def is_access_denied(error):
    """True if a botocore error is an authorisation failure."""
    code = error.response.get('Error', {}).get('Code', '')
    return 'AccessDenied' in code or code in ('UnauthorizedException', 'AccessDeniedException')


def get_github_token():
    """Retrieve the GitHub PAT from Secrets Manager."""
    try:
        response = secrets_client.get_secret_value(SecretId='eventbridge-workflow-trigger')
        secret = json.loads(response['SecretString'])
        return secret['eventbridge-workflow-trigger']
    except Exception as e:
        print(f"Error retrieving GitHub token: {str(e)}")
        raise


def is_changeset_processed(changeset_id):
    """Return True if this change set has already been handled."""
    try:
        response = table.get_item(Key={'changeSetId': changeset_id})
        return 'Item' in response
    except Exception as e:
        print(f"Error checking DynamoDB: {str(e)}")
        # Fail closed: treating an unknown change set as processed is safer than
        # re-dispatching a workflow we may already have dispatched.
        return True


def mark_changeset_processed(changeset_id, image_tag, status, test_status=None):
    """Record a handled change set.

    Attribute names match the table schema (camelCase): changeSetId (hash key),
    status + createdDate (StatusIndex GSI), expirationTime (TTL attribute).
    """
    try:
        expiration_time = int((datetime.now() + timedelta(days=90)).timestamp())

        item = {
            'changeSetId': changeset_id,
            'imageTag': image_tag,
            'status': status,
            'createdDate': datetime.now().isoformat(),
            'expirationTime': expiration_time,
        }

        if test_status:
            item['testStatus'] = test_status

        table.put_item(Item=item)
        print(f"Marked change set {changeset_id} as processed with status: {status}")
    except Exception as e:
        print(f"Error writing to DynamoDB: {str(e)}")


def update_test_status(changeset_id, test_status):
    """Advance the testStatus of a tracked change set."""
    try:
        table.update_item(
            Key={'changeSetId': changeset_id},
            UpdateExpression='SET testStatus = :status, productionTriggeredAt = :timestamp',
            ExpressionAttributeValues={
                ':status': test_status,
                ':timestamp': datetime.now().isoformat(),
            },
        )
        print(f"Updated change set {changeset_id} test status to: {test_status}")
    except Exception as e:
        print(f"Error updating test status: {str(e)}")


def trigger_github_workflow(workflow, image_tag=None, dry_run=None):
    """Dispatch a GitHub Actions workflow on main."""
    github_token = get_github_token()

    url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/workflows/{workflow}/dispatches'

    headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {github_token}',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json',
    }

    payload = {'ref': 'main', 'inputs': {}}

    if image_tag is not None:
        payload['inputs']['image_tag'] = image_tag
    if dry_run is not None:
        payload['inputs']['dry_run'] = str(dry_run).lower()

    try:
        response = http.request('POST', url, body=json.dumps(payload).encode('utf-8'), headers=headers)

        print(f"GitHub API response: {response.status}")

        if response.status == 204:
            print(f"✅ Successfully triggered workflow: {workflow}")
            return True

        print(f"❌ Failed to trigger workflow: {response.data.decode('utf-8')}")
        return False
    except Exception as e:
        print(f"Error triggering GitHub workflow: {str(e)}")
        return False


def get_completed_tests():
    """Return tracked items whose validation passed but which have not been released."""
    try:
        response = table.scan(
            FilterExpression='testStatus = :status',
            ExpressionAttributeValues={':status': 'completed'},
        )
        return response.get('Items', [])
    except Exception as e:
        print(f"Error scanning for completed tests: {str(e)}")
        return []


def change_details(change):
    """Return a change's detail payload as a dict.

    describe_change_set returns both DetailsDocument (already parsed) and Details
    (a JSON string). Prefer the parsed form and fall back to the string.
    """
    document = change.get('DetailsDocument')
    if isinstance(document, dict):
        return document

    try:
        parsed = json.loads(change.get('Details') or '{}')
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def iter_change_sets(status=None, since=None):
    """Yield change set summaries for our product, newest first.

    Follows NextToken instead of reading a single page. The old code requested
    one or two results and discarded the continuation token, so any change set
    that was not the most recent was invisible.
    """
    filters = [{'Name': 'EntityId', 'ValueList': [PRODUCT_ID]}]
    if status:
        filters.append({'Name': 'Status', 'ValueList': [status]})
    if since:
        filters.append({'Name': 'AfterStartTime', 'ValueList': [since.strftime('%Y-%m-%dT%H:%M:%SZ')]})

    kwargs = {
        'Catalog': CATALOG,
        'FilterList': filters,
        'Sort': {'SortBy': 'StartTime', 'SortOrder': 'DESCENDING'},
        'MaxResults': PAGE_SIZE,
    }

    pages = 0
    while True:
        response = marketplace_client.list_change_sets(**kwargs)

        for summary in response.get('ChangeSetSummaryList', []):
            yield summary

        pages += 1
        token = response.get('NextToken')

        if not token:
            return

        if pages >= MAX_PAGES:
            print(
                f"⚠️  Stopped paginating change sets after {pages} pages "
                f"({pages * PAGE_SIZE} entries); more history exists but was not read."
            )
            return

        kwargs['NextToken'] = token


def get_product_versions():
    """Return the listing's versions, describing the product at most once per run.

    Requires aws-marketplace:DescribeEntity. An authorisation failure here is
    raised rather than swallowed: without it every restriction lookup answers
    "not restricted yet", which is indistinguishable from a healthy pipeline
    waiting and is precisely how the original defect stayed invisible for 30
    hours. Better to fail the invocation and show up in the error metric.
    """
    if 'versions' in _invocation_cache:
        return _invocation_cache['versions']

    try:
        response = marketplace_client.describe_entity(Catalog=CATALOG, EntityId=PRODUCT_ID)
        details = json.loads(response.get('Details') or '{}')
    except ClientError as e:
        if is_access_denied(e):
            print(
                "❌ Denied aws-marketplace:DescribeEntity on "
                f"{PRODUCT_ID}. Restriction matching cannot work without it and "
                "no release will ever be triggered. Failing loudly instead of "
                "waiting silently."
            )
            raise
        print(f"Error describing product entity {PRODUCT_ID}: {str(e)}")
        return []
    except Exception as e:
        print(f"Error describing product entity {PRODUCT_ID}: {str(e)}")
        return []

    versions = details.get('Versions', [])
    _invocation_cache['versions'] = versions
    return versions


def get_delivery_option_ids(version_title):
    """Return the delivery option ids belonging to a listing version title.

    A RestrictDeliveryOptions change set names only the delivery option ids it
    withdrew, so this mapping is the only way to tie a restriction back to the
    version it restricted.
    """
    for version in get_product_versions():
        if version.get('VersionTitle') == version_title:
            return {
                option['Id']
                for option in version.get('DeliveryOptions', [])
                if option.get('Id')
            }

    print(f"Version {version_title} not present on product {PRODUCT_ID}")
    return set()


def get_recent_change_sets():
    """Materialise the change set list once per invocation, newest first."""
    if 'change_sets' not in _invocation_cache:
        _invocation_cache['change_sets'] = list(iter_change_sets())
    return _invocation_cache['change_sets']


def describe_change_set_cached(changeset_id):
    """describe_change_set memoised for the invocation, since lookups overlap."""
    described = _invocation_cache.setdefault('described', {})

    if changeset_id not in described:
        described[changeset_id] = marketplace_client.describe_change_set(
            Catalog=CATALOG, ChangeSetId=changeset_id
        )

    return described[changeset_id]


def find_restriction_changeset(image_tag):
    """Find the change set that restricted a given version title.

    Returns {'ChangeSetId': ..., 'Status': ...} or None. The status is returned
    unfiltered so callers can distinguish "still restricting" from "restricted".
    """
    option_ids = get_delivery_option_ids(image_tag)

    if not option_ids:
        print(f"No delivery options resolved for {image_tag}; cannot match a restriction")
        return None

    described = 0

    for summary in get_recent_change_sets():
        changeset_id = summary.get('ChangeSetId')

        if described >= MAX_DESCRIBES:
            print(
                f"⚠️  Examined {described} change sets without finding a restriction "
                f"for {image_tag}; stopping short of the full history."
            )
            return None

        try:
            detail = describe_change_set_cached(changeset_id)
        except Exception as e:
            print(f"Error checking change set {changeset_id}: {str(e)}")
            continue

        described += 1

        for change in detail.get('ChangeSet', []):
            if change.get('ChangeType') != RESTRICTION_CHANGE_TYPE:
                continue

            restricted_ids = set(change_details(change).get('DeliveryOptionIds', []))

            if restricted_ids & option_ids:
                return {'ChangeSetId': changeset_id, 'Status': summary.get('Status')}

    return None


def extract_version_title(detail_response):
    """Pull the version title out of a change set's detail payload."""
    for change in detail_response.get('ChangeSet', []):
        details = change_details(change)
        version = details.get('Version')
        if isinstance(version, dict) and version.get('VersionTitle'):
            return version['VersionTitle']
    return None


def process_new_versions():
    """PART 1: dispatch validation for newly published test versions."""
    processed = 0
    triggered = 0
    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)

    print(f"=== Checking for new SUCCEEDED change sets since {since.date()} ===")

    for summary in iter_change_sets(status='SUCCEEDED', since=since):
        changeset_id = summary.get('ChangeSetId')

        if is_changeset_processed(changeset_id):
            continue

        print(f"Processing new SUCCEEDED change set: {changeset_id}")

        try:
            detail = describe_change_set_cached(changeset_id)
        except Exception as e:
            print(f"Error describing change set {changeset_id}: {str(e)}")
            continue

        image_tag = extract_version_title(detail)

        if not image_tag:
            mark_changeset_processed(changeset_id, 'unknown', 'no_image_tag')
            continue

        print(f"Found image tag: {image_tag}")

        if not image_tag.startswith(TEST_TAG_PREFIX):
            print(f"Skipping image outside the automated pipeline: {image_tag}")
            mark_changeset_processed(changeset_id, image_tag, 'skipped_not_test')
            processed += 1
            continue

        print(f"Checking if {image_tag} is already restricted...")
        restriction = find_restriction_changeset(image_tag)

        if restriction:
            print(
                f"⏭️  Image {image_tag} already restricted "
                f"(ChangeSet: {restriction['ChangeSetId']}, Status: {restriction['Status']}); "
                f"it has already been validated"
            )
            mark_changeset_processed(changeset_id, image_tag, 'skipped_already_restricted')
            processed += 1
            continue

        print(f"✅ No restriction found for {image_tag} - proceeding with test workflow")

        if trigger_github_workflow(GITHUB_WORKFLOW_TEST, image_tag=image_tag):
            mark_changeset_processed(changeset_id, image_tag, 'test_triggered', test_status='testing')
            triggered += 1
        else:
            mark_changeset_processed(changeset_id, image_tag, 'failed_trigger')

        processed += 1

    return processed, triggered


def release_validated_versions():
    """PART 2: dispatch production release once a validated image is restricted."""
    triggered = 0

    print("\n=== Checking for completed tests ready for production release ===")
    completed_tests = get_completed_tests()
    print(f"Found {len(completed_tests)} completed tests")

    for item in completed_tests:
        changeset_id = item['changeSetId']
        image_tag = item['imageTag']

        print(f"\nChecking test image: {image_tag}")

        restriction = find_restriction_changeset(image_tag)

        if not restriction:
            print(f"⏳ No restriction change set found yet for {image_tag}. Will check again next cycle.")
            continue

        print(f"Found restriction change set {restriction['ChangeSetId']} with status: {restriction['Status']}")

        if restriction['Status'] != 'SUCCEEDED':
            print(f"⏳ Restriction still in progress (Status: {restriction['Status']}). Waiting...")
            continue

        print(f"✅ Test image {image_tag} is successfully restricted!")

        version = image_tag[len(TEST_TAG_PREFIX):]
        print(f"🚀 Triggering production release for version {version}...")

        # Empty image_tag means the deploy workflow uses the Dockerfile version.
        if trigger_github_workflow(GITHUB_WORKFLOW_PROD, image_tag='', dry_run=False):
            update_test_status(changeset_id, 'production_released')
            triggered += 1
            print(f"✅ Successfully triggered production release for version {version}")
        else:
            print(f"❌ Failed to trigger production release for version {version}")

    return triggered


def lambda_handler(event, context):
    print("Starting marketplace change set polling...")

    # Execution contexts are reused between invocations. Without this the run
    # would answer from the previous run's view of the listing.
    reset_invocation_cache()

    try:
        processed_count, triggered_test_count = process_new_versions()
        triggered_prod_count = release_validated_versions()

        result_message = (
            f"Polling complete. Processed: {processed_count}, "
            f"Triggered tests: {triggered_test_count}, "
            f"Triggered production:{triggered_prod_count}"
        )
        print(result_message)

        return {
            'statusCode': 200,
            'body': json.dumps(
                {
                    'message': result_message,
                    'processed': processed_count,
                    'triggered_tests': triggered_test_count,
                    'triggered_production': triggered_prod_count,
                }
            ),
        }
    except Exception as e:
        print(f"Fatal error in lambda_handler: {str(e)}")
        raise
