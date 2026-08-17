#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$DIR/../.." && pwd)"
cd "$PROJECT_DIR"

PYTHON="$DIR/.venv/bin/python3"
LOG_DIR="$DIR/logs"
mkdir -p "$LOG_DIR"

RUN_ID=$(date +%Y%m%d-%H%M%S)
LOG_ZH="$LOG_DIR/gen_zh_${RUN_ID}.log"
LOG_EN="$LOG_DIR/gen_en_${RUN_ID}.log"
LOG_UPDATER="$LOG_DIR/review_updater_${RUN_ID}.log"

echo "[start] Cleaning up existing generation processes..."
pkill -f "generate_qwen3_voice.py" || true
pkill -f "background_review_updater.py" || true
sleep 1

echo "[start] Generating initial Review HTML..."
"$PYTHON" "$DIR/generate_voice_review_html.py" --mode full --out-dir "$PROJECT_DIR/voice/review_samples/full_generated_review" || true
"$PYTHON" "$DIR/generate_voice_review_html.py" --mode full --out-dir "$DIR/voice_review" || true

echo "[start] Launching Background Review Updater -> $LOG_UPDATER"
nohup "$PYTHON" "$DIR/background_review_updater.py" > "$LOG_UPDATER" 2>&1 &
PID_UPDATER=$!

echo "[start] Launching GPU 0 (ZH generation) -> $LOG_ZH"
CUDA_VISIBLE_DEVICES=0 nohup "$PYTHON" "$DIR/generate_qwen3_voice.py" \
    --reference-workflow legacy \
    --force \
    --phase voice \
    --lang zh \
    --device cuda:0 \
    --review-out-dir "$DIR/voice_review" \
    --review-all \
    --review-update-interval 30 \
    > "$LOG_ZH" 2>&1 &
PID_ZH=$!

echo "[start] Launching GPU 1 (EN generation) -> $LOG_EN"
CUDA_VISIBLE_DEVICES=1 nohup "$PYTHON" "$DIR/generate_qwen3_voice.py" \
    --reference-workflow legacy \
    --force \
    --phase voice \
    --lang en \
    --device cuda:0 \
    > "$LOG_EN" 2>&1 &
PID_EN=$!

echo ""
echo "=========================================================="
echo " Multi-GPU Voice Generation Started in Background"
echo "=========================================================="
echo "  ZH PID (GPU 0):      $PID_ZH"
echo "  EN PID (GPU 1):      $PID_EN"
echo "  Updater PID:         $PID_UPDATER"
echo "  ZH Log:              $LOG_ZH"
echo "  EN Log:              $LOG_EN"
echo "  Updater Log:         $LOG_UPDATER"
echo "  Review HTML 1:       $PROJECT_DIR/voice/review_samples/full_generated_review/index.html"
echo "  Review HTML 2:       $DIR/voice_review/index.html"
echo "=========================================================="
