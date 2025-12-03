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


class RadioQuestionFiller(QuestionFillerBasic):
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
        """Initialize options from label elements"""  # noqa: E402
        try:
            label_elements = self.question.locator("label")
            labels = label_elements.all()
            self.options = []
            for label in labels:
                text = label.text_content()
                if text:
                    self.options.append(text.strip())
        except Exception as e:
            logger.error(f"Failed to initialize options: {e}")
            self.options = []

    def fill_value(self, value: Answer) -> Answer:
        answer = value
        input_element = self.question.locator("input").first
        input_count = input_element.count()
        if input_count > 0:
            try:
                idx = self.options.index(value.answer)
                if idx >= 0:
                    input_nth = self.question.locator("input").nth(idx)
                    if self.browser_operator:
                        self.browser_operator.op(input_nth.check, force=True)
                    else:
                        input_nth.check(force=True)
                else:
                    logger.error(
                        f"Option {value.answer} not found in options: {self.options}"
                    )
                    answer = Answer("", "", False)
            except Exception as e:
                logger.error(f"Error checking radio option: {e}, value: {value.answer}")
                answer = Answer("", "", False)
        else:
            logger.error(
                f"No select element found for question: {self.question_text}, value: {value.answer}"  # noqa: E501
            )
            answer = Answer("", "", False)
        return answer

    def select_option_by_ai(self) -> Answer:
        ideal_answer = self.generate_text_answer()
        # load the template
        system_context = "You are filling out a job application form."
        format = {
            "type": "object",
            "properties": {"option_value": {"type": "string", "enum": self.options}},
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
            answer = ai_result.get("option_value", "")
        else:
            # Fallback if AI call fails
            answer = self.options[0] if len(self.options) > 0 else ""
        if answer not in self.options:
            logger.warning(
                f"Failed to select option {answer} from options: {self.options}. Try again without json format."  # noqa: E501
            )
            # Fallback to first option
            answer = self.options[0] if len(self.options) > 0 else ""
            if answer not in self.options:
                # try to select the first option
                logger.warning(
                    f"Answer {answer} not in options: {self.options}, using the first option: {self.options[0]}"  # noqa: E501
                )
                answer = Answer(self.options[0], ideal_answer.reference, False)
        return Answer(
            answer,
            ideal_answer.reference,
            ideal_answer.confident,
            ideal_answer.thinking,
        )

    def try_predefined_select_answer(self) -> Answer:
        answer = Answer("", "", False)
        # switch case on the question_text
        if self.question_text in self.config_reader.profile.faq_template:
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
            answer_str = self.config_reader.profile.faq_template[
                self.question_text
            ].get("answer", "")
            if answer_str in self.options:
                answer = Answer(
                    answer_str,
                    f"From FAQ: {self.question_text}",
                    True,
                    "Trying to fill from FAQ",  # noqa: E402
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
