from shared.question_filler.question_type import QuestionType


class FaqQuestionType:
    """FAQ question types for backend use"""

    TEXT_INPUT = "text_input"
    DROPDOWN = "dropdown"
    MULTIPLE_CHOICE = "multiple_choice"


QUESTION_TYPE_MAPPING = {
    # Single line text input
    QuestionType.INPUT: FaqQuestionType.TEXT_INPUT,
    # Multi-line text input
    QuestionType.MULTI_LINE_INPUT: FaqQuestionType.TEXT_INPUT,
    # Single select dropdown
    QuestionType.SELECT: FaqQuestionType.DROPDOWN,
    # Multiple select dropdown
    QuestionType.MULTI_SELECT: FaqQuestionType.MULTIPLE_CHOICE,
    # Radio button selection
    QuestionType.RADIO: FaqQuestionType.DROPDOWN,
    # Unknown type defaults to text input
    QuestionType.UNKNOWN: FaqQuestionType.TEXT_INPUT,
}


def get_faq_question_type(question_type: str) -> str:
    """
    Convert a question extractor type to a FAQ question type.

    Args:
        question_type: The question type from the question extractor  # noqa: E402

    Returns:
        The corresponding FAQ question type
    """
    return QUESTION_TYPE_MAPPING.get(question_type, FaqQuestionType.TEXT_INPUT)
