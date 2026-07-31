"""Handler modules for specialist agent routing.

Re-exports all handler functions for convenient importing.
"""

from src.app.domain.services.handlers.communications import handle_communications
from src.app.domain.services.handlers.diary import handle_diary
from src.app.domain.services.handlers.memory import handle_memory
from src.app.domain.services.handlers.notification import handle_notification
from src.app.domain.services.handlers.plan_day import handle_plan_day
from src.app.domain.services.handlers.project import handle_project
from src.app.domain.services.handlers.research import handle_research
from src.app.domain.services.handlers.review import handle_review
from src.app.domain.services.handlers.save import handle_save
from src.app.domain.services.handlers.socratic import handle_socratic
from src.app.domain.services.handlers.tools import handle_tools

__all__ = [
    "handle_communications",
    "handle_diary",
    "handle_memory",
    "handle_notification",
    "handle_plan_day",
    "handle_project",
    "handle_research",
    "handle_review",
    "handle_save",
    "handle_socratic",
    "handle_tools",
]
