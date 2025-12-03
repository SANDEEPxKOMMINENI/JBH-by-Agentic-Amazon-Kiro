"""
Cover Letter Generator for JobHuntr v2
Adapted from v1's cover letter generation functionality
"""

import logging
import os
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from jinja2 import Environment, FileSystemLoader  # pylint: disable=import-error

from constants import SERVICE_GATEWAY_URL  # noqa: E402
from shared.activity_manager import ActivityType  # noqa: E402

logger = logging.getLogger(__name__)


class CoverLetterGenerator:
    """
    Cover letter generator that creates both text and PDF versions
    Similar to v1's generate_cover_letter functionality
    """

    def __init__(
        self,
        config_reader=None,
        activity_callback: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize the cover letter generator

        Args:
            config_reader: Configuration reader with user profile data
            activity_callback: Callback function for sending activity messages
        """
        self.config_reader = config_reader
        self.activity_callback = activity_callback

        # Setup template environment
        template_dir = os.path.join(os.path.dirname(__file__), "templates")
        self.env = Environment(loader=FileSystemLoader(template_dir))

    def send_activity(self, message: str, activity_type: str = ActivityType.ACTION):
        """Send activity message if callback is available"""
        if self.activity_callback:
            self.activity_callback(message, activity_type)
        else:
            logger.info(f"[{activity_type.upper()}] {message}")

    def generate_cover_letter_text(
        self, position_info: Dict, include_signature: bool = False
    ) -> tuple[str, str, str]:
        """
        Generate cover letter text content - identical structure to v1
        Uses the same API endpoint as Step 4 & 5 to ensure consistency.

        Args:
            position_info: Dictionary containing job/position information
            include_signature: Whether to include signature in the cover letter

        Returns:
            Tuple of (cover_letter_text, thinking, applicant_name)
            The cover_letter_text includes the applicant's actual name in the signature.
        """
        try:
            # Generate cover letter draft using same API as Step 4 & 5
            cover_letter, thinking, applicant_name = self.generate_cover_letter_draft(
                position_info
            )

            # Verify applicant name is included in text (API should include it per prompt)
            if applicant_name:
                if applicant_name in cover_letter:
                    logger.debug(
                        f"?Applicant name '{applicant_name}' confirmed in cover letter text"
                    )
                else:
                    logger.warning(
                        f"?Applicant name '{applicant_name}' was extracted but not found in text. "
                        "The API prompt requires including the name - this may indicate an issue."
                    )

            # Return cover letter with thinking and applicant_name
            return cover_letter, thinking, applicant_name

        except Exception as e:
            logger.error(f"Error generating cover letter text: {e}")
            # Return basic fallback
            return (self._generate_basic_cover_letter(position_info), "", "")

    def generate_cover_letter_pdf(
        self,
        position_info: Dict,
        pdf_path: str,
        html_template: str,
        cover_letter_text: Optional[str] = None,
        applicant_name: Optional[str] = None,
    ) -> Tuple[str, Optional[str], str]:
        """
        Generate cover letter PDF by applying text to HTML template
        Uses the SAME API endpoint as Step 4 & 5 in the frontend wizard for consistency.

        Flow:
        1. If cover_letter_text not provided, generates it first (uses same API as Step 4 & 5)
        2. Calls /api/cover-letter/apply-text-to-template (same as Step 4 & 5)
        3. Converts HTML to PDF
        4. Uploads PDF to blob storage
        5. Creates cover letter record in database

        Args:
            position_info: Dictionary containing job/position information
            pdf_path: Path where to save the PDF
            html_template: HTML template to apply text to (from template's html_content)
            cover_letter_text: Pre-generated cover letter text (optional, will generate if None)
            applicant_name: Applicant's name (optional, extracted from text if not provided)

        Returns:
            Tuple of (pdf_path, blob_url, final_html) where blob_url is None if upload failed
        """
        self.send_activity(" Generating cover letter PDF...")

        # Generate text content if not provided
        if cover_letter_text is None:
            cover_letter_text, _, applicant_name = self.generate_cover_letter_text(
                position_info
            )

        # Apply text to HTML template using API endpoint
        import requests  # noqa: E402

        auth_token = self._get_auth_token()

        api_data = {
            "cover_letter_text": cover_letter_text,
            "template_html": html_template,
            "applicant_name": applicant_name or "",
            "company_name": position_info.get("company_name", "Company"),
            "position_title": position_info.get("position_title", "Position"),
            "save_as_generated": True,  # Save as generated cover letter
        }

        # Call the apply text to template endpoint
        api_url = self._get_api_base_url() + "/api/cover-letter/apply-text-to-template"
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        }

        response = requests.post(api_url, json=api_data, headers=headers, timeout=120)

        result = response.json()
        if result.get("success") and result.get("html"):
            final_html = result.get("html")

            # Create temporary HTML file
            temp_html_path = Path(pdf_path).with_suffix(".html")
            temp_html_path.write_text(final_html, encoding="utf-8")

            # Convert HTML to PDF using sync generator (like ATS template does)
            from util.pdf_generator import generate_pdf_from_html  # noqa: E402

            # Read HTML content and use sync PDF generator
            html_content = temp_html_path.read_text(encoding="utf-8")
            output_dir = Path(pdf_path).parent
            filename = Path(pdf_path).stem

            generated_pdf_path = generate_pdf_from_html(
                html_content=html_content, output_dir=output_dir, filename=filename
            )

            # Upload PDF to blob storage
            blob_url = None
            try:
                self.send_activity(
                    " Uploading cover letter to cloud storage...", ActivityType.ACTION
                )
                blob_url = self._upload_pdf_to_blob_storage(str(generated_pdf_path))

                if blob_url:
                    self.send_activity(
                        "?Cover letter uploaded to cloud storage", ActivityType.RESULT
                    )
                else:
                    self.send_activity(
                        "?Failed to upload cover letter to cloud storage",
                        ActivityType.RESULT,
                    )
            except Exception as upload_error:
                logger.error(
                    f"Error uploading cover letter to blob storage: {upload_error}"
                )
                self.send_activity(
                    "?Cover letter generated but upload failed", ActivityType.RESULT
                )

            # Cleanup temp file
            if temp_html_path.exists():
                temp_html_path.unlink()

            self.send_activity(result.get("thinking", ""), ActivityType.THINKING)
            self.send_activity(
                f"Cover letter PDF saved to: {pdf_path}", ActivityType.RESULT
            )
            return pdf_path, blob_url, final_html

        raise Exception(
            f"Failed to apply text to template: {result.get('error', 'Unknown error')}"
        )

    def generate_cover_letter(
        self,
        position_info: Dict,
        pdf_path: Optional[str] = None,
        application_history_id: Optional[str] = None,
    ) -> Tuple[str, str, Optional[str]]:
        """
        Generate complete cover letter (text and optionally PDF)
        Uses the SAME API endpoints as Step 4 & 5 in the frontend wizard for consistency.

        This is the unified entry point for all cover letter generation:
        - Text-only generation (for questions): Returns text with applicant name
        - PDF generation (for uploads): Returns text + PDF with applicant name

        Flow:
        1. Checks if cover letter template is selected (required)
        2. Fetches template from database
        3. Generates text using /api/cover-letter/generate-text-draft (same as Step 4 & 5)
        4. If pdf_path provided: Applies text to template using /api/cover-letter/apply-text-to-template (same as Step 4 & 5)
        5. Creates PDF and uploads to blob storage (if pdf_path provided)

        Args:
            position_info: Dictionary containing job/position information
            pdf_path: Optional path to save PDF version. If None, only text is generated.
            application_history_id: Optional ID to update application history with cover letter ID

        Returns:
            Tuple of (cover_letter_text, pdf_path or None, cover_letter_id or None)
            - cover_letter_text: Always includes applicant name in signature
            - pdf_path: Path to PDF file if generated, None otherwise
            - cover_letter_id: Database ID if PDF was generated, None otherwise
        """
        try:
            # Check if cover letter template is selected
            if not self.config_reader:
                error_msg = "Config reader is required for cover letter generation"
                logger.error(error_msg)
                raise ValueError(error_msg)

            selected_template_id = getattr(
                self.config_reader.profile, "selected_cover_letter_template_id", None
            )

            if not selected_template_id:
                self.send_activity(
                    "No cover letter template selected. Skipping cover letter generation.",
                    ActivityType.RESULT,
                )
                return ("", None, None)

            # Fetch template to get HTML content (if not already loaded in profile)
            from services.supabase_client import supabase_client  # noqa: E402

            cover_letter_template = supabase_client.get_cover_letter_template_by_id(
                selected_template_id
            )

            if not cover_letter_template:
                error_msg = f"Cover letter template {selected_template_id} not found"
                logger.error(error_msg)
                raise ValueError(error_msg)

            # Use HTML content from template (prefer profile's loaded content, fallback to template)
            html_template = getattr(
                self.config_reader.profile, "cover_letter_html_content", ""
            ) or (cover_letter_template.html_content or "")

            if not html_template:
                error_msg = (
                    "Cover letter template HTML content is required but not found. "
                    "Please ensure the template has HTML content."
                )
                logger.error(error_msg)
                raise ValueError(error_msg)

            # Generate text content
            include_signature = bool(pdf_path)
            (
                cover_letter_text,
                thinking,
                applicant_name,
            ) = self.generate_cover_letter_text(position_info, include_signature)

            # Generate PDF if path provided
            actual_pdf_path = None
            cover_letter_id = None
            if pdf_path:
                # Ensure directory exists
                os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
                actual_pdf_path, blob_url, final_html = self.generate_cover_letter_pdf(
                    position_info,
                    pdf_path,
                    html_template,
                    cover_letter_text,
                    applicant_name,
                )

                # Generate filename from position info
                company_name = position_info.get("company_name", "Company").replace(
                    " ", "_"
                )
                position_title = position_info.get(
                    "position_title", "Position"
                ).replace(" ", "_")
                file_name = f"cover_letter_{company_name}_{position_title}.pdf"

                # Create cover letter record with final HTML (not template), blob URL, filename, and thinking  # noqa: E501
                self.send_activity(
                    " Creating cover letter record...", ActivityType.ACTION
                )
                cover_letter_id = self._create_generated_cover_letter_record(
                    final_html,  # Use final generated HTML instead of template
                    blob_url,
                    file_name,
                    thinking,
                )

                if cover_letter_id:
                    self.send_activity(
                        "?Cover letter record created", ActivityType.RESULT
                    )

                    # Update application history if ID provided
                    if application_history_id:
                        self.send_activity(
                            " Linking cover letter to application history...",
                            ActivityType.ACTION,
                        )
                        if self._update_application_history_cover_letter_id(
                            application_history_id, cover_letter_id
                        ):
                            self.send_activity(
                                "?Application history updated with cover letter",
                                ActivityType.RESULT,
                            )
                        else:
                            self.send_activity(
                                "?Failed to update application history",
                                ActivityType.RESULT,
                            )
                else:
                    self.send_activity(
                        "?Failed to create cover letter record", ActivityType.RESULT
                    )

            return cover_letter_text, actual_pdf_path, cover_letter_id

        except Exception as e:
            logger.error(f"Error in generate_cover_letter: {e}")
            # Return basic fallback
            basic_letter = self._generate_basic_cover_letter(position_info)
            return basic_letter, None, None

    def generate_cover_letter_draft(self, position_info: Dict) -> tuple[str, str, str]:
        """
        Generate cover letter draft using API endpoint
        Uses the SAME API endpoint as Step 4 & 5 in the frontend wizard for consistency.

        Flow:
        1. Fetches selected cover letter template from database
        2. Gets resume_content from template's example_resume_id
        3. Gets user_instructions from template's user_instruction
        4. Calls /api/cover-letter/generate-text-draft (same as Step 4 & 5)
        5. Returns text with applicant name included in signature

        Args:
            position_info: Dictionary containing job/position information

        Returns:
            Tuple of (cover_letter_text, thinking, applicant_name)
            - cover_letter_text: Plain text cover letter with applicant name in signature
            - thinking: AI's thinking process
            - applicant_name: Extracted applicant name (also included in text)
        """
        self.send_activity("Generating cover letter")

        # Validate config reader exists
        if not self.config_reader:
            error_msg = "Config reader is required for cover letter generation"
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Get selected cover letter template ID
        selected_template_id = getattr(
            self.config_reader.profile, "selected_cover_letter_template_id", None
        )

        if not selected_template_id:
            error_msg = "No cover letter template selected"
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Fetch cover letter template from database
        from services.supabase_client import supabase_client  # noqa: E402

        cover_letter_template = supabase_client.get_cover_letter_template_by_id(
            selected_template_id
        )

        if not cover_letter_template:
            error_msg = f"Cover letter template {selected_template_id} not found"
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Get user_instruction from template
        cover_letter_prompt = cover_letter_template.user_instruction or ""

        # Get resume content from template's example_resume_id

        # Validate required data
        if not self.config_reader.profile.resume:
            error_msg = (
                "Resume content is required but not found in cover letter template. "
                "Please set an example resume in the template."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Format position info
        position_info_str = self._pretty_print_dict(position_info)

        # Use API endpoint for cover letter generation
        import requests  # noqa: E402

        # Get auth token
        auth_token = self._get_auth_token()

        # Prepare API request data
        api_data = {
            "resume_content": self.config_reader.profile.resume,
            "job_description": position_info_str,
            "user_instructions": cover_letter_prompt,
            "company_name": position_info.get("company_name", "Company"),
            "position_title": position_info.get("position_title", "Position"),
        }

        # Call the text draft endpoint
        api_url = self._get_api_base_url() + "/api/cover-letter/generate-text-draft"
        headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        }

        response = requests.post(api_url, json=api_data, headers=headers, timeout=60)

        result = response.json()
        if result.get("success") and result.get("text"):
            thinking = result.get("thinking", "")
            cover_letter = result.get("text", "")
            applicant_name = result.get("applicant_name", "")

            # Send thinking activity
            if thinking:
                self.send_activity(thinking, ActivityType.THINKING)

            # Store applicant name for potential use in PDF generation
            if applicant_name:
                self.send_activity(f"Extracted applicant name: {applicant_name}")

            return cover_letter, thinking, applicant_name

        raise Exception(f"API call failed: {result.get('error', 'Unknown error')}")

    def _get_auth_token(self) -> str:
        """
        Get authentication token for API calls.
        Uses the same JWT token manager as other backend services.
        """
        try:
            from services.jwt_token_manager import jwt_token_manager  # noqa: E402

            # Get current token from JWT token manager
            token = jwt_token_manager.get_token()
            if token:
                return token
            else:
                logger.warning("No JWT token available for cover letter API calls")
                return None
        except Exception as e:
            logger.error(f"Error getting auth token: {e}")
            return None

    def _get_api_base_url(self) -> str:
        """Get the base URL for API calls."""
        import os  # noqa: E402

        return os.getenv("SERVICE_GATEWAY_URL", SERVICE_GATEWAY_URL)

    def maybe_get_cover_letter_from_submission_queue(self, app_history_id: str) -> str:
        """
        Check for cached cover letter from submission queue - same as v1  # noqa: E402
        For v2 simplified version, always return empty (no submission queue)
        """
        # In v1 this would check submission_queue_tracker
        # For v2, we don't have submission queue, so always generate new
        return ""

    def _generate_basic_cover_letter(self, position_info: Dict) -> str:
        """Fallback basic cover letter generation"""
        company_name = position_info.get("company_name", "the company")
        position_title = position_info.get("position_title", "this position")

        # Try to get applicant name from config reader
        applicant_name = ""
        if self.config_reader and hasattr(self.config_reader.profile, "name"):
            applicant_name = self.config_reader.profile.name

        # Build signature line
        signature = applicant_name if applicant_name else "Sincerely"

        return f"""Dear Hiring Manager,

I am writing to express my strong interest in the {position_title} position at {company_name}. With my background and skills outlined in my resume, I believe I would be a valuable addition to your team.

My experience aligns well with the requirements for this role, and I am excited about the opportunity to contribute to {company_name}'s continued success. I am particularly drawn to this position because it offers the chance to apply my skills in a dynamic environment.

I would welcome the opportunity to discuss how my background and enthusiasm can benefit your team. Thank you for your consideration.

Best regards,
{signature}"""

    def _pretty_print_dict(self, data: Dict) -> str:
        """
        Pretty print dictionary for position info - same as v1
        """
        if not data:
            return ""

        result = []
        for key, value in data.items():
            if value:
                result.append(f"{key}: {value}")

        return "\n".join(result)

    def _html_to_pdf(self, html_path: str, pdf_path: str):
        """
        Convert HTML to PDF
        Simplified version for v2 - uses basic conversion
        """
        try:
            # Try to use playwright for PDF generation if available
            from browser.automation import sync_playwright  # noqa: E402

            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                page.goto(f"file://{html_path}")
                page.pdf(
                    path=pdf_path,
                    print_background=True,
                    format="A4",
                    margin={
                        "top": "0in",
                        "right": "0in",
                        "bottom": "0in",
                        "left": "0in",
                    },
                    prefer_css_page_size=True,
                    page_ranges="1",  # Only generate the first page
                )
                browser.close()

        except ImportError:
            logger.warning("Playwright not available, PDF generation skipped")
            # For now, just copy the HTML file as fallback
            import shutil  # noqa: E402

            shutil.copy(html_path, pdf_path.replace(".pdf", ".html"))
        except Exception as e:
            logger.error(f"Error converting HTML to PDF: {e}")
            raise

    def _upload_pdf_to_blob_storage(self, pdf_path: str) -> Optional[str]:
        """Upload generated PDF to blob storage via service gateway"""
        try:
            import requests  # noqa: E402

            # Get auth token
            from services.jwt_token_manager import jwt_token_manager  # noqa: E402

            token = jwt_token_manager.get_token()
            if not token:
                logger.error("No auth token available for blob upload")
                return None

            # Read the PDF file
            with open(pdf_path, "rb") as f:
                pdf_content = f.read()

            # Create form data for file upload
            filename = f"cover_letter_{Path(pdf_path).stem}.pdf"
            files = {"file": (filename, pdf_content, "application/pdf")}

            # Upload to service gateway blob endpoint
            response = requests.post(
                f"{self._get_api_base_url()}/api/blob/upload?folder=cover_letters",
                headers={"Authorization": f"Bearer {token}"},
                files=files,
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    return result.get("blob_url")
                else:
                    logger.error(f"Blob upload failed: {result}")
                    return None
            else:
                logger.error(
                    f"Blob upload HTTP error {response.status_code}: {response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error uploading PDF to blob storage: {e}")
            return None

    def _create_generated_cover_letter_record(
        self,
        html_content: str,
        blob_url: Optional[str] = None,
        file_name: Optional[str] = None,
        thinking: Optional[str] = None,
    ) -> Optional[str]:
        """Create a generated cover letter record in the database"""
        try:
            import requests  # noqa: E402

            # Get auth token
            from services.jwt_token_manager import jwt_token_manager  # noqa: E402

            token = jwt_token_manager.get_token()
            if not token:
                logger.error("No auth token available for creating cover letter record")
                return None

            # Create the generated cover letter record with all fields
            create_data = {"html_content": html_content, "cover_letter_url": blob_url}

            # Add optional fields if provided
            if file_name:
                create_data["file_name"] = file_name
            if thinking:
                create_data["thinking"] = thinking

            response = requests.post(
                f"{self._get_api_base_url()}/api/cover-letter/generated",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=create_data,
            )

            if response.status_code in [200, 201]:
                result = response.json()
                logger.info(f"API Response: {result}")  # Debug logging
                if result.get("success"):
                    cover_letter_id = result.get("id")
                    logger.info(
                        f"Created generated cover letter record: {cover_letter_id}"
                    )

                    return cover_letter_id
                else:
                    logger.error(f"Failed to create cover letter record: {result}")
                    return None
            else:
                logger.error(
                    f"Create cover letter record HTTP error {response.status_code}: {response.text}"  # noqa: E501
                )
                return None

        except Exception as e:
            logger.error(f"Error creating generated cover letter record: {e}")
            return None

    def _update_application_history_cover_letter_id(
        self, app_history_id: str, cover_letter_id: str
    ) -> bool:
        """Update application history with cover letter ID"""
        try:
            import requests  # noqa: E402

            # Debug logging
            logger.info(
                f"Updating application history {app_history_id} with cover letter ID: {cover_letter_id}"  # noqa: E501
            )

            if not cover_letter_id:
                logger.error("Cover letter ID is empty or None")
                return False

            # Get auth token
            from services.jwt_token_manager import jwt_token_manager  # noqa: E402

            token = jwt_token_manager.get_token()
            if not token:
                logger.error("No auth token available for updating application history")
                return False

            # Update the application history record
            update_data = {"cover_letter_id": cover_letter_id}
            logger.info(f"Sending update data: {update_data}")

            response = requests.put(
                f"{self._get_api_base_url()}/api/application-history/{app_history_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=update_data,
            )

            logger.info(f"Response status code: {response.status_code}")
            logger.info(f"Response text: {response.text}")

            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    logger.info(
                        f"Updated application history {app_history_id} with cover letter ID {cover_letter_id}"  # noqa: E501
                    )
                    return True
                else:
                    logger.error(f"Failed to update application history: {result}")
                    return False
            else:
                logger.error(
                    f"Update application history HTTP error {response.status_code}: {response.text}"  # noqa: E501
                )
                return False

        except Exception as e:
            logger.error(f"Error updating application history: {e}")
            return False


# Convenience function for easy usage
def generate_cover_letter(
    position_info: Dict,
    pdf_path: Optional[str] = None,
    config_reader=None,
    activity_callback: Optional[Callable[[str], None]] = None,
    application_history_id: Optional[str] = None,
) -> Tuple[str, str, Optional[str]]:
    """
    Convenience function to generate cover letter

    Args:
        position_info: Dictionary containing job/position information
        pdf_path: Optional path to save PDF version
        config_reader: Optional configuration reader
        activity_callback: Optional callback for activity messages
        application_history_id: Optional ID to update application history with cover letter ID  # noqa: E501

    Returns:
        Tuple of (cover_letter_text, pdf_path or None, cover_letter_id or None)
    """
    generator = CoverLetterGenerator(config_reader, activity_callback)
    return generator.generate_cover_letter(
        position_info, pdf_path, application_history_id
    )
