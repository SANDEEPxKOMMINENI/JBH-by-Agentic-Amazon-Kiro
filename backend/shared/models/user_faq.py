"""
UserFaq model for Supabase user_faq table
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel

QuestionTypeEnum = Literal["text_input", "dropdown", "multiple_choice"]


class UserFaq(BaseModel):
    """Model for public.user_faq table"""

    id: UUID
    user_id: Optional[UUID] = None
    question_text: str
    answer: Optional[str] = None
    question_type: QuestionTypeEnum = "text_input"
    options: Optional[Union[Dict[str, Any], List[str]]] = None
    confident: Optional[bool] = False
    order_index: Optional[int] = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda dt: dt.isoformat() if dt else None,
            UUID: lambda uuid: str(uuid) if uuid else None,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for config reader"""
        # Handle options - convert list to dict if needed
        options_value = self.options
        if isinstance(options_value, list):
            # Convert list to dict with indices as keys
            options_value = {str(i): opt for i, opt in enumerate(options_value)}
        elif options_value is None:
            options_value = {}

        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "question": self.question_text,
            "answer": self.answer or "",
            "question_type": self.question_type,
            "options": options_value,
            "confident": self.confident or False,
            "order_index": self.order_index or 0,
            "created_at": (self.created_at.isoformat() if self.created_at else None),
            "updated_at": (self.updated_at.isoformat() if self.updated_at else None),
        }

    def to_faq_template_format(self) -> Dict[str, Dict[str, Any]]:
        """Convert to the format expected by question filler FAQ template"""
        question_key = self.question_text.lower()
        return {
            question_key: {
                "question_text": self.question_text,
                "answer": self.answer or "",
                "question_type": self.question_type,
                "confident": self.confident or False,
            }
        }
