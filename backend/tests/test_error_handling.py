"""
Tests for error handling methods in StartHuntingAction
"""

import os
import sys
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from linkedin_bot.actions.start_hunting_action import StartHuntingAction
from shared.models.application_history import ApplicationStatus


@pytest.fixture
def mock_bot_instance():
    """Create a mock bot instance"""
    bot = Mock()
    bot.bot_id = "test_bot_123"
    bot.is_running = False
    bot.page = Mock()
    bot.browser_operator = Mock()
    bot.browser_operator.browser_session = Mock()
    bot.workflow_run_id = "test_workflow_123"
    return bot


@pytest.fixture
def action_instance(mock_bot_instance):
    """Create StartHuntingAction instance with mocked dependencies"""
    with patch(
        "linkedin_bot.actions.start_hunting_action.BaseAction.__init__",
        return_value=None,
    ):
        action = StartHuntingAction(mock_bot_instance)
        action.bot = mock_bot_instance
        action.logger = Mock()
        action.send_activity_message = Mock()
        action.activity_manager = Mock()
        action.application_history_tracker = Mock()
        action.application_history_tracker.cur_recording_app_history_id = "test_app_123"
        action.cur_job_data = {
            "company_name": "Test Corp",
            "job_title": "Software Engineer",
            "application_url": "https://linkedin.com/jobs/123",
        }
        return action


class TestUploadScreenshotToBlob:
    """Tests for _upload_screenshot_to_blob method"""

    def test_upload_success(self, action_instance):
        """Should successfully upload screenshot and return URL"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"url": "https://blob.storage/screenshot.png"}

        with patch("os.path.basename", return_value="screenshot.png"), patch(
            "builtins.open", mock_open(read_data=b"fake_image_data")
        ), patch("requests.post", return_value=mock_response) as mock_post, patch(
            "services.jwt_token_manager.jwt_token_manager.get_token",
            return_value="test_token",
        ):
            result = action_instance._upload_screenshot_to_blob(
                "/path/to/screenshot.png"
            )

            assert result == "https://blob.storage/screenshot.png"
            mock_post.assert_called_once()

            # Verify correct endpoint was called
            call_args = mock_post.call_args
            assert "/api/blob/upload" in call_args[0][0]
            assert "container=screenshots" in call_args[0][0]
            assert "folder=failed-jobs" in call_args[0][0]

    def test_upload_no_token(self, action_instance):
        """Should return None when JWT token is not available"""
        with patch(
            "services.jwt_token_manager.jwt_token_manager.get_token", return_value=None
        ):
            result = action_instance._upload_screenshot_to_blob(
                "/path/to/screenshot.png"
            )

            assert result is None
            action_instance.logger.warning.assert_called_with(
                "No JWT token available for screenshot upload"
            )

    def test_upload_api_error(self, action_instance):
        """Should return None when blob storage API returns error"""
        mock_response = Mock()
        mock_response.status_code = 500

        with patch("os.path.basename", return_value="screenshot.png"), patch(
            "builtins.open", mock_open(read_data=b"fake_image_data")
        ), patch("requests.post", return_value=mock_response), patch(
            "services.jwt_token_manager.jwt_token_manager.get_token",
            return_value="test_token",
        ):
            result = action_instance._upload_screenshot_to_blob(
                "/path/to/screenshot.png"
            )

            assert result is None
            action_instance.logger.error.assert_called()

    def test_upload_network_error(self, action_instance):
        """Should handle network errors gracefully"""
        with patch("os.path.basename", return_value="screenshot.png"), patch(
            "builtins.open", mock_open(read_data=b"fake_image_data")
        ), patch("requests.post", side_effect=Exception("Network error")), patch(
            "services.jwt_token_manager.jwt_token_manager.get_token",
            return_value="test_token",
        ):
            result = action_instance._upload_screenshot_to_blob(
                "/path/to/screenshot.png"
            )

            assert result is None
            action_instance.logger.error.assert_called_with(
                "Error uploading screenshot: Network error"
            )


class TestSendMixpanelFailedApplication:
    """Tests for _send_mixpanel_failed_application method"""

    def test_send_success(self, action_instance):
        """Should successfully send Mixpanel event"""
        mock_response = Mock()
        mock_response.status_code = 200

        test_error = Exception("Test error")
        screenshot_url = "https://blob.storage/screenshot.png"

        with patch("requests.post", return_value=mock_response) as mock_post, patch(
            "services.jwt_token_manager.jwt_token_manager.get_token",
            return_value="test_token",
        ), patch("traceback.format_exc", return_value="Traceback details"):
            action_instance._send_mixpanel_failed_application(
                test_error, screenshot_url
            )

            # Verify Mixpanel endpoint was called
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "/api/analytics/mixpanel" in call_args[0][0]

            # Verify payload contains job data, error, and screenshot
            payload = call_args[1]["json"]
            assert payload["event_name"] == "failed_an_application"
            assert payload["properties"]["company_name"] == "Test Corp"
            assert payload["properties"]["job_title"] == "Software Engineer"
            assert payload["properties"]["error"] == "Test error"
            assert payload["properties"]["screenshot_url"] == screenshot_url
            assert "traceback" in payload["properties"]

            action_instance.logger.info.assert_called_with(
                "Mixpanel event sent successfully"
            )

    def test_send_no_token(self, action_instance):
        """Should skip sending when no JWT token available"""
        with patch(
            "services.jwt_token_manager.jwt_token_manager.get_token", return_value=None
        ):
            action_instance._send_mixpanel_failed_application(Exception("Test"), None)

            action_instance.logger.warning.assert_called_with(
                "No JWT token available for Mixpanel event"
            )

    def test_send_api_error(self, action_instance):
        """Should log error when Mixpanel API fails"""
        mock_response = Mock()
        mock_response.status_code = 500

        with patch("requests.post", return_value=mock_response), patch(
            "services.jwt_token_manager.jwt_token_manager.get_token",
            return_value="test_token",
        ), patch("traceback.format_exc", return_value="Traceback"):
            action_instance._send_mixpanel_failed_application(Exception("Test"), None)

            action_instance.logger.error.assert_called()


class TestSendSlackFailedNotification:
    """Tests for _send_slack_failed_notification method"""

    def test_send_success_with_screenshot(self, action_instance):
        """Should successfully send Slack notification with screenshot"""
        mock_response = Mock()
        mock_response.status_code = 200

        test_error = Exception("Test error")
        screenshot_url = "https://blob.storage/screenshot.png"

        with patch("requests.post", return_value=mock_response) as mock_post, patch(
            "services.jwt_token_manager.jwt_token_manager.get_token",
            return_value="test_token",
        ), patch("traceback.format_exc", return_value="Traceback details"):
            action_instance._send_slack_failed_notification(test_error, screenshot_url)

            # Verify Slack endpoint was called
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "/api/analytics/slack" in call_args[0][0]

            # Verify payload structure
            payload = call_args[1]["json"]
            assert payload["channel"] == "failed_jobs"
            assert "Test Corp" in payload["text"]
            assert "Software Engineer" in payload["text"]

            # Verify blocks contain rich formatting
            blocks = payload["blocks"]
            assert len(blocks) > 0
            assert blocks[0]["type"] == "header"

            # Verify screenshot is included
            image_blocks = [b for b in blocks if b["type"] == "image"]
            assert len(image_blocks) == 1
            assert image_blocks[0]["image_url"] == screenshot_url

            action_instance.logger.info.assert_called_with(
                "Slack notification sent successfully"
            )

    def test_send_success_without_screenshot(self, action_instance):
        """Should send Slack notification without screenshot when not available"""
        mock_response = Mock()
        mock_response.status_code = 200

        with patch("requests.post", return_value=mock_response) as mock_post, patch(
            "services.jwt_token_manager.jwt_token_manager.get_token",
            return_value="test_token",
        ), patch("traceback.format_exc", return_value="Traceback"):
            action_instance._send_slack_failed_notification(Exception("Test"), None)

            # Verify no image block when screenshot is None
            payload = mock_post.call_args[1]["json"]
            image_blocks = [b for b in payload["blocks"] if b["type"] == "image"]
            assert len(image_blocks) == 0

    def test_send_includes_job_url(self, action_instance):
        """Should include job URL in notification when available"""
        mock_response = Mock()
        mock_response.status_code = 200

        with patch("requests.post", return_value=mock_response) as mock_post, patch(
            "services.jwt_token_manager.jwt_token_manager.get_token",
            return_value="test_token",
        ), patch("traceback.format_exc", return_value="Traceback"):
            action_instance._send_slack_failed_notification(Exception("Test"), None)

            payload = mock_post.call_args[1]["json"]
            blocks = payload["blocks"]

            # Find section with job URL
            url_sections = [
                b
                for b in blocks
                if b["type"] == "section" and "Job URL" in b["text"]["text"]
            ]
            assert len(url_sections) == 1
            assert "linkedin.com/jobs/123" in url_sections[0]["text"]["text"]

    def test_send_no_token(self, action_instance):
        """Should skip sending when no JWT token available"""
        with patch(
            "services.jwt_token_manager.jwt_token_manager.get_token", return_value=None
        ):
            action_instance._send_slack_failed_notification(Exception("Test"), None)

            action_instance.logger.warning.assert_called_with(
                "No JWT token available for Slack notification"
            )


class TestHandleFailedToApply:
    """Tests for _handle_failed_to_apply method"""

    def test_full_error_handling_flow(self, action_instance, mock_bot_instance):
        """Should execute complete error handling flow"""
        test_error = Exception("Application failed")

        # Mock all dependencies
        mock_bot_instance.page = Mock()
        mock_screenshot_path = "/tmp/screenshot.png"
        mock_screenshot_url = "https://blob.storage/screenshot.png"

        action_instance.bot.browser_operator.take_screenshot.return_value = (
            mock_screenshot_path
        )

        with patch.object(
            action_instance,
            "_upload_screenshot_to_blob",
            return_value=mock_screenshot_url,
        ) as mock_upload, patch.object(
            action_instance, "_send_mixpanel_failed_application"
        ) as mock_mixpanel, patch.object(
            action_instance, "_send_slack_failed_notification"
        ) as mock_slack, patch(
            "traceback.format_exc", return_value="Traceback"
        ):
            action_instance._handle_failed_to_apply(test_error)

            # Verify application history was updated
            action_instance.application_history_tracker.update_application.assert_called_with(
                "test_app_123", "status", ApplicationStatus.FAILED.value
            )
            action_instance.application_history_tracker.sync_application_history.assert_called_once()

            # Verify screenshot was taken and uploaded
            action_instance.bot.browser_operator.take_screenshot.assert_called_with(
                mock_bot_instance.page
            )
            mock_upload.assert_called_with(mock_screenshot_path)

            # Verify Mixpanel and Slack were notified
            mock_mixpanel.assert_called_with(test_error, mock_screenshot_url)
            mock_slack.assert_called_with(test_error, mock_screenshot_url)

    def test_error_handling_continues_on_screenshot_failure(self, action_instance):
        """Should continue error handling even if screenshot fails"""
        test_error = Exception("Application failed")

        # Make screenshot fail
        action_instance.bot.browser_operator.take_screenshot.side_effect = Exception(
            "Screenshot failed"
        )

        with patch.object(
            action_instance, "_send_mixpanel_failed_application"
        ) as mock_mixpanel, patch.object(
            action_instance, "_send_slack_failed_notification"
        ) as mock_slack, patch(
            "traceback.format_exc", return_value="Traceback"
        ):
            action_instance._handle_failed_to_apply(test_error)

            # Should still send notifications even though screenshot failed
            mock_mixpanel.assert_called_with(test_error, None)
            mock_slack.assert_called_with(test_error, None)

    def test_error_handling_continues_on_mixpanel_failure(self, action_instance):
        """Should continue to Slack even if Mixpanel fails"""
        test_error = Exception("Application failed")

        with patch.object(
            action_instance, "_upload_screenshot_to_blob", return_value=None
        ), patch.object(
            action_instance,
            "_send_mixpanel_failed_application",
            side_effect=Exception("Mixpanel error"),
        ), patch.object(
            action_instance, "_send_slack_failed_notification"
        ) as mock_slack, patch(
            "traceback.format_exc", return_value="Traceback"
        ):
            action_instance._handle_failed_to_apply(test_error)

            # Should still send Slack notification
            mock_slack.assert_called_once()

    def test_no_application_history_id(self, action_instance):
        """Should handle case when no application history ID exists"""
        action_instance.application_history_tracker.cur_recording_app_history_id = None
        test_error = Exception("Application failed")

        with patch.object(
            action_instance, "_upload_screenshot_to_blob", return_value=None
        ), patch.object(
            action_instance, "_send_mixpanel_failed_application"
        ), patch.object(
            action_instance, "_send_slack_failed_notification"
        ), patch(
            "traceback.format_exc", return_value="Traceback"
        ):
            action_instance._handle_failed_to_apply(test_error)

            # Should not try to update application history
            action_instance.application_history_tracker.update_application.assert_not_called()

    def test_browser_closed_error_interrupted(self, action_instance):
        """Should handle browser closure as interruption, not failure"""
        test_error = Exception("Target page, context or browser has been closed")

        with patch.object(
            action_instance, "_send_mixpanel_interrupted_application"
        ) as mock_interrupted, patch.object(
            action_instance, "_send_mixpanel_failed_application"
        ) as mock_failed, patch.object(
            action_instance, "_send_slack_failed_notification"
        ) as mock_slack, patch.object(
            action_instance, "_upload_screenshot_to_blob"
        ) as mock_upload, patch(
            "traceback.format_exc", return_value="Traceback"
        ):
            action_instance._handle_failed_to_apply(test_error)

            # Should send interrupted event, not failed
            mock_interrupted.assert_called_once_with(test_error)
            mock_failed.assert_not_called()

            # Should NOT send Slack notification
            mock_slack.assert_not_called()

            # Should NOT try to take screenshot
            mock_upload.assert_not_called()

            # Should NOT update application history as failed
            action_instance.application_history_tracker.update_application.assert_not_called()

            # Should log at WARNING level
            action_instance.logger.warning.assert_called()

    def test_browser_closed_variations(self, action_instance):
        """Should detect various browser closure error messages"""
        error_variations = [
            "Target page, context or browser has been closed",
            "Browser has been closed",
            "Context has been closed",
            "target page has been closed",  # lowercase
            "THE BROWSER HAS BEEN CLOSED",  # uppercase
        ]

        for error_msg in error_variations:
            test_error = Exception(error_msg)

            with patch.object(
                action_instance, "_send_mixpanel_interrupted_application"
            ) as mock_interrupted, patch.object(
                action_instance, "_send_slack_failed_notification"
            ) as mock_slack, patch(
                "traceback.format_exc", return_value="Traceback"
            ):
                action_instance._handle_failed_to_apply(test_error)

                # Should be detected as browser closure
                mock_interrupted.assert_called_once()
                mock_slack.assert_not_called()

                # Reset mocks for next iteration
                mock_interrupted.reset_mock()
                mock_slack.reset_mock()

    def test_normal_error_not_treated_as_interruption(self, action_instance):
        """Should treat normal errors as failures, not interruptions"""
        test_error = Exception("Some other error message")

        with patch.object(
            action_instance, "_send_mixpanel_interrupted_application"
        ) as mock_interrupted, patch.object(
            action_instance, "_send_mixpanel_failed_application"
        ) as mock_failed, patch.object(
            action_instance, "_send_slack_failed_notification"
        ) as mock_slack, patch.object(
            action_instance, "_upload_screenshot_to_blob", return_value=None
        ), patch(
            "traceback.format_exc", return_value="Traceback"
        ):
            action_instance._handle_failed_to_apply(test_error)

            # Should send failed event, not interrupted
            mock_failed.assert_called_once()
            mock_interrupted.assert_not_called()

            # Should send Slack notification
            mock_slack.assert_called_once()

            # Should update application history as failed
            action_instance.application_history_tracker.update_application.assert_called()


class TestSendMixpanelInterruptedApplication:
    """Tests for _send_mixpanel_interrupted_application method"""

    def test_send_interrupted_success(self, action_instance):
        """Should successfully send interrupted application event"""
        mock_response = Mock()
        mock_response.status_code = 200

        test_error = Exception("Browser closed")

        with patch("requests.post", return_value=mock_response) as mock_post, patch(
            "services.jwt_token_manager.jwt_token_manager.get_token",
            return_value="test_token",
        ):
            action_instance._send_mixpanel_interrupted_application(test_error)

            # Verify correct endpoint and event name
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "/api/analytics/mixpanel" in call_args[0][0]

            # Verify payload
            payload = call_args[1]["json"]
            assert payload["event_name"] == "interrupted_an_application"
            assert payload["properties"]["error"] == "Browser closed"
            assert payload["properties"]["reason"] == "browser_closed"
            assert payload["properties"]["company_name"] == "Test Corp"

            # Verify NO screenshot_url or traceback in properties
            assert "screenshot_url" not in payload["properties"]
            assert "traceback" not in payload["properties"]

    def test_send_interrupted_no_token(self, action_instance):
        """Should skip sending when no JWT token available"""
        with patch(
            "services.jwt_token_manager.jwt_token_manager.get_token",
            return_value=None,
        ):
            action_instance._send_mixpanel_interrupted_application(Exception("Test"))

            action_instance.logger.warning.assert_called_with(
                "No JWT token available for Mixpanel event"
            )

    def test_send_interrupted_api_error(self, action_instance):
        """Should log error when API fails"""
        mock_response = Mock()
        mock_response.status_code = 500

        with patch("requests.post", return_value=mock_response), patch(
            "services.jwt_token_manager.jwt_token_manager.get_token",
            return_value="test_token",
        ):
            action_instance._send_mixpanel_interrupted_application(Exception("Test"))

            action_instance.logger.error.assert_called()
