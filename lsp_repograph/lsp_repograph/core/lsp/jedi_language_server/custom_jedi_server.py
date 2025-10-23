"""
Provides Python specific instantiation of the LanguageServer class. Contains various configurations and settings specific to Python.
"""

import json
import logging
import os
import pathlib
from contextlib import asynccontextmanager
from typing import AsyncIterator

from multilspy.multilspy_logger import MultilspyLogger
from multilspy.language_server import LanguageServer
from multilspy.lsp_protocol_handler.server import ProcessLaunchInfo
from multilspy.lsp_protocol_handler.lsp_types import InitializeParams
from multilspy.multilspy_config import MultilspyConfig


class CustomJediServer(LanguageServer):
    """
    Provides Python specific instantiation of the LanguageServer class. Contains various configurations and settings specific to Python.
    """

    def __init__(self, config: MultilspyConfig, logger: MultilspyLogger, repository_root_path: str, custom_init_params: dict | None = None):
        """
        Creates a JediServer instance with custom initialization parameters. For example, we can configure the included virtual environments
        
        Args:
            config: MultilspyConfig instance
            logger: MultilspyLogger instance  
            repository_root_path: Path to repository root
            custom_init_params: Custom initialization parameters to override defaults
        """
        super().__init__(
            config,
            logger,
            repository_root_path,
            ProcessLaunchInfo(cmd="jedi-language-server", cwd=repository_root_path),
            "python",
        )
        self.custom_init_params = custom_init_params or {}

    def _get_initialize_params(self, repository_absolute_path: str) -> InitializeParams:
        """
        Returns the initialize params for the Jedi Language Server with custom parameters applied.
        """
        with open(os.path.join(os.path.dirname(__file__), "initialize_params.json"), "r") as f:
            d = json.load(f)

        del d["_description"]

        d["processId"] = os.getpid()
        assert d["rootPath"] == "$rootPath"
        d["rootPath"] = repository_absolute_path

        assert d["rootUri"] == "$rootUri"
        d["rootUri"] = pathlib.Path(repository_absolute_path).as_uri()

        assert d["workspaceFolders"][0]["uri"] == "$uri"
        d["workspaceFolders"][0]["uri"] = pathlib.Path(repository_absolute_path).as_uri()

        assert d["workspaceFolders"][0]["name"] == "$name"
        d["workspaceFolders"][0]["name"] = os.path.basename(repository_absolute_path)

        # Apply custom initialization parameters
        if self.custom_init_params:
            self._merge_custom_params(d, self.custom_init_params)

        return d

    def _merge_custom_params(self, base_params: dict, custom_params: dict) -> None:
        """
        Recursively merge custom parameters into base parameters.
        
        Args:
            base_params: Base initialization parameters to modify
            custom_params: Custom parameters to merge in
        """
        for key, value in custom_params.items():
            if key in base_params and isinstance(base_params[key], dict) and isinstance(value, dict):
                # Recursively merge nested dictionaries
                self._merge_custom_params(base_params[key], value)
            else:
                # Overwrite or add the parameter
                base_params[key] = value

    @asynccontextmanager
    async def start_server(self) -> AsyncIterator["CustomJediServer"]:
        """
        Starts the JEDI Language Server, waits for the server to be ready and yields the LanguageServer instance.

        Usage:
        ```
        async with lsp.start_server():
            # LanguageServer has been initialized and ready to serve requests
            await lsp.request_definition(...)
            await lsp.request_references(...)
            # Shutdown the LanguageServer on exit from scope
        # LanguageServer has been shutdown
        ```
        """

        async def execute_client_command_handler(params):
            return []

        async def do_nothing(params):
            return

        async def check_experimental_status(params):
            if params["quiescent"] == True:
                self.completions_available.set()

        async def window_log_message(msg):
            self.logger.log(f"LSP: window/logMessage: {msg}", logging.INFO)

        self.server.on_request("client/registerCapability", do_nothing)
        self.server.on_notification("language/status", do_nothing)
        self.server.on_notification("window/logMessage", window_log_message)
        self.server.on_request("workspace/executeClientCommand", execute_client_command_handler)
        self.server.on_notification("$/progress", do_nothing)
        self.server.on_notification("textDocument/publishDiagnostics", do_nothing)
        self.server.on_notification("language/actionableNotification", do_nothing)
        self.server.on_notification("experimental/serverStatus", check_experimental_status)

        async with super().start_server():
            self.logger.log("Starting jedi-language-server server process", logging.INFO)
            await self.server.start()
            initialize_params = self._get_initialize_params(self.repository_root_path)

            self.logger.log(
                "Sending initialize request from LSP client to LSP server and awaiting response",
                logging.INFO,
            )
            init_response = await self.server.send.initialize(initialize_params)
            assert init_response["capabilities"]["textDocumentSync"]["change"] == 2
            assert "completionProvider" in init_response["capabilities"]
            assert init_response["capabilities"]["completionProvider"] == {
                "triggerCharacters": [".", "'", '"'],
                "resolveProvider": True,
            }

            self.server.notify.initialized({})

            yield self

            await self.server.shutdown()
            await self.server.stop()
