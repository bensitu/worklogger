import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RELEASE_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "release-build.yml"


class ReleaseWorkflowOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow_text = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    def test_release_workflow_does_not_start_from_preexisting_tag_push(self):
        self.assertIn("workflow_dispatch:", self.workflow_text)
        self.assertNotIn("push:", self.workflow_text)
        self.assertNotIn("refs/tags", self.workflow_text.split("jobs:", 1)[0])

    def test_release_job_waits_for_all_platform_builds(self):
        release_job = self.workflow_text.split("  release:", 1)[1]
        for job_name in ("build-windows", "build-macos", "build-linux"):
            self.assertIn(f"      - {job_name}", release_job)

    def test_release_tag_is_created_after_artifacts_are_verified(self):
        release_job = self.workflow_text.split("  release:", 1)[1]
        download_index = release_job.index("- name: Download build artifacts")
        verify_index = release_job.index("- name: Show release files")
        tag_index = release_job.index("- name: Create release tag after verified builds")
        release_index = release_job.index("- name: Create or update draft GitHub Release")

        self.assertLess(download_index, verify_index)
        self.assertLess(verify_index, tag_index)
        self.assertLess(tag_index, release_index)

    def test_release_tag_step_allows_rerun_for_same_commit_only(self):
        release_job = self.workflow_text.split("  release:", 1)[1]
        tag_step = release_job.split("- name: Create release tag after verified builds", 1)[1]
        tag_step = tag_step.split("- name: Create or update draft GitHub Release", 1)[0]

        self.assertIn('tag_sha="$(git rev-list -n 1 "${RELEASE_VERSION}")"', tag_step)
        self.assertIn('if [ "$tag_sha" != "$GITHUB_SHA" ]; then', tag_step)
        self.assertIn("exit 1", tag_step)
        self.assertIn("already exists at ${GITHUB_SHA}", tag_step)

    def test_release_tag_step_can_use_workflow_scoped_secret_token(self):
        release_job = self.workflow_text.split("  release:", 1)[1]
        self.assertIn("persist-credentials: false", release_job)
        self.assertIn("RELEASE_TAG_TOKEN: ${{ secrets.RELEASE_TAG_TOKEN || github.token }}", release_job)
        self.assertIn("RELEASE_TAG_TOKEN_SOURCE", release_job)
        self.assertIn("AUTHORIZATION: basic ${auth_header}", release_job)
        self.assertIn("Contents write and Workflows write permission", release_job)
        self.assertIn("token: ${{ secrets.RELEASE_TAG_TOKEN || github.token }}", release_job)


if __name__ == "__main__":
    unittest.main()
