#!/usr/bin/env bash
# запустить добор очереди в фоне, если он не работает и pending > 0. второй копии не будет.
cd "$(dirname "$0")" && exec ../.venv/bin/python gosplan_drain.py start
