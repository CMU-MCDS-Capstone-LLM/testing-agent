python -m testing_agent.main --config testing-agent-config.yaml


workflow：
生成name_map
  - python3 testing-agent/regenerate_name_map.py
  - python3 testing-agent/verify_name_map.py
装环境 
  - python setup_env_final_for_failed_repos.py
生成testing-agent-config.yaml 
跑testingagent


testing-agentl新的features：
- 最后的layer
- repograph source module的替换
- import的问题修复

每个repo的helper tests生成情况：
  - 没问题的：16个
  - llm syntax问题： 3个
  - llm repo性质问题或者其他问题：7个
  - 可以试试的 repo性质问题：4个
  - 肯定不能用的 环境不兼容/repo内容问题：13个




  - 目前生成了helper tests的，但是max-iteration设置的比较小，质量可以更高，不过现在也算能用：23个
  ✅  - 1and1_confluencer__df895ac8e75c13e32e2369bc4d9c88aa036ab9d4
  ？  - aiortc_aiortc__d30c24009196f6f520010f7cca1d24e7506163be
  ？  - amesar_mlflow-tools__431737a891b13a73ec7bdbc507fad21531f2cbf3
  ✅  - azure_aztk__19dde429a702c29bdcf86a69805053ecfd02edee
  ✅  - czheo_syntax_sugar_python__1dbc1d44855acd57f280cca03878681e8dc26b01
  ✅  - educationaltestingservice_skll__f870a65904a449103d8f147e9746e548965f27d1
  ✅  - emlid_ntripbrowser__9161c1943a8623892b174c98cdf686a4a0ce8673
  ✅  - godaddy_tartufo__553dc5fb7ddef597cafda451954fa4cba23acde6
  ✅  - google_capirca__eb768ea7e8cb33ab16786ddeb52b53122c740c65
  x  - grahame_sedge__3badf078e2f4153db161cada1c7a23901e36ab7f
  ？  - greenbone_python-gvm__75a11ed482b70b5ffceaac939294ebaad2d7fe58
  ？  - hbldh_pybankid__79e424cef579d6bffc1e40048e46febbd53aded5
  ！ - hxlstandard_libhxl-python__0babff28e04c7da97cae91de78e86295bc42b118       test路径有点问题
  ✅  - htrc_htrc-feature-reader__7eae68aa368f3e1bc41b36a4f504f8bbe6ff46c8
  ✅  - nlpia_nlpia-bot__054d5d207cba12d9b5c4765454be1c51424ea4f3
  ✅  - obsidianforensics_hindsight__973b3d3278609c144f11542bd24164243ee165af
  x  - openstack_ironic-inspector__f4648facf76ff2ac742fc11bb81880f262e61ee2
    - redhat-cip_hardware__a429c38cf6e6630f6bc1d1793f1aa2a75b21cc03
    - romanz_trezor-agent__e1bbdb4bccb9c81a34123cc89fbb6ef2750ab33b
    - tankerhq_tbump__54b12e29d860336593ff24a514f4d2c9c483b470
    - terryyin_google-translate-python__ac375b49cf1e72e0a79f78ba1a74e57b6c3f8aed
    - tgalal_python-axolotl__f74a936745db2c2f04575bd63308d6b6c0cc91ce
  ！ - thombashi_tcconfig__7ba8676b3b9347ef15142bfeba30d611822c154d      test路径有点问题

  - llm generate不对的：3个
    bretttolbert_verbecc-svc__24a848d285ae2c6f3e5b06d1a8ee718cb3f17133：    E   `)`; SyntaxError: invalid syntax
    celery_celery__9b39fc41998c708c6612f0c7bf4393bf48f72e9b     不会mock东西，具体的看prompt
    jsybrandt_agatha__b570ef0eed11a0d55f1e00d0291fccad62f06222    LLM 生成的导入语句格式错误：`from module import (` 后面直接跟 `)`（空导入列表）导致生成的测试文件有语法错误：`SyntaxError: invalid syntax`

  - 环境不兼容，修半天修不对：3个
    - naver_claf__cffe4993564244545f085ede95eb848b94d07bde
    - slackapi_python-slack-sdk__5f4d92a8048814fc4938753594e74d7cfc74c27a
    - skoczen_will__437f8be397b864dc83c67af8942467907ccf1c21

  - repo或者repo-yaml的内容有问题，修不了：x个
  ?  - cyberbotics_urdf2webots__723168dbfff6132aa5591837d43c960679a0a2c4
    - pep8__pycodestyle__cyberbotics@urdf2webots__723168db.yaml里面只有tests/test_pep8.py，这不该被测，不要了
    - alice-biometrics_petisco__9abf7b1f6ef8c55bdddcb9a5c2eff513f6a93130
      This repository cannot be tested because it fails during import.
      Multiple Pydantic validators share the same function name (validate_value) across different modules, causing a ConfigError: duplicate validator function.
      Since this error occurs before any tests can run, the repository is considered untestable and is skipped.
    - apryor6_flaskerize__59d8319355bf95f26949fe13ac3d6be5b5282fb6
      The migration patch only touches Jinja template files (*.template, {{ name }}). Templates are not executable Python modules and cannot be used for behavioral test-based migration.
    - simonlindholm_decomp-permuter__cfbb706402fe106ae19762279eab8294a531f20c 
      源代码使用相对导入（from .error import），但项目缺少setup.py/pyproject.toml标准布局。
      虽然decision.json判断需要editable安装，但实际无法实现，导致测试文件无法正确导入源模块。
      repo的code structure与标准Python项目不兼容。
    - zalando_spilo__a83681c756fe8dfc8e5117c690bde16319e3e943
      E  from postgres-appliance.callback_aws import associate_address, get_instance_metadata, list_volumes, main; SyntaxError: invalid syntax



  - repo性质特殊，看看能不能直接删了原来的tests: 4个
   -  ansible-community_molecule__b7d7740db482624182dd6c31600ca1c09669cfc5  import file that includes unimportable names, repo naming did not obey the rule
    - bcgov_theorgbook__728f86e941dfb6bdbee27628d28425757af5f22d
      一开始decision.json的test command（python manage.py test）就跑不起来，这个repo的Django 无法启动，因为 settings.AUTH_USER_MODEL 指向的自定义用户模型 api.User 在项目中不存在，导致框架在初始化时直接抛出 ImproperlyConfigured 错误。
    - ctlearn-project_ctlearn__2375af87fa36b7c93c5a3be5cab81784d4a2f64e
      ctalearn.data not found, a data folder is missing in repo
    - hbldh_pybankid__79e424cef579d6bffc1e40048e46febbd53aded5
      BankIDClient 的构造器在执行第 0 步就调用 suds.Client 并访问未定义的 transport 属性（如 options），属于外部 SOAP/SSL 依赖，无法通过 mock 隔离，因此任何 CoverAgent 生成的初始化相关测试都会在收集阶段崩溃，导致无限失败循环；这类 repo 必须标记为不可覆盖测试目标。
    - huggingface_transfer-learning-conv-ai__16074b209c8a94c887c2b869d773ea5f56d8593b
      Skipped because this legacy repo depends on a removed ParlAI module (projects.convai2) that no longer exists in any installable version.
    - kinto_kinto__951dd25ca87f6e4b47a87d254cc187331c4d031c     confirmed
        Kinto upstream tests 100% 不可能跑通,它们依赖：
        PostgreSQL backend，多个 storage adapters，Pyramid plugins，Kinto server 初始化流程，多级 OpenAPI schema / permissions / views, 其实我们的环境只需要跑 migration pass-to-pass，不是要跑一个完整的 Kinto server。
   ？ - ojarva_python-sshpubkeys__e3ee2d2635e8489ef6e3a57520e3bf1b61d94962 
        这个 repo 的核心功能完全依赖真实、完整、合法的 SSH 公钥二进制结构（RSA/DSA/ECDSA）才能触发深层解析逻辑，而 LLM 无法生成有效密钥、unittest 的测试又触发不了解析路径，所以几乎所有核心代码都不会被覆盖
    - microsoft_nni__b955ac99a46094d2d701d447e9df07509767cc32
      NNI 这个 repo 在 import 阶段就依赖真实实验平台（dispatcher、runtime、experiment_id），无法通过 mock 介入，导致 pytest 在收集阶段直接崩，所以必须跳过。
    - paradoxalarminterface_pai__fac6f807b02028921310e48d14f3b71b365e283b     
    - openstack_oslo.messaging__5a842ae15582e4eedfb1b2510eaf4a8997701f58
    - keepsafe_aiohttp__e51fb1ff1ebdde566b96af0090c5c63cf1a62b1b
      “aiohttp（keepsafe_aiohttp）在 PyMigBench snapshot 中缺失关键 git submodules（vendor/http-parser），导致 pip 在 editable 构建阶段强制要求子模块而失败；由于子模块 metadata 已被剥离，该 datapoint 无法修复，必须跳过。” 环境都不对
    - pimoroni_inky__cba36514eb8c881f8bd1d92b0b6a5bf12b4b72fb 
      depends on raspberry Pi
    - princetonuniversity_psyneulink__5253a55c46d529b69397fc1d54d3f8e7262c337b
      “这个 repo 在 import 阶段就因自身代码缺陷触发 KohonenMechanism 的默认构造错误，因此不是文件传输问题，而是 snapshot 本身不可用于自动测试。”
    - rapid-design-of-systems-laboratory_beluga__078e3e56fe5b86d9c188aaf249a72296bd6fa753
      Covering visualization modules is very slow and can freeze execution—avoid including them.
    - trungdong_prov__acb9b05f0bd99b3fbd58e5f1a684d1cfc28961f8
      因为 prov/dot.py 大部分逻辑依赖真实的 PROV Model（ProvBundle / ProvRecord / identifier / uri / namespaces / attributes / relations / nested bundles 等），而 LLM 生成的 MockBundle / MockRecord 永远无法模拟真实行为，导致那些代码路径永远不会被执行，所以 coverage 永远卡在 ~14%。
    - mete0r_pyhwp__0c5c5e7898e5c82ad5543ad4f990cbc69439619a
      “Skip this repo: HWP5 module in mete0r/pyhwp is fundamentally broken (tag model duplication & import crashes); cannot be made importable under Py3.6.”



 ✅ 版本兼容（6 个）

  | Repo                                                                | Decision | Actual | Status |
  |---------------------------------------------------------------------|----------|--------|--------|
  | 1and1_confluencer__df895ac8e75c13e32e2369bc4d9c88aa036ab9d4         | 3.7      | 3.7    | ✅      |
  | greenbone_python-gvm__75a11ed482b70b5ffceaac939294ebaad2d7fe58      | 3.8      | 3.8    | ✅      |
  | hxlstandard_libhxl-python__0babff28e04c7da97cae91de78e86295bc42b118 | 3.8      | 3.8    | ✅      |
  | htrc_htrc-feature-reader__7eae68aa368f3e1bc41b36a4f504f8bbe6ff46c8  | 3.8      | 3.8    | ✅      |
  | nlpia_nlpia-bot__054d5d207cba12d9b5c4765454be1c51424ea4f3           | 3.7      | 3.7    | ✅      |
  | redhat-cip_hardware__a429c38cf6e6630f6bc1d1793f1aa2a75b21cc03       | 3.7      | 3.7    | ✅      |

  ⚠️ 版本不兼容（17 个）

  | Repo                                                                       | 问题                 |
  |----------------------------------------------------------------------------|--------------------|
  | aiortc_aiortc__d30c24009196f6f520010f7cca1d24e7506163be                    | 3.6 → 3.10（4个大版本差） |
  | amesar_mlflow-tools__431737a891b13a73ec7bdbc507fad21531f2cbf3              | 3.8 → 3.10（2个版本差）  |
  | azure_aztk__19dde429a702c29bdcf86a69805053ecfd02edee                       | 3.6 → 3.8（2个版本差）   |
  | czheo_syntax_sugar_python__1dbc1d44855acd57f280cca03878681e8dc26b01        | 3.6 → 3.10（4个大版本差） |
  | educationaltestingservice_skll__f870a65904a449103d8f147e9746e548965f27d1   | 3.6 → 3.8（2个版本差）   |
  | emlid_ntripbrowser__9161c1943a8623892b174c98cdf686a4a0ce8673               | 3.6 → 3.10（4个大版本差） |
  | godaddy_tartufo__553dc5fb7ddef597cafda451954fa4cba23acde6                  | 3.8 → 3.10（2个版本差）  |
  | google_capirca__eb768ea7e8cb33ab16786ddeb52b53122c740c65                   | 3.6 → 3.8（2个版本差）   |
  | grahame_sedge__3badf078e2f4153db161cada1c7a23901e36ab7f                    | 3.6 → 3.10（4个大版本差） |
  | hbldh_pybankid__79e424cef579d6bffc1e40048e46febbd53aded5                   | 3.6 → 3.10（4个大版本差） |
  | obsidianforensics_hindsight__973b3d3278609c144f11542bd24164243ee165af      | 3.8 → 3.10（2个版本差）  |
  | openstack_ironic-inspector__f4648facf76ff2ac742fc11bb81880f262e61ee2       | 3.8 → 3.10（2个版本差）  |
  | romanz_trezor-agent__e1bbdb4bccb9c81a34123cc89fbb6ef2750ab33b              | 3.8 → 3.10（2个版本差）  |
  | tankerhq_tbump__54b12e29d860336593ff24a514f4d2c9c483b470                   | 3.7 → 3.10（3个版本差）  |
  | terryyin_google-translate-python__ac375b49cf1e72e0a79f78ba1a74e57b6c3f8aed | 3.6 → 3.8（2个版本差）   |
  | tgalal_python-axolotl__f74a936745db2c2f04575bd63308d6b6c0cc91ce            | 3.6 → 3.8（2个版本差）   |
  | thombashi_tcconfig__7ba8676b3b9347ef15142bfeba30d611822c154d               | 3.8 → 3.10（2个版本差）  |