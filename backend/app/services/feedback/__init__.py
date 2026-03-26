"""Feedback service — collect ratings, manage unanswered questions."""

from app.services.feedback.service import FeedbackService, get_feedback_service

__all__ = ["FeedbackService", "get_feedback_service"]
