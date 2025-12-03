import logging

from shared.question_filler.answer import Answer
from shared.question_filler.faq_question_type_mapping import (
    FaqQuestionType,
    get_faq_question_type,
)
from shared.question_filler.question_filler_basic.question_filller_basic import (
    QuestionFillerBasic,
)

logger = logging.getLogger(__name__)


class SelectionQuestionFiller(QuestionFillerBasic):
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
        # Initialize options - will be populated async
        self.options = []

    def _initialize_options(self):
        """Initialize options from select element"""  # noqa: E402
        try:
            select_element = self.question.locator("select")
            select_count = select_element.count()
            if select_count > 0:
                first_select = select_element.first
                option_elements = first_select.locator("option")
                option_texts = option_elements.all_text_contents()
                self.options = [
                    o.strip()
                    for o in option_texts
                    if o.strip() and o.strip().lower() != "select an option"
                ]
        except Exception as e:
            logger.error(f"Failed to initialize options: {e}")
            self.options = []

    def fill_value(self, value: Answer) -> Answer:
        try:
            select_element = self.question.locator("select")
            select_count = select_element.count()
            if select_count > 0:
                first_element = select_element.first
                first_count = first_element.count()
                if first_count > 1:
                    logger.warning(
                        "Found more than 1 select element, using the first one"
                    )
                    select_element = first_element
                if self.browser_operator:
                    self.browser_operator.op(
                        select_element.select_option, value=value.answer
                    )
                else:
                    select_element.select_option(value=value.answer)
                return value
            else:
                logger.error(
                    f"No select element found for question: {self.question_text}, value: {value}"  # noqa: E501
                )
                return Answer("", "", False)
        except Exception:
            return Answer("", "", False)

    def select_option_by_ai(self) -> Answer:
        ideal_answer = self.generate_text_answer()
        # load the template
        system_context = "You are filling out a job application form."
        format = {
            "type": "object",
            "properties": {"option_value": {"type": "string", "enum": self.options}},
            "required": ["option_value"],
        }
        context = {
            "ideal_answer": ideal_answer.answer,
            "options": self.options,
        }
        prompt = f"context={context}, please select the closest match to the ideal answer from the options."  # noqa: E501
        # Call AI engine through service gateway
        from services.ai_engine_client import AIEngineClient  # noqa: E402

        ai_client = AIEngineClient()
        ai_result = ai_client.call_ai(
            prompt=prompt,
            system=system_context,
            format=format,
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
            application_id=self.app_history_id,
        )

        # Extract answer from AI result
        if ai_result and isinstance(ai_result, dict):
            answer = ai_result
        else:
            # Fallback if AI call fails
            answer = {"option_value": self.options[0] if len(self.options) > 0 else ""}
        answer_str = (
            answer.get("option_value", "") if isinstance(answer, dict) else answer
        )
        if isinstance(answer, str):
            logger.warning(
                f"Answer {answer} is not a dictionary, using the answer directly."
            )

        if answer_str not in self.options:
            logger.warning(
                f"Failed to select option {answer_str} from options: {self.options}. Try again without json format."  # noqa: E501
            )
            # Fallback to first option
            answer_str = self.options[0] if len(self.options) > 0 else ""
            if answer_str not in self.options and len(self.options) > 0:
                # try to select the second option
                answer_str = self.options[0]
                logger.warning(
                    f"Answer {answer_str} not in options: {self.options}, using the second option: {answer_str}"  # noqa: E501
                )
        return Answer(
            answer_str,
            ideal_answer.reference,
            ideal_answer.confident,
            ideal_answer.thinking,
        )

    def try_predefined_select_answer(self) -> Answer:
        answer = Answer("", "", False)
        # switch case on the question_text
        if (
            self.question_text in self.config_reader.profile.faq_template
            and self.config_reader.profile.faq_template[self.question_text].get(
                "answer", ""
            )
            in self.options
        ):
            if (
                self.config_reader.profile.faq_template[self.question_text].get(
                    "question_type", get_faq_question_type(self.question_type)
                )
                != FaqQuestionType.DROPDOWN
            ):
                logger.warning(
                    f"Question {self.question_text} is not a dropdown question, skipping"  # noqa: E501
                )
                return answer
            answer = Answer(
                self.config_reader.profile.faq_template[self.question_text].get(
                    "answer", ""
                ),
                f"From FAQ: {self.question_text}",
                True,
            )
        elif "email address" in self.question_text:
            # pick the second option (first option is "Select an option")
            select_element = self.question.locator("select").first
            select_count = select_element.count()
            if select_count > 0 and len(self.options) > 0:
                answer = Answer(
                    self.options[0], f"From FAQ: {self.question_text}", True
                )
            else:
                logger.error(
                    f"No select element found for question: {self.question_text}"  # noqa: E501
                )
        return answer

    def fill_question(self) -> Answer:
        # Initialize options first
        self._initialize_options()

        answer = self.fill_question_helper(
            self.fill_value,
            self.try_predefined_select_answer,
            self.select_option_by_ai,
        )
        return answer
