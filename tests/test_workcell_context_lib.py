import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LIB = REPO_ROOT / "sandbox" / "workcell-context-lib.sh"


class WorkcellContextLibTests(unittest.TestCase):
    def write_skill(self, root: Path, name: str, title: str) -> None:
        skill_dir = root / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"# {title}\n", encoding="utf-8")

    def test_skill_restore_uses_requested_default_after_prepare_skills(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            default_skills = root / "defaults"
            repo_skills = root / "repo" / "skills"
            source_skills = root / "persisted" / "workcell-skills"
            native_skills = root / "persisted" / "skills"
            merged_skills = root / "merged"

            self.write_skill(default_skills, "chrome-integration", "Chrome default")
            self.write_skill(default_skills, "flutter-integration", "Flutter default")
            self.write_skill(repo_skills, "chrome-integration", "Chrome custom repo")

            script = f"""
. {LIB}
WORKCELL_CONTEXT_REPO_ROOT={root / 'repo'}
WORKCELL_DEFAULT_SKILLS={default_skills}
WORKCELL_SKILLS_SOURCE={source_skills}
WORKCELL_SKILLS_NATIVE={native_skills}
WORKCELL_MERGED_SKILLS={merged_skills}
wc_skill_restore chrome-integration
"""
            result = subprocess.run(
                ["sh", "-c", script],
                input="y\n",
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=True,
            )

            self.assertIn(f"Source: {default_skills / 'chrome-integration'}", result.stdout)
            self.assertNotIn(f"Source: {default_skills / 'flutter-integration'}", result.stdout)
            restored = (repo_skills / "chrome-integration" / "SKILL.md").read_text(encoding="utf-8")
            self.assertEqual(restored, "# Chrome default\n")


if __name__ == "__main__":
    unittest.main()
