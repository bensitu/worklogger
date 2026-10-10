"""Account-specific project management and safe record associations."""

from dataclasses import replace
from uuid import uuid4

from worklogger.domain.projects.models import Project, WorkContext, WorkItem
from worklogger.domain.projects.repositories import ProjectRepository
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result


class ProjectService:
    def __init__(self, user_id: int, repository: ProjectRepository):
        self.user_id, self.repository = user_id, repository

    @staticmethod
    def _run(operation):
        try:
            return Result.success(operation())
        except ValueError as error:
            return Result.failure(ValidationError(str(error), str(error)))
        except Exception:
            return Result.failure(InfrastructureError("work_context_operation_failed", "work_context_operation_failed"))

    def list_projects(self):
        return self._run(lambda: self.repository.list_projects(self.user_id))

    def catalog(self):
        return self._run(lambda: self.repository.catalog(self.user_id))

    def list_work_items(self, project_id):
        return self._run(lambda: self.repository.list_work_items(self.user_id, project_id))

    def save_project(self, name, code="", previous=None):
        def save():
            if previous and previous.archived:
                raise ValueError("project_unavailable")
            project = Project(previous.id if previous else uuid4().hex, name.strip(), code.strip(), previous.revision if previous else 0)
            return self.repository.save_project(self.user_id, project, create=previous is None)
        return self._run(save)

    def save_work_item(self, project_id, title, source_url="", completed=False, previous=None):
        def save():
            if previous and (previous.archived or previous.project_id != project_id):
                raise ValueError("work_item_unavailable")
            item = WorkItem(previous.id if previous else uuid4().hex, project_id, title.strip(), source_url.strip(),
                            bool(completed), previous.revision if previous else 0)
            return self.repository.save_work_item(self.user_id, item, create=previous is None)
        return self._run(save)

    def archive_project(self, project):
        return self._run(lambda: self.repository.save_project(self.user_id, replace(project, archived=True), create=False))

    def archive_work_item(self, item):
        return self._run(lambda: self.repository.save_work_item(self.user_id, replace(item, archived=True), create=False))

    def resolve(self, context: WorkContext, original: WorkContext | None = None):
        if context.project_id is None:
            return context
        projects = self.repository.list_projects(self.user_id)
        project = next((project for project in projects if project.id == context.project_id), None)
        unchanged = original is not None and (context.project_id, context.work_item_id) == (original.project_id, original.work_item_id)
        if project is None or (project.archived and not unchanged):
            raise ValueError("project_unavailable")
        item = None
        if context.work_item_id:
            item = next((item for item in self.repository.list_work_items(self.user_id, project.id) if item.id == context.work_item_id), None)
            if item is None or (item.archived and not unchanged):
                raise ValueError("work_item_unavailable")
        if unchanged:
            return original
        return WorkContext(project.id, item.id if item else None, project.name, item.title if item else "")
