#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yaml"
ENV_FILE="${SCRIPT_DIR}/.env"
CONTAINER_NAME="ollama_Y"
MEMORY_BUSY_THRESHOLD_MIB="${MEMORY_BUSY_THRESHOLD_MIB:-1024}"

error() {
  printf '错误: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || error "缺少命令: $1"
}

require_command docker
require_command nvidia-smi

if ! docker compose version >/dev/null 2>&1; then
  error "未检测到 Docker Compose v2，请确认 'docker compose version' 可正常执行。"
fi

[[ -f "$COMPOSE_FILE" ]] || error "找不到 $COMPOSE_FILE"

if [[ "${EUID}" -ne 0 ]] && ! docker info >/dev/null 2>&1; then
  error "当前用户无权访问 Docker。请使用 root，或将用户加入 docker 组。"
fi

GPU_COUNT="$(nvidia-smi --query-gpu=index --format=csv,noheader,nounits 2>/dev/null | wc -l | tr -d ' ')"
[[ "$GPU_COUNT" =~ ^[0-9]+$ ]] || error "无法读取 GPU 数量。"
(( GPU_COUNT > 0 )) || error "未检测到 NVIDIA GPU。"

# 可选文件锁，避免两个管理员同时切换同一个 Ollama 容器。
LOCK_FILE="/tmp/ollama_Y_gpu_select.lock"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  flock -n 9 || error "另一个 GPU 选择脚本正在运行。"
fi

gpu_uuid() {
  nvidia-smi -i "$1" --query-gpu=uuid --format=csv,noheader,nounits | xargs
}

gpu_memory_used() {
  nvidia-smi -i "$1" --query-gpu=memory.used --format=csv,noheader,nounits | xargs
}

gpu_process_lines() {
  local index="$1"
  local uuid
  uuid="$(gpu_uuid "$index")"

  nvidia-smi \
    --query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory \
    --format=csv,noheader,nounits 2>/dev/null \
    | awk -F',' -v target="$uuid" '
        {
          for (i = 1; i <= NF; i++) {
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", $i)
          }
          if ($1 == target) {
            printf "PID=%s  显存=%s MiB  进程=%s\n", $2, $4, $3
          }
        }
      '
}

gpu_is_busy() {
  local index="$1"
  local memory_used processes
  memory_used="$(gpu_memory_used "$index")"
  processes="$(gpu_process_lines "$index")"

  if [[ -n "$processes" ]]; then
    return 0
  fi

  if [[ "$memory_used" =~ ^[0-9]+$ ]] && (( memory_used >= MEMORY_BUSY_THRESHOLD_MIB )); then
    return 0
  fi

  return 1
}

show_gpu_status() {
  printf '\n当前 GPU 状态：\n'
  printf '%-5s %-26s %-12s %-12s %-10s %-8s %-8s\n' \
    '编号' '型号' '显存已用' '显存总量' '利用率' '温度' '状态'

  local line index name mem_used mem_total util temp status
  while IFS=',' read -r index name mem_used mem_total util temp; do
    index="$(xargs <<<"$index")"
    name="$(xargs <<<"$name")"
    mem_used="$(xargs <<<"$mem_used")"
    mem_total="$(xargs <<<"$mem_total")"
    util="$(xargs <<<"$util")"
    temp="$(xargs <<<"$temp")"

    if gpu_is_busy "$index"; then
      status='占用'
    else
      status='空闲'
    fi

    printf '%-5s %-26s %-12s %-12s %-10s %-8s %-8s\n' \
      "$index" "${name:0:26}" "${mem_used} MiB" "${mem_total} MiB" \
      "${util}%" "${temp}°C" "$status"
  done < <(
    nvidia-smi \
      --query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu \
      --format=csv,noheader,nounits
  )

  printf '\nGPU 计算进程：\n'
  local found=0 i processes
  for ((i = 0; i < GPU_COUNT; i++)); do
    processes="$(gpu_process_lines "$i")"
    if [[ -n "$processes" ]]; then
      found=1
      printf '\nGPU %s:\n%s\n' "$i" "$processes"
    fi
  done

  if (( found == 0 )); then
    printf '未检测到 GPU 计算进程。\n'
  fi
  printf '\n'
}

show_gpu_status

printf '请选择 Ollama 使用的 GPU 编号（0-%s），输入 q 退出: ' "$((GPU_COUNT - 1))"
read -r SELECTED_GPU

if [[ "$SELECTED_GPU" == 'q' || "$SELECTED_GPU" == 'Q' ]]; then
  printf '已取消。\n'
  exit 0
fi

[[ "$SELECTED_GPU" =~ ^[0-9]+$ ]] || error "GPU 编号必须是整数。"
(( SELECTED_GPU >= 0 && SELECTED_GPU < GPU_COUNT )) || error "GPU 编号超出范围。"

# 选择后再次读取，尽量降低检查与启动之间的竞争窗口。
if gpu_is_busy "$SELECTED_GPU"; then
  printf '\n警告：GPU %s 当前可能已被占用。\n' "$SELECTED_GPU"
  printf '当前计算进程：\n'
  gpu_process_lines "$SELECTED_GPU" || true
  printf '当前显存占用：%s MiB\n' "$(gpu_memory_used "$SELECTED_GPU")"
  printf '确认仍要使用该 GPU？请输入大写 YES: '
  read -r CONFIRM
  [[ "$CONFIRM" == 'YES' ]] || error "已取消启动。"
fi

cat > "${ENV_FILE}.tmp" <<EOF_ENV
OLLAMA_GPU_ID=${SELECTED_GPU}
OLLAMA_BIND_ADDRESS=0.0.0.0
EOF_ENV
mv "${ENV_FILE}.tmp" "$ENV_FILE"
chmod 600 "$ENV_FILE"

printf '\n正在校验 Compose 配置……\n'
docker compose \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  config >/dev/null

printf '正在使用宿主机 GPU %s 启动 %s……\n' "$SELECTED_GPU" "$CONTAINER_NAME"
docker compose \
  --env-file "$ENV_FILE" \
  -f "$COMPOSE_FILE" \
  up -d --force-recreate

sleep 2

printf '\n容器状态：\n'
docker ps \
  --filter "name=^/${CONTAINER_NAME}$" \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

printf '\nGPU %s 当前状态：\n' "$SELECTED_GPU"
nvidia-smi -i "$SELECTED_GPU" \
  --query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu \
  --format=csv,noheader

printf '\n最近日志：\n'
docker logs --tail 30 "$CONTAINER_NAME" 2>&1 || true

printf '\n启动完成。API 地址：\n'
printf '  本机: http://127.0.0.1:11434\n'
printf '  局域网/组网: http://<服务器IP>:11434\n'
printf '\n模型目录：/mnt/vol1/ollama_Y\n'
printf '拉取模型示例：docker exec -it %s ollama pull qwen3.6:35b\n' "$CONTAINER_NAME"
printf '查看模型状态：docker exec %s ollama ps\n' "$CONTAINER_NAME"
