This demo runs testing agent on the migration commit [adithyabsk/keep2roam@d340eea2fdedde8908334eda34325d058fc88282](https://github.com/adithyabsk/keep2roam/commit/d340eea2fdedde8908334eda34325d058fc88282). To focus on demonstrating the execution setup, the demo sets desired coverage to be 10%, so one iteration of test generation will succeed.

To run this demo, follow these steps

1. Set the environment variable `OPENAI_API_KEY` to be your openai api key

2. Git clone testing-agent

    ```bash
    git clone https://github.com/CMU-MCDS-Capstone-LLM/testing-agent.git
    cd testing-agent
    ```

3. Create the testing agent conda environment with python version 3.11.13, and run `pip install -e .` at the root folder of testing-agent. We will call this env `testing-agent`

    ```bash
    conda create --name <testing-agent-env-name> python=3.11.13
    conda activate <testing-agent-env-name>
    pip install -e .
    ```

4. Unzip the repo

    ```bash
    tar xf demos/keep2roam/tiny_data/repos.tar.gz --directory=demos/keep2roam/tiny_data/
    ```

    In pipeline, this will be handled by a dedicated downloader ([pymigbench_dl](https://github.com/CMU-MCDS-Capstone-LLM/pymigbench_dl))

5. Create the repo conda environment with python version 3.7.9

    ```bash
    conda create --name <repo-env-name> python=3.7.9
    conda activate <repo-env-name>
    pip install marshmallow==3.8.0
    pip install pytest pytest-cov coverage
    conda deactivate
    ```

    In pipeline, the environment setup will be handled before we run testing agent.

6. Modify all absolute paths in the config file

    The config file is located at `demos/keep2roam/tiny_data/configs/adithyabsk_keep2roam__d340eea2fdedde8908334eda34325d058fc88282/testing-agent-config.yaml`

    Here is a list of all fields containing path

    - `project_root_candidates`:

    - `code_coverage_report_path`:

    - `html_report_path`:

    - `log_file`:

    - `log_db_path`:

    - `selector_output_path`:

    - `cover_agent_log_db_path`:

    - `repo_venv_python_candidates`: add the path to python interpreter under repo conda env

    - `repo_env_pre_commands`: source the host machine's `conda.sh`, and conda activate the repo conda env

        Note: Before conda activate, we must initialize conda. This can be manually done by sourcing the `conda.sh` script under the folder that conda is installed.

    We won't use the relative path way, because the current codebase uses repo's root folder as base folder, and store things like coverage report or log directly under repo, which is not what we want.

    In the pipeline, such a config file will be automatically generated

    In pipeline, there will be a remote runner that execute commands within repo container, so all path should be path inside repo container. In repo container, python is installed globally in repo container, so we don't need to set these two fields, and testing-agent will use default python in repo container.

7. Run the `run.sh` under testing agent's root folder

    ```bash
    ./demos/keep2roam/run.sh
    ```

The test log will be written to `demos/keep2roam/tiny_data/input-tests`, while the actual test will be stored under `demos/keep2roam/tiny_data/repos/adithyabsk_keep2roam__d340eea2fdedde8908334eda34325d058fc88282/tests`

TODO: Test this out
