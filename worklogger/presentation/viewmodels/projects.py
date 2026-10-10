"""Project catalog operations exposed to presentation workflows."""

from worklogger.app.ports import ProjectOperations


class ProjectManagerViewModel:
    def __init__(self, service: ProjectOperations):
        self.service = service

    def list_projects(self):
        return self.service.list_projects()

    def inventory(self):
        return self.service.catalog()

    def list_work_items(self, project_id):
        return self.service.list_work_items(project_id)

    def save_project(self, name, code, previous=None):
        return self.service.save_project(name, code, previous)

    def save_work_item(self, project_id, title, source_url, completed, previous=None):
        return self.service.save_work_item(project_id, title, source_url, completed, previous)

    def archive_project(self, project):
        return self.service.archive_project(project)

    def archive_work_item(self, item):
        return self.service.archive_work_item(item)
