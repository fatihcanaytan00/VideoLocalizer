from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Union

import yaml


class AccountsError(Exception):
    """Raised when accounts.yaml is missing, malformed, or fails validation."""


@dataclass(frozen=True)
class AccountProfile:
    name: str
    client_secret_file: str
    token_file: str


def load_accounts(path: Union[str, Path] = "config/accounts.yaml") -> List[AccountProfile]:
    accounts_path = Path(path)
    if not accounts_path.is_file():
        raise AccountsError(f"Accounts file not found: {accounts_path}")

    with accounts_path.open("r", encoding="utf-8") as f:
        try:
            raw = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise AccountsError(f"Accounts file is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise AccountsError("Accounts file must contain a YAML mapping at the top level.")

    raw_accounts = raw.get("accounts")
    if not isinstance(raw_accounts, list) or not raw_accounts:
        raise AccountsError("Accounts file must contain a non-empty 'accounts' list.")

    profiles: List[AccountProfile] = []
    seen_names = set()
    for index, entry in enumerate(raw_accounts):
        if not isinstance(entry, dict):
            raise AccountsError(f"accounts[{index}] must be a mapping.")

        name = _require_str(entry, "name", index)
        if name in seen_names:
            raise AccountsError(f"Duplicate account name: '{name}'")
        seen_names.add(name)

        client_secret_file = _require_str(entry, "client_secret_file", index)
        token_file = _require_str(entry, "token_file", index)

        profiles.append(
            AccountProfile(name=name, client_secret_file=client_secret_file, token_file=token_file)
        )

    return profiles


def get_account(profiles: List[AccountProfile], name: str) -> AccountProfile:
    for profile in profiles:
        if profile.name == name:
            return profile
    available = ", ".join(p.name for p in profiles)
    raise AccountsError(f"Unknown account '{name}'. Available accounts: {available}")


def _require_str(entry: dict, key: str, index: int) -> str:
    if key not in entry:
        raise AccountsError(f"accounts[{index}] is missing required field: {key}")
    value = entry[key]
    if not isinstance(value, str) or not value.strip():
        raise AccountsError(f"accounts[{index}].{key} must be a non-empty string.")
    return value.strip()
