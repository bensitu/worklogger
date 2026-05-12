import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = PROJECT_ROOT / "WorkLogger_build_macOS.sh"
RELEASE_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "release-build.yml"


class MacOSBuildScriptResilienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script_text = BUILD_SCRIPT.read_text(encoding="utf-8")
        cls.workflow_text = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    def test_llama_runtime_install_retries_are_configurable(self):
        self.assertIn('LLAMA_CPP_INSTALL_RETRIES="${LLAMA_CPP_INSTALL_RETRIES:-3}"', self.script_text)
        self.assertIn(
            'retry "$LLAMA_CPP_INSTALL_RETRIES" 5 "Install local-model runtime (${target_arch})"',
            self.script_text,
        )

    def test_arm64_release_build_skips_known_bad_metal_wheel(self):
        requirement = "llama-cpp-python>=0.3.22,!=0.3.23"
        self.assertIn(requirement, self.script_text)
        self.assertIn(f'LLAMA_CPP_REQUIREMENT_ARM64: "{requirement}"', self.workflow_text)

    def test_x86_release_build_uses_legacy_cpu_wheel(self):
        requirement = "llama-cpp-python==0.3.2"
        self.assertIn(requirement, self.script_text)
        self.assertIn(f'LLAMA_CPP_REQUIREMENT_X86_64: "{requirement}"', self.workflow_text)
        self.assertIn('LLAMA_CPP_ALLOW_VERSION_MISMATCH: "1"', self.workflow_text)

    def test_downloaded_llama_wheel_is_checked_before_install(self):
        self.assertIn("verify_wheel_integrity()", self.script_text)
        self.assertIn("zipfile.ZipFile", self.script_text)
        self.assertIn("wheel_file.testzip()", self.script_text)

        integrity_check = self.script_text.index(
            'verify_wheel_integrity "$target_arch" "$python_exe" "$wheel_path"'
        )
        pip_install = self.script_text.index(
            'run_arch "$target_arch" "$python_exe" -m pip "${pip_args[@]}"',
            integrity_check,
        )
        self.assertLess(integrity_check, pip_install)

    def test_llama_wheel_dependencies_are_installed_before_no_deps_wheel(self):
        self.assertIn("install_llama_python_dependencies()", self.script_text)
        self.assertIn('"numpy>=1.20.0"', self.script_text)
        self.assertIn('"diskcache>=5.6.1"', self.script_text)
        self.assertIn('"jinja2>=2.11.3"', self.script_text)
        self.assertIn("pip_args=(install --verbose --no-compile --no-deps)", self.script_text)

        dependency_install = self.script_text.index(
            'install_llama_python_dependencies "$target_arch" "$python_exe"'
        )
        wheel_install = self.script_text.index(
            'run_arch "$target_arch" "$python_exe" -m pip "${pip_args[@]}"',
            dependency_install,
        )
        self.assertLess(dependency_install, wheel_install)

    def test_heartbeat_child_process_keeps_strict_error_handling(self):
        match = re.search(r"run_with_heartbeat\(\) \{(?P<body>.*?)\n\}", self.script_text, re.S)
        self.assertIsNotNone(match)
        self.assertIn("set -euo pipefail", match.group("body"))


if __name__ == "__main__":
    unittest.main()
