"""
Answer class for question filler
Adapted from v1 for v2's async operations
"""


class Answer:
    """Represents an answer to a form question"""

    def __init__(
        self,
        answer: str,
        reference: str = "",
        confident: bool = True,
        thinking: str = "",
    ):
        self.answer = answer
        self.reference = reference
        self.confident = confident
        self.thinking = thinking

    def to_dict(self):
        """Convert answer to dictionary format"""
        return {
            "answer": self.answer,
            "reference": self.reference,
            "confident": self.confident,
            "thinking": self.thinking,
        }
