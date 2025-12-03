"""
Question Filler - Async version for v2
Adapted from v1's question_filler for async operations with full functionality
"""

import logging
from typing import Callable, Optional

from activity.base_activity import ActivityType
from browser.automation import Locator  # pylint: disable=import-error

from .answer import Answer
from .input_question_filler.input_question_filler import InputQuestionFiller
from .multi_line_input_question_filler.multi_line_input_question_filler import (
    MultiLineInputQuestionFiller,
)
from .multi_selection_question_filler.multi_selection_question_filler import (
    MultiSelectionQuestionFiller,
)
from .question_type import QuestionType
from .radio_question_filler.radio_question_filler import RadioQuestionFiller
from .selection_question_filler.selection_question_filler import SelectionQuestionFiller

logger = logging.getLogger(__name__)


class QuestionFiller:
    """
    Async question filler for LinkedIn job application forms.
    Adapted from v1's QuestionFiller for v2's async architecture.
    """

    def __init__(
        self,
        config_reader=None,
        application_history_tracker=None,
        submission_queue_tracker=None,
        activity_callback: Optional[Callable] = None,
        browser_operator=None,
    ):
        """
        Initialize the question filler

        Args:
            config_reader: Configuration reader (v2 structure that reads from DB)
            application_history_tracker: Application history tracker
            submission_queue_tracker: Submission queue tracker
            activity_callback: Callback for sending activity messages
            browser_operator: Browser operator for page access
        """
        self.config_reader = config_reader
        self.application_history_tracker = application_history_tracker
        self.submission_queue_tracker = submission_queue_tracker
        self.activity_callback = activity_callback
        self.browser_operator = browser_operator

    def send_activity(self, message: str, activity_type: str = ActivityType.ACTION):
        """Send activity message if callback is available"""
        if self.activity_callback:
            self.activity_callback(message, activity_type)
        else:
            logger.info(f"[{activity_type.upper()}] {message}")

    def detect_question_type(self, question_element: Locator) -> str:
        """
        Detect the type of question based on the element.
        Simplified placeholder until LinkedIn form handling is expanded.
        """
        # TODO: Implement proper question type detection based on LinkedIn
        # form structure
        # For now, return INPUT as default
        return QuestionType.INPUT

    def construct_question_filler(
        self,
        question: Locator,
        question_text: str,
        question_type: str,
        app_history_id: str,
    ):
        """Construct the appropriate question filler based on question type"""
        if question_type == QuestionType.SELECT:
            return SelectionQuestionFiller(
                self.config_reader,
                question,
                question_text,
                question_type,
                app_history_id,
                self.application_history_tracker,
                self.submission_queue_tracker,
            )
        elif question_type == QuestionType.INPUT:
            return InputQuestionFiller(
                self.config_reader,
                question,
                question_text,
                question_type,
                app_history_id,
                self.application_history_tracker,
                self.submission_queue_tracker,
                self.browser_operator,
            )
        elif question_type == QuestionType.RADIO:
            return RadioQuestionFiller(
                self.config_reader,
                question,
                question_text,
                question_type,
                app_history_id,
                self.application_history_tracker,
                self.submission_queue_tracker,
                self.browser_operator,
            )
        elif question_type == QuestionType.MULTI_LINE_INPUT:
            return MultiLineInputQuestionFiller(
                self.config_reader,
                question,
                question_text,
                question_type,
                app_history_id,
                self.application_history_tracker,
                self.submission_queue_tracker,
                self.browser_operator,
            )
        elif question_type == QuestionType.MULTI_SELECT:
            return MultiSelectionQuestionFiller(
                self.config_reader,
                question,
                question_text,
                question_type,
                app_history_id,
                self.application_history_tracker,
                self.submission_queue_tracker,
                self.browser_operator,
            )
        else:
            raise ValueError(f"Unknown question type: {question_type}")

    def fill_question(
        self,
        question_element: Locator,
        question_text: str,
        question_type: str,
        app_history_id: str,
    ) -> Answer:
        """
        Fill a question in the job application form

        Args:
            question_element: The DOM element for the question
            question_text: The text of the question
            question_type: Type of question (input, select, etc.)
            app_history_id: ID of the job being applied to

        Returns:
            Answer object with the response
        """
        filler = self.construct_question_filler(
            question_element, question_text, question_type, app_history_id
        )

        self.send_activity(f"Filling question: {question_text}")

        answer = filler.fill_question()

        if answer.thinking:
            self.send_activity(answer.thinking, ActivityType.THINKING)

        # Create unified confidence message format (ASCII-safe)
        if answer.answer and answer.answer.strip():
            if answer.confident:
                msg = f"Answer: `{answer.answer}` (confident)"
            else:
                msg = f"Answer: `{answer.answer}` (not confident)"
        else:
            if answer.confident:
                msg = "Confident (no answer provided)"
            else:
                msg = "Not confident (no answer provided)"

        # Add reference information if available
        if answer.reference and answer.reference.strip():
            msg += f", Reference: {answer.reference}"
        elif answer.confident and answer.answer and answer.answer.strip():
            # Provide a default reference for confident answers that don't have one
            msg += ", Reference: AI analysis"

        # Add warning for non-confident answers
        if not answer.confident:
            msg += " - This application will not be submitted."

        self.send_activity(msg, ActivityType.RESULT)
        return answer

    def empty_question(
        self,
        question: Locator,
        question_text: str,
        question_type: str,
        app_history_id: str,
    ):
        """Empty a question (fill with empty string for optional fields)"""
        filler = self.construct_question_filler(
            question, question_text, question_type, app_history_id
        )
        if question_type in {QuestionType.INPUT, QuestionType.MULTI_LINE_INPUT}:
            # fill with empty string
            activity_msg = (
                "Filling question: "
                f"{question_text} with empty string since it's optional"
            )
            self.send_activity(activity_msg)
            filler.fill_value(Answer("", "", False))

    def fill_cover_letter_question(
        self,
        question: Locator,
        question_text: str,
        question_type: str,
        app_history_id: str,
        position_info: dict,
    ):
        """
        Fill cover letter question - looks up submission queue for existing cover letter
        """
        answer = Answer("", "", False)
        filler = self.construct_question_filler(
            question, question_text, question_type, app_history_id
        )

        self.send_activity(f"Filling question: {question_text}")
        self.send_activity("Thinking...", ActivityType.THINKING)

        cover_letter = self.maybe_get_cover_letter_from_submission_queue(app_history_id)
        if not cover_letter:
            cover_letter, _ = self.generate_cover_letter(
                position_info, app_history_id=app_history_id
            )

        answer = Answer(cover_letter, "", True)
        filler.fill_value(answer)
        filler.add_log(answer, ai_gen=True)
        return answer

    def maybe_get_cover_letter_from_submission_queue(self, app_history_id: str) -> str:
        """Get cover letter from submission queue if it exists"""
        if not self.submission_queue_tracker:
            return ""

        cover_letter = (
            self.submission_queue_tracker.submission_queue.get(app_history_id, {})
            .get("questions_and_answers", {})
            .get("cover letter", {})
            .get("answer", "")
        )
        if cover_letter:
            logger.info(
                "Using cover letter from submission queue for job %s",
                app_history_id,
            )
        return cover_letter

    def generate_cover_letter(
        self,
        position_info: dict,
        pdf_path: Optional[str] = None,
        app_history_id: Optional[str] = None,
    ) -> tuple[str, str]:
        """Generate cover letter using AI"""
        self.send_activity("Generating cover letter")

        # Call AI engine through service gateway
        from services.ai_engine_client import AIEngineClient  # noqa: E402

        ai_client = AIEngineClient()

        # Create prompt for cover letter generation
        prompt = (
            "Generate a professional cover letter for this position:\n\n"
            f"Position: {position_info.get('title', 'Unknown Position')}\n"
            f"Company: {position_info.get('company', 'Unknown Company')}\n"
            "Description: "
            f"{position_info.get('description', 'No description available')}\n\n"
            "Please write a compelling cover letter that highlights "
            "relevant experience and shows enthusiasm for the role."
        )

        system_context = (
            "You are a professional cover letter writer. Write "
            "personalized, compelling cover letters that help "
            "candidates stand out."
        )

        format_spec = {
            "type": "object",
            "properties": {
                "cover_letter": {"type": "string"},
                "applicant_name": {"type": "string"},
            },
            "required": ["cover_letter", "applicant_name"],
        }

        ai_result = ai_client.call_ai(
            prompt=prompt,
            system=system_context,
            format=format_spec,
            model=(
                self.config_reader.model.name
                if self.config_reader and hasattr(self.config_reader, "model")
                else "gpt-4.1"
            ),
            additional_system_prompt=(
                self.config_reader.model.additional_system_prompt
                if self.config_reader and hasattr(self.config_reader, "model")
                else ""
            ),
            retry_times=3,
            application_id=app_history_id,
        )

        # Extract results from AI response
        if ai_result and isinstance(ai_result, dict):
            cover_letter = ai_result.get(
                "cover_letter", "Cover letter generation failed"
            )
            applicant_name = ai_result.get("applicant_name", "Applicant")
        else:
            # Fallback if AI call fails
            cover_letter = (
                "I am writing to express my interest in this position. "
                "I believe my skills and experience make me a strong "
                "candidate for this role."
            )
            applicant_name = "Applicant"

        return cover_letter, applicant_name
