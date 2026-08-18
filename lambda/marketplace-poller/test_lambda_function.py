"""Tests for the marketplace polling Lambda.

The payloads below are copied from real change sets on the Liquibase Secure
listing, so a regression that reintroduces the original bug fails here rather
than stalling a release for a day and a half.

Reference change sets (product prod-l2panlvbozc5e):
  bf4hk6bw552h3yw9nbvtmte87  RestrictDeliveryOptions  restricted test-5.2.2
  5yb1p6ojdo2aet2sse0jjfby1  AddDeliveryOptions       published test-5.2.2
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

import lambda_function as lf  # noqa: E402

TEST_TAG = 'test-5.2.2'
OPTION_ID = '676c131d-495a-49ba-93c4-fa124193205c'
OTHER_OPTION_ID = 'be22dfae-0000-0000-0000-000000000000'

# describe_entity payload, trimmed to the fields the code reads.
ENTITY = {
    'Details': (
        '{"Versions": ['
        '{"VersionTitle": "5.2.1", "DeliveryOptions": [{"Id": "' + OTHER_OPTION_ID + '"}]},'
        '{"VersionTitle": "test-5.2.2", "DeliveryOptions": [{"Id": "' + OPTION_ID + '"}]}'
        ']}'
    )
}

# The real restriction change set. Note there is no VersionTitle anywhere in it:
# that absence is the whole reason the original title comparison could not work.
RESTRICTION_DETAIL = {
    'ChangeSetId': 'bf4hk6bw552h3yw9nbvtmte87',
    'Status': 'SUCCEEDED',
    'ChangeSet': [
        {
            'ChangeType': 'RestrictDeliveryOptions',
            'Entity': {'Type': 'ContainerProduct@1.0', 'Identifier': 'prod-l2panlvbozc5e'},
            'Details': '{"DeliveryOptionIds":["' + OPTION_ID + '"]}',
            'DetailsDocument': {'DeliveryOptionIds': [OPTION_ID]},
            'ErrorDetailList': [],
        }
    ],
}

# The publish change set, which does carry a version title.
ADD_DETAIL = {
    'ChangeSetId': '5yb1p6ojdo2aet2sse0jjfby1',
    'Status': 'SUCCEEDED',
    'ChangeSet': [
        {
            'ChangeType': 'AddDeliveryOptions',
            'Entity': {'Type': 'ContainerProduct@1.0', 'Identifier': 'prod-l2panlvbozc5e'},
            'DetailsDocument': {
                'Version': {'VersionTitle': TEST_TAG},
                'DeliveryOptions': [{'DeliveryOptionTitle': 'Liquibase Secure Docker Image'}],
            },
            'ErrorDetailList': [],
        }
    ],
}


def summary(changeset_id, status='SUCCEEDED'):
    return {'ChangeSetId': changeset_id, 'Status': status}


class FindRestrictionChangesetTest(unittest.TestCase):
    """The lookup that stalled the 5.2.2 release."""

    def setUp(self):
        self.client = MagicMock()
        self.client.describe_entity.return_value = ENTITY
        patcher = patch.object(lf, 'marketplace_client', self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_matches_restrict_delivery_options_by_option_id(self):
        """The regression test: the real RestrictDeliveryOptions payload is found."""
        self.client.list_change_sets.return_value = {
            'ChangeSetSummaryList': [summary('bf4hk6bw552h3yw9nbvtmte87')]
        }
        self.client.describe_change_set.return_value = RESTRICTION_DETAIL

        result = lf.find_restriction_changeset(TEST_TAG)

        self.assertIsNotNone(result, "the restriction for test-5.2.2 must be found")
        self.assertEqual(result['ChangeSetId'], 'bf4hk6bw552h3yw9nbvtmte87')
        self.assertEqual(result['Status'], 'SUCCEEDED')

    def test_reports_in_progress_restriction_status_unfiltered(self):
        """A restriction still applying is returned so the caller can wait rather than release."""
        self.client.list_change_sets.return_value = {
            'ChangeSetSummaryList': [summary('bf4hk6bw552h3yw9nbvtmte87', 'APPLYING')]
        }
        self.client.describe_change_set.return_value = dict(RESTRICTION_DETAIL, Status='APPLYING')

        result = lf.find_restriction_changeset(TEST_TAG)

        self.assertEqual(result['Status'], 'APPLYING')

    def test_ignores_restriction_of_a_different_version(self):
        """A restriction whose option ids do not overlap is not ours."""
        self.client.list_change_sets.return_value = {
            'ChangeSetSummaryList': [summary('someotherchangeset')]
        }
        self.client.describe_change_set.return_value = {
            'ChangeSet': [
                {
                    'ChangeType': 'RestrictDeliveryOptions',
                    'DetailsDocument': {'DeliveryOptionIds': [OTHER_OPTION_ID]},
                }
            ]
        }

        self.assertIsNone(lf.find_restriction_changeset(TEST_TAG))

    def test_ignores_add_delivery_options(self):
        """Publishing a version is not restricting it."""
        self.client.list_change_sets.return_value = {
            'ChangeSetSummaryList': [summary('5yb1p6ojdo2aet2sse0jjfby1')]
        }
        self.client.describe_change_set.return_value = ADD_DETAIL

        self.assertIsNone(lf.find_restriction_changeset(TEST_TAG))

    def test_finds_restriction_that_is_not_the_newest_change_set(self):
        """Guards the MaxResults=1 bug: the restriction is rarely the latest change set."""
        self.client.list_change_sets.return_value = {
            'ChangeSetSummaryList': [
                summary('newer-unrelated-1'),
                summary('newer-unrelated-2'),
                summary('bf4hk6bw552h3yw9nbvtmte87'),
            ]
        }

        unrelated = {'ChangeSet': [{'ChangeType': 'UpdatePricingTerms', 'DetailsDocument': {}}]}
        self.client.describe_change_set.side_effect = lambda **kw: (
            RESTRICTION_DETAIL if kw['ChangeSetId'] == 'bf4hk6bw552h3yw9nbvtmte87' else unrelated
        )

        result = lf.find_restriction_changeset(TEST_TAG)

        self.assertIsNotNone(result, "a restriction behind newer change sets must still be found")
        self.assertEqual(result['ChangeSetId'], 'bf4hk6bw552h3yw9nbvtmte87')

    def test_returns_none_when_version_absent_from_listing(self):
        """An unknown version title yields no delivery options, so no restriction."""
        self.client.list_change_sets.return_value = {'ChangeSetSummaryList': []}

        self.assertIsNone(lf.find_restriction_changeset('test-9.9.9'))
        self.client.describe_change_set.assert_not_called()

    def test_survives_describe_entity_failure(self):
        """A DescribeEntity denial must not raise; the caller keeps waiting instead."""
        self.client.describe_entity.side_effect = Exception('AccessDeniedException')

        self.assertIsNone(lf.find_restriction_changeset(TEST_TAG))


class PaginationTest(unittest.TestCase):
    """The continuation token used to be requested and then discarded."""

    def setUp(self):
        self.client = MagicMock()
        self.client.describe_entity.return_value = ENTITY
        patcher = patch.object(lf, 'marketplace_client', self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_follows_next_token(self):
        self.client.list_change_sets.side_effect = [
            {'ChangeSetSummaryList': [summary('page1')], 'NextToken': 'tok'},
            {'ChangeSetSummaryList': [summary('page2')]},
        ]

        ids = [s['ChangeSetId'] for s in lf.iter_change_sets()]

        self.assertEqual(ids, ['page1', 'page2'])

    def test_stops_at_max_pages(self):
        """A listing that never stops paginating cannot hang the invocation."""
        self.client.list_change_sets.return_value = {
            'ChangeSetSummaryList': [summary('x')],
            'NextToken': 'always-more',
        }

        collected = list(lf.iter_change_sets())

        self.assertEqual(len(collected), lf.MAX_PAGES)

    def test_filters_to_our_product(self):
        self.client.list_change_sets.return_value = {'ChangeSetSummaryList': []}

        list(lf.iter_change_sets())

        filters = self.client.list_change_sets.call_args.kwargs['FilterList']
        entity_filter = next(f for f in filters if f['Name'] == 'EntityId')
        self.assertEqual(entity_filter['ValueList'], [lf.PRODUCT_ID])


class ChangeDetailsTest(unittest.TestCase):
    """Both payload shapes AWS returns must be readable."""

    def test_prefers_parsed_details_document(self):
        change = {'DetailsDocument': {'DeliveryOptionIds': ['a']}, 'Details': '{"DeliveryOptionIds":["b"]}'}
        self.assertEqual(lf.change_details(change)['DeliveryOptionIds'], ['a'])

    def test_falls_back_to_details_string(self):
        change = {'Details': '{"DeliveryOptionIds":["b"]}'}
        self.assertEqual(lf.change_details(change)['DeliveryOptionIds'], ['b'])

    def test_tolerates_malformed_and_missing_details(self):
        self.assertEqual(lf.change_details({'Details': 'not json'}), {})
        self.assertEqual(lf.change_details({}), {})
        self.assertEqual(lf.change_details({'Details': '"a string"'}), {})


class NewVersionScanTest(unittest.TestCase):
    """PART 1 must not reach back over the whole listing history."""

    def setUp(self):
        self.client = MagicMock()
        self.client.describe_entity.return_value = ENTITY
        patcher = patch.object(lf, 'marketplace_client', self.client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_applies_lookback_window(self):
        """Without this bound, old released tags would be re-validated."""
        self.client.list_change_sets.return_value = {'ChangeSetSummaryList': []}

        lf.process_new_versions()

        filters = self.client.list_change_sets.call_args.kwargs['FilterList']
        names = {f['Name'] for f in filters}
        self.assertIn('AfterStartTime', names)
        self.assertIn('Status', names)

    @patch.object(lf, 'mark_changeset_processed')
    @patch.object(lf, 'trigger_github_workflow', return_value=True)
    @patch.object(lf, 'is_changeset_processed', return_value=False)
    def test_skips_already_restricted_image(self, _processed, trigger, mark):
        """The duplicate-validation guard was dead while the lookup was broken."""
        self.client.list_change_sets.return_value = {
            'ChangeSetSummaryList': [summary('5yb1p6ojdo2aet2sse0jjfby1')]
        }
        self.client.describe_change_set.side_effect = lambda **kw: (
            ADD_DETAIL if kw['ChangeSetId'] == '5yb1p6ojdo2aet2sse0jjfby1' else RESTRICTION_DETAIL
        )

        with patch.object(lf, 'find_restriction_changeset', return_value={'ChangeSetId': 'r', 'Status': 'SUCCEEDED'}):
            lf.process_new_versions()

        trigger.assert_not_called()
        self.assertEqual(mark.call_args.args[2], 'skipped_already_restricted')

    @patch.object(lf, 'mark_changeset_processed')
    @patch.object(lf, 'trigger_github_workflow', return_value=True)
    @patch.object(lf, 'is_changeset_processed', return_value=False)
    def test_dispatches_validation_for_new_test_version(self, _processed, trigger, _mark):
        self.client.list_change_sets.return_value = {
            'ChangeSetSummaryList': [summary('5yb1p6ojdo2aet2sse0jjfby1')]
        }
        self.client.describe_change_set.return_value = ADD_DETAIL

        with patch.object(lf, 'find_restriction_changeset', return_value=None):
            processed, triggered = lf.process_new_versions()

        self.assertEqual((processed, triggered), (1, 1))
        trigger.assert_called_once_with(lf.GITHUB_WORKFLOW_TEST, image_tag=TEST_TAG)

    @patch.object(lf, 'mark_changeset_processed')
    @patch.object(lf, 'trigger_github_workflow')
    @patch.object(lf, 'is_changeset_processed', return_value=False)
    def test_ignores_non_test_versions(self, _processed, trigger, mark):
        """A public release must never trigger the validation workflow."""
        self.client.list_change_sets.return_value = {'ChangeSetSummaryList': [summary('prod-cs')]}
        self.client.describe_change_set.return_value = {
            'ChangeSet': [{'DetailsDocument': {'Version': {'VersionTitle': '5.2.2'}}}]
        }

        lf.process_new_versions()

        trigger.assert_not_called()
        self.assertEqual(mark.call_args.args[2], 'skipped_not_test')

    @patch.object(lf, 'mark_changeset_processed')
    @patch.object(lf, 'trigger_github_workflow')
    @patch.object(lf, 'is_changeset_processed', return_value=False)
    def test_ignores_hand_published_titles_containing_test(self, _processed, trigger, mark):
        """devopstest-* and friends contain 'test-' but must stay manual.

        A substring check would adopt these into the pipeline and eventually
        publish them, which is why the selection is anchored to the prefix. The
        listing currently holds devopstest-5.2.0, devopstest-5.2.1,
        devopstests-5.2.1, devopstest1-5.2.1 and devopstest-5.2.2.
        """
        for title in ('devopstest-5.2.2', 'devopstests-5.2.1', 'devopstest1-5.2.1', 'qa-5.2.2'):
            with self.subTest(title=title):
                trigger.reset_mock()
                mark.reset_mock()
                self.client.list_change_sets.return_value = {
                    'ChangeSetSummaryList': [summary(f'cs-{title}')]
                }
                self.client.describe_change_set.return_value = {
                    'ChangeSet': [{'DetailsDocument': {'Version': {'VersionTitle': title}}}]
                }

                lf.process_new_versions()

                trigger.assert_not_called()
                self.assertEqual(mark.call_args.args[2], 'skipped_not_test')

    @patch.object(lf, 'mark_changeset_processed')
    @patch.object(lf, 'trigger_github_workflow', return_value=True)
    @patch.object(lf, 'is_changeset_processed', return_value=False)
    def test_accepts_run_suffixed_test_tag(self, _processed, trigger, _mark):
        """The auto-trigger now appends a run number so attempts are retryable."""
        self.client.list_change_sets.return_value = {'ChangeSetSummaryList': [summary('cs-suffixed')]}
        self.client.describe_change_set.return_value = {
            'ChangeSet': [{'DetailsDocument': {'Version': {'VersionTitle': 'test-5.2.2-482'}}}]
        }

        with patch.object(lf, 'find_restriction_changeset', return_value=None):
            lf.process_new_versions()

        trigger.assert_called_once_with(lf.GITHUB_WORKFLOW_TEST, image_tag='test-5.2.2-482')


class ProductionReleaseTest(unittest.TestCase):
    """PART 2: the leg that never once fired in production."""

    @patch.object(lf, 'update_test_status')
    @patch.object(lf, 'trigger_github_workflow', return_value=True)
    @patch.object(lf, 'get_completed_tests')
    def test_releases_once_restriction_succeeded(self, completed, trigger, update):
        completed.return_value = [{'changeSetId': 'cs1', 'imageTag': TEST_TAG}]

        with patch.object(lf, 'find_restriction_changeset', return_value={'ChangeSetId': 'r', 'Status': 'SUCCEEDED'}):
            triggered = lf.release_validated_versions()

        self.assertEqual(triggered, 1)
        trigger.assert_called_once_with(lf.GITHUB_WORKFLOW_PROD, image_tag='', dry_run=False)
        update.assert_called_once_with('cs1', 'production_released')

    @patch.object(lf, 'trigger_github_workflow')
    @patch.object(lf, 'get_completed_tests')
    def test_waits_while_restriction_still_applying(self, completed, trigger):
        completed.return_value = [{'changeSetId': 'cs1', 'imageTag': TEST_TAG}]

        with patch.object(lf, 'find_restriction_changeset', return_value={'ChangeSetId': 'r', 'Status': 'APPLYING'}):
            self.assertEqual(lf.release_validated_versions(), 0)

        trigger.assert_not_called()

    @patch.object(lf, 'trigger_github_workflow')
    @patch.object(lf, 'get_completed_tests')
    def test_does_not_release_without_a_restriction(self, completed, trigger):
        """Releasing while the test image is still public would be wrong."""
        completed.return_value = [{'changeSetId': 'cs1', 'imageTag': TEST_TAG}]

        with patch.object(lf, 'find_restriction_changeset', return_value=None):
            self.assertEqual(lf.release_validated_versions(), 0)

        trigger.assert_not_called()


class ContractWithRestrictScriptTest(unittest.TestCase):
    """The mismatch that caused the incident, asserted directly."""

    def test_restriction_change_type_matches_the_shell_script(self):
        script = os.path.join(
            os.path.dirname(__file__), '..', '..', '.github', 'utils', 'restrict-aws-mp-listing.sh'
        )

        with open(script) as handle:
            body = handle.read()

        self.assertIn(
            f'"ChangeType": "{lf.RESTRICTION_CHANGE_TYPE}"',
            body,
            "the change type this Lambda matches must be the one restrict-aws-mp-listing.sh submits",
        )


if __name__ == '__main__':
    unittest.main()
