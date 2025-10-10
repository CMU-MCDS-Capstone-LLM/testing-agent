import ast
import json
import os
import re
#{
from typing import Set
#}
from cover_agent.CustomLogger import CustomLogger
from cover_agent.FilePreprocessor import FilePreprocessor
from cover_agent.AgentCompletionABC import AgentCompletionABC
from cover_agent.settings.config_loader import get_settings
from cover_agent.utils import load_yaml

MAX_TESTS_PER_RUN = 4


class UnitTestGenerator:
    def __init__(
        self,
        source_file_path: str,
        test_file_path: str,
        code_coverage_report_path: str,
        test_command: str,
        llm_model: str,
        agent_completion: AgentCompletionABC,
        test_command_dir: str = os.getcwd(),
        included_files: list = None,
        coverage_type="cobertura",
        additional_instructions: str = "",
        use_report_coverage_feature_flag: bool = False,
        project_root: str = "",
    ):
        """
        Initialize the UnitTestGenerator class with the provided parameters.

        Parameters:
            source_file_path (str): The path to the source file being tested.
            test_file_path (str): The path to the test file where generated tests will be written.
            code_coverage_report_path (str): The path to the code coverage report file.
            test_command (str): The command to run tests.
            llm_model (str): The language model to be used for test generation.
            agent_completion (AgentCompletionABC): The agent completion object to be used for test generation.
            api_base (str, optional): The base API url to use in case model is set to Ollama or Hugging Face. Defaults to an empty string.
            test_command_dir (str, optional): The directory where the test command should be executed. Defaults to the current working directory.
            included_files (str, optional): Additional files to include (raw). Defaults to ""
            coverage_type (str, optional): The type of coverage report. Defaults to "cobertura".
            desired_coverage (int, optional): The desired coverage percentage. Defaults to 90.
            additional_instructions (str, optional): Additional instructions for test generation. Defaults to an empty string.
            use_report_coverage_feature_flag (bool, optional): Setting this to True considers the coverage of all the files in the coverage report.
                                                               This means we consider a test as good if it increases coverage for a different
                                                               file other than the source file. Defaults to False.

        Returns:
            None
        """
        # Class variables
        self.project_root = project_root
        self.source_file_path = source_file_path
        self.test_file_path = test_file_path
        self.code_coverage_report_path = code_coverage_report_path
        self.test_command = test_command
        self.test_command_dir = test_command_dir
        self.included_files = included_files
        self.coverage_type = coverage_type
        self.additional_instructions = additional_instructions
        self.language = self.get_code_language(source_file_path)
        self.use_report_coverage_feature_flag = use_report_coverage_feature_flag
        self.last_coverage_percentages = {}
        self.llm_model = llm_model
        self.agent_completion = agent_completion

        # Get the logger instance from CustomLogger
        self.logger = CustomLogger.get_logger(__name__)

        # States to maintain within this class
        self.preprocessor = FilePreprocessor(self.test_file_path)
        self.total_input_token_count = 0
        self.total_output_token_count = 0
        self.testing_framework = "Unknown"
        self.code_coverage_report = ""

        # Read self.source_file_path into a string
        with open(self.source_file_path, "r") as f:
            self.source_code = f.read()

        with open(self.test_file_path, "r") as f:
            self.test_code = f.read()
        #{
        # Cache symbols defined in the source file so we can auto-import them if needed
        self.source_defined_symbols = self._extract_source_defined_symbols(
            self.source_code
        )
        #}

    def get_code_language(self, source_file_path):
        """
        Get the programming language based on the file extension of the provided source file path.

        Parameters:
            source_file_path (str): The path to the source file for which the programming language needs to be determined.

        Returns:
            str: The programming language inferred from the file extension of the provided source file path. Defaults to 'unknown' if the language cannot be determined.
        """
        # Retrieve the mapping of languages to their file extensions from settings
        language_extension_map_org = get_settings().language_extension_map_org

        # Initialize a dictionary to map file extensions to their corresponding languages
        extension_to_language = {}

        # Populate the extension_to_language dictionary
        for language, extensions in language_extension_map_org.items():
            for ext in extensions:
                extension_to_language[ext] = language

        # Extract the file extension from the source file path
        extension_s = "." + source_file_path.rsplit(".")[-1]

        # Initialize the default language name as 'unknown'
        language_name = "unknown"

        # Check if the extracted file extension is in the dictionary
        if extension_s and (extension_s in extension_to_language):
            # Set the language name based on the file extension
            language_name = extension_to_language[extension_s]

        # Return the language name in lowercase
        return language_name.lower()
    #{
    @staticmethod
    def _extract_source_defined_symbols(source_code: str) -> Set[str]:
        symbols: Set[str] = set()
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return symbols

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.add(node.name)
        return symbols

    @staticmethod
    def _extract_imported_symbols(code_snippet: str) -> Set[str]:
        imported: Set[str] = set()
        if not code_snippet:
            return imported
        try:
            tree = ast.parse(code_snippet, type_comments=True)
        except SyntaxError:
            return imported

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.asname or alias.name.split(".")[0])
        return imported

    @staticmethod
    def _extract_local_symbol_names(code_snippet: str) -> Set[str]:
        locals_set: Set[str] = set()
        if not code_snippet:
            return locals_set
        try:
            tree = ast.parse(code_snippet)
        except SyntaxError:
            return locals_set

        built_locals = set()

        class LocalVisitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                locals_set.add(node.name)
                for arg in (
                    list(node.args.args)
                    + list(node.args.posonlyargs)
                    + list(node.args.kwonlyargs)
                ):
                    locals_set.add(arg.arg)
                if node.args.vararg:
                    locals_set.add(node.args.vararg.arg)
                if node.args.kwarg:
                    locals_set.add(node.args.kwarg.arg)
                self.generic_visit(node)

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_With(self, node):
                for item in node.items:
                    if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                        locals_set.add(item.optional_vars.id)
                self.generic_visit(node)

            def visit_For(self, node):
                targets = []
                if isinstance(node.target, ast.Name):
                    targets.append(node.target.id)
                elif isinstance(node.target, (ast.Tuple, ast.List)):
                    targets.extend(
                        name.id
                        for name in node.target.elts
                        if isinstance(name, ast.Name)
                    )
                locals_set.update(targets)
                self.generic_visit(node)

        LocalVisitor().visit(tree)

        locals_set.update(built_locals)
        return locals_set

    def _extract_called_source_names(self, code_snippet: str) -> Set[str]:
        names: Set[str] = set()
        if not code_snippet:
            return names
        try:
            tree = ast.parse(code_snippet)
        except SyntaxError:
            return names

        local_names = self._extract_local_symbol_names(code_snippet)
        builtin_names = set(dir(__builtins__))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    candidate = func.id
                    if (
                        candidate in self.source_defined_symbols
                        and candidate not in local_names
                        and candidate not in builtin_names
                    ):
                        names.add(candidate)
        return names

    @staticmethod
    def _merge_import_lines(existing_code: str, new_lines: Set[str]) -> str:
        lines = []
        seen = set()
        for block in [existing_code] if existing_code else []:
            for line in block.split("\n"):
                stripped = line.strip()
                if stripped and stripped not in seen:
                    lines.append(stripped)
                    seen.add(stripped)
        for line in sorted(new_lines):
            stripped = line.strip()
            if stripped and stripped not in seen:
                lines.append(stripped)
                seen.add(stripped)
        return "\n".join(lines)

    def _infer_source_module_name(self) -> str:
        if self.project_root:
            rel_path = os.path.relpath(self.source_file_path, self.project_root)
        else:
            rel_path = os.path.basename(self.source_file_path)
        module, _ = os.path.splitext(rel_path)
        module = module.replace(os.sep, ".")
        return module
    #}
    def check_for_failed_test_runs(self, failed_test_runs):
        """
        Processes the failed test runs and returns a formatted string with details of the failed tests.

        Args:
            failed_test_runs (list): A list of dictionaries containing information about failed test runs.

        Returns:
            str: A formatted string with details of the failed tests.
        """
        if not failed_test_runs:
            failed_test_runs_value = ""
        else:
            failed_test_runs_value = ""
            try:
                for failed_test in failed_test_runs:
                    failed_test_dict = failed_test.get("code", {})
                    if not failed_test_dict:
                        continue
                    # dump dict to str
                    code = json.dumps(failed_test_dict)
                    error_message = failed_test.get("error_message", None)
                    failed_test_runs_value += f"Failed Test:\n```\n{code}\n```\n"
                    if error_message:
                        failed_test_runs_value += (
                            f"Test execution error analysis:\n{error_message}\n\n\n"
                        )
                    else:
                        failed_test_runs_value += "\n\n"
            except Exception as e:
                self.logger.error(f"Error processing failed test runs: {e}")
                failed_test_runs_value = ""

        return failed_test_runs_value

    def generate_tests(
        self, failed_test_runs, language, testing_framework, code_coverage_report
    ):
        """
        Generate tests using the AI model based on the constructed prompt.

        This method generates tests by calling the AI model with the constructed prompt.
        It handles both dry run and actual test generation scenarios. In a dry run, it returns canned test responses.
        In the actual run, it calls the AI model with the prompt and processes the response to extract test
        information such as test tags, test code, test name, and test behavior.

        Parameters:
            max_tokens (int, optional): The maximum number of tokens to use for generating tests. Defaults to 4096.

        Returns:
            dict: A dictionary containing the generated tests with test tags, test code, test name, and test behavior. If an error occurs during test generation, an empty dictionary is returned.

        Raises:
            Exception: If there is an error during test generation, such as a parsing error while processing the AI model response.
        """
        failed_test_runs_value = self.check_for_failed_test_runs(failed_test_runs)
        response, prompt_token_count, response_token_count, self.prompt = (
            self.agent_completion.generate_tests(
                source_file_name=os.path.relpath(
                    self.source_file_path, self.project_root
                ),
                max_tests=MAX_TESTS_PER_RUN,
                source_file_numbered="\n".join(
                    f"{i + 1} {line}"
                    for i, line in enumerate(self.source_code.split("\n"))
                ),
                code_coverage_report=code_coverage_report,
                additional_instructions_text=self.additional_instructions,
                additional_includes_section=self.included_files,
                language=language,
                test_file=self.test_code,
                failed_tests_section=failed_test_runs_value,
                test_file_name=os.path.relpath(self.test_file_path, self.project_root),
                testing_framework=testing_framework,
            )
        )

        self.total_input_token_count += prompt_token_count
        self.total_output_token_count += response_token_count
        try:
            tests_dict = load_yaml(
                response,
                keys_fix_yaml=["test_tags", "test_code", "test_name", "test_behavior"],
            )
            if tests_dict is None:
                return {}
        except Exception as e:
            self.logger.error(f"Error during test generation: {e}")
            # Record the error as a failed test attempt
            fail_details = {
                "status": "FAIL",
                "reason": f"Parsing error: {e}",
                "exit_code": None,  # No exit code as it's a parsing issue
                "stderr": str(e),
                "stdout": "",  # No output expected from a parsing error
                "test": response,  # Use the response that led to the error
            }
            # self.failed_test_runs.append(fail_details)
            tests_dict = []
        #{
        module_import_path = self._infer_source_module_name()
        module_alias = module_import_path.split(".")[-1]
        module_alias_name = f"{module_alias}_module"
        existing_imported_symbols = self._extract_imported_symbols(self.test_code)

        if isinstance(tests_dict, dict):
            candidate_tests = tests_dict.get("new_tests", [])
        else:
            candidate_tests = tests_dict

        for generated_test in candidate_tests or []:
            test_code_snippet = generated_test.get("test_code", "")
            if not test_code_snippet:
                continue

            test_code_snippet = self._simplify_path_dunder_str_mock(
                test_code_snippet
            )
            generated_test["test_code"] = test_code_snippet

            (
                test_code_snippet,
                alias_needed,
            ) = self._qualify_source_references_with_module_alias(
                test_code_snippet=test_code_snippet,
                module_name=module_alias,
                alias_name=module_alias_name,
            )

            if alias_needed and module_alias_name not in existing_imported_symbols:
                alias_import_line = f"import {module_import_path} as {module_alias_name}"
                generated_test["new_imports_code"] = self._merge_import_lines(
                    generated_test.get("new_imports_code", ""),
                    {alias_import_line},
                )
                existing_imported_symbols.add(module_alias_name)

            if alias_needed:
                generated_test["test_code"] = test_code_snippet

            referenced_symbols = self._extract_called_source_names(test_code_snippet)
            if not referenced_symbols:
                continue

            current_imports = existing_imported_symbols.union(
                self._extract_imported_symbols(
                    generated_test.get("new_imports_code", "")
                ),
                self._extract_local_symbol_names(test_code_snippet),
            )

            missing_symbols = {
                symbol for symbol in referenced_symbols if symbol not in current_imports
            }

            if not missing_symbols:
                continue

            import_lines = {
                f"from {module_import_path} import {symbol}"
                for symbol in missing_symbols
            }

            generated_test["new_imports_code"] = self._merge_import_lines(
                generated_test.get("new_imports_code", ""), import_lines
            )

            existing_imported_symbols.update(missing_symbols)
        #}
        return tests_dict

    @staticmethod
    def _simplify_path_dunder_str_mock(test_code_snippet: str) -> str:
        """Replace fragile `__str__` mocking on `Path` specs with concrete paths."""
        lines = test_code_snippet.splitlines()
        if not lines:
            return test_code_snippet

        assignment_regex = re.compile(
            r"^(?P<indent>\s*)(?P<var>[A-Za-z_][\w]*)\s*=\s*mocker\.Mock\(\s*spec\s*=\s*Path\s*\)"
        )
        skip_indices: set[int] = set()
        replacements: dict[int, str] = {}

        added_open_patch = "builtins.open" in test_code_snippet

        for idx, line in enumerate(lines):
            if idx in skip_indices:
                continue

            match = assignment_regex.match(line)
            if not match:
                continue

            var_name = match.group("var")
            indent = match.group("indent")

            # Look for a subsequent __str__ mock
            str_idx = None
            for search_idx in range(idx + 1, len(lines)):
                candidate_line = lines[search_idx]
                if f"{var_name}.__str__" in candidate_line:
                    str_idx = search_idx
                    break
                if candidate_line.strip().startswith("def "):
                    break

            if str_idx is None:
                continue

            # Ensure there are no other attribute mutations for this mock
            other_attr_usage = any(
                f"{var_name}." in candidate_line and "__str__" not in candidate_line
                for candidate_line in lines
            )
            if other_attr_usage:
                continue

            str_line = lines[str_idx]
            value_match = re.search(
                r"__str__\.return_value\s*=\s*(['\"])(?P<path>.+?)\1",
                str_line,
            )
            if not value_match:
                continue

            path_literal = value_match.group("path")
            quote_char = value_match.group(1)

            # Rebuild the assignment with a concrete Path literal
            replacement_line = (
                f"{indent}{var_name} = Path({quote_char}{path_literal}{quote_char})"
            )

            if not added_open_patch:
                replacement_line = (
                    f"{replacement_line}\n"
                    f"{indent}mocker.patch('builtins.open', mocker.mock_open())"
                )
                added_open_patch = True

            replacements[idx] = replacement_line
            skip_indices.add(str_idx)

        if not replacements and not skip_indices:
            return test_code_snippet

        new_lines = []
        for idx, line in enumerate(lines):
            if idx in skip_indices:
                continue
            if idx in replacements:
                new_lines.append(replacements[idx])
            else:
                new_lines.append(line)

        return "\n".join(new_lines)

    def _qualify_source_references_with_module_alias(
        self, test_code_snippet: str, module_name: str, alias_name: str
    ) -> tuple[str, bool]:
        """Rewrite calls into module-qualified references when needed."""
        try:
            tree = ast.parse(test_code_snippet, type_comments=True)
        except SyntaxError:
            return test_code_snippet, False

        lines = test_code_snippet.splitlines(keepends=True)
        if not lines:
            return test_code_snippet, False

        line_offsets = []
        total = 0
        for line in lines:
            line_offsets.append(total)
            total += len(line)

        replacements: list[tuple[int, int, str]] = []
        alias_needed = False
        source_symbols = self.source_defined_symbols

        def node_offsets(node: ast.AST) -> tuple[int, int] | None:
            if not (
                hasattr(node, "lineno")
                and hasattr(node, "col_offset")
                and hasattr(node, "end_lineno")
                and hasattr(node, "end_col_offset")
            ):
                return None
            start = line_offsets[node.lineno - 1] + node.col_offset
            end = line_offsets[node.end_lineno - 1] + node.end_col_offset
            return start, end

        class _Collector(ast.NodeVisitor):
            def visit_Call(self, node):
                nonlocal alias_needed
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                    if func_name in source_symbols:
                        offsets = node_offsets(node.func)
                        if offsets:
                            start, end = offsets
                            replacements.append(
                                (start, end, f"{alias_name}.{func_name}")
                            )
                            alias_needed = True
                self.generic_visit(node)

            def visit_Attribute(self, node):
                nonlocal alias_needed
                if (
                    isinstance(node.value, ast.Name)
                    and node.value.id == module_name
                ):
                    offsets = node_offsets(node.value)
                    if offsets:
                        start, end = offsets
                        replacements.append((start, end, alias_name))
                        alias_needed = True
                self.generic_visit(node)

        _Collector().visit(tree)

        if not replacements:
            return test_code_snippet, False

        # Deduplicate overlapping replacements by keeping the last occurrence per span.
        unique_replacements: dict[tuple[int, int], str] = {}
        for start, end, text in replacements:
            unique_replacements[(start, end)] = text

        new_code = test_code_snippet
        for (start, end), text in sorted(
            unique_replacements.items(), key=lambda item: item[0][0], reverse=True
        ):
            new_code = new_code[:start] + text + new_code[end:]

        return new_code, alias_needed
