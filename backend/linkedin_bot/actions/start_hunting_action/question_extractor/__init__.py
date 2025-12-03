import logging

from browser.automation import Locator
from shared.question_filler.question_type import QuestionType

logger = logging.getLogger(__name__)


class QuestionExtractor:
    def __init__(self, question: Locator):
        self.question = question
        self.question_text = None
        self.question_type = None
        self.required: bool = None

    @staticmethod
    def create(question: Locator):
        """Create and initialize a QuestionExtractor with sync operations"""
        try:
            extractor = QuestionExtractor(question)
            extractor.question_text = extractor.extract_question()
            extractor.question_type = extractor.get_question_type()
            extractor.required = extractor.is_required()
            return extractor
        except Exception as e:
            logger.error(f"Failed to create QuestionExtractor: {e}")
            # Return a fallback extractor with default values
            extractor = QuestionExtractor(question)
            extractor.question_text = "Unknown question"
            extractor.question_type = QuestionType.UNKNOWN
            extractor.required = False
            return extractor

    def extract_question(self):
        # check if there is a span with the question text
        span = self.question.locator("span")
        if span.count() > 0:
            self.question_text = span.first.inner_text()
        else:
            self.question_text = self.question.inner_text()
            self.question_text = (
                self.question_text.strip() if self.question_text else ""
            )
        # Clean up the question text
        # First strip leading/trailing whitespace and newlines
        self.question_text = self.question_text.strip()

        # Replace internal newlines with spaces and clean up extra whitespace
        self.question_text = " ".join(self.question_text.split())

        # Check if the question text is duplicate (e.g. "What is your name?What is your name?")  # noqa: E501
        # Handle cases where duplicates might have slight whitespace differences
        if len(self.question_text) > 0:
            mid_point = len(self.question_text) // 2
            first_half = self.question_text[:mid_point].strip()
            second_half = self.question_text[mid_point:].strip()

            # Check if first half equals second half (ignoring whitespace)
            if first_half == second_half and len(first_half) > 0:
                self.question_text = first_half

        # Final cleanup - strip any remaining whitespace
        self.question_text = self.question_text.strip()
        if not self.question_text:
            previous_element = self.question.locator("xpath=..").locator(
                "xpath=preceding-sibling::*[1]"
            )
            # check if the previous element has class jobs-easy-apply-form-section__group-subtitle or jobs-easy-apply-form-section__group-title  # noqa: E501
            if (
                "jobs-easy-apply-form-section__group-subtitle"
                in previous_element.get_attribute("class")
                or "jobs-easy-apply-form-section__group-title"
                in previous_element.get_attribute("class")
            ):
                self.question_text = previous_element.text_content()
                # remove ending *
                self.question_text = self.question_text.rstrip("*")
                # if it is subtitle, continue to check the previous element
                if (
                    "jobs-easy-apply-form-section__group-subtitle"
                    in previous_element.get_attribute("class")
                ):
                    subtitle = previous_element.text_content()
                    # remove ending *
                    subtitle = subtitle.rstrip("*")
                    previous_element = previous_element.locator(
                        "xpath=preceding-sibling::*[1]"
                    )
                    # check if previous element has class jobs-easy-apply-form-section__group-title  # noqa: E501
                    if (
                        "jobs-easy-apply-form-section__group-title"
                        in previous_element.get_attribute("class")
                    ):
                        title = previous_element.text_content()
                        # remove ending *
                        title = title.rstrip("*")
                        self.question_text = f"{title} {subtitle}"
            else:
                logger.warning(
                    f"No question text found for question: {self.question.text_content().strip()}"  # noqa: E501
                )
        return self.question_text

    def get_question_type(self):
        if self.question.locator("select").count() > 0:
            self.question_type = QuestionType.SELECT
        elif (
            self.question.locator("input").count() == 1
            and self.question.locator("input").first.get_attribute("type") == "text"
        ):
            placeholder = self.question.locator("input").first.get_attribute(
                "placeholder"
            )
            if placeholder:
                self.question_text = f"{self.question_text} (e.g. {placeholder})"
                logger.info(f"added placeholder to question text: {self.question_text}")
            self.question_type = QuestionType.INPUT
        elif (
            self.question.locator("input").count() > 1
            and self.question.locator("input").first.get_attribute("type") == "radio"
        ):
            self.question_type = QuestionType.RADIO
        elif (
            self.question.locator("input").count() >= 1
            and self.question.locator("input").first.get_attribute("type") == "checkbox"
        ):
            self.question_type = QuestionType.MULTI_SELECT
        elif self.question.locator("textarea").count() > 0:
            self.question_type = QuestionType.MULTI_LINE_INPUT
        else:
            self.question_type = QuestionType.UNKNOWN
        return self.question_type

    def is_required(self):
        question_text = self.question.text_content()
        self.required = "required" in question_text.strip().lower()

        if self.required:
            return self.required

        if self.question_type == QuestionType.INPUT:
            input_element = self.question.locator("input").first
            if (
                input_element.get_attribute("required") == ""
                or input_element.get_attribute("aria-required") == "true"
            ):
                self.required = True
        elif self.question_type == QuestionType.MULTI_LINE_INPUT:
            textarea_element = self.question.locator("textarea").first
            if (
                textarea_element.get_attribute("required") == ""
                or textarea_element.get_attribute("aria-required") == "true"
            ):
                self.required = True
        elif self.question_type == QuestionType.SELECT:
            select_element = self.question.locator("select").first
            if (
                select_element.get_attribute("required") == ""
                or select_element.get_attribute("aria-required") == "true"
            ):
                self.required = True
        elif self.question_type == QuestionType.MULTI_SELECT:
            element = self.question.locator("legend")
            if element.count() > 0:
                element_text = element.text_content()
                if "required" in element_text:
                    self.required = True

        elif self.question_type == QuestionType.RADIO:
            radio_element = self.question.locator("input").first
            if (
                radio_element.get_attribute("required") == ""
                or radio_element.get_attribute("aria-required") == "true"
            ):
                self.required = True

        return self.required
