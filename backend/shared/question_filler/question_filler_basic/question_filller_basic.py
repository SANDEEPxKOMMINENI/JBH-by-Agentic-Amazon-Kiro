import json
import logging
import os
from datetime import datetime
from typing import Callable, List, Union

from browser.automation import Locator  # pylint: disable=import-error
from constants import OUTPUT_DIR
from shared.question_filler.answer import Answer  # noqa: E402
from shared.question_filler.faq_question_type_mapping import (  # noqa: E402
    get_faq_question_type,
)
from shared.question_filler.question_type import QuestionType  # noqa: E402

logger = logging.getLogger(__name__)


class QuestionFillerBasic:
    def __init__(
        self,
        config_reader,
        question: Locator,
        question_text: str,
        question_type: str,
        app_history_id: str,
        application_history_tracker,
        submission_queue_tracker,
    ):
        self.app_history_id = app_history_id
        self.config_reader = config_reader
        self.question = question
        self.question_text = question_text.lower()
        self.question_type = question_type
        today = datetime.now().strftime("%Y-%m-%d")

        # Create output directory structure if needed
        question_filler_dir = os.path.join(OUTPUT_DIR, "question_filler")
        if not os.path.exists(question_filler_dir):
            logger.info(f"Creating question filler directory: {question_filler_dir}")
            os.makedirs(question_filler_dir)
        self.log_path = os.path.join(question_filler_dir, f"{today}.log")

        self.application_history_tracker = application_history_tracker
        self.submission_queue_tracker = submission_queue_tracker
        self.options = None

    def add_log(self, answer: Union[Answer, list[Answer]], ai_gen=False):
        """Add log entry for the question and answer - matches v1's behavior"""
        options = []
        if (
            self.question_type
            in {
                QuestionType.MULTI_SELECT,
                QuestionType.RADIO,
                QuestionType.SELECT,
            }
            and self.options is not None
        ):
            options = self.options

        # Extract answer data
        answer_str = ""
        reference_str = ""
        confident_str = ""
        if isinstance(answer, Answer):
            answer_str = answer.answer
            reference_str = answer.reference
            confident_str = answer.confident
        if isinstance(answer, list):
            answer_str = ", ".join([a.answer for a in answer])
            reference_str = answer[0].reference if answer else ""
            confident_str = all(a.confident for a in answer) if answer else False

        # Create log entry matching v1's format
        new_log = {
            "question": self.question_text,
            "question_type": get_faq_question_type(self.question_type),
            "answer": answer_str,
            "reference": reference_str,
            "confident": confident_str,
            "ai_generated": ai_gen,
            "options": options,
        }

        # Log to file (with timestamp for debugging)
        log_entry_with_timestamp = {
            "timestamp": datetime.now().isoformat(),
            **new_log,
            "app_history_id": self.app_history_id,
            "options": options,
        }

        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(log_entry_with_timestamp) + "\n")
        except Exception as e:
            logger.error(f"Failed to write log: {e}")

        # Update application history tracker (matching v1's add_log_helper)
        if self.application_history_tracker and self.app_history_id:
            try:
                # Get existing Q&A list for this job
                job_data = self.application_history_tracker.application_history
                history_qna = job_data.get(self.app_history_id, {}).get(
                    "questions_and_answers", []
                )

                # Append new Q&A to existing list and deduplicate
                updated_qna = history_qna + [new_log]
                deduplicated_qna = (
                    self.application_history_tracker.deduplicate_questions_and_answers(
                        updated_qna
                    )
                )

                self.application_history_tracker.update_application(
                    self.app_history_id,
                    "questions_and_answers",
                    deduplicated_qna,
                )
            except Exception as e:
                logger.error(f"Failed to update application history: {e}")

        # Update submission queue tracker (if available)
        if self.submission_queue_tracker and self.app_history_id:
            try:
                # Get existing submission Q&A dict for this job
                queue_data = self.submission_queue_tracker.submission_queue
                submission_qna = queue_data.get(self.app_history_id, {}).get(
                    "questions_and_answers", {}
                )

                # Add this Q&A to submission queue (keyed by question text)
                submission_entry = new_log.copy()
                submission_entry["question_text"] = submission_entry.pop("question")
                if options:
                    submission_entry["options"] = options

                submission_qna[self.question_text] = submission_entry

                self.submission_queue_tracker.update_submission_item(
                    self.app_history_id,
                    "questions_and_answers",
                    submission_qna,
                )
            except Exception as e:
                logger.error(f"Failed to update submission queue: {e}")

    def create_system_context(
        self, processed_question_text: str, system_context_material: List[str] = None
    ) -> str:
        if not system_context_material:
            # Simplified for v2 - use basic context if config_reader is available
            if self.config_reader and hasattr(self.config_reader, "profile"):
                filtered_faq_template = {}
                resume = {}
                additional_info = ""

                if hasattr(self.config_reader.profile, "faq_template"):
                    # only use faq with aligned question type
                    filtered_faq_template = {
                        k: v
                        for k, v in self.config_reader.profile.faq_template.items()
                        if get_faq_question_type(
                            v.get("question_type", self.question_type)
                        )
                        == get_faq_question_type(self.question_type)
                    }

                if hasattr(self.config_reader.profile, "resume"):
                    resume = self.config_reader.profile.resume

                if hasattr(self.config_reader.profile, "additional_profile_info"):
                    additional_info = self.config_reader.profile.additional_profile_info

                if "mm/dd/yyyy" in processed_question_text.lower():
                    resume = {}

                system_context_material = [
                    f"FAQ={json.dumps(filtered_faq_template)}",
                    f"Resume={json.dumps(resume)}",
                    f"Additional Profile Info={additional_info}",
                    f"today={datetime.now().strftime('%Y-%m-%d')}",
                    (
                        "return an answer, reference copy from given materials, "
                        "and whether you are extremely confident about the "
                        "answer in json format. If you can't find strong "
                        "reference then it's not confident and the reference "
                        "can't be the question text itself."
                    ),
                ]
            else:
                # Fallback for when config_reader is not available
                system_context_material = [
                    f"today={datetime.now().strftime('%Y-%m-%d')}",
                    (
                        "return an answer, reference copy from given materials, "
                        "and whether you are extremely confident about the "
                        "answer in json format. If you can't find strong "
                        "reference then it's not confident."
                    ),
                ]
        return (
            "This is your personal information:\n"
            f"{system_context_material}. "
            "You are filling out a job application form."
        )

    def _normalize_text(self, text: str) -> str:
        """Normalize text for exact matching by lowercasing and removing extra whitespace"""
        return " ".join(text.lower().split())

    def try_return_exact_match(self, threshold: float = 1) -> Answer:
        # Normalize question text once
        normalized_question = self._normalize_text(self.question_text)

        # Check FAQ templates for exact match
        faq_keys = [
            k
            for k, v in self.config_reader.profile.faq_template.items()
            if v
            and get_faq_question_type(v.get("question_type", self.question_type))
            == get_faq_question_type(self.question_type)
        ]

        for key in faq_keys:
            if self._normalize_text(key) == normalized_question:
                answer = self.config_reader.profile.faq_template[key]
                reference = f"From FAQ: {key}"
                return Answer(answer, reference, True)

        return Answer("", "", False)

    def preprocess_question_text(self):
        if "how many years of work experience do you have with" in self.question_text:
            processed_question_text = self.question_text.replace(
                "how many years of work experience do you have with",
                "Yr of Exp with",
            )
        elif "earliest start date" in self.question_text:
            processed_question_text = self.question_text.replace(
                "earliest start date",
                f"earliest start date to start working (has to be later than {datetime.now().strftime('%Y-%m-%d')})",  # noqa: E501
            )
        else:
            processed_question_text = self.question_text
        return processed_question_text

    def create_prompt(self, processed_question_text: str, retry_errors: list = []):
        prompt = f"Answer the following question: {self.question_text}"
        prompt += "\n\nIf you are not confident about any answer, return 'None', 'No' or other appropriate word"  # noqa: E501
        prompt += (
            "\nbut don't return empty string or say not provided or say not applicable."
        )
        prompt += "\nMake sure to return a plain text format as straight answer"
        if retry_errors:
            prompt = f"Answer the following question without explanation: {processed_question_text}\n\n Make sure {retry_errors[-1][1]}"  # noqa: E501
        return prompt

    def preprocess_format(
        self, processed_question_text: str, format: str, retry_errors: list = []
    ):
        if retry_errors:
            last_error = retry_errors[-1][1]
            if "Enter a decimal number" in last_error:
                # change answer to number
                format["properties"]["answer"]["type"] = "number"
                logger.info(f"Detected error: {last_error}, using format: {format}")
        if "how many year" in processed_question_text.lower():
            format["properties"]["answer"]["type"] = "number"
            logger.info(
                "Detected question related to year, replace answer type to number"
            )
        if "mm/dd/yyyy" in processed_question_text.lower():
            format: dict = {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "object",
                        "properties": {
                            "day": {"type": "number", "enum": list(range(1, 32))},
                            "month": {"type": "number", "enum": list(range(1, 13))},
                            "year": {"type": "number", "enum": list(range(1900, 2100))},
                        },
                        "required": ["day", "month", "year"],
                    },
                    "reference": {
                        "type": "string",
                        "description": "original reference copy that supports the answer. Must be in format of 'From XXX: <original reference in plain text (not json)>'",  # noqa: E501
                        "maxLength": 100,
                    },
                    "confident": {
                        "type": "boolean",
                        "description": "whether you are extremely confident about the answer. If you can't find any reference or the answer is None, then it's not confident",  # noqa: E501
                    },
                },
                "required": ["answer", "reference", "confident"],
            }
            logger.info(
                "Detected question related to date, replace answer type to date"
            )
        if self.config_reader.model.name == "gpt-4.1":
            format["properties"]["thinking"] = {
                "type": "string",
                "description": "explain me why you are confident or not"
                "and how you come up with the answer in 1-2 sentences. "
                "If you can't find any reference, just say 'No reference found'",
            }
        return format

    def postprocess_answer(self, answer: dict, format: str):
        if not isinstance(answer.get("answer", {}), dict):
            return answer
        if (
            "day" in answer.get("answer", {})
            and "month" in answer.get("answer", {})
            and "year" in answer.get("answer", {})
        ):
            # pad day and month with 0 if they are less than 10
            answer[
                "answer"
            ] = f"{answer['answer']['month']:02d}/{answer['answer']['day']:02d}/{answer['answer']['year']}"  # noqa: E501
        return answer

    def postprocess_confident(self, res: dict, retry_errors: list):
        if retry_errors:
            # check if all previous answers are confident
            all_confident = all([r[0].confident for r in retry_errors])
            res["confident"] = all_confident and res["confident"]

        thinking = res.get("thinking", "")
        if thinking == "No reference found":
            res["confident"] = False

        return res

    def answer_by_system_context(
        self,
        retry_errors: list = [],
        format: dict = None,
    ) -> Answer:
        if format is None:
            format = {
                "type": "object",
                "properties": {
                    "answer": {"type": "string"},
                    "reference": {
                        "type": "string",
                        "description": "original reference copy that supports the answer. Must be in format of 'From XXX: <original reference in plain text (not json)>'",  # noqa: E501
                        "maxLength": 100,
                    },
                    "confident": {
                        "type": "boolean",
                        "description": "whether you are extremely confident about the answer. If you can't find any reference or the answer is None, then it's not confident",  # noqa: E501
                    },
                },
                "required": ["answer", "reference", "confident"],
            }

        processed_question_text = self.preprocess_question_text()
        prompt = self.create_prompt(processed_question_text, retry_errors)
        format = self.preprocess_format(processed_question_text, format, retry_errors)
        system_context = self.create_system_context(processed_question_text)

        # Call AI engine through service gateway
        from services.ai_engine_client import AIEngineClient  # noqa: E402

        ai_client = AIEngineClient()
        res = ai_client.call_ai(
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

        # Handle case where AI call fails
        if res is None:
            res = {
                "answer": "N/A",
                "reference": "From system: AI call failed",
                "confident": False,
                "thinking": "AI engine call failed",
            }

        res = self.postprocess_answer(res, format)
        res = self.postprocess_confident(res, retry_errors)

        return Answer(
            str(res.get("answer", "")),
            res.get("reference", ""),
            res.get("confident", False),
            res.get("thinking", ""),
        )

    def generate_text_answer(
        self, retry_errors: list = [], disable_exact_match: bool = True
    ) -> Answer:
        """
        return an Answer object
        """
        if not retry_errors and not disable_exact_match:
            answer = self.try_return_exact_match()
            if answer.confident:
                return answer
        answer = self.answer_by_system_context(retry_errors)
        return answer

    def fill_question_helper(
        self,
        fill_value_func: Callable,
        answer_by_predefined_func: Callable,
        answer_by_ai_func: Callable,
    ):
        logger.info(f"Filling question with text: {self.question_text}")
        for f in [
            answer_by_predefined_func,
            answer_by_ai_func,
        ]:
            answer = f()
            answer_is_confident = answer.confident

            # Simplified confidence check for v2
            confident = answer_is_confident
            if self.config_reader and hasattr(self.config_reader, "application"):
                confident = (
                    answer_is_confident
                    or not self.config_reader.application.record_unseen_faqs_and_skip_application  # noqa: E501
                )

            maybe_thinking = answer.thinking
            if answer.answer:
                ai_gen = f == answer_by_ai_func
                answer = fill_value_func(answer)
                answer.thinking = maybe_thinking
                self.add_log(answer, ai_gen=ai_gen)
                if confident:
                    logger.debug(
                        f"Filled question: {self.question_text} with answer: {answer}, ai_gen: {ai_gen}"  # noqa: E501
                    )
                    break
                else:
                    logger.info(
                        f"Skipping question: {self.question_text} with placeholder answer: {answer.answer} because answer is not confident"  # noqa: E501
                    )
        return answer
