"""Account-specific keyring identities and controlled credential deletion."""

import hashlib
from pathlib import Path

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.security.key_store import SystemCredentialStore, trusted_keyring_backend
from worklogger.infrastructure.backup.recovery import remove_account_recovery


def account_credential_namespaces(user_id, database_path):
    namespace = str(Path(database_path).resolve())
    identity = namespace + ":" + str(user_id)
    return "worklogger.external." + hashlib.sha256(identity.encode()).hexdigest(), namespace


def cleanup_account_credentials(user_id, database_path, *, backend=None):
    try:
        remove_account_recovery(user_id, database_path)
        external_service, proxy_namespace = account_credential_namespaces(user_id, database_path)
        backend = backend if backend is not None else trusted_keyring_backend()
        if backend.get_password(external_service, "ai_api_key") is not None:
            backend.delete_password(external_service, "ai_api_key")
        store = SystemCredentialStore(namespace=proxy_namespace, backend=backend)
        for name in (f"proxy_password:{user_id}", f"cloud_backup:{user_id}"):
            result = store.set_secret(name, "")
            if not result.ok:
                return result
        return Result.success(None)
    except Exception:
        return Result.failure(InfrastructureError("credential_storage_unavailable", "credential_storage_unavailable"))
