import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROOT_ARTIFACTS = ("catalog.json", "manifest.json")


class RootArtifactHygieneTests(unittest.TestCase):
    @staticmethod
    def _cleanup_root_artifacts() -> None:
        for filename in ROOT_ARTIFACTS:
            path = PROJECT_ROOT / filename
            if path.exists():
                path.unlink()

    def tearDown(self) -> None:
        self._cleanup_root_artifacts()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._cleanup_root_artifacts()

    def test_generated_model_metadata_does_not_pollute_project_root(self):
        self._cleanup_root_artifacts()
        for filename in ROOT_ARTIFACTS:
            self.assertFalse((PROJECT_ROOT / filename).exists(), filename)


if __name__ == "__main__":
    unittest.main()

