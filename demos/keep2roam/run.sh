#!/bin/bash

CONFIG_PATH="demos/keep2roam/tiny_data/configs/adithyabsk_keep2roam__d340eea2fdedde8908334eda34325d058fc88282/testing-agent-config.yaml"

rm -rf demos/keep2roam/tiny_data/input-tests/adithyabsk_keep2roam__d340eea2fdedde8908334eda34325d058fc88282
rm -rf demos/keep2roam/tiny_data/repos/adithyabsk_keep2roam__d340eea2fdedde8908334eda34325d058fc88282/tests
python3 -m testing_agent.main --config "$CONFIG_PATH"

