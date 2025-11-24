#!/usr/bin/env bash

# Repo 列表
repos=(
"1and1_confluencer__df895ac8e75c13e32e2369bc4d9c88aa036ab9d4"
"aiortc_aiortc__d30c24009196f6f520010f7cca1d24e7506163be"
"amesar_mlflow-tools__431737a891b13a73ec7bdbc507fad21531f2cbf3"
"czheo_syntax_sugar_python__1dbc1d44855acd57f280cca03878681e8dc26b01"
"emlid_ntripbrowser__9161c1943a8623892b174c98cdf686a4a0ce8673"
"godaddy_tartufo__553dc5fb7ddef597cafda451954fa4cba23acde6"
"grahame_sedge__3badf078e2f4153db161cada1c7a23901e36ab7f"
"greenbone_python-gvm__75a11ed482b70b5ffceaac939294ebaad2d7fe58"
"hbldh_pybankid__79e424cef579d6bffc1e40048e46febbd53aded5"
"hxlstandard_libhxl-python__0babff28e04c7da97cae91de78e86295bc42b118"
"nlpia_nlpia-bot__054d5d207cba12d9b5c4765454be1c51424ea4f3"
"obsidianforensics_hindsight__973b3d3278609c144f11542bd24164243ee165af"
"openstack_ironic-inspector__f4648facf76ff2ac742fc11bb81880f262e61ee2"
"romanz_trezor-agent__e1bbdb4bccb9c81a34123cc89fbb6ef2750ab33b"
"tankerhq_tbump__54b12e29d860336593ff24a514f4d2c9c483b470"
"thombashi_tcconfig__7ba8676b3b9347ef15142bfeba30d611822c154d"
)

# 遍历
for repo in "${repos[@]}"; do
    echo "====== $repo ======"
    cd "$repo"

    # 修改 max_iterations 为 10（肯定存在）
    sed -i "s/max_iterations:.*/max_iterations: 10/" testing-agent-config.yaml

    # 运行 TestingAgent
    python -m testing_agent.main --config testing-agent-config.yaml

    cd ..
done
