from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ErrorType = Literal[
    "grammar",
    "spelling",
    "word_choice",
    "punctuation",
    "word_order",
    "missing_word",
    "extra_word",
    "conjugation",
    "gender_agreement",
    "number_agreement",
    "tone_register",
    "other",
]

DifficultyLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    original: str = Field(
        min_length=1, description="The erroneous word or phrase from the original sentence"
    )
    correction: str = Field(min_length=1, description="The corrected word or phrase")
    error_type: ErrorType = Field(description="Category of the error")
    explanation: str = Field(
        min_length=1,
        description="A brief, learner-friendly explanation written in the native language",
    )


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sentence: str = Field(
        min_length=1, description="The learner's sentence in the target language"
    )
    target_language: str = Field(
        min_length=2, description="The language the learner is studying"
    )
    native_language: str = Field(
        min_length=2,
        description="The learner's native language -- explanations will be in this language",
    )


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    corrected_sentence: str = Field(
        description="The grammatically corrected version of the input sentence"
    )
    is_correct: bool = Field(description="true if the original sentence had no errors")
    errors: list[ErrorDetail] = Field(
        default_factory=list,
        description="List of errors found. Empty if the sentence is correct.",
    )
    difficulty: DifficultyLevel = Field(
        description="CEFR difficulty level: A1, A2, B1, B2, C1, or C2"
    )

    @model_validator(mode="after")
    def _enforce_consistency(self) -> "FeedbackResponse":
        if self.is_correct and self.errors:
            raise ValueError("is_correct cannot be true when errors are present")
        if not self.is_correct and not self.errors:
            raise ValueError("is_correct cannot be false when errors are empty")
        return self
