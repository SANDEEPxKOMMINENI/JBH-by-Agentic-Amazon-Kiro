#!/usr/bin/env python3
"""
Connect Contacts Action for LinkedIn Bot

This action sends connection requests to collected contacts.
"""

import logging
import time
from datetime import datetime
from typing import Any

from browser.browser_operator import BrowserOperator  # noqa: E402
from services.supabase_client import supabase_client  # noqa: E402

from .base_action import BaseAction  # noqa: E402

logger = logging.getLogger(__name__)


class ConnectContactsAction(BaseAction):
    """
    Action to send connection requests to contacts.

    Takes a list of contact records and sends LinkedIn connection
    requests with optional messages.
    """

    def __init__(
        self,
        bot_instance,
        message_template: str | None = None,
        use_individual_messages: bool = False,
    ):
        """
        Initialize the connect contacts action

        Args:
            bot_instance: Bot instance
            message_template: Optional message template with {first_name} placeholder
            use_individual_messages: If True, use each contact's individual message
        """
        super().__init__(bot_instance)
        self.browser_operator: BrowserOperator | None = None
        self.page = None
        self.message_template = message_template
        self.use_individual_messages = use_individual_messages

    @property
    def action_name(self) -> str:
        """Return the name of this action"""
        return "connect_contacts"

    def execute(self, contacts: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Execute the connect contacts action.

        Args:
            contacts: List of contact dictionaries with id, name, linkedin_url

        Returns:
            Dict with success status and stats
        """
        self.logger.info(f"Starting to connect with {len(contacts)} contacts")

        if not contacts:
            return {
                "success": False,
                "message": "No contacts provided",
                "connected_count": 0,
            }

        # Initialize browser
        try:
            self._init_browser()
        except Exception as e:
            self.logger.error(f"Failed to initialize browser: {e}")
            return {
                "success": False,
                "message": f"Failed to initialize browser: {str(e)}",
                "connected_count": 0,
            }

        connected_count = 0
        failed_count = 0

        try:
            for idx, contact in enumerate(contacts, 1):
                # Check if bot is still running
                if not getattr(self.bot, "is_running", True):
                    self.logger.info("Bot stopped, halting connection process")
                    break

                contact_name = contact.get("name", "Unknown")
                self.logger.info(
                    f"Processing contact {idx}/{len(contacts)}: {contact_name}"
                )

                try:
                    success = self._connect_to_contact(contact)
                    if success:
                        connected_count += 1
                        # Update contact status to outreached
                        self._update_contact_status(contact.get("id"), "outreached")
                    else:
                        failed_count += 1

                    # Small delay between requests to avoid rate limiting
                    time.sleep(2)

                except Exception as e:
                    self.logger.error(
                        f"Error connecting to contact {contact.get('name')}: {e}"
                    )
                    failed_count += 1
                    continue

        finally:
            self._cleanup_browser()

        self.logger.info(
            f"Connection process completed. Connected: {connected_count}, "
            f"Failed: {failed_count}"
        )

        return {
            "success": True,
            "message": f"Connected to {connected_count} contacts",
            "connected_count": connected_count,
            "failed_count": failed_count,
        }

    def _init_browser(self):
        """Initialize browser and navigate to LinkedIn"""
        self.logger.info("Initializing browser for connection requests")
        self.browser_operator = BrowserOperator(
            headless=False,
        )

        # Set bot instance reference for stop signal detection
        self.browser_operator.set_bot_instance(self.bot)

        # Start browser and get page
        self.page = self.browser_operator.start()

    def _cleanup_browser(self):
        """Clean up browser resources"""
        if self.browser_operator:
            self.logger.info("Closing browser")
            self.browser_operator.close()
            self.page = None

    def _connect_to_contact(self, contact: dict[str, Any]) -> bool:
        """
        Send connection request to a single contact.

        Args:
            contact: Contact dictionary with name, linkedin_url

        Returns:
            True if connection sent successfully
        """
        linkedin_url = contact.get("linkedin_url", "")
        name = contact.get("name", "Unknown")

        if not linkedin_url:
            self.logger.warning(f"No LinkedIn URL for contact {name}")
            return False

        try:
            # Navigate to profile
            self.logger.info(f"Navigating to {name}'s profile")
            self.browser_operator.navigate_to(linkedin_url)
            time.sleep(3)

            # Find connect button
            modal = self._open_connection_modal()

            # Check if already pending
            if modal == "already_pending":
                contact_id = contact.get("id")
                if contact_id:
                    try:
                        self._update_contact_status(contact_id)
                        self.logger.info(
                            f"Marked {name} as outreached (already pending)"
                        )
                        return True
                    except Exception as update_error:
                        self.logger.error(
                            f"Failed to update contact status: {update_error}"
                        )
                return True

            if not modal:
                self.logger.warning(f"Could not open connection modal for {name}")
                return False

            # Determine message to use
            message = None
            if self.use_individual_messages:
                # Use contact's individual message
                message = contact.get("message")
            elif self.message_template:
                # Use shared template
                message = self.message_template

            # Send with or without message
            if message:
                success = self._send_connection_with_message(modal, contact, message)
                # Format message with actual first name for storage
                first_name = name.split()[0] if name else "there"
                final_message = message.replace("{first_name}", first_name)
            else:
                success = self._send_connection_without_message(modal)
                final_message = None

            if success:
                self.logger.info(f"Successfully sent connection request to {name}")

                # Update contact status with actual message sent
                contact_id = contact.get("id")
                if contact_id:
                    try:
                        self._update_contact_status(contact_id, final_message)
                    except Exception as update_error:
                        self.logger.error(
                            f"Failed to update contact status: {update_error}"
                        )
                        # Don't fail if status update fails
            else:
                self.logger.warning(f"Failed to send connection request to {name}")

            return success

        except Exception as e:
            self.logger.error(f"Error connecting to {name}: {e}")
            return False

    def _open_connection_modal(self) -> Any:
        """
        Find and click the Connect button to open the modal.

        Returns:
            The modal locator if found, None otherwise
        """
        try:
            # Check if connection is already pending
            pending_button = self.page.locator("button[aria-label*='Pending']")
            if pending_button.count() > 0:
                self.logger.info("Connection already pending, marking as outreached")
                return "already_pending"

            connect_button = (
                self.page.locator("button[aria-label*='More actions']")
                .locator("../..")
                .locator("button[class*=artdeco-button]")
                .get_by_text("Connect")
            )

            if connect_button.count() == 0 or not connect_button.first.is_visible():
                self.logger.info("Connect button not visible, trying More button")

                # Try the More actions button
                more_button = self.page.locator("button[aria-label*='More actions']")
                if more_button.count() == 0:
                    self.logger.warning("No More button found")
                    return None
                elif more_button.count() > 1:
                    # iterate to find the first visible more button
                    for button in more_button.all():
                        if button.is_visible():
                            more_button = button
                            break

                self.browser_operator.click_with_op(more_button)
                time.sleep(1)

                # Find Connect in dropdown
                dropdown = self.page.locator("div.artdeco-dropdown__content-inner")
                if dropdown.count() == 0:
                    return None
                elif dropdown.count() > 1:
                    # iterate to find the first visible connect button
                    for d in dropdown.all():
                        if d.is_visible():
                            dropdown = d
                            break

                connect_button = dropdown.get_by_text("Connect", exact=True)
                if connect_button.count() == 0:
                    # Check if already pending
                    pending_button = self.page.locator("button[aria-label*='Pending']")
                    if pending_button.count() > 0:
                        self.logger.info("Connection pending, marking as outreached")
                        return "already_pending"

                    self.logger.warning("Connect button not found in dropdown")
                    return None

            # Click Connect button
            self.browser_operator.click_with_op(connect_button.first)
            time.sleep(1)

            # Wait for modal to appear
            modal = self.page.locator("div[role='dialog']")
            if modal.count() == 0:
                self.logger.warning("Connection modal did not appear")
                return None

            return modal.first

        except Exception as e:
            self.logger.error(f"Error opening connection modal: {e}")
            return None

    def _send_connection_with_message(
        self, modal: Any, contact: dict[str, Any], message: str
    ) -> bool:
        """
        Send connection request with a personalized message.

        Args:
            modal: The connection modal locator
            contact: Contact information
            message: The message to send

        Returns:
            True if message sent successfully
        """
        try:
            # Click "Add a note"
            add_note_button = modal.locator("button[aria-label='Add a note']")
            if add_note_button.count() == 0:
                self.logger.warning("Add note button not found")
                return False

            self.browser_operator.click_with_op(add_note_button.first)
            time.sleep(0.5)

            # Fill in the message
            message_textarea = modal.locator("textarea[name='message']")
            if message_textarea.count() == 0:
                self.logger.warning("Message textarea not found")
                return False

            # Format message with first name
            name = contact.get("name", "")
            first_name = name.split()[0] if name else "there"
            formatted_message = message.replace("{first_name}", first_name)

            self.browser_operator.op(
                lambda: message_textarea.first.fill(formatted_message)
            )
            time.sleep(0.5)

            # Click send
            send_button = modal.locator("button[aria-label='Send invitation']")
            if send_button.count() == 0:
                self.logger.warning("Send button not found")
                return False

            self.browser_operator.click_with_op(send_button.first)
            time.sleep(1)

            # Check for weekly limit warning
            if self._check_for_limit_warning(modal):
                self.logger.warning("Reached weekly invitation limit")
                self.bot.is_running = False  # Stop the process
                return False

            return True

        except Exception as e:
            self.logger.error(f"Error sending connection with message: {e}")
            return False

    def _send_connection_without_message(self, modal: Any) -> bool:
        """
        Send connection request without a message.

        Args:
            modal: The connection modal locator

        Returns:
            True if connection sent successfully
        """
        try:
            # Click "Send without a note"
            send_button = modal.locator("button[aria-label='Send without a note']")
            if send_button.count() == 0:
                # Try alternative: direct Send button
                send_button = modal.locator("button[aria-label='Send invitation']")
                if send_button.count() == 0:
                    self.logger.warning("Send button not found")
                    return False

            self.browser_operator.click_with_op(send_button.first)
            time.sleep(1)

            # Check for weekly limit warning
            if self._check_for_limit_warning(modal):
                self.logger.warning("Reached weekly invitation limit")
                self.bot.is_running = False  # Stop the process
                return False

            return True

        except Exception as e:
            self.logger.error(f"Error sending connection without message: {e}")
            return False

    def _check_for_limit_warning(self, modal: Any) -> bool:
        """
        Check if LinkedIn shows the weekly invitation limit warning.

        Returns:
            True if limit reached
        """
        try:
            time.sleep(1)
            heading = modal.locator("h2")
            if heading.count() > 0:
                text = heading.first.inner_text().lower()
                if "limit" in text or "reached" in text:
                    return True
            return False
        except Exception:
            return False

    def _update_contact_status(self, contact_id: str, sent_message: str | None = None):
        """
        Update contact status to 'outreached' with timestamp in database

        Args:
            contact_id: Contact ID to update
            sent_message: The actual message sent (or None if no message)
        """
        if not contact_id:
            return

        try:
            update_data = {
                "status": "outreached",
                "outreached_at": datetime.utcnow().isoformat(),
                "draft_message": sent_message or "",
            }
            supabase_client.update_contact(contact_id, update_data)
            self.logger.info(f"Updated contact {contact_id} status to outreached")
        except Exception as e:
            self.logger.error(f"Failed to update contact status: {e}")
