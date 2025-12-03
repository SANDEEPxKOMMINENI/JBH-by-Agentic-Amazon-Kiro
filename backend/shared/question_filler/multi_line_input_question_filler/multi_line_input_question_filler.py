import logging
import time
from typing import List, Tuple

from shared.question_filler.answer import Answer
from shared.question_filler.faq_question_type_mapping import (
    FaqQuestionType,
    get_faq_question_type,
)
from shared.question_filler.question_filler_basic.question_filller_basic import (
    QuestionFillerBasic,
)

logger = logging.getLogger(__name__)


class MultiLineInputQuestionFiller(QuestionFillerBasic):
    def __init__(
        self,
        config_reader,
        question,
        question_text,
        question_type,
        app_history_id,
        application_history_tracker,
        submission_queue_tracker,
        browser_operator=None,
    ):
        super().__init__(
            config_reader,
            question,
            question_text,
            question_type,
            app_history_id,
            application_history_tracker,
            submission_queue_tracker,
        )
        self.browser_operator = browser_operator
        self.cached_faq = {}  # Initialize cached_faq

    def fill_value(self, value: Answer):
        element = self.question.locator("textarea")
        element_count = element.count()
        if element_count == 1 and isinstance(value.answer, str):
            first_element = element.first
            first_count = first_element.count()
            if first_count > 1:
                logger.warning(
                    "Found more than 1 textarea element, using the first one"
                )
                element = first_element
            if self.browser_operator:
                self.browser_operator.op(element.fill, value=value.answer)
            else:
                element.fill(value.answer)
        else:
            logger.error(
                f"No input element found for question: {self.question_text}, value: {value}"  # noqa: E501
            )

    def fill_value_with_ai_retry(self, value: Answer, num_retries: int = 3) -> Answer:
        retry_errors: List[Tuple[Answer, str]] = []
        answer = value
        for _ in range(num_retries):
            self.fill_value(answer)
            answer = self.maybe_triggered_list_answer(answer)
            # blur the textarea
            if self.browser_operator:
                self.browser_operator.op(self.question.locator("textarea").first.blur)
            else:
                self.question.locator("textarea").first.blur()
            error_message = self.maybe_error_message(answer)
            if error_message:
                retry_errors.append((answer, error_message))
                answer = self.fill_input_by_ai(retry_errors=retry_errors)
            else:
                break
        return answer

    def fill_input_by_ai(self, retry_errors: list = []) -> Answer:
        answer = self.generate_text_answer()
        return answer

    def try_predefined_input_answer(self) -> Answer:
        answer = Answer("", "", False)
        # switch case on the question_text
        if self.question_text in self.config_reader.profile.faq_template:
            if (
                self.config_reader.profile.faq_template[self.question_text].get(
                    "question_type", get_faq_question_type(self.question_type)
                )
                != FaqQuestionType.TEXT_INPUT
            ):
                logger.warning(
                    f"Question {self.question_text} is not a text input, skipping"
                )
                return answer
            answer = Answer(
                self.config_reader.profile.faq_template[self.question_text].get(
                    "answer", ""
                ),
                f"From FAQ: {self.question_text}",
                True,
                "Trying to fill from FAQ",  # noqa: E402
            )
        return answer

    def maybe_triggered_list_answer(self, answer: Answer) -> Answer:
        # pick the first option
        time.sleep(0.5)
        option = self.question.locator(".basic-typeahead__selectable")
        option_count = option.count()
        if option and option_count > 0:
            first_option = option.first
            text_content = first_option.text_content()
            answer = Answer(
                text_content.strip(),
                answer.reference,
                answer.confident,
            )
            if self.browser_operator:
                self.browser_operator.op(first_option.click)
            else:
                first_option.click()
        return answer

    def maybe_error_message(self, answer: Answer) -> str:
        # check if alert is present
        alert = self.question.get_by_role("alert")
        alert_count = alert.count()
        if alert and alert_count > 0:
            first_alert = alert.first
            text_content = first_alert.text_content()
            return text_content.strip()

        # check if returned answer is empty
        if not answer:
            return "No answer found"

        # check if returned json like format, have a balanced number of { and }
        answer_str = str(answer.answer)
        if answer_str.count("{") > 0 and answer_str.count("{") == answer_str.count("}"):
            return "Returned a json like format instead of plain text, please fix it"

        return ""  # Ensure a string is always returned

    def fill_question(self) -> Answer:
        answer = self.fill_question_helper(
            self.fill_value_with_ai_retry,
            self.try_predefined_input_answer,
            self.fill_input_by_ai,
        )
        return answer
