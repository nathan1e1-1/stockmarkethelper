#!/bin/zsh
cd /Users/nthnp/Developer/stockmarkethelper/engine || exit 1
exec .venv/bin/python -u -m autotrader.main
