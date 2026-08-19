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

import yaml
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
        lf.reset_invocation_cache()
        self.addCleanup(lf.reset_invocation_cache)

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

    def test_survives_non_auth_describe_entity_failure(self):
        """A transient DescribeEntity failure degrades to "keep waiting".

        Authorisation failures deliberately do not: see AccessDeniedTest.
        """
        self.client.describe_entity.side_effect = Exception('boom')

        self.assertIsNone(lf.find_restriction_changeset(TEST_TAG))


class PaginationTest(unittest.TestCase):
    """The continuation token used to be requested and then discarded."""

    def setUp(self):
        self.client = MagicMock()
        self.client.describe_entity.return_value = ENTITY
        patcher = patch.object(lf, 'marketplace_client', self.client)
        patcher.start()
        self.addCleanup(patcher.stop)
        lf.reset_invocation_cache()
        self.addCleanup(lf.reset_invocation_cache)

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
        lf.reset_invocation_cache()
        self.addCleanup(lf.reset_invocation_cache)

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
        # The bare version, never the test tag: the production title is public
        # and permanent, and the workflow compares it against the Dockerfile to
        # refuse publishing something nobody validated.
        #
        # It travels as validated_version, not image_tag: image_tag is the ECR
        # tag to build, which is what the dry-run job and the input's own
        # description mean by it.
        trigger.assert_called_once_with(
            lf.GITHUB_WORKFLOW_PROD, validated_version='5.2.2', dry_run=False
        )
        # Dispatched, not released. A 204 only says GitHub accepted the run.
        update.assert_called_once_with('cs1', 'production_dispatched')

    @patch.object(lf, 'update_test_status')
    @patch.object(lf, 'trigger_github_workflow', return_value=True)
    @patch.object(lf, 'get_completed_tests')
    def test_strips_the_run_suffix_before_releasing(self, completed, trigger, _update):
        """A run-suffixed tag must not become the public version title."""
        completed.return_value = [{'changeSetId': 'cs1', 'imageTag': 'test-5.2.2-482.1'}]

        with patch.object(lf, 'find_restriction_changeset', return_value={'ChangeSetId': 'r', 'Status': 'SUCCEEDED'}):
            lf.release_validated_versions()

        trigger.assert_called_once_with(
            lf.GITHUB_WORKFLOW_PROD, validated_version='5.2.2', dry_run=False
        )

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


    @patch.object(lf, 'update_test_status')
    @patch.object(lf, 'trigger_github_workflow')
    @patch.object(lf, 'get_completed_tests')
    def test_does_not_release_on_a_terminal_failed_restriction(self, completed, trigger, update):
        """FAILED is terminal: waiting on it is an indefinite silent stall."""
        completed.return_value = [{'changeSetId': 'cs1', 'imageTag': TEST_TAG}]

        with patch.object(lf, 'find_restriction_changeset', return_value={'ChangeSetId': 'r', 'Status': 'FAILED'}):
            self.assertEqual(lf.release_validated_versions(), 0)

        trigger.assert_not_called()
        # The row stays at completed so the watchdog still counts it as stalled.
        update.assert_not_called()

    @patch.object(lf, 'update_test_status')
    @patch.object(lf, 'trigger_github_workflow')
    @patch.object(lf, 'get_completed_tests')
    def test_does_not_release_on_a_cancelled_restriction(self, completed, trigger, update):
        completed.return_value = [{'changeSetId': 'cs1', 'imageTag': TEST_TAG}]

        with patch.object(lf, 'find_restriction_changeset', return_value={'ChangeSetId': 'r', 'Status': 'CANCELLED'}):
            self.assertEqual(lf.release_validated_versions(), 0)

        trigger.assert_not_called()
        update.assert_not_called()


class RestrictionPreferenceTest(unittest.TestCase):
    """A newer duplicate submission must not bury an older successful one."""

    def setUp(self):
        lf.reset_invocation_cache()

    def _listing(self):
        return [{'VersionTitle': TEST_TAG, 'DeliveryOptions': [{'Id': 'opt-1'}]}]

    def test_succeeded_wins_over_a_newer_failed_duplicate(self):
        """Re-running validation resubmits the restriction; the marketplace
        rejects the duplicate, and that FAILED change set is newer."""
        change_sets = [
            {'ChangeSetId': 'newer-failed', 'Status': 'FAILED'},
            {'ChangeSetId': 'older-succeeded', 'Status': 'SUCCEEDED'},
        ]
        described = {
            cs['ChangeSetId']: {
                'ChangeSet': [
                    {
                        'ChangeType': 'RestrictDeliveryOptions',
                        'DetailsDocument': {'DeliveryOptionIds': ['opt-1']},
                    }
                ]
            }
            for cs in change_sets
        }

        with patch.object(lf, 'get_product_versions', return_value=self._listing()), \
             patch.object(lf, 'get_recent_change_sets', return_value=change_sets), \
             patch.object(lf, 'describe_change_set_cached', side_effect=lambda i: described[i]):
            result = lf.find_restriction_changeset(TEST_TAG)

        self.assertEqual(result, {'ChangeSetId': 'older-succeeded', 'Status': 'SUCCEEDED'})

    def test_reports_the_newest_when_none_succeeded(self):
        """With no success anywhere, the caller must still see a terminal status."""
        change_sets = [{'ChangeSetId': 'only-failed', 'Status': 'FAILED'}]
        described = {
            'only-failed': {
                'ChangeSet': [
                    {
                        'ChangeType': 'RestrictDeliveryOptions',
                        'DetailsDocument': {'DeliveryOptionIds': ['opt-1']},
                    }
                ]
            }
        }

        with patch.object(lf, 'get_product_versions', return_value=self._listing()), \
             patch.object(lf, 'get_recent_change_sets', return_value=change_sets), \
             patch.object(lf, 'describe_change_set_cached', side_effect=lambda i: described[i]):
            result = lf.find_restriction_changeset(TEST_TAG)

        self.assertEqual(result, {'ChangeSetId': 'only-failed', 'Status': 'FAILED'})


class ConfirmDispatchedReleaseTest(unittest.TestCase):
    """A 204 is an accepted dispatch, not a published version."""

    @patch.object(lf, 'update_test_status')
    @patch.object(lf, 'get_tests_by_status')
    def test_promotes_once_the_version_is_public(self, by_status, update):
        by_status.return_value = [{'changeSetId': 'cs1', 'imageTag': 'test-5.2.2-482.1'}]
        listing = [{'VersionTitle': '5.2.2', 'DeliveryOptions': [{'Visibility': 'Public'}]}]

        with patch.object(lf, 'get_product_versions', return_value=listing):
            self.assertEqual(lf.confirm_dispatched_releases(), 1)

        # The literal is the contract with release_validated_versions. If either
        # side changes it the loop silently stops promoting rows, and the tests
        # would still pass without this assertion.
        by_status.assert_called_once_with('production_dispatched')
        update.assert_called_once_with('cs1', 'production_released')

    @patch.object(lf, 'update_test_status')
    @patch.object(lf, 'get_tests_by_status')
    def test_leaves_it_dispatched_when_the_release_never_landed(self, by_status, update):
        """The production run can fail after GitHub accepts the dispatch."""
        by_status.return_value = [{'changeSetId': 'cs1', 'imageTag': 'test-5.2.2-482.1'}]
        listing = [{'VersionTitle': '5.2.1', 'DeliveryOptions': [{'Visibility': 'Public'}]}]

        with patch.object(lf, 'get_product_versions', return_value=listing):
            self.assertEqual(lf.confirm_dispatched_releases(), 0)

        update.assert_not_called()

    @patch.object(lf, 'update_test_status')
    @patch.object(lf, 'get_tests_by_status')
    def test_a_restricted_version_does_not_count_as_released(self, by_status, update):
        by_status.return_value = [{'changeSetId': 'cs1', 'imageTag': 'test-5.2.2-482.1'}]
        listing = [{'VersionTitle': '5.2.2', 'DeliveryOptions': [{'Visibility': 'Restricted'}]}]

        with patch.object(lf, 'get_product_versions', return_value=listing):
            self.assertEqual(lf.confirm_dispatched_releases(), 0)

        update.assert_not_called()


    @patch.object(lf, 'update_test_status')
    @patch.object(lf, 'get_tests_by_status')
    def test_accepts_a_version_level_visibility(self, by_status, update):
        """Some entity shapes carry Visibility on the version, not the option."""
        by_status.return_value = [{'changeSetId': 'cs1', 'imageTag': 'test-5.2.2-482.1'}]
        listing = [{'VersionTitle': '5.2.2', 'Visibility': 'Public', 'DeliveryOptions': [{'Id': 'x'}]}]

        with patch.object(lf, 'get_product_versions', return_value=listing):
            self.assertEqual(lf.confirm_dispatched_releases(), 1)

        update.assert_called_once_with('cs1', 'production_released')

    @patch.object(lf, 'update_test_status')
    @patch.object(lf, 'get_tests_by_status')
    def test_fails_loudly_when_no_version_reports_visibility(self, by_status, update):
        """If the field is gone, every release would sit dispatched forever.

        That is the indefinite silent wait this whole ticket is about, so the
        shape is asserted rather than assumed.
        """
        by_status.return_value = [{'changeSetId': 'cs1', 'imageTag': 'test-5.2.2-482.1'}]
        listing = [{'VersionTitle': '5.2.2', 'DeliveryOptions': [{'Id': 'opt-1'}]}]

        with patch.object(lf, 'get_product_versions', return_value=listing):
            self.assertEqual(lf.confirm_dispatched_releases(), 0)

        update.assert_not_called()

    @patch.object(lf, 'update_test_status')
    @patch.object(lf, 'get_tests_by_status')
    def test_never_confirms_from_product_level_visibility(self, by_status, update):
        """The product is Public permanently; confirming on it would promote
        every dispatched row and restore the false 'released' state."""
        by_status.return_value = [{'changeSetId': 'cs1', 'imageTag': 'test-5.2.2-482.1'}]
        # 5.2.2 is present but Restricted; only an older version is Public.
        listing = [
            {'VersionTitle': '5.2.2', 'DeliveryOptions': [{'Visibility': 'Restricted'}]},
            {'VersionTitle': '5.2.1', 'DeliveryOptions': [{'Visibility': 'Public'}]},
        ]

        with patch.object(lf, 'get_product_versions', return_value=listing):
            self.assertEqual(lf.confirm_dispatched_releases(), 0)

        update.assert_not_called()


class InvocationCacheTest(unittest.TestCase):
    """Each lookup used to refetch everything, risking the 60s timeout."""

    def setUp(self):
        self.client = MagicMock()
        self.client.describe_entity.return_value = ENTITY
        self.client.list_change_sets.return_value = {
            'ChangeSetSummaryList': [summary('bf4hk6bw552h3yw9nbvtmte87')]
        }
        self.client.describe_change_set.return_value = RESTRICTION_DETAIL
        patcher = patch.object(lf, 'marketplace_client', self.client)
        patcher.start()
        self.addCleanup(patcher.stop)
        lf.reset_invocation_cache()
        self.addCleanup(lf.reset_invocation_cache)

    def test_repeated_lookups_hit_the_api_once(self):
        for _ in range(5):
            lf.find_restriction_changeset(TEST_TAG)

        self.assertEqual(self.client.describe_entity.call_count, 1)
        self.assertEqual(self.client.list_change_sets.call_count, 1)
        self.assertEqual(self.client.describe_change_set.call_count, 1)

    def test_cache_does_not_survive_into_the_next_invocation(self):
        """Lambda reuses containers; a stale listing would report a missing restriction."""
        lf.find_restriction_changeset(TEST_TAG)
        self.assertEqual(self.client.describe_entity.call_count, 1)

        with patch.object(lf, 'process_new_versions', return_value=(0, 0)), \
             patch.object(lf, 'release_validated_versions', return_value=0):
            lf.lambda_handler({}, None)

        lf.find_restriction_changeset(TEST_TAG)
        self.assertEqual(
            self.client.describe_entity.call_count, 2,
            "lambda_handler must clear the cache so a new invocation re-reads the listing",
        )


class AccessDeniedTest(unittest.TestCase):
    """An IAM gap must not look like a healthy pipeline waiting."""

    def setUp(self):
        self.client = MagicMock()
        patcher = patch.object(lf, 'marketplace_client', self.client)
        patcher.start()
        self.addCleanup(patcher.stop)
        lf.reset_invocation_cache()
        self.addCleanup(lf.reset_invocation_cache)

    def test_describe_entity_denial_raises_rather_than_waiting_quietly(self):
        from botocore.exceptions import ClientError

        self.client.describe_entity.side_effect = ClientError(
            {'Error': {'Code': 'AccessDeniedException', 'Message': 'nope'}}, 'DescribeEntity'
        )

        with self.assertRaises(ClientError):
            lf.find_restriction_changeset(TEST_TAG)

    def test_other_client_errors_still_degrade_gracefully(self):
        from botocore.exceptions import ClientError

        self.client.describe_entity.side_effect = ClientError(
            {'Error': {'Code': 'ThrottlingException', 'Message': 'slow down'}}, 'DescribeEntity'
        )

        self.assertIsNone(lf.find_restriction_changeset(TEST_TAG))


class ReleasedVersionTest(unittest.TestCase):
    """Turning a test tag back into the version to publish."""

    def test_strips_run_number_and_attempt(self):
        self.assertEqual(lf.released_version('test-5.2.2-482.1'), '5.2.2')

    def test_strips_bare_run_number(self):
        self.assertEqual(lf.released_version('test-5.2.2-482'), '5.2.2')

    def test_tolerates_tags_predating_the_suffix(self):
        self.assertEqual(lf.released_version('test-5.2.2'), '5.2.2')

    def test_keeps_a_prerelease_qualifier(self):
        """Only a trailing run suffix goes; the version's own hyphen stays."""
        self.assertEqual(lf.released_version('test-5.2.2-beta-482.1'), '5.2.2-beta')
        self.assertEqual(lf.released_version('test-5.2.2-rc1-9.2'), '5.2.2-rc1')


class CompletedTestsPaginationTest(unittest.TestCase):
    """Scan applies its filter after the 1 MB page limit, so pages can come back
    empty while later ones still hold completed tests."""

    def test_follows_last_evaluated_key(self):
        table = MagicMock()
        table.scan.side_effect = [
            {'Items': [{'changeSetId': 'a'}], 'LastEvaluatedKey': {'changeSetId': 'a'}},
            {'Items': [], 'LastEvaluatedKey': {'changeSetId': 'b'}},
            {'Items': [{'changeSetId': 'c'}]},
        ]

        with patch.object(lf, 'table', table):
            items = lf.get_completed_tests()

        self.assertEqual([i['changeSetId'] for i in items], ['a', 'c'])
        self.assertEqual(table.scan.call_count, 3)

    def test_returns_partial_results_on_failure(self):
        table = MagicMock()
        table.scan.side_effect = [
            {'Items': [{'changeSetId': 'a'}], 'LastEvaluatedKey': {'changeSetId': 'a'}},
            Exception('throttled'),
        ]

        with patch.object(lf, 'table', table):
            items = lf.get_completed_tests()

        self.assertEqual([i['changeSetId'] for i in items], ['a'])


class ContractWithRepoTest(unittest.TestCase):
    """The couplings that are invisible at review time, asserted directly."""

    @staticmethod
    def repo_file(*parts):
        return os.path.join(os.path.dirname(__file__), '..', '..', *parts)

    def test_restriction_change_type_matches_the_shell_script(self):
        with open(self.repo_file('.github', 'utils', 'restrict-aws-mp-listing.sh')) as handle:
            body = handle.read()

        self.assertIn(
            f'"ChangeType": "{lf.RESTRICTION_CHANGE_TYPE}"',
            body,
            "the change type this Lambda matches must be the one restrict-aws-mp-listing.sh submits",
        )

    def test_auto_trigger_still_generates_a_selectable_tag(self):
        """If the generated tag stops matching TEST_TAG_PREFIX, the poller silently
        ignores every future release. Nothing else in CI would notice."""
        with open(self.repo_file('.github', 'workflows', 'auto-trigger-marketplace-deployment.yml')) as handle:
            body = handle.read()

        self.assertIn(
            f'TEST_VERSION="{lf.TEST_TAG_PREFIX}',
            body,
            "auto-trigger must generate a tag starting with the prefix the poller selects on",
        )

    def test_deploy_workflow_accepts_the_input_the_poller_sends(self):
        """The poller sends validated_version. A workflow_dispatch naming an
        input the workflow does not declare is rejected outright, so the whole
        production leg would go back to never firing, and it would fail exactly
        where nobody looks. This is the same class of cross-file drift that
        caused TECHOPS-1091: RestrictVersion vs RestrictDeliveryOptions.
        """
        with open(self.repo_file('.github', 'workflows', 'deploy-extension-to-marketplace.yml')) as handle:
            workflow = yaml.safe_load(handle)

        # PyYAML parses the bare `on:` key as the boolean True.
        triggers = workflow.get('on', workflow.get(True, {}))
        declared = set(triggers['workflow_dispatch']['inputs'])

        self.assertIn('validated_version', declared)
        self.assertIn('dry_run', declared)
        # image_tag must survive too: the dry-run job and the manual release
        # path both still use it as the ECR tag.
        self.assertIn('image_tag', declared)

    def test_poller_sends_the_version_as_validated_version_not_image_tag(self):
        """image_tag means "ECR tag to build" everywhere else in that workflow."""
        sent = {}

        def capture(workflow, **kwargs):
            sent.update(kwargs)
            return True

        with patch.object(lf, 'get_completed_tests', return_value=[{'changeSetId': 'cs1', 'imageTag': TEST_TAG}]), \
             patch.object(lf, 'find_restriction_changeset', return_value={'ChangeSetId': 'r', 'Status': 'SUCCEEDED'}), \
             patch.object(lf, 'update_test_status'), \
             patch.object(lf, 'trigger_github_workflow', side_effect=capture):
            lf.release_validated_versions()

        self.assertEqual(sent.get('validated_version'), '5.2.2')
        self.assertNotIn('image_tag', sent)


if __name__ == '__main__':
    unittest.main()
