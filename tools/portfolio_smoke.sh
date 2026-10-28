#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
python -m docweave.cli data/purchase_order.json data/invoice.json
python -m docweave.three_way_cli data/purchase_order.json data/invoice.json data/goods_receipt_note.json
