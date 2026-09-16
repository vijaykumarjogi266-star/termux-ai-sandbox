"""
Phase A Governance Core - Policy Engine
Provides deterministic evaluation of proposed file changes.
"""

from enum import Enum
import os
import fnmatch
import json
from typing import List, Optional, Dict, Any


class PolicyDecision(Enum):
    AUTO_APPROVE = "AUTO_APPROVE"
    REJECT = "REJECT"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"


class ApprovalEngine:
    """
    Evaluates proposed file changes against safety and governance rules.
    """

    DEFAULT_ALLOWED_PATHS = ['sandbox/', 'solution.py', 'phase_c_proof/', 'data_processor.py']
    DEFAULT_PROTECTED_PATHS = ['agent/policy.py', '.env', 'phase_c_proof/protected_mock.txt']
    DEFAULT_INFRA_INDICATORS = [
        'deploy',
        'deployment',
        'production',
        'prod.',
        'prod/',
        'prod_',
        'infra',
        'infrastructure',
        'docker',
        'dockerfile',
        'k8s',
        'kubernetes',
        'terraform',
        'helm',
        '.github/workflows',
    ]

    def __init__(
        self,
        allowed_paths: Optional[List[str]] = None,
        protected_paths: Optional[List[str]] = None,
        infra_indicators: Optional[List[str]] = None,
    ):
        self.allowed_paths = (
            list(allowed_paths)
            if allowed_paths is not None
            else list(self.DEFAULT_ALLOWED_PATHS)
        )
        self.protected_paths = (
            list(protected_paths)
            if protected_paths is not None
            else list(self.DEFAULT_PROTECTED_PATHS)
        )
        self.infra_indicators = (
            list(infra_indicators)
            if infra_indicators is not None
            else list(self.DEFAULT_INFRA_INDICATORS)
        )

    def _normalize(self, path: str) -> str:
        p = path.strip().replace('\\', '/')
        while p.startswith('./'):
            p = p[2:]
        return p

    def _is_path_matching(self, file_path: str, rule: str) -> bool:
        norm_file = self._normalize(file_path)
        norm_rule = self._normalize(rule)

        # Exact match
        if norm_file == norm_rule:
            return True

        # Directory prefix match (e.g. 'sandbox/' or if rule represents a folder)
        if rule.endswith('/') or norm_rule.endswith('/'):
            prefix = norm_rule if norm_rule.endswith('/') else norm_rule + '/'
            if norm_file.startswith(prefix):
                return True
        else:
            if norm_file.startswith(norm_rule + '/'):
                return True

        # Glob pattern match (e.g. *.py, src/*)
        if fnmatch.fnmatch(norm_file, norm_rule) or fnmatch.fnmatch(os.path.basename(norm_file), norm_rule):
            return True

        return False

    def is_protected(self, file_path: str) -> bool:
        return any(self._is_path_matching(file_path, rule) for rule in self.protected_paths)

    def is_allowed(self, file_path: str) -> bool:
        return any(self._is_path_matching(file_path, rule) for rule in self.allowed_paths)

    def add_allowed_path(self, path: str):
        norm = self._normalize(path)
        if norm and norm not in self.allowed_paths:
            self.allowed_paths.append(norm)

    def add_protected_path(self, path: str):
        norm = self._normalize(path)
        if norm and norm not in self.protected_paths:
            self.protected_paths.append(norm)

    def implies_infra_or_production(self, file_path: str) -> bool:
        lower_path = self._normalize(file_path).lower()
        return any(indicator.lower() in lower_path for indicator in self.infra_indicators)

    def evaluate_changes(self, changed_files_list: List[str]) -> PolicyDecision:
        """
        Evaluate a list of changed files according to governance policy.

        - If any file is in protected_paths or outside allowed_paths: REJECT
        - If any change implies production deployment or infrastructure changes: HUMAN_REQUIRED
        - Otherwise: AUTO_APPROVE
        """
        if not changed_files_list:
            return PolicyDecision.AUTO_APPROVE

        # Rule 1: Protected or outside allowed paths -> REJECT
        for file_path in changed_files_list:
            if self.is_protected(file_path) or not self.is_allowed(file_path):
                return PolicyDecision.REJECT

        # Rule 2: Infrastructure or production changes -> HUMAN_REQUIRED
        for file_path in changed_files_list:
            if self.implies_infra_or_production(file_path):
                return PolicyDecision.HUMAN_REQUIRED

        # Rule 3: Otherwise -> AUTO_APPROVE
        return PolicyDecision.AUTO_APPROVE

    @classmethod
    def load_from_config(cls, config_path: str) -> "ApprovalEngine":
        """
        Load policy configuration from a JSON file.
        """
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(
                allowed_paths=data.get("allowed_paths"),
                protected_paths=data.get("protected_paths"),
                infra_indicators=data.get("infra_indicators"),
            )
        return cls()

    def save_config(self, config_path: str):
        """
        Persist policy configuration to a JSON file.
        """
        data = {
            "allowed_paths": self.allowed_paths,
            "protected_paths": self.protected_paths,
            "infra_indicators": self.infra_indicators,
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

