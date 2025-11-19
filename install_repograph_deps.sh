#!/usr/bin/env bash
set -euo pipefail
PKGS=(
argparse
attr
attrs
botocore
bunch
chardet
configparser
dill
django-rest-swagger
docopt
ed25519
enum
fabric3
flask
flask-restplus
fuzzywuzzy
ipaddr
jsonpath-rw
kafka-python
leveldb
logbook
multiprocess
multiprocessing
pep8
prettytable
pycryptodome
pydotplus
pyopenssl
pytorch-pretrained-bert
pytorch-transformers
requests
retrying
ruamel.yaml
slackclient
smbus-cffi
suds
toml
ujson
umsgpack
urllib3
)
python -m pip install --upgrade pip
for pkg in "${PKGS[@]}"; do
  echo "+++ installing $pkg"
  python -m pip install "$pkg" || echo "WARNING: failed $pkg (continuing)"
done
