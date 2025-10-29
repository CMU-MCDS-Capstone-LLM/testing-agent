#!/bin/bash

CONFIG_PATH="/home/eiger/CMU/2025_Spring/11634_Capstone/codebase/tiny_data/configs/adithyabsk_keep2roam__d340eea2fdedde8908334eda34325d058fc88282/testing-agent-config.yaml"

python3 -m testing_agent.main --config "$CONFIG_PATH"
