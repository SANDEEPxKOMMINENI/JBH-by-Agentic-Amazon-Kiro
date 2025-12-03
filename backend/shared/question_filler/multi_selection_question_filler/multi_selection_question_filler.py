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


class MultiSelectionQuestionFiller(QuestionFillerBasic):
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

    def fill_value(self, answer: Answer) -> Answer:
        new_answers = []
        for value in answer.answer:
            if value not in self.options:
                logger.error(f"Value {value} not in options: {self.options}, skipping")
                continue
            idx = self.options.index(value)
            input_element = self.question.locator("input").nth(idx)
            input_count = input_element.count()
            if input_count == 1:
                if self.browser_operator:
                    self.browser_operator.op(input_element.check, force=True)
                else:
                    input_element.check(force=True)
                new_answers.append(value)
            elif input_count > 1:
                logger.warning(
                    f"Multiple input elements found for question: {self.question_text}, value: {value.answer}"  # noqa: E501
                )
            else:
                logger.error(
                    f"No select element found for question: {self.question_text}, value: {value}"  # noqa: E501
                )
        return Answer(new_answers, answer.reference, answer.confident)

    def select_options_by_ai(self) -> Answer:
        ideal_answer = self.generate_text_answer()
        # load the template
        system_context = "You are filling out a job application form."
        format = {
            "type": "array",
            "items": {"type": "string", "enum": self.options},
            "minItems": 1,
            "required": True,
        }
        context = {"ideal_answer": ideal_answer.answer, "options": self.options}
        prompt = f"context={context}, please select at least one option that matches to the ideal answer from the options."  # noqa: E501
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

        # Extract answers from AI result
        if ai_result and isinstance(ai_result, list):
            answers = ai_result
        elif ai_result and isinstance(ai_result, dict) and "answers" in ai_result:
            answers = ai_result["answers"]
        else:
            # Fallback if AI call fails
            answers = [self.options[0]] if len(self.options) > 0 else []
        selected_options = []
        for answer in answers:
            if answer not in self.options:
                logger.warning(
                    f"Failed to select option {answer} from options: {self.options}. Try again without json format."  # noqa: E501
                )
                continue
            selected_options.append(answer)
        if not selected_options and len(self.options) > 0:
            # select second option
            selected_options.append(self.options[0])
            logger.warning(
                f"Failed to select option {answers} from options: {self.options}, using the second option: {selected_options}"  # noqa: E501
            )
        return Answer(
            selected_options,
            ideal_answer.reference,
            ideal_answer.confident,
            ideal_answer.thinking,
        )

    def try_predefined_select_answer(self) -> Answer:
        answer = Answer([], "", False)
        # switch case on the question_text
        if self.question_text in self.config_reader.profile.faq_template:
            if (
                self.config_reader.profile.faq_template[self.question_text].get(
                    "question_type", get_faq_question_type(self.question_type)
                )
                != FaqQuestionType.MULTIPLE_CHOICE
            ):
                logger.warning(
                    f"Question {self.question_text} is not a multiple choice question, skipping"  # noqa: E501
                )
                return answer
            answer_dict: dict = self.config_reader.profile.faq_template[
                self.question_text
            ]
            if isinstance(answer_dict, str):
                answer_dict = {
                    "answer": [answer_dict],
                    "reference": "",
                    "confident": True,
                }
            for answer_str in answer_dict.get("answer"):
                if answer_str not in self.options:
                    logger.warning(
                        f"Answer {answer_str} not in options: {self.options}, skipping"
                    )
                    continue
                answer.answer.append(answer_str)
                answer.reference = f"From FAQ: {self.question_text}"
                answer.confident = True
        return answer

    def fill_question(self) -> Answer:
        # Initialize options first
        self._initialize_options()

        answer = self.fill_question_helper(
            self.fill_value,
            self.try_predefined_select_answer,
            self.select_options_by_ai,
        )
        return answer
