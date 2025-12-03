class Answer:
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
        return {
            "answer": self.answer,
            "reference": self.reference,
            "confident": self.confident,
            "thinking": self.thinking,
        }
