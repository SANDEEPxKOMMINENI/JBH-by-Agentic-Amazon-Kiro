"""
LLM Credential Manager - Store user's LLM API credentials locally.

Credentials are stored per workflow run and provider to avoid re-entry.
Storage location: {BASE_DIR}/llm_credential/{workflow_run_id}_{provider}.json
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional

from constants import BASE_DIR

logger = logging.getLogger(__name__)

# Credential storage directory
CREDENTIAL_DIR = os.path.join(BASE_DIR, "llm_credential")
os.makedirs(CREDENTIAL_DIR, exist_ok=True)


class LLMCredentialManager:
    """Manage LLM API credentials stored locally on user's machine."""

    @staticmethod
    def _get_credential_path(workflow_run_id: str, provider: str) -> str:
        """
        Get the file path for storing credentials.

        Args:
            workflow_run_id: The workflow run ID
            provider: LLM provider (openai, claude, gemini, azure)

        Returns:
            Path to credential file
        """
        filename = f"{workflow_run_id}_{provider}.json"
        return os.path.join(CREDENTIAL_DIR, filename)

    @staticmethod
    def save_credentials(
        workflow_run_id: str,
        provider: str,
        api_key: str,
        model: Optional[str] = None,
        endpoint: Optional[str] = None,
    ) -> bool:
        """
        Save LLM credentials to local storage.

        Args:
            workflow_run_id: The workflow run ID
            provider: LLM provider (openai, claude, gemini, azure)
            api_key: API key
            model: Model name (optional, stored in credentials but not in filename)
            endpoint: Endpoint URL for Azure (optional)

        Returns:
            True if saved successfully, False otherwise
        """
        if not workflow_run_id or not provider or not api_key:
            logger.warning("Missing required parameters for credential save")
            return False

        try:
            credential_path = LLMCredentialManager._get_credential_path(
                workflow_run_id, provider
            )

            # Store credentials including model if provided
            credentials = {
                "provider": provider,
                "api_key": api_key,
            }

            if model:
                credentials["model"] = model

            if endpoint:
                credentials["endpoint"] = endpoint

            with open(credential_path, "w", encoding="utf-8") as f:
                json.dump(credentials, f, indent=2)

            logger.info(
                f"Saved LLM credentials for workflow {workflow_run_id}, provider {provider}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to save LLM credentials: {e}")
            return False

    @staticmethod
    def load_credentials(
        workflow_run_id: str, provider: str
    ) -> Optional[Dict[str, str]]:
        """
        Load LLM credentials from local storage.

        Supports both old format (workflow_id_provider_model.json) and
        new format (workflow_id_provider.json) for backward compatibility.

        Args:
            workflow_run_id: The workflow run ID
            provider: LLM provider (openai, claude, gemini, azure)

        Returns:
            Dictionary with credentials or None if not found
        """
        if not workflow_run_id or not provider:
            return None

        try:
            # Try new format first: {workflow_id}_{provider}.json
            credential_path = LLMCredentialManager._get_credential_path(
                workflow_run_id, provider
            )

            if os.path.exists(credential_path):
                with open(credential_path, "r", encoding="utf-8") as f:
                    credentials = json.load(f)
                logger.info(
                    f"Loaded LLM credentials for workflow {workflow_run_id}, provider {provider}"
                )
                return credentials

            # Fallback: Try to find old format files {workflow_id}_{provider}_{model}.json
            # Look for any file matching the pattern
            if os.path.exists(CREDENTIAL_DIR):
                prefix = f"{workflow_run_id}_{provider}_"
                for filename in os.listdir(CREDENTIAL_DIR):
                    if filename.startswith(prefix) and filename.endswith(".json"):
                        old_path = os.path.join(CREDENTIAL_DIR, filename)
                        with open(old_path, "r", encoding="utf-8") as f:
                            credentials = json.load(f)
                        logger.info(
                            f"Loaded LLM credentials from old format: {filename}"
                        )

                        # Optionally migrate to new format
                        try:
                            new_path = LLMCredentialManager._get_credential_path(
                                workflow_run_id, provider
                            )
                            with open(new_path, "w", encoding="utf-8") as f:
                                json.dump(credentials, f, indent=2)
                            logger.info(
                                f"Migrated credentials to new format: {os.path.basename(new_path)}"
                            )
                            # Delete old file after successful migration
                            os.remove(old_path)
                            logger.info(f"Removed old format file: {filename}")
                        except Exception as migrate_error:
                            logger.warning(
                                f"Failed to migrate credentials: {migrate_error}"
                            )

                        return credentials

            logger.debug(f"No credentials found for {workflow_run_id}/{provider}")
            return None

        except Exception as e:
            logger.error(f"Failed to load LLM credentials: {e}")
            return None

    @staticmethod
    def delete_credentials(workflow_run_id: str, provider: str) -> bool:
        """
        Delete stored credentials.

        Args:
            workflow_run_id: The workflow run ID
            provider: LLM provider

        Returns:
            True if deleted successfully, False otherwise
        """
        if not workflow_run_id or not provider:
            return False

        try:
            credential_path = LLMCredentialManager._get_credential_path(
                workflow_run_id, provider
            )

            if os.path.exists(credential_path):
                os.remove(credential_path)
                logger.info(
                    f"Deleted LLM credentials for workflow {workflow_run_id}, provider {provider}"
                )
                return True

            return False

        except Exception as e:
            logger.error(f"Failed to delete LLM credentials: {e}")
            return False

    @staticmethod
    def list_all_credentials() -> Dict[str, list]:
        """
        List all stored credentials.

        Returns:
            Dictionary mapping workflow_run_id to list of providers
        """
        credentials_map = {}

        try:
            if not os.path.exists(CREDENTIAL_DIR):
                return credentials_map

            for filename in os.listdir(CREDENTIAL_DIR):
                if filename.endswith(".json"):
                    # Parse filename: {workflow_run_id}_{provider}.json
                    name_parts = filename.replace(".json", "").split("_")
                    if len(name_parts) >= 2:
                        # Last part is provider, rest is workflow_run_id
                        provider = name_parts[-1]
                        workflow_run_id = "_".join(name_parts[:-1])

                        if workflow_run_id not in credentials_map:
                            credentials_map[workflow_run_id] = []

                        credentials_map[workflow_run_id].append(provider)

        except Exception as e:
            logger.error(f"Failed to list credentials: {e}")

        return credentials_map
